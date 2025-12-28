"""Platform for CozyLife light integration."""
from __future__ import annotations

import logging
from typing import Any

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

from .const import (
    DOMAIN,
    LIGHT_TYPE_CODE,
    DPID_TEMP,
    DPID_BRIGHT,
    DPID_HUE,
    DPID_SAT,
    DPID_SWITCH,
    DPID_WORK_MODE,
    SATURATION_SCALE,
    MIN_COLOR_TEMP_KELVIN,
    MAX_COLOR_TEMP_KELVIN,
)
from .entity import CozyLifeEntity
from .tcp_client import TcpClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the CozyLife Light from a config entry."""
    lights = [
        CozyLifeLight(client)
        for client in hass.data[DOMAIN][config_entry.entry_id]["tcp_client"]
        if client.device_type_code == LIGHT_TYPE_CODE
    ]
    async_add_entities(lights)


class CozyLifeLight(CozyLifeEntity, LightEntity):
    """Representation of a CozyLife light."""

    _attr_min_color_temp_kelvin: int = MIN_COLOR_TEMP_KELVIN
    _attr_max_color_temp_kelvin: int = MAX_COLOR_TEMP_KELVIN
    _attr_assumed_state = False  # We query actual device state, not assumed

    def __init__(self, tcp_client: TcpClient) -> None:
        """Initialize the light entity.

        Args:
            tcp_client: The TCP client for device communication.
        """
        super().__init__(tcp_client)
        _LOGGER.debug("Initializing CozyLifeLight for device %s", tcp_client.device_id)

        # Light-specific state attributes
        self._attr_brightness: int | None = None
        self._attr_hs_color: tuple[float, float] | None = None
        self._attr_color_temp: int | None = None
        self._attr_color_temp_kelvin: int | None = None
        self._attr_supported_color_modes: set[ColorMode] = {ColorMode.BRIGHTNESS}
        self._attr_color_mode: ColorMode = ColorMode.BRIGHTNESS

    def _get_default_model(self) -> str:
        """Return the default model name for lights."""
        return "Light"

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        self._update_features()
        # Fetch initial state from device
        await self.async_update()

    def _update_features(self) -> None:
        """Update supported features based on device capabilities."""
        dpid = self._tcp_client.dpid
        _LOGGER.debug(
            "Before update: %s color_mode=%s, supported=%s, dpid=%s",
            self._unique_id,
            self._attr_color_mode,
            self._attr_supported_color_modes,
            dpid,
        )

        supported: set[ColorMode] = {ColorMode.BRIGHTNESS}
        if DPID_TEMP in dpid:
            supported.add(ColorMode.COLOR_TEMP)

        if DPID_HUE in dpid or DPID_SAT in dpid:
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
            "After update: %s color_mode=%s, supported=%s",
            self._unique_id,
            self._attr_color_mode,
            self._attr_supported_color_modes,
        )

    async def async_update(self) -> None:
        """Query device and update attributes."""
        self._state = await self._tcp_client.query()
        _LOGGER.debug("Light state: %s", self._state)

        if not self._state:
            return

        # Check if device is on (non-zero value)
        self._attr_is_on = bool(self._state.get(DPID_SWITCH, 0))

        if DPID_BRIGHT in self._state:
            # Device uses 0-1000, HA uses 0-255
            # Use proper rounding for accurate mapping
            device_brightness = self._state[DPID_BRIGHT]
            self._attr_brightness = min(round(device_brightness * 255 / 1000), 255)

        if DPID_HUE in self._state and DPID_SAT in self._state:
            self._attr_hs_color = (
                float(self._state[DPID_HUE]),
                float(self._state[DPID_SAT]) / SATURATION_SCALE,
            )

        if DPID_TEMP in self._state:
            # 0-1000 map to 500-153 mireds (2000K-6500K)
            # mireds = 500 - (value / 2)
            mireds = 500 - int(self._state[DPID_TEMP] / 2)
            # Clamp mireds to valid range (153-500 for 2000K-6500K)
            mireds = max(153, min(500, mireds))
            self._attr_color_temp = mireds
            # Prevent division by zero
            self._attr_color_temp_kelvin = int(1000000 / max(mireds, 1))

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the CT color value in Kelvin."""
        return self._attr_color_temp_kelvin

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        brightness: int | None = kwargs.get(ATTR_BRIGHTNESS)
        colortemp_kelvin: int | None = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        hs_color: tuple[float, float] | None = kwargs.get(ATTR_HS_COLOR)

        _LOGGER.debug("turn_on kwargs=%s", kwargs)

        payload: dict[str, int] = {DPID_SWITCH: 255, DPID_WORK_MODE: 0}

        if brightness is not None:
            # Clamp to valid range (0-1000) to prevent overflow
            # brightness is 0-255, device expects 0-1000
            device_brightness = min(int(brightness * 1000 / 255), 1000)
            payload[DPID_BRIGHT] = device_brightness

        if hs_color is not None:
            payload[DPID_HUE] = int(hs_color[0])
            payload[DPID_SAT] = int(hs_color[1] * SATURATION_SCALE)

        if colortemp_kelvin is not None:
            # mireds = 1000000 / kelvin
            # value = 1000 - mireds * 2
            # Prevent division by zero
            safe_kelvin = max(colortemp_kelvin, 1)
            mireds = 1000000 / safe_kelvin
            val = max(0, min(1000, int(1000 - mireds * 2)))
            payload[DPID_TEMP] = val

        # Send control command
        success = await self._async_send_command(payload)

        if success:
            # Query actual state from device instead of assuming
            await self.async_update()
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to turn on %s", self._device_name)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        _LOGGER.debug("turn_off kwargs=%s", kwargs)

        success = await self._async_send_command({DPID_SWITCH: 0})

        if success:
            # Query actual state from device instead of assuming
            await self.async_update()
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to turn off %s", self._device_name)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value [float, float]."""
        return self._attr_hs_color

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        return self._attr_brightness

    @property
    def color_mode(self) -> ColorMode | None:
        """Return the color mode of the light."""
        return self._attr_color_mode
