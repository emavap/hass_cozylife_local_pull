"""Example Load Platform integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
import logging
import asyncio
from .const import (
    DOMAIN,
    LANG
)
from .utils import async_get_pid_list
from .udp_discover import get_ip
from .discovery import async_discover_devices
from .tcp_client import tcp_client


_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["light", "switch"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the CozyLife Local component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CozyLife Local from a config entry."""
    _LOGGER.debug('async_setup_entry start')
    
    # UDP Discovery (run in executor)
    ip_udp = await hass.async_add_executor_job(get_ip)
    
    # Hostname Discovery
    ip_hostname = await async_discover_devices(hass)
    
    # Config IPs
    ip_config_str = entry.data.get('ips', '')
    ip_config = [ip.strip() for ip in ip_config_str.split(',') if ip.strip()]
    
    # Merge IPs
    ip_list = list(set(ip_udp + ip_hostname + ip_config))

    if 0 == len(ip_list):
        _LOGGER.info('Discovery found no devices, but integration will load. Check logs for details.')
        # We continue to allow the integration to load even if no devices found initially
    
    _LOGGER.debug(f'try connect ip_list: {ip_list}')
    await async_get_pid_list(LANG)

    clients = [tcp_client(item) for item in ip_list]
    
    # Connect to devices to get info
    if clients:
        connect_tasks = [client.connect() for client in clients]
        await asyncio.gather(*connect_tasks)
    
    # Filter clients that have valid device info
    valid_clients = [c for c in clients if c.device_type_code]
    
    _LOGGER.debug(f"Found {len(valid_clients)} valid devices out of {len(clients)} candidates")

    hass.data[DOMAIN][entry.entry_id] = {
        'tcp_client': valid_clients,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
