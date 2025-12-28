"""Base entity for CozyLife devices."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, DPID_SWITCH
from .tcp_client import TcpClient

_LOGGER = logging.getLogger(__name__)


class CozyLifeEntity(Entity):
    """Base representation of a CozyLife device entity."""

    _attr_assumed_state: bool = True  # Use optimistic updates
    _attr_has_entity_name: bool = True

    def __init__(self, tcp_client: TcpClient) -> None:
        """Initialize the entity.

        Args:
            tcp_client: The TCP client for device communication.
        """
        self._tcp_client: TcpClient = tcp_client
        self._unique_id: str = tcp_client.device_id
        # Use model name and type code as the display name
        self._device_name: str = (
            f"{tcp_client.device_model_name} ({tcp_client.device_type_code})"
        )
        # Entity name set to None so HA uses device name directly
        self._attr_name: str | None = None

        # Initialize state
        self._attr_is_on: bool = False
        self._state: dict[str, Any] = {}

        # Device info for HA device registry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tcp_client.device_id)},
            name=self._device_name,
            manufacturer="CozyLife",
            model=tcp_client.device_model_name or self._get_default_model(),
        )

    def _get_default_model(self) -> str:
        """Return the default model name for this entity type.

        Override in subclasses.

        Returns:
            Default model name string.
        """
        return "Device"

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        # Only connect if not already connected (connection happens during setup)
        if not self._tcp_client.is_connected():
            await self._tcp_client.connect()

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

    async def async_update(self) -> None:
        """Query device and update state."""
        self._state = await self._tcp_client.query()
        if self._state:
            # Check if device is on (state key '1' is non-zero)
            self._attr_is_on = bool(self._state.get(DPID_SWITCH, 0))

    async def _async_send_command(self, payload: dict[str, Any]) -> bool:
        """Send a control command to the device.

        Args:
            payload: The command payload.

        Returns:
            True if the command was successful.
        """
        return await self._tcp_client.control(payload)

