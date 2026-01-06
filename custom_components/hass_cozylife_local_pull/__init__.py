"""CozyLife Local Pull integration for Home Assistant.

This integration allows local control of CozyLife smart devices without cloud dependency.
Devices are discovered via UDP broadcast and hostname scanning, then controlled via TCP.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    LANG,
    SUPPORT_DEVICE_CATEGORY,
    CONF_CONNECTION_TIMEOUT,
    CONF_COMMAND_TIMEOUT,
    CONF_RESPONSE_TIMEOUT,
    CONF_SCAN_INTERVAL,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_RESPONSE_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    HEALTH_CHECK_INTERVAL,
    REDISCOVERY_INTERVAL,
)
from .discovery import async_discover_devices
from .tcp_client import TcpClient
from .udp_discover import get_ip
from .utils import async_get_pid_list

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["light", "switch"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the CozyLife Local component.

    Args:
        hass: The Home Assistant instance.
        config: The configuration dictionary.

    Returns:
        True if setup was successful.
    """
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CozyLife Local from a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being set up.

    Returns:
        True if setup was successful.
    """
    _LOGGER.debug("async_setup_entry start")

    # Ensure domain data is initialized
    hass.data.setdefault(DOMAIN, {})

    # Run UDP and hostname discovery in parallel for faster startup
    udp_task = hass.async_add_executor_job(get_ip)
    hostname_task = async_discover_devices(hass)
    discovery_results = await asyncio.gather(udp_task, hostname_task, return_exceptions=True)

    # Extract results, handling any exceptions
    ip_udp: list[str] = discovery_results[0] if isinstance(discovery_results[0], list) else []
    ip_hostname: list[str] = discovery_results[1] if isinstance(discovery_results[1], list) else []

    if isinstance(discovery_results[0], Exception):
        _LOGGER.warning("UDP discovery failed: %s", discovery_results[0])
    if isinstance(discovery_results[1], Exception):
        _LOGGER.warning("Hostname discovery failed: %s", discovery_results[1])

    # Config IPs (manually specified)
    ip_config_str: str = entry.data.get("ips", "")
    ip_config: list[str] = [ip.strip() for ip in ip_config_str.split(",") if ip.strip()]

    # Merge and deduplicate IPs
    ip_list: list[str] = list(set(ip_udp + ip_hostname + ip_config))

    if not ip_list:
        _LOGGER.info(
            "Discovery found no devices, but integration will load. Check logs for details."
        )

    _LOGGER.debug("Attempting to connect to ip_list: %s", ip_list)

    # Pre-fetch PID list for device identification
    await async_get_pid_list(hass, LANG)

    # Get timeout configuration from entry data
    connection_timeout = entry.data.get(CONF_CONNECTION_TIMEOUT, DEFAULT_CONNECTION_TIMEOUT)
    command_timeout = entry.data.get(CONF_COMMAND_TIMEOUT, DEFAULT_COMMAND_TIMEOUT)
    response_timeout = entry.data.get(CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT)

    _LOGGER.debug(
        "Using timeouts: connection=%s, command=%s, response=%s",
        connection_timeout,
        command_timeout,
        response_timeout,
    )

    # Create TCP clients for each discovered IP with configured timeouts
    clients: list[TcpClient] = [
        TcpClient(
            ip,
            hass=hass,
            connection_timeout=connection_timeout,
            command_timeout=command_timeout,
            response_timeout=response_timeout,
        )
        for ip in ip_list
    ]

    # Connect to devices to get info with retries for initial setup
    # Some devices may need multiple attempts during startup
    if clients:
        _LOGGER.info("Connecting to %d discovered device(s)...", len(clients))
        connect_tasks = [client.connect() for client in clients]
        await asyncio.gather(*connect_tasks, return_exceptions=True)

        # Give devices that failed a second chance after a brief delay
        failed_clients = [c for c in clients if not c.device_id]
        if failed_clients:
            _LOGGER.info(
                "Retrying %d device(s) that didn't respond on first attempt...",
                len(failed_clients)
            )
            await asyncio.sleep(2)  # Brief delay before retry
            retry_tasks = [c.connect(force=True) for c in failed_clients]
            await asyncio.gather(*retry_tasks, return_exceptions=True)

    # Filter clients that connected successfully
    # Include devices with known supported types, OR devices that connected but type is unknown
    # (we'll try to use them as switches/lights based on their capabilities)
    valid_clients: list[TcpClient] = []
    for c in clients:
        if c.device_type_code and c.device_type_code in SUPPORT_DEVICE_CATEGORY:
            # Known supported device type
            valid_clients.append(c)
        elif c.device_id and not c.device_type_code:
            # Device connected (has device_id) but type unknown - default to switch
            _LOGGER.info(
                "Device at %s connected but type unknown (ID=%s), will try as switch",
                c._ip,
                c.device_id,
            )
            c._info.device_type_code = "00"  # Default to switch
            valid_clients.append(c)
        elif c.available and c.device_id:
            # Device is available and has ID - include it
            valid_clients.append(c)

    # Log any unsupported devices for debugging
    unsupported = [c for c in clients if c.device_type_code and c.device_type_code not in SUPPORT_DEVICE_CATEGORY]
    for c in unsupported:
        _LOGGER.warning(
            "Skipping unsupported device type '%s' at IP %s",
            c.device_type_code,
            c._ip,
        )

    # Log devices that failed to connect
    failed = [c for c in clients if not c.device_id and not c.available]
    for c in failed:
        _LOGGER.warning(
            "Failed to connect to device at %s (last error: %s)",
            c._ip,
            getattr(c, '_last_error', None) or "unknown",
        )

    _LOGGER.info(
        "Found %d valid devices out of %d candidates", len(valid_clients), len(clients)
    )

    # Track devices that need re-discovery (shared between health check and rediscovery)
    devices_needing_rediscovery: set[str] = set()

    # Set up background connection health monitor
    async def async_connection_health_check(_now) -> None:
        """Periodically check connection health, send heartbeats, and reconnect if needed."""
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        clients_to_check = entry_data.get("tcp_client", [])

        for client in clients_to_check:
            try:
                # Check if device needs re-discovery due to repeated failures
                if client.needs_rediscovery and client.device_id:
                    if client.device_id not in devices_needing_rediscovery:
                        devices_needing_rediscovery.add(client.device_id)
                        _LOGGER.info(
                            "Health check: device %s at %s needs re-discovery after %d failures",
                            client.device_id,
                            client._ip,
                            client.consecutive_failures,
                        )

                # If device is marked unavailable, force reconnection (bypass backoff)
                if not client.available:
                    _LOGGER.debug(
                        "Health check: forcing reconnection for unavailable device %s",
                        client._ip,
                    )
                    # Use force=True to bypass exponential backoff timer
                    # This ensures we actually try to connect, not just skip due to backoff
                    await client.connect(force=True)
                    # If reconnection succeeded, remove from rediscovery set
                    if client.available and client.device_id:
                        devices_needing_rediscovery.discard(client.device_id)
                # If connection is stale (socket closed but still marked available), reconnect
                elif not client.is_connected() and client.available:
                    _LOGGER.debug(
                        "Health check: connection stale for %s, reconnecting", client._ip
                    )
                    await client.connect(force=True)
                # If connected but idle, send heartbeat to keep connection alive
                elif client.needs_heartbeat():
                    _LOGGER.debug(
                        "Health check: sending heartbeat to %s", client._ip
                    )
                    heartbeat_ok = await client.heartbeat()
                    if not heartbeat_ok:
                        _LOGGER.debug(
                            "Health check: heartbeat failed for %s, will retry next cycle",
                            client._ip,
                        )
            except Exception as e:
                _LOGGER.debug("Health check error for %s: %s", client._ip, e)

    # Schedule periodic health checks
    cancel_health_check = async_track_time_interval(
        hass,
        async_connection_health_check,
        timedelta(seconds=HEALTH_CHECK_INTERVAL),
    )

    # Set up periodic re-discovery to find new devices or devices with changed IPs
    async def async_periodic_rediscovery(_now) -> None:
        """Periodically re-scan network for new devices or IP changes."""
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        current_clients = entry_data.get("tcp_client", [])
        known_ips = {client._ip for client in current_clients}
        known_device_ids = {client.device_id for client in current_clients if client.device_id}

        # Check if any devices specifically need re-discovery
        urgent_rediscovery = bool(devices_needing_rediscovery)
        if urgent_rediscovery:
            _LOGGER.info(
                "Re-discovery: urgent scan for devices that need it: %s",
                devices_needing_rediscovery,
            )
        else:
            _LOGGER.debug("Re-discovery: scanning for new devices (known IPs: %s)", known_ips)

        # Run discovery
        try:
            udp_task = hass.async_add_executor_job(get_ip)
            hostname_task = async_discover_devices(hass)
            discovery_results = await asyncio.gather(udp_task, hostname_task, return_exceptions=True)

            ip_udp: list[str] = discovery_results[0] if isinstance(discovery_results[0], list) else []
            ip_hostname: list[str] = discovery_results[1] if isinstance(discovery_results[1], list) else []

            discovered_ips = set(ip_udp + ip_hostname)
            new_ips = discovered_ips - known_ips

            if new_ips:
                _LOGGER.info("Re-discovery found %d new IP(s): %s", len(new_ips), new_ips)

                # Create clients for new IPs
                connection_timeout = entry.data.get(CONF_CONNECTION_TIMEOUT, DEFAULT_CONNECTION_TIMEOUT)
                command_timeout = entry.data.get(CONF_COMMAND_TIMEOUT, DEFAULT_COMMAND_TIMEOUT)
                response_timeout = entry.data.get(CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT)

                for ip in new_ips:
                    new_client = TcpClient(
                        ip,
                        hass=hass,
                        connection_timeout=connection_timeout,
                        command_timeout=command_timeout,
                        response_timeout=response_timeout,
                    )
                    if await new_client.connect():
                        # Check if this is a new device or a known device with new IP
                        if new_client.device_id and new_client.device_id not in known_device_ids:
                            # Truly new device
                            if new_client.device_type_code in SUPPORT_DEVICE_CATEGORY:
                                current_clients.append(new_client)
                                _LOGGER.info(
                                    "Re-discovery: added new device %s at %s",
                                    new_client.device_id,
                                    ip,
                                )
                            else:
                                _LOGGER.info(
                                    "Re-discovery: new device at %s has unsupported type %s",
                                    ip,
                                    new_client.device_type_code,
                                )
                        elif new_client.device_id in known_device_ids:
                            # Known device with new IP - update existing client
                            _LOGGER.info(
                                "Re-discovery: device %s moved to new IP %s",
                                new_client.device_id,
                                ip,
                            )
                            # Find and update the old client
                            for old_client in current_clients:
                                if old_client.device_id == new_client.device_id:
                                    old_client._ip = ip
                                    await old_client.disconnect()
                                    await old_client.connect(force=True)
                                    # Clear rediscovery flag since we found the device
                                    devices_needing_rediscovery.discard(new_client.device_id)
                                    break
                            # Don't add the new_client since we updated the old one
                            await new_client.disconnect()
                    else:
                        _LOGGER.debug("Re-discovery: couldn't connect to new IP %s", ip)

            else:
                _LOGGER.debug("Re-discovery: no new devices found")

        except Exception as e:
            _LOGGER.warning("Re-discovery error: %s", e)

    # Schedule periodic re-discovery
    cancel_rediscovery = async_track_time_interval(
        hass,
        async_periodic_rediscovery,
        timedelta(seconds=REDISCOVERY_INTERVAL),
    )

    # Get configured scan interval
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    _LOGGER.debug("Using scan interval: %s seconds", scan_interval)

    hass.data[DOMAIN][entry.entry_id] = {
        "tcp_client": valid_clients,
        "cancel_health_check": cancel_health_check,
        "cancel_rediscovery": cancel_rediscovery,
        "scan_interval": scan_interval,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being unloaded.

    Returns:
        True if unload was successful.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})

        # Cancel the health check task
        cancel_health_check = entry_data.get("cancel_health_check")
        if cancel_health_check:
            cancel_health_check()

        # Cancel the re-discovery task
        cancel_rediscovery = entry_data.get("cancel_rediscovery")
        if cancel_rediscovery:
            cancel_rediscovery()

        # Close all TCP connections before removing data
        clients = entry_data.get("tcp_client", [])
        for client in clients:
            try:
                await client.disconnect()
            except Exception as e:
                _LOGGER.debug("Error disconnecting client: %s", e)

        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
