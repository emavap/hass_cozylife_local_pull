"""CozyLife Local Pull integration for Home Assistant.

This integration allows local control of CozyLife smart devices without cloud dependency.
Devices are discovered via UDP broadcast and hostname scanning, then controlled via TCP.
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    LANG,
    SUPPORT_DEVICE_CATEGORY,
    CONF_CONNECTION_TIMEOUT,
    CONF_COMMAND_TIMEOUT,
    CONF_RESPONSE_TIMEOUT,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_RESPONSE_TIMEOUT,
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

    # Connect to devices to get info
    if clients:
        connect_tasks = [client.connect() for client in clients]
        await asyncio.gather(*connect_tasks, return_exceptions=True)

    # Filter clients that have valid device info and supported device types
    valid_clients: list[TcpClient] = [
        c for c in clients
        if c.device_type_code and c.device_type_code in SUPPORT_DEVICE_CATEGORY
    ]

    # Log any unsupported devices for debugging
    unsupported = [c for c in clients if c.device_type_code and c.device_type_code not in SUPPORT_DEVICE_CATEGORY]
    for c in unsupported:
        _LOGGER.warning(
            "Skipping unsupported device type '%s' at IP %s",
            c.device_type_code,
            c._ip
        )

    _LOGGER.debug(
        "Found %d valid devices out of %d candidates", len(valid_clients), len(clients)
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "tcp_client": valid_clients,
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
        # Close all TCP connections before removing data
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        clients = entry_data.get("tcp_client", [])
        for client in clients:
            try:
                await client.disconnect()
            except Exception as e:
                _LOGGER.debug("Error disconnecting client: %s", e)

        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
