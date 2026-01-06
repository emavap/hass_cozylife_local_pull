# -*- coding: utf-8 -*-
"""Device coordinator for managing CozyLife device connections."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    SUPPORT_DEVICE_CATEGORY,
    DEVICE_STATE_ONLINE,
    DEVICE_STATE_OFFLINE,
    DEVICE_STATE_CONNECTING,
    DEVICE_REDISCOVERY_INTERVAL,
    HEALTH_CHECK_INTERVAL,
    REDISCOVERY_INTERVAL,
    SIGNAL_DEVICE_STATE,
    SIGNAL_DEVICE_CONNECTED,
    SIGNAL_DEVICE_DISCONNECTED,
    CACHE_DEVICE_REGISTRY,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_RESPONSE_TIMEOUT,
)
from .tcp_client import TcpClient
from .discovery import async_discover_devices
from .udp_discover import get_ip

_LOGGER = logging.getLogger(__name__)


@dataclass
class DeviceEntry:
    """Represents a tracked device with its connection state."""

    device_id: str
    ip: str
    client: TcpClient
    device_type: str = ""
    last_seen: float = field(default_factory=time.monotonic)
    offline_since: float | None = None
    last_rediscovery_attempt: float = 0.0


class DeviceCoordinator:
    """Coordinates device connections, reconnection, and re-discovery.

    This class is responsible for:
    - Maintaining a registry of all known devices by device_id
    - Managing persistent connections to each device
    - Triggering re-discovery when devices go offline
    - Updating device IPs when they change (e.g., after DHCP renewal)
    - Dispatching device state changes to entities via signals
    """

    def __init__(
        self,
        hass: HomeAssistant,
        connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
    ) -> None:
        """Initialize the device coordinator.

        Args:
            hass: Home Assistant instance.
            connection_timeout: Timeout for establishing connections.
            command_timeout: Timeout for sending commands.
            response_timeout: Timeout for waiting for responses.
        """
        self._hass = hass
        self._connection_timeout = connection_timeout
        self._command_timeout = command_timeout
        self._response_timeout = response_timeout

        # Device registry: device_id -> DeviceEntry
        self._devices: dict[str, DeviceEntry] = {}
        # IP to device_id mapping for quick lookup
        self._ip_to_device: dict[str, str] = {}

        # Background task handles
        self._cancel_health_check: Callable[[], None] | None = None
        self._cancel_rediscovery: Callable[[], None] | None = None
        self._is_running: bool = False

    @property
    def devices(self) -> dict[str, DeviceEntry]:
        """Return the device registry."""
        return self._devices

    @property
    def clients(self) -> list[TcpClient]:
        """Return list of all TCP clients for backward compatibility."""
        return [entry.client for entry in self._devices.values()]

    def get_client(self, device_id: str) -> TcpClient | None:
        """Get the TCP client for a specific device.

        Args:
            device_id: The device ID to look up.

        Returns:
            The TcpClient for the device, or None if not found.
        """
        entry = self._devices.get(device_id)
        return entry.client if entry else None

    def get_client_by_ip(self, ip: str) -> TcpClient | None:
        """Get the TCP client for a device by IP.

        Args:
            ip: The IP address to look up.

        Returns:
            The TcpClient for the device, or None if not found.
        """
        device_id = self._ip_to_device.get(ip)
        if device_id:
            return self.get_client(device_id)
        return None

    async def start(self) -> None:
        """Start the coordinator and all background tasks."""
        if self._is_running:
            _LOGGER.debug("Coordinator already running")
            return

        _LOGGER.info("Starting device coordinator")
        self._is_running = True

        # Start background health check
        self._cancel_health_check = async_track_time_interval(
            self._hass,
            self._async_health_check,
            timedelta(seconds=HEALTH_CHECK_INTERVAL),
        )

        # Start background re-discovery
        self._cancel_rediscovery = async_track_time_interval(
            self._hass,
            self._async_rediscovery,
            timedelta(seconds=REDISCOVERY_INTERVAL),
        )

        # Start persistent connections for all registered devices
        for entry in self._devices.values():
            await entry.client.start_persistent_connection()

    async def stop(self) -> None:
        """Stop the coordinator and all background tasks."""
        _LOGGER.info("Stopping device coordinator")
        self._is_running = False

        # Cancel background tasks
        if self._cancel_health_check:
            self._cancel_health_check()
            self._cancel_health_check = None

        if self._cancel_rediscovery:
            self._cancel_rediscovery()
            self._cancel_rediscovery = None

        # Stop all device connections
        for entry in self._devices.values():
            try:
                await entry.client.stop_persistent_connection()
            except Exception as e:
                _LOGGER.debug("Error stopping client %s: %s", entry.device_id, e)

    async def add_device(self, client: TcpClient) -> bool:
        """Add a device to the coordinator.

        Args:
            client: The connected TcpClient for the device.

        Returns:
            True if the device was added, False if it was already registered.
        """
        if not client.device_id:
            _LOGGER.warning("Cannot add device without device_id from IP %s", client.ip)
            return False

        device_id = client.device_id

        if device_id in self._devices:
            # Device already registered, update IP if changed
            entry = self._devices[device_id]
            if entry.ip != client.ip:
                _LOGGER.info(
                    "Device %s IP changed from %s to %s",
                    device_id,
                    entry.ip,
                    client.ip,
                )
                # Update IP mapping
                self._ip_to_device.pop(entry.ip, None)
                self._ip_to_device[client.ip] = device_id
                entry.ip = client.ip
                entry.client.update_ip(client.ip)
            return False

        # New device
        entry = DeviceEntry(
            device_id=device_id,
            ip=client.ip,
            client=client,
            device_type=client.device_type_code,
            last_seen=time.monotonic(),
        )

        self._devices[device_id] = entry
        self._ip_to_device[client.ip] = device_id

        # Register state callback
        client.register_state_callback(self._on_device_state_update)

        _LOGGER.info(
            "Registered device %s (type=%s) at %s",
            device_id,
            client.device_type_code,
            client.ip,
        )

        # Start persistent connection if coordinator is running
        if self._is_running:
            await client.start_persistent_connection()

        return True

    async def remove_device(self, device_id: str) -> bool:
        """Remove a device from the coordinator.

        Args:
            device_id: The device ID to remove.

        Returns:
            True if the device was removed.
        """
        entry = self._devices.pop(device_id, None)
        if not entry:
            return False

        self._ip_to_device.pop(entry.ip, None)

        try:
            await entry.client.stop_persistent_connection()
        except Exception as e:
            _LOGGER.debug("Error stopping client for %s: %s", device_id, e)

        _LOGGER.info("Removed device %s", device_id)
        return True

    @callback
    def _on_device_state_update(self, device_id: str, state: dict[str, Any]) -> None:
        """Handle device state updates from TcpClient.

        Args:
            device_id: The device that sent the update.
            state: The new state dictionary.
        """
        entry = self._devices.get(device_id)
        if entry:
            entry.last_seen = time.monotonic()
            entry.offline_since = None

        # Dispatch to entities via Home Assistant dispatcher
        signal = f"{SIGNAL_DEVICE_STATE}_{device_id}"
        async_dispatcher_send(self._hass, signal, state)

    async def _async_health_check(self, _now) -> None:
        """Periodic health check for all devices.

        This checks each device's connection state and triggers
        re-discovery for devices that have been offline too long.
        """
        current_time = time.monotonic()

        for device_id, entry in self._devices.items():
            client = entry.client

            # Check device state
            if client.device_state == DEVICE_STATE_ONLINE:
                entry.last_seen = current_time
                entry.offline_since = None
            elif client.device_state == DEVICE_STATE_OFFLINE:
                if entry.offline_since is None:
                    entry.offline_since = current_time
                    _LOGGER.warning(
                        "Device %s (%s) went offline", device_id, entry.ip
                    )
                    # Dispatch disconnection signal
                    async_dispatcher_send(
                        self._hass,
                        f"{SIGNAL_DEVICE_DISCONNECTED}_{device_id}",
                    )

                # Check if we should trigger re-discovery for this device
                offline_duration = current_time - entry.offline_since
                since_last_rediscovery = current_time - entry.last_rediscovery_attempt

                if since_last_rediscovery >= DEVICE_REDISCOVERY_INTERVAL:
                    _LOGGER.info(
                        "Device %s offline for %.0fs, triggering re-discovery",
                        device_id,
                        offline_duration,
                    )
                    entry.last_rediscovery_attempt = current_time
                    # Trigger targeted re-discovery for this device
                    asyncio.create_task(self._rediscover_device(device_id))

    async def _async_rediscovery(self, _now) -> None:
        """Periodic network scan to find new devices or devices with changed IPs."""
        _LOGGER.debug("Running periodic re-discovery scan")

        try:
            # Run UDP and hostname discovery in parallel
            udp_task = self._hass.async_add_executor_job(get_ip)
            hostname_task = async_discover_devices(self._hass)
            results = await asyncio.gather(udp_task, hostname_task, return_exceptions=True)

            ip_udp = results[0] if isinstance(results[0], list) else []
            ip_hostname = results[1] if isinstance(results[1], list) else []

            discovered_ips = set(ip_udp + ip_hostname)
            known_ips = set(self._ip_to_device.keys())
            new_ips = discovered_ips - known_ips

            if new_ips:
                _LOGGER.info("Re-discovery found %d new IP(s): %s", len(new_ips), new_ips)
                await self._check_new_ips(new_ips)
            else:
                _LOGGER.debug("Re-discovery: no new IPs found")

        except Exception as e:
            _LOGGER.warning("Re-discovery error: %s", e)

    async def _check_new_ips(self, new_ips: set[str]) -> None:
        """Check newly discovered IPs and update device registry.

        Args:
            new_ips: Set of IP addresses to check.
        """
        for ip in new_ips:
            try:
                # Create temporary client to identify the device
                client = TcpClient(
                    ip,
                    hass=self._hass,
                    connection_timeout=self._connection_timeout,
                    command_timeout=self._command_timeout,
                    response_timeout=self._response_timeout,
                )

                if await client.connect():
                    device_id = client.device_id
                    if not device_id:
                        await client.disconnect()
                        continue

                    # Check if this is a known device with new IP
                    if device_id in self._devices:
                        entry = self._devices[device_id]
                        old_ip = entry.ip

                        _LOGGER.info(
                            "Device %s found at new IP: %s -> %s",
                            device_id,
                            old_ip,
                            ip,
                        )

                        # Update IP mapping
                        self._ip_to_device.pop(old_ip, None)
                        self._ip_to_device[ip] = device_id
                        entry.ip = ip

                        # Reconnect with new IP
                        await entry.client.reconnect_with_new_ip(ip)
                        await client.disconnect()  # Close temp client

                        # Dispatch reconnection signal
                        async_dispatcher_send(
                            self._hass,
                            f"{SIGNAL_DEVICE_CONNECTED}_{device_id}",
                        )

                    elif client.device_type_code in SUPPORT_DEVICE_CATEGORY:
                        # New device - add to registry
                        await self.add_device(client)
                        _LOGGER.info(
                            "Re-discovery: added new device %s at %s",
                            device_id,
                            ip,
                        )
                    else:
                        _LOGGER.debug(
                            "Re-discovery: device at %s has unsupported type %s",
                            ip,
                            client.device_type_code,
                        )
                        await client.disconnect()
                else:
                    _LOGGER.debug("Re-discovery: couldn't connect to %s", ip)

            except Exception as e:
                _LOGGER.debug("Re-discovery error for IP %s: %s", ip, e)

    async def _rediscover_device(self, device_id: str) -> None:
        """Try to find a specific offline device.

        This runs discovery and specifically looks for the given device_id
        at any IP address.

        Args:
            device_id: The device ID to search for.
        """
        _LOGGER.debug("Searching for offline device %s", device_id)

        try:
            # Run discovery
            udp_task = self._hass.async_add_executor_job(get_ip)
            hostname_task = async_discover_devices(self._hass)
            results = await asyncio.gather(udp_task, hostname_task, return_exceptions=True)

            ip_udp = results[0] if isinstance(results[0], list) else []
            ip_hostname = results[1] if isinstance(results[1], list) else []

            all_ips = set(ip_udp + ip_hostname)

            # Check each discovered IP
            for ip in all_ips:
                # Skip if this IP is already assigned to another device
                if ip in self._ip_to_device:
                    continue

                try:
                    client = TcpClient(
                        ip,
                        hass=self._hass,
                        connection_timeout=self._connection_timeout,
                        command_timeout=self._command_timeout,
                        response_timeout=self._response_timeout,
                    )

                    if await client.connect():
                        if client.device_id == device_id:
                            # Found the device!
                            entry = self._devices.get(device_id)
                            if entry:
                                old_ip = entry.ip
                                _LOGGER.info(
                                    "Found offline device %s at new IP: %s -> %s",
                                    device_id,
                                    old_ip,
                                    ip,
                                )

                                # Update IP mapping
                                self._ip_to_device.pop(old_ip, None)
                                self._ip_to_device[ip] = device_id
                                entry.ip = ip

                                # Reconnect with new IP
                                await entry.client.reconnect_with_new_ip(ip)
                                entry.offline_since = None

                                # Dispatch reconnection signal
                                async_dispatcher_send(
                                    self._hass,
                                    f"{SIGNAL_DEVICE_CONNECTED}_{device_id}",
                                )

                            await client.disconnect()
                            return  # Found the device, done

                        await client.disconnect()

                except Exception as e:
                    _LOGGER.debug("Error checking IP %s for device %s: %s", ip, device_id, e)

            _LOGGER.debug("Device %s not found in discovery scan", device_id)

        except Exception as e:
            _LOGGER.warning("Error during targeted re-discovery for %s: %s", device_id, e)
