"""CozyLife Local Pull integration for Home Assistant.

This integration allows local control of CozyLife smart devices without cloud dependency.
Devices are discovered via UDP broadcast and hostname scanning, then controlled via TCP.

Key features:
- Persistent connections with automatic reconnection
- Push-style updates when devices change state
- Automatic re-discovery when devices change IP (e.g., after DHCP renewal)
- Graceful handling of offline devices with smart reconnection
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv

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
)
from .coordinator import DeviceCoordinator
from .discovery import async_discover_devices
from .tcp_client import TcpClient
from .udp_discover import get_ip
from .utils import async_get_pid_list

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["light", "switch"]

# Service names
SERVICE_FORCE_RECONNECT = "force_reconnect"
SERVICE_RECONNECT_ALL = "reconnect_all"

# Service schemas
SERVICE_FORCE_RECONNECT_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Optional("ip_address"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the CozyLife Local component.

    Args:
        hass: The Home Assistant instance.
        config: The configuration dictionary.

    Returns:
        True if setup was successful.
    """
    hass.data.setdefault(DOMAIN, {})

    async def handle_force_reconnect(call: ServiceCall) -> None:
        """Handle force_reconnect service call."""
        device_id = call.data.get("device_id")
        ip_address = call.data.get("ip_address")

        if not device_id and not ip_address:
            _LOGGER.warning("force_reconnect requires either device_id or ip_address")
            return

        # Find the device across all config entries
        for entry_data in hass.data[DOMAIN].values():
            if not isinstance(entry_data, dict):
                continue
            coordinator: DeviceCoordinator | None = entry_data.get("coordinator")
            if not coordinator:
                continue

            for client in coordinator.devices.values():
                match = False
                if device_id and client.device_id == device_id:
                    match = True
                elif ip_address and client.ip == ip_address:
                    match = True

                if match:
                    _LOGGER.info(
                        "Force reconnecting device %s at %s",
                        client.device_id,
                        client.ip,
                    )
                    await client.disconnect()
                    await asyncio.sleep(1)
                    if await client.connect(force=True):
                        _LOGGER.info("Device %s reconnected successfully", client.device_id)
                    else:
                        _LOGGER.warning("Device %s failed to reconnect", client.device_id)
                    return

        _LOGGER.warning("Device not found for force_reconnect: device_id=%s, ip=%s", device_id, ip_address)

    async def handle_reconnect_all(call: ServiceCall) -> None:
        """Handle reconnect_all service call."""
        _LOGGER.info("Reconnecting all CozyLife devices...")

        for entry_data in hass.data[DOMAIN].values():
            if not isinstance(entry_data, dict):
                continue
            coordinator: DeviceCoordinator | None = entry_data.get("coordinator")
            if not coordinator:
                continue

            for client in coordinator.devices.values():
                _LOGGER.info("Reconnecting %s at %s", client.device_id, client.ip)
                await client.disconnect()

            await asyncio.sleep(2)

            for client in coordinator.devices.values():
                await client.connect(force=True)

        _LOGGER.info("Reconnect all complete")

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_RECONNECT,
        handle_force_reconnect,
        schema=SERVICE_FORCE_RECONNECT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RECONNECT_ALL,
        handle_reconnect_all,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CozyLife Local from a config entry.

    This function:
    1. Discovers devices via UDP broadcast and hostname scanning
    2. Creates a DeviceCoordinator to manage all devices
    3. Starts persistent connections with automatic reconnection
    4. Sets up background tasks for health checks and re-discovery

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

    # Create the device coordinator
    coordinator = DeviceCoordinator(
        hass,
        connection_timeout=connection_timeout,
        command_timeout=command_timeout,
        response_timeout=response_timeout,
    )

    # Create TCP clients for each discovered IP with configured timeouts
    # Mark devices with configured IPs for aggressive reconnection
    ip_config_set = set(ip_config)  # Set of manually configured IPs
    clients: list[TcpClient] = [
        TcpClient(
            ip,
            hass=hass,
            connection_timeout=connection_timeout,
            command_timeout=command_timeout,
            response_timeout=response_timeout,
            is_configured=(ip in ip_config_set),  # Enable aggressive reconnect for configured IPs
        )
        for ip in ip_list
    ]

    if ip_config_set:
        _LOGGER.info(
            "Configured IPs with aggressive reconnection: %s",
            ", ".join(ip_config_set)
        )

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

    # Filter clients that connected successfully and register with coordinator
    valid_clients: list[TcpClient] = []
    for c in clients:
        if c.device_type_code and c.device_type_code in SUPPORT_DEVICE_CATEGORY:
            # Known supported device type
            await coordinator.add_device(c)
            valid_clients.append(c)
        elif c.device_id and not c.device_type_code:
            # Device connected (has device_id) but type unknown - default to switch
            _LOGGER.info(
                "Device at %s connected but type unknown (ID=%s), will try as switch",
                c.ip,
                c.device_id,
            )
            c._info.device_type_code = "00"  # Default to switch
            await coordinator.add_device(c)
            valid_clients.append(c)
        elif c.available and c.device_id:
            # Device is available and has ID - include it
            await coordinator.add_device(c)
            valid_clients.append(c)

    # Log any unsupported devices for debugging
    unsupported = [c for c in clients if c.device_type_code and c.device_type_code not in SUPPORT_DEVICE_CATEGORY]
    for c in unsupported:
        _LOGGER.warning(
            "Skipping unsupported device type '%s' at IP %s",
            c.device_type_code,
            c.ip,
        )
        await c.disconnect()

    # Log devices that failed to connect
    failed = [c for c in clients if not c.device_id and not c.available]
    for c in failed:
        _LOGGER.warning(
            "Failed to connect to device at %s (last error: %s)",
            c.ip,
            getattr(c, '_last_error', None) or "unknown",
        )

    _LOGGER.info(
        "Found %d valid devices out of %d candidates", len(valid_clients), len(clients)
    )

    # Start the coordinator (starts persistent connections and background tasks)
    await coordinator.start()

    # Get configured scan interval
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    _LOGGER.debug("Using scan interval: %s seconds", scan_interval)

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "tcp_client": valid_clients,  # Keep for backward compatibility with platforms
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

        # Stop the coordinator (stops all background tasks and connections)
        coordinator = entry_data.get("coordinator")
        if coordinator:
            await coordinator.stop()

        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
