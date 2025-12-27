"""Platform for CozyLife switch integration."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from typing import Any, Dict, Optional
from .const import (
    DOMAIN,
    SWITCH_TYPE_CODE,
)
from .tcp_client import TcpClient
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the CozyLife Switch from a config entry."""
    switches = []
    for item in hass.data[DOMAIN][config_entry.entry_id]['tcp_client']:
        if SWITCH_TYPE_CODE == item.device_type_code:
            switches.append(CozyLifeSwitch(item))

    async_add_entities(switches)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None
) -> None:
    """Set up the switch platform (legacy method)."""
    _LOGGER.debug(f'setup_platform called with discovery_info={discovery_info}')

    if discovery_info is None:
        return

    if 'tcp_client' in hass.data[DOMAIN]:
        switches = []
        for item in hass.data[DOMAIN]['tcp_client']:
            if SWITCH_TYPE_CODE == item.device_type_code:
                switches.append(CozyLifeSwitch(item))

        async_add_entities(switches)


class CozyLifeSwitch(SwitchEntity):
    """Representation of a CozyLife switch."""

    _attr_assumed_state: bool = True  # Use optimistic updates
    _attr_has_entity_name: bool = True

    def __init__(self, tcp_client: TcpClient) -> None:
        """Initialize the switch entity.

        Args:
            tcp_client: The TCP client for device communication.
        """
        _LOGGER.debug(f'Initializing CozyLifeSwitch for device {tcp_client.device_id}')
        self._tcp_client: TcpClient = tcp_client
        self._unique_id: str = tcp_client.device_id
        # Use user-given name if available, otherwise fall back to model name
        self._device_name: str = (
            tcp_client.device_name
            or tcp_client.device_model_name
            or "CozyLife Switch"
        )
        # Entity name set to None so HA uses device name directly
        self._attr_name: Optional[str] = None

        # Initialize state attributes
        self._attr_is_on: bool = False
        self._state: Dict[str, Any] = {}

        # Device info for HA device registry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tcp_client.device_id)},
            name=self._device_name,
            manufacturer="CozyLife",
            model=tcp_client.device_model_name or "Switch",
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await self._tcp_client.connect()
        await self.async_update()

    async def async_update(self) -> None:
        """Query device and update state."""
        self._state = await self._tcp_client.query()
        if self._state:
            self._attr_is_on = self._state.get('1', 0) != 0

    @property
    def available(self) -> bool:
        """Return if the device is available."""
        return self._tcp_client.available

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self._attr_is_on

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        _LOGGER.debug(f'turn_on:{kwargs}')

        # Send control command - now waits for confirmation
        success = await self._tcp_client.control({'1': 255})

        if success:
            # Update local state optimistically
            self._attr_is_on = True
            # State will be synced on next poll - no need for immediate async_update
            self.async_write_ha_state()
        else:
            _LOGGER.warning(f"Failed to turn on {self._device_name}")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        _LOGGER.debug(f'turn_off:{kwargs}')

        # Send control command - now waits for confirmation
        success = await self._tcp_client.control({'1': 0})

        if success:
            # Update local state optimistically
            self._attr_is_on = False
            # State will be synced on next poll - no need for immediate async_update
            self.async_write_ha_state()
        else:
            _LOGGER.warning(f"Failed to turn off {self._device_name}")
