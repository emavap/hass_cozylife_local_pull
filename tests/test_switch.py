"""Tests for switch entity."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.hass_cozylife_local_pull.switch import CozyLifeSwitch
from custom_components.hass_cozylife_local_pull.tcp_client import tcp_client


@pytest.mark.unit
@pytest.mark.asyncio
class TestCozyLifeSwitch:
    """Test CozyLife switch entity."""

    @pytest.fixture
    def mock_tcp_client(self):
        """Create a mock TCP client."""
        client = MagicMock(spec=tcp_client)
        client.device_id = "test_switch_456"
        client.device_model_name = "Test Switch"
        client.dpid = ['1']
        client.available = True
        client.connect = AsyncMock(return_value=True)
        client.query = AsyncMock(return_value={'1': 255})
        client.control = AsyncMock(return_value=True)
        return client

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))
        return hass

    async def test_switch_init(self, mock_tcp_client):
        """Test switch initialization."""
        switch = CozyLifeSwitch(mock_tcp_client)

        assert switch._tcp_client == mock_tcp_client
        assert switch._unique_id == "test_switch_456"
        assert "Test Switch" in switch._device_name

    async def test_switch_added_to_hass(self, mock_tcp_client, mock_hass):
        """Test switch added to Home Assistant."""
        switch = CozyLifeSwitch(mock_tcp_client)
        switch.hass = mock_hass

        await switch.async_added_to_hass()

        mock_tcp_client.connect.assert_called_once()
        mock_tcp_client.query.assert_called_once()

    async def test_switch_async_update_on(self, mock_tcp_client):
        """Test switch state update when on."""
        mock_tcp_client.query = AsyncMock(return_value={'1': 255})
        switch = CozyLifeSwitch(mock_tcp_client)

        await switch.async_update()

        assert switch._attr_is_on is True

    async def test_switch_async_update_off(self, mock_tcp_client):
        """Test switch state update when off."""
        mock_tcp_client.query = AsyncMock(return_value={'1': 0})
        switch = CozyLifeSwitch(mock_tcp_client)

        await switch.async_update()

        assert switch._attr_is_on is False

    async def test_switch_async_update_no_data(self, mock_tcp_client):
        """Test switch state update with no data."""
        mock_tcp_client.query = AsyncMock(return_value={})
        switch = CozyLifeSwitch(mock_tcp_client)
        switch._attr_is_on = True

        await switch.async_update()

        # State should remain unchanged
        assert switch._attr_is_on is True

    async def test_switch_turn_on(self, mock_tcp_client, mock_hass):
        """Test turning switch on."""
        switch = CozyLifeSwitch(mock_tcp_client)
        switch.hass = mock_hass
        switch.async_write_ha_state = MagicMock()
        switch._attr_is_on = False

        await switch.async_turn_on()

        mock_tcp_client.control.assert_called_once_with({'1': 255})
        assert switch._attr_is_on is True
        switch.async_write_ha_state.assert_called_once()

    async def test_switch_turn_off(self, mock_tcp_client, mock_hass):
        """Test turning switch off."""
        switch = CozyLifeSwitch(mock_tcp_client)
        switch.hass = mock_hass
        switch.async_write_ha_state = MagicMock()
        switch._attr_is_on = True

        await switch.async_turn_off()

        mock_tcp_client.control.assert_called_once_with({'1': 0})
        assert switch._attr_is_on is False
        switch.async_write_ha_state.assert_called_once()

    async def test_switch_turn_on_failure(self, mock_tcp_client, mock_hass):
        """Test handling of turn on failure."""
        mock_tcp_client.control = AsyncMock(return_value=False)
        switch = CozyLifeSwitch(mock_tcp_client)
        switch.hass = mock_hass
        switch._attr_is_on = False

        await switch.async_turn_on()

        # State should not be updated on failure
        assert switch._attr_is_on is False
        mock_hass.async_create_task.assert_not_called()

    async def test_switch_turn_off_failure(self, mock_tcp_client, mock_hass):
        """Test handling of turn off failure."""
        mock_tcp_client.control = AsyncMock(return_value=False)
        switch = CozyLifeSwitch(mock_tcp_client)
        switch.hass = mock_hass
        switch._attr_is_on = True

        await switch.async_turn_off()

        # State should not be updated on failure
        assert switch._attr_is_on is True
        mock_hass.async_create_task.assert_not_called()

    async def test_switch_available(self, mock_tcp_client):
        """Test switch availability."""
        switch = CozyLifeSwitch(mock_tcp_client)

        mock_tcp_client.available = True
        assert switch.available is True

        mock_tcp_client.available = False
        assert switch.available is False

    async def test_switch_properties(self, mock_tcp_client):
        """Test switch properties."""
        switch = CozyLifeSwitch(mock_tcp_client)
        switch._attr_is_on = True

        assert switch.is_on is True
        assert switch._attr_name is None  # Entity name is None, uses device name
        assert switch._device_name == "Test Switch"  # Device name for registry
        assert switch.unique_id == "test_switch_456"

        switch._attr_is_on = False
        assert switch.is_on is False
