"""Platform for sensor integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.light import LightEntity
# from homeassistant.components.light import *
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from typing import Any
from .const import (
    DOMAIN,
    LIGHT_TYPE_CODE,
)
from .tcp_client import tcp_client
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the CozyLife Light from a config entry."""
    lights = []
    for item in hass.data[DOMAIN][config_entry.entry_id]['tcp_client']:
        if LIGHT_TYPE_CODE == item.device_type_code:
            lights.append(CozyLifeLight(item))
    
    async_add_entities(lights)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the sensor platform."""
    # We only want this platform to be set up via discovery.
    _LOGGER.info(
        f'setup_platform.hass={hass},config={config},add_entities={async_add_entities},discovery_info={discovery_info}')
    
    if discovery_info is None:
        return
    
    # This legacy method might fail if hass.data[DOMAIN] is not populated as expected
    # But we keep it for reference or if we decide to support legacy setup later.
    if 'tcp_client' in hass.data[DOMAIN]:
        lights = []
        for item in hass.data[DOMAIN]['tcp_client']:
            if LIGHT_TYPE_CODE == item.device_type_code:
                lights.append(CozyLifeLight(item))
        
        async_add_entities(lights)


class CozyLifeLight(LightEntity):
    _tcp_client = None
    
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_min_color_temp_kelvin = 2000
    _attr_max_color_temp_kelvin = 6500
    
    def __init__(self, tcp_client: tcp_client) -> None:
        """Initialize the sensor."""
        _LOGGER.info('__init__')
        self._tcp_client = tcp_client
        self._unique_id = tcp_client.device_id
        self._name = tcp_client.device_model_name + ' ' + tcp_client.device_id[-4:]
        
    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await self._tcp_client.connect()
        self._update_features()
        
    def _update_features(self):
        _LOGGER.info(f'before:{self._unique_id}._attr_color_mode={self._attr_color_mode}._attr_supported_color_modes='
                     f'{self._attr_supported_color_modes}.dpid={self._tcp_client.dpid}')
        
        supported = {ColorMode.BRIGHTNESS}
        if '3' in self._tcp_client.dpid:
            supported.add(ColorMode.COLOR_TEMP)
        
        if '5' in self._tcp_client.dpid or '6' in self._tcp_client.dpid:
            supported.add(ColorMode.HS)
            
        # Clean up supported modes
        if ColorMode.HS in supported:
            if ColorMode.BRIGHTNESS in supported:
                supported.remove(ColorMode.BRIGHTNESS)
            self._attr_color_mode = ColorMode.HS
        elif ColorMode.COLOR_TEMP in supported:
            if ColorMode.BRIGHTNESS in supported:
                supported.remove(ColorMode.BRIGHTNESS)
            self._attr_color_mode = ColorMode.COLOR_TEMP
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS

        self._attr_supported_color_modes = supported
        
        _LOGGER.info(f'after:{self._unique_id}._attr_color_mode={self._attr_color_mode}._attr_supported_color_modes='
                     f'{self._attr_supported_color_modes}.dpid={self._tcp_client.dpid}')
    
    async def async_update(self):
        """
        query device & set attr
        :return:
        """
        self._state = await self._tcp_client.query()
        _LOGGER.debug(f'_state={self._state}')
        
        if not self._state:
            return

        self._attr_is_on = 0 < self._state.get('1', 0)
        
        if '4' in self._state:
            self._attr_brightness = int(self._state['4'] / 4)
        
        if '5' in self._state:
            self._attr_hs_color = (int(self._state['5']), int(self._state['6'] / 10))
        
        if '3' in self._state:
            # 0-1000 map to 500-153 mireds (2000K-6500K)
            # mireds = 500 - (value / 2)
            mireds = 500 - int(self._state['3'] / 2)
            self._attr_color_temp = mireds
            if mireds > 0:
                self._attr_color_temp_kelvin = int(1000000 / mireds)
    
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
    def color_temp_kelvin(self) -> int | None:
        """Return the CT color value in Kelvin."""
        return self._attr_color_temp_kelvin

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._unique_id

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._attr_is_on = True
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        # 153 ~ 500
        colortemp_kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        # tuple
        hs_color = kwargs.get(ATTR_HS_COLOR)
        
        _LOGGER.info(f'turn_on.kwargs={kwargs}')
        
        payload = {'1': 255, '2': 0}
        if brightness is not None:
            payload['4'] = brightness * 4
            self._attr_brightness = brightness
        
        if hs_color is not None:
            payload['5'] = int(hs_color[0])
            payload['6'] = int(hs_color[1] * 10)
            self._attr_hs_color = hs_color
        
        if colortemp_kelvin is not None:
            # mireds = 1000000 / kelvin
            # value = 1000 - mireds * 2
            mireds = 1000000 / colortemp_kelvin
            val = int(1000 - mireds * 2)
            if val < 0: val = 0
            if val > 1000: val = 1000
            payload['3'] = val
        
        await self._tcp_client.control(payload)
        await self.async_update()
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False
        _LOGGER.info(f'turn_off.kwargs={kwargs}')
        await self._tcp_client.control({'1': 0})
        await self.async_update()
    
    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value [float, float]."""
        return self._attr_hs_color
    
    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        return self._attr_brightness
    
    @property
    def color_mode(self) -> str | None:
        """Return the color mode of the light."""
        return self._attr_color_mode
    
    # def set_brightness(self, b):
    #     _LOGGER.info('set_brightness')
    #
    #     self._attr_brightness = b
    #
    # def set_hs(self, hs_color, duration) -> None:
    #     """Set bulb's color."""
    #     _LOGGER.info('set_hs')
    #     self._attr_hs_color = (hs_color[0], hs_color[1])
