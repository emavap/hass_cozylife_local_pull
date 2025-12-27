"""CozyLife Local Pull integration for Home Assistant.

This integration allows local control of CozyLife smart devices without cloud dependency.
Devices are discovered via UDP broadcast and hostname scanning, then controlled via TCP.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
import logging
import asyncio
from typing import List
from .const import (
    DOMAIN,
    LANG
)
from .utils import async_get_pid_list
from .udp_discover import get_ip
from .discovery import async_discover_devices
from .tcp_client import TcpClient


_LOGGER = logging.getLogger(__name__)
PLATFORMS: List[str] = ["light", "switch"]


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
    _LOGGER.debug('async_setup_entry start')

    # Ensure domain data is initialized
    hass.data.setdefault(DOMAIN, {})

    # UDP Discovery (run in executor to avoid blocking)
    ip_udp: List[str] = await hass.async_add_executor_job(get_ip)

    # Hostname Discovery
    ip_hostname: List[str] = await async_discover_devices(hass)

    # Config IPs (manually specified)
    ip_config_str: str = entry.data.get('ips', '')
    ip_config: List[str] = [ip.strip() for ip in ip_config_str.split(',') if ip.strip()]

    # Merge and deduplicate IPs
    ip_list: List[str] = list(set(ip_udp + ip_hostname + ip_config))

    if not ip_list:
        _LOGGER.info('Discovery found no devices, but integration will load. Check logs for details.')

    _LOGGER.debug(f'Attempting to connect to ip_list: {ip_list}')

    # Pre-fetch PID list for device identification
    await async_get_pid_list(LANG)

    # Create TCP clients for each discovered IP
    clients: List[TcpClient] = [TcpClient(ip) for ip in ip_list]

    # Connect to devices to get info
    if clients:
        connect_tasks = [client.connect() for client in clients]
        await asyncio.gather(*connect_tasks, return_exceptions=True)

    # Filter clients that have valid device info
    valid_clients: List[TcpClient] = [c for c in clients if c.device_type_code]

    _LOGGER.debug(f"Found {len(valid_clients)} valid devices out of {len(clients)} candidates")

    hass.data[DOMAIN][entry.entry_id] = {
        'tcp_client': valid_clients,
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
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
