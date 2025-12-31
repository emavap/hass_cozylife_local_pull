"""Platform for CozyLife switch integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    SWITCH_TYPE_CODE,
    DPID_SWITCH,
    DEFAULT_SCAN_INTERVAL,
)
from .entity import CozyLifeEntity
from .tcp_client import TcpClient

_LOGGER = logging.getLogger(__name__)

# Will be set dynamically based on config
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the CozyLife Switch from a config entry."""
    # Get configured scan interval
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    scan_interval = entry_data.get("scan_interval", DEFAULT_SCAN_INTERVAL)

    # Update module-level SCAN_INTERVAL for Home Assistant polling
    global SCAN_INTERVAL
    SCAN_INTERVAL = timedelta(seconds=scan_interval)
    _LOGGER.debug("Switch platform using scan interval: %s seconds", scan_interval)

    switches = [
        CozyLifeSwitch(client)
        for client in entry_data["tcp_client"]
        if client.device_type_code == SWITCH_TYPE_CODE
    ]
    async_add_entities(switches, update_before_add=True)


class CozyLifeSwitch(CozyLifeEntity, SwitchEntity):
    """Representation of a CozyLife switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_assumed_state = False  # We query actual device state, not assumed

    def __init__(self, tcp_client: TcpClient) -> None:
        """Initialize the switch entity.

        Args:
            tcp_client: The TCP client for device communication.
        """
        super().__init__(tcp_client)
        _LOGGER.debug("Initializing CozyLifeSwitch for device %s", tcp_client.device_id)

    def _get_default_model(self) -> str:
        """Return the default model name for switches."""
        return "Switch"

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        await self.async_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        _LOGGER.debug("turn_on: %s", kwargs)

        success = await self._async_send_command({DPID_SWITCH: 255})

        if success:
            # Query actual state from device instead of assuming
            await self.async_update()
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to turn on %s", self._device_name)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        _LOGGER.debug("turn_off: %s", kwargs)

        success = await self._async_send_command({DPID_SWITCH: 0})

        if success:
            # Query actual state from device instead of assuming
            await self.async_update()
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to turn off %s", self._device_name)
