"""Base entity for CozyLife devices."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import (
    DOMAIN,
    DPID_SWITCH,
    DEFAULT_SCAN_INTERVAL,
    SIGNAL_DEVICE_STATE,
    SIGNAL_DEVICE_CONNECTED,
    SIGNAL_DEVICE_DISCONNECTED,
    DEVICE_STATE_ONLINE,
    DEVICE_STATE_OFFLINE,
)
from .tcp_client import TcpClient

_LOGGER = logging.getLogger(__name__)

# Default scan interval - can be overridden per entity
# With dispatcher pattern, polling is less critical but still useful as fallback
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)


class CozyLifeEntity(Entity):
    """Base representation of a CozyLife device entity.

    This entity uses the dispatcher pattern to receive push updates from
    the device coordinator. When the device sends state updates, they are
    dispatched to this entity without needing to poll.

    Polling is still enabled as a fallback for devices that don't push
    updates frequently.
    """

    _attr_has_entity_name: bool = True
    _attr_should_poll: bool = True  # Keep polling as fallback

    def __init__(self, tcp_client: TcpClient) -> None:
        """Initialize the entity.

        Args:
            tcp_client: The TCP client for device communication.
        """
        self._tcp_client: TcpClient = tcp_client
        self._unique_id: str = tcp_client.device_id
        # Use user-given device name if available, otherwise just model name
        if tcp_client.device_name:
            self._device_name: str = tcp_client.device_name
        elif tcp_client.device_model_name:
            self._device_name = tcp_client.device_model_name
        else:
            self._device_name = f"CozyLife {tcp_client.device_id[:8]}"
        # Entity name set to None so HA uses device name directly
        self._attr_name: str | None = None

        # Initialize state
        self._attr_is_on: bool = False
        self._state: dict[str, Any] = {}

        # Dispatcher unsubscribe callbacks
        self._unsub_state: Callable[[], None] | None = None
        self._unsub_connected: Callable[[], None] | None = None
        self._unsub_disconnected: Callable[[], None] | None = None

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
        """Run when entity about to be added to hass.

        Subscribe to dispatcher signals for push updates.
        """
        # Subscribe to state updates
        device_id = self._tcp_client.device_id
        self._unsub_state = async_dispatcher_connect(
            self.hass,
            f"{SIGNAL_DEVICE_STATE}_{device_id}",
            self._handle_state_update,
        )

        # Subscribe to connection events
        self._unsub_connected = async_dispatcher_connect(
            self.hass,
            f"{SIGNAL_DEVICE_CONNECTED}_{device_id}",
            self._handle_device_connected,
        )
        self._unsub_disconnected = async_dispatcher_connect(
            self.hass,
            f"{SIGNAL_DEVICE_DISCONNECTED}_{device_id}",
            self._handle_device_disconnected,
        )

        # Only connect if not already connected (connection happens during setup)
        if not self._tcp_client.is_connected():
            await self._tcp_client.connect()

        # Initialize with last known state if available
        # Only process if it's a real dict (not a mock or None)
        last_state = self._tcp_client.last_state
        if last_state and isinstance(last_state, dict):
            self._process_state_update(last_state)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is about to be removed from hass.

        Unsubscribe from dispatcher signals.
        """
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_connected:
            self._unsub_connected()
            self._unsub_connected = None
        if self._unsub_disconnected:
            self._unsub_disconnected()
            self._unsub_disconnected = None

    def _process_state_update(self, state: dict[str, Any]) -> None:
        """Process state update without writing to HA.

        This updates internal state but doesn't trigger HA state write.
        Used during initialization before entity is fully registered.

        Args:
            state: The new state dictionary.
        """
        if not state or not isinstance(state, dict):
            return

        self._state.update(state)
        # Check if device is on (state key '1' is non-zero)
        self._attr_is_on = bool(self._state.get(DPID_SWITCH, 0))
        _LOGGER.debug(
            "State update for %s: is_on=%s, state=%s",
            self._device_name,
            self._attr_is_on,
            state,
        )

    @callback
    def _handle_state_update(self, state: dict[str, Any]) -> None:
        """Handle state update from dispatcher.

        This is called when the device pushes a state update.
        Override in subclasses to handle specific state processing.

        Args:
            state: The new state dictionary.
        """
        if not state or not isinstance(state, dict):
            return

        self._process_state_update(state)
        self.async_write_ha_state()

    @callback
    def _handle_device_connected(self) -> None:
        """Handle device reconnection event."""
        _LOGGER.info("Device %s reconnected", self._device_name)
        self.async_write_ha_state()

    @callback
    def _handle_device_disconnected(self) -> None:
        """Handle device disconnection event."""
        _LOGGER.info("Device %s disconnected", self._device_name)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if the device is available.

        Uses the device state from TcpClient to determine availability.
        Falls back to the legacy available flag for backward compatibility.
        """
        # Check new device_state property if it exists and is a valid state
        device_state = getattr(self._tcp_client, 'device_state', None)
        if device_state is not None and isinstance(device_state, str):
            return device_state == DEVICE_STATE_ONLINE
        # Fall back to legacy available flag
        return bool(getattr(self._tcp_client, 'available', False))

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self._attr_is_on

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    async def async_update(self) -> None:
        """Query device and update state.

        This is called by Home Assistant's polling mechanism as a fallback.
        With the dispatcher pattern, most updates come via push, but polling
        ensures we catch any missed updates.
        """
        # If device is unavailable, don't poll - let the reconnect logic handle it
        if not self.available:
            _LOGGER.debug(
                "Device %s unavailable, skipping poll update", self._device_name
            )
            return

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

