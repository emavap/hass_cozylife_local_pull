"""Platform for sensor integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from typing import Any, Final, Literal, TypedDict, final
from .const import (
    DOMAIN,
    SWITCH_TYPE_CODE,
    LIGHT_TYPE_CODE,
    LIGHT_DPID,
    SWITCH,
    WORK_MODE,
    TEMP,
    BRIGHT,
    HUE,
    SAT,
)
import logging

_LOGGER = logging.getLogger(__name__)
_LOGGER.info('switch')


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the CozyLife Switch from a config entry."""
    switchs = []
    for item in hass.data[DOMAIN][config_entry.entry_id]['tcp_client']:
        if SWITCH_TYPE_CODE == item.device_type_code:
            switchs.append(CozyLifeSwitch(item))
    
    async_add_entities(switchs)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the sensor platform."""
    # We only want this platform to be set up via discovery.
    _LOGGER.info('setup_platform')
    _LOGGER.info(f'ip={hass.data[DOMAIN]}')
    
    if discovery_info is None:
        return

    if 'tcp_client' in hass.data[DOMAIN]:
        switchs = []
        for item in hass.data[DOMAIN]['tcp_client']:
            if SWITCH_TYPE_CODE == item.device_type_code:
                switchs.append(CozyLifeSwitch(item))
        
        async_add_entities(switchs)


class CozyLifeSwitch(SwitchEntity):
    _tcp_client = None
    _attr_is_on = True
    
    def __init__(self, tcp_client) -> None:
        """Initialize the sensor."""
        _LOGGER.info('__init__')
        self._tcp_client = tcp_client
        self._unique_id = tcp_client.device_id
        self._name = tcp_client.device_model_name + ' ' + tcp_client.device_id[-4:]
        
    async def async_added_to_hass(self) -> None:
        await self._tcp_client.connect()
        await self.async_update()
    
    async def async_update(self):
        self._state = await self._tcp_client.query()
        if self._state:
            self._attr_is_on = 0 != self._state.get('1', 0)
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def available(self) -> bool:
        """Return if the device is available."""
        return True
    
    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self._attr_is_on
    
    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._unique_id
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._attr_is_on = True
        _LOGGER.info(f'turn_on:{kwargs}')
        await self._tcp_client.control({'1': 255})
        await self.async_update()
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False
        await self._tcp_client.control({'1': 0})
        await self.async_update()
        _LOGGER.info('turn_off')
        self._tcp_client.control({'1': 0})
        return None
        
        raise NotImplementedError()
