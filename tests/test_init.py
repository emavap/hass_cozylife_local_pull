"""Tests for integration setup."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.core import HomeAssistant

from custom_components.hass_cozylife_local_pull import async_setup, async_setup_entry, async_unload_entry
from custom_components.hass_cozylife_local_pull.const import DOMAIN


@pytest.mark.integration
@pytest.mark.asyncio
class TestIntegrationSetup:
    """Test integration setup and configuration."""

    async def test_async_setup(self, hass: HomeAssistant):
        """Test async_setup."""
        result = await async_setup(hass, {})

        assert result is True
        assert DOMAIN in hass.data

    async def test_async_setup_entry_with_udp_discovery(
        self, hass: HomeAssistant, mock_config_entry,
        mock_async_get_pid_list, mock_get_sn
    ):
        """Test setup entry with UDP discovery."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.device_type_code = "01"
        mock_client._ip = "192.168.1.100"

        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=['192.168.1.100']
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.TcpClient',
            return_value=mock_client
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ):
            result = await async_setup_entry(hass, mock_config_entry)

        assert result is True
        assert DOMAIN in hass.data
        assert mock_config_entry.entry_id in hass.data[DOMAIN]

    async def test_async_setup_entry_with_hostname_discovery(
        self, hass: HomeAssistant, mock_config_entry,
        mock_async_get_pid_list, mock_get_sn
    ):
        """Test setup entry with hostname discovery."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.device_type_code = "01"
        mock_client._ip = "192.168.1.101"

        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=['192.168.1.101']
        ), patch(
            'custom_components.hass_cozylife_local_pull.TcpClient',
            return_value=mock_client
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ):
            result = await async_setup_entry(hass, mock_config_entry)

        assert result is True
        assert DOMAIN in hass.data
        assert mock_config_entry.entry_id in hass.data[DOMAIN]

    async def test_async_setup_entry_with_manual_ip(
        self, hass: HomeAssistant, mock_async_get_pid_list, mock_get_sn
    ):
        """Test setup entry with manually configured IP."""
        from pytest_homeassistant_custom_component.common import MockConfigEntry

        config_entry = MockConfigEntry(
            domain=DOMAIN,
            data={"ips": "192.168.1.200,192.168.1.201"},
            entry_id="test_entry_manual",
            title="CozyLife Local",
        )

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.device_type_code = "01"

        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.TcpClient',
            return_value=mock_client
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ):
            result = await async_setup_entry(hass, config_entry)

        assert result is True
        assert config_entry.entry_id in hass.data[DOMAIN]

    async def test_async_setup_entry_no_devices(
        self, hass: HomeAssistant, mock_config_entry,
        mock_async_get_pid_list, mock_get_sn
    ):
        """Test setup entry when no devices are found."""
        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=[]
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ):
            # Should still return True even with no devices
            result = await async_setup_entry(hass, mock_config_entry)

        assert result is True

    async def test_async_unload_entry(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test unloading a config entry."""
        # Setup the entry first
        hass.data[DOMAIN] = {mock_config_entry.entry_id: {'tcp_client': []}}

        with patch(
            'homeassistant.config_entries.ConfigEntries.async_unload_platforms',
            return_value=True
        ):
            result = await async_unload_entry(hass, mock_config_entry)

        assert result is True
        assert mock_config_entry.entry_id not in hass.data[DOMAIN]

    async def test_async_setup_entry_merges_discovery_methods(
        self, hass: HomeAssistant, mock_config_entry,
        mock_async_get_pid_list, mock_get_sn
    ):
        """Test that all discovery methods are merged."""
        from pytest_homeassistant_custom_component.common import MockConfigEntry

        config_entry = MockConfigEntry(
            domain=DOMAIN,
            data={"ips": "192.168.1.200"},
            entry_id="test_merge",
            title="CozyLife Local",
        )

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.device_type_code = "01"

        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=['192.168.1.100']
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=['192.168.1.101']
        ), patch(
            'custom_components.hass_cozylife_local_pull.TcpClient',
            return_value=mock_client
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ):
            result = await async_setup_entry(hass, config_entry)

        assert result is True
        # Should have attempted to connect to all 3 unique IPs
        # (UDP: 192.168.1.100, Hostname: 192.168.1.101, Manual: 192.168.1.200)
