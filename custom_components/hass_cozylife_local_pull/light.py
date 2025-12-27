"""Platform for CozyLife light integration."""
from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from typing import Any, Optional, Set, Tuple, Dict
from .const import (
    DOMAIN,
    LIGHT_TYPE_CODE,
)
from .tcp_client import TcpClient
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
    """Representation of a CozyLife light."""

    _attr_min_color_temp_kelvin: int = 2000
    _attr_max_color_temp_kelvin: int = 6500
    _attr_assumed_state: bool = True  # Use optimistic updates
    _attr_has_entity_name: bool = True

    def __init__(self, tcp_client: TcpClient) -> None:
        """Initialize the light entity.

        Args:
            tcp_client: The TCP client for device communication.
        """
        _LOGGER.debug(f'Initializing CozyLifeLight for device {tcp_client.device_id}')
        self._tcp_client: TcpClient = tcp_client
        self._unique_id: str = tcp_client.device_id
        # Entity name - will be combined with device name by HA
        self._attr_name: Optional[str] = "Light"
        # Device name for the registry
        self._device_name: str = f"{tcp_client.device_model_name} {tcp_client.device_id[-4:]}"

        # Initialize state attributes
        self._attr_is_on: bool = False
        self._attr_brightness: Optional[int] = None
        self._attr_hs_color: Optional[Tuple[float, float]] = None
        self._attr_color_temp: Optional[int] = None
        self._attr_color_temp_kelvin: Optional[int] = None
        self._attr_supported_color_modes: Set[ColorMode] = {ColorMode.BRIGHTNESS}
        self._attr_color_mode: ColorMode = ColorMode.BRIGHTNESS
        self._state: Dict[str, Any] = {}

        # Device info for HA device registry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tcp_client.device_id)},
            name=self._device_name,
            manufacturer="CozyLife",
            model=tcp_client.device_model_name or "Light",
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await self._tcp_client.connect()
        self._update_features()

    def _update_features(self) -> None:
        """Update supported features based on device capabilities."""
        _LOGGER.debug(
            f'before:{self._unique_id}._attr_color_mode={self._attr_color_mode}.'
            f'_attr_supported_color_modes={self._attr_supported_color_modes}.'
            f'dpid={self._tcp_client.dpid}'
        )

        supported: Set[ColorMode] = {ColorMode.BRIGHTNESS}
        if '3' in self._tcp_client.dpid:
            supported.add(ColorMode.COLOR_TEMP)

        if '5' in self._tcp_client.dpid or '6' in self._tcp_client.dpid:
            supported.add(ColorMode.HS)

        # Clean up supported modes - HS and COLOR_TEMP imply brightness
        if ColorMode.HS in supported:
            supported.discard(ColorMode.BRIGHTNESS)
            self._attr_color_mode = ColorMode.HS
        elif ColorMode.COLOR_TEMP in supported:
            supported.discard(ColorMode.BRIGHTNESS)
            self._attr_color_mode = ColorMode.COLOR_TEMP
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS

        self._attr_supported_color_modes = supported

        _LOGGER.debug(
            f'after:{self._unique_id}._attr_color_mode={self._attr_color_mode}.'
            f'_attr_supported_color_modes={self._attr_supported_color_modes}.'
            f'dpid={self._tcp_client.dpid}'
        )
    
    async def async_update(self) -> None:
        """Query device and update attributes."""
        self._state = await self._tcp_client.query()
        _LOGGER.debug(f'_state={self._state}')

        if not self._state:
            return

        self._attr_is_on = self._state.get('1', 0) > 0

        if '4' in self._state:
            self._attr_brightness = int(self._state['4'] / 4)

        if '5' in self._state and '6' in self._state:
            self._attr_hs_color = (
                float(self._state['5']),
                float(self._state['6']) / 10
            )

        if '3' in self._state:
            # 0-1000 map to 500-153 mireds (2000K-6500K)
            # mireds = 500 - (value / 2)
            mireds = 500 - int(self._state['3'] / 2)
            # Clamp mireds to valid range (153-500 for 2000K-6500K)
            mireds = max(153, min(500, mireds))
            self._attr_color_temp = mireds
            self._attr_color_temp_kelvin = int(1000000 / mireds)

    @property
    def available(self) -> bool:
        """Return if the device is available."""
        return self._tcp_client.available

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self._attr_is_on

    @property
    def color_temp_kelvin(self) -> Optional[int]:
        """Return the CT color value in Kelvin."""
        return self._attr_color_temp_kelvin

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        brightness: Optional[int] = kwargs.get(ATTR_BRIGHTNESS)
        colortemp_kelvin: Optional[int] = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        hs_color: Optional[Tuple[float, float]] = kwargs.get(ATTR_HS_COLOR)

        _LOGGER.debug(f'turn_on.kwargs={kwargs}')

        payload: Dict[str, int] = {'1': 255, '2': 0}
        if brightness is not None:
            payload['4'] = brightness * 4

        if hs_color is not None:
            payload['5'] = int(hs_color[0])
            payload['6'] = int(hs_color[1] * 10)

        if colortemp_kelvin is not None:
            # mireds = 1000000 / kelvin
            # value = 1000 - mireds * 2
            mireds = 1000000 / colortemp_kelvin
            val = max(0, min(1000, int(1000 - mireds * 2)))
            payload['3'] = val

        # Send control command - now waits for confirmation
        success = await self._tcp_client.control(payload)

        if success:
            # Update local state optimistically
            self._attr_is_on = True
            if brightness is not None:
                self._attr_brightness = brightness
            if hs_color is not None:
                self._attr_hs_color = hs_color
            if colortemp_kelvin is not None:
                self._attr_color_temp_kelvin = colortemp_kelvin
            # State will be synced on next poll - no need for immediate async_update
            self.async_write_ha_state()
        else:
            _LOGGER.warning(f"Failed to turn on {self._device_name}")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        _LOGGER.debug(f'turn_off.kwargs={kwargs}')

        # Send control command - now waits for confirmation
        success = await self._tcp_client.control({'1': 0})

        if success:
            # Update local state optimistically
            self._attr_is_on = False
            # State will be synced on next poll - no need for immediate async_update
            self.async_write_ha_state()
        else:
            _LOGGER.warning(f"Failed to turn off {self._device_name}")

    @property
    def hs_color(self) -> Optional[Tuple[float, float]]:
        """Return the hue and saturation color value [float, float]."""
        return self._attr_hs_color

    @property
    def brightness(self) -> Optional[int]:
        """Return the brightness of this light between 0..255."""
        return self._attr_brightness

    @property
    def color_mode(self) -> Optional[ColorMode]:
        """Return the color mode of the light."""
        return self._attr_color_mode
