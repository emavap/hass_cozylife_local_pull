"""Example Load Platform integration."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.typing import ConfigType
import logging
import asyncio
from .const import (
    DOMAIN,
    LANG
)
from .utils import get_pid_list
from .udp_discover import get_ip
from .discovery import async_discover_devices
from .tcp_client import tcp_client


_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    
    """
    config:{'lang': 'zh', 'ip': ['192.168.5.201', '192.168.5.202', '192.168.5.1']}
}
    """
    _LOGGER.info('async_setup start')
    
    # UDP Discovery (run in executor)
    ip_udp = await hass.async_add_executor_job(get_ip)
    
    # Hostname Discovery
    ip_hostname = await async_discover_devices(hass)
    
    # Config IPs
    ip_config = config[DOMAIN].get('ip') if config[DOMAIN].get('ip') is not None else []
    
    # Merge IPs
    ip_list = list(set(ip_udp + ip_hostname + ip_config))

    if 0 == len(ip_list):
        _LOGGER.info('discover nothing')
        return True

    _LOGGER.info(f'try connect ip_list: {ip_list}')
    lang_from_config = (config[DOMAIN].get('lang') if config[DOMAIN].get('lang') is not None else LANG)
    get_pid_list(lang_from_config)

    clients = [tcp_client(item) for item in ip_list]
    
    # Connect to devices to get info
    connect_tasks = [client.connect() for client in clients]
    await asyncio.gather(*connect_tasks)
    
    # Filter clients that have valid device info
    valid_clients = [c for c in clients if c.device_type_code]

    hass.data[DOMAIN] = {
        'temperature': 24,
        'ip': ip_list,
        'tcp_client': valid_clients,
    }

    hass.async_create_task(async_load_platform(hass, 'light', DOMAIN, {}, config))
    hass.async_create_task(async_load_platform(hass, 'switch', DOMAIN, {}, config))
    return True
