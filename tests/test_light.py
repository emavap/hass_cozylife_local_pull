"""Tests for light entity."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
)

from custom_components.hass_cozylife_local_pull.light import CozyLifeLight
from custom_components.hass_cozylife_local_pull.tcp_client import tcp_client


@pytest.mark.unit
@pytest.mark.asyncio
class TestCozyLifeLight:
    """Test CozyLife light entity."""

    @pytest.fixture
    def mock_tcp_client(self):
        """Create a mock TCP client."""
        client = MagicMock(spec=tcp_client)
        client.device_id = "test_light_123"
        client.device_model_name = "Test Light"
        client.device_type_code = "01"
        client.dpid = ['1', '2', '3', '4', '5', '6']
        client.available = True
        client.connect = AsyncMock(return_value=True)
        client.query = AsyncMock(return_value={
            '1': 255,
            '2': 0,
            '3': 500,
            '4': 512,
            '5': 180,
            '6': 500
        })
        client.control = AsyncMock(return_value=True)
        return client

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))
        return hass

    async def test_light_init(self, mock_tcp_client):
        """Test light initialization."""
        light = CozyLifeLight(mock_tcp_client)

        assert light._tcp_client == mock_tcp_client
        assert light._unique_id == "test_light_123"
        assert light._device_name == "Test Light (01)"

    async def test_light_added_to_hass(self, mock_tcp_client, mock_hass):
        """Test light added to Home Assistant."""
        light = CozyLifeLight(mock_tcp_client)
        light.hass = mock_hass

        await light.async_added_to_hass()

        mock_tcp_client.connect.assert_called_once()

    async def test_light_update_features_rgbcw(self, mock_tcp_client):
        """Test feature detection for RGBCW light."""
        mock_tcp_client.dpid = ['1', '2', '3', '4', '5', '6']
        light = CozyLifeLight(mock_tcp_client)

        light._update_features()

        assert ColorMode.HS in light._attr_supported_color_modes
        assert light._attr_color_mode == ColorMode.HS

    async def test_light_update_features_cw(self, mock_tcp_client):
        """Test feature detection for CW light."""
        mock_tcp_client.dpid = ['1', '2', '3', '4']
        light = CozyLifeLight(mock_tcp_client)

        light._update_features()

        assert ColorMode.COLOR_TEMP in light._attr_supported_color_modes
        assert light._attr_color_mode == ColorMode.COLOR_TEMP

    async def test_light_update_features_brightness_only(self, mock_tcp_client):
        """Test feature detection for brightness-only light."""
        mock_tcp_client.dpid = ['1', '2', '4']
        light = CozyLifeLight(mock_tcp_client)

        light._update_features()

        assert ColorMode.BRIGHTNESS in light._attr_supported_color_modes
        assert light._attr_color_mode == ColorMode.BRIGHTNESS

    async def test_light_async_update(self, mock_tcp_client):
        """Test light state update."""
        light = CozyLifeLight(mock_tcp_client)

        await light.async_update()

        assert light._attr_is_on is True
        assert light._attr_brightness == 128  # 512 / 4
        assert light._attr_hs_color == (180, 50)  # (180, 500/10)

    async def test_light_turn_on_basic(self, mock_tcp_client, mock_hass):
        """Test turning light on."""
        light = CozyLifeLight(mock_tcp_client)
        light.hass = mock_hass
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on()

        mock_tcp_client.control.assert_called_once()
        call_args = mock_tcp_client.control.call_args[0][0]
        assert call_args['1'] == 255
        assert light._attr_is_on is True
        light.async_write_ha_state.assert_called_once()

    async def test_light_turn_on_with_brightness(self, mock_tcp_client, mock_hass):
        """Test turning light on with brightness."""
        light = CozyLifeLight(mock_tcp_client)
        light.hass = mock_hass
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(**{ATTR_BRIGHTNESS: 200})

        call_args = mock_tcp_client.control.call_args[0][0]
        assert call_args['4'] == 800  # 200 * 4
        assert light._attr_brightness == 200

    async def test_light_turn_on_with_color_temp(self, mock_tcp_client, mock_hass):
        """Test turning light on with color temperature."""
        light = CozyLifeLight(mock_tcp_client)
        light.hass = mock_hass
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(**{ATTR_COLOR_TEMP_KELVIN: 4000})

        call_args = mock_tcp_client.control.call_args[0][0]
        assert '3' in call_args
        assert light._attr_color_temp_kelvin == 4000

    async def test_light_turn_on_with_hs_color(self, mock_tcp_client, mock_hass):
        """Test turning light on with HS color."""
        light = CozyLifeLight(mock_tcp_client)
        light.hass = mock_hass
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(**{ATTR_HS_COLOR: (120, 75)})

        call_args = mock_tcp_client.control.call_args[0][0]
        assert call_args['5'] == 120
        assert call_args['6'] == 750  # 75 * 10
        assert light._attr_hs_color == (120, 75)

    async def test_light_turn_off(self, mock_tcp_client, mock_hass):
        """Test turning light off."""
        light = CozyLifeLight(mock_tcp_client)
        light.hass = mock_hass
        light.async_write_ha_state = MagicMock()
        light._attr_is_on = True

        await light.async_turn_off()

        mock_tcp_client.control.assert_called_once_with({'1': 0})
        assert light._attr_is_on is False
        light.async_write_ha_state.assert_called_once()

    async def test_light_turn_on_failure(self, mock_tcp_client, mock_hass):
        """Test handling of turn on failure."""
        mock_tcp_client.control = AsyncMock(return_value=False)
        light = CozyLifeLight(mock_tcp_client)
        light.hass = mock_hass

        await light.async_turn_on()

        # State should not be updated on failure
        mock_hass.async_create_task.assert_not_called()

    async def test_light_available(self, mock_tcp_client):
        """Test light availability."""
        light = CozyLifeLight(mock_tcp_client)

        mock_tcp_client.available = True
        assert light.available is True

        mock_tcp_client.available = False
        assert light.available is False

    async def test_light_properties(self, mock_tcp_client):
        """Test light properties."""
        light = CozyLifeLight(mock_tcp_client)
        light._attr_is_on = True
        light._attr_brightness = 150
        light._attr_hs_color = (240, 80)
        light._attr_color_temp_kelvin = 3500

        assert light.is_on is True
        assert light.brightness == 150
        assert light.hs_color == (240, 80)
        assert light.color_temp_kelvin == 3500
        assert light.unique_id == "test_light_123"
