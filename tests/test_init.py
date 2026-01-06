"""Tests for integration setup."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.core import HomeAssistant

from custom_components.hass_cozylife_local_pull import async_setup, async_setup_entry, async_unload_entry
from custom_components.hass_cozylife_local_pull.const import DOMAIN


def create_mock_client(ip: str = "192.168.1.100", device_type: str = "01"):
    """Create a properly configured mock TcpClient."""
    mock_client = MagicMock()
    mock_client.connect = AsyncMock(return_value=True)
    mock_client.disconnect = AsyncMock()
    mock_client.start_persistent_connection = AsyncMock()
    mock_client.stop_persistent_connection = AsyncMock()
    mock_client.register_state_callback = MagicMock()
    mock_client.device_type_code = device_type
    mock_client.device_id = f"device_{ip.replace('.', '_')}"
    mock_client.ip = ip
    mock_client._ip = ip
    mock_client.available = True
    return mock_client


def create_mock_coordinator():
    """Create a properly configured mock DeviceCoordinator."""
    mock_coordinator = MagicMock()
    mock_coordinator.start = AsyncMock()
    mock_coordinator.stop = AsyncMock()
    mock_coordinator.add_device = AsyncMock(return_value=True)
    mock_coordinator.clients = []
    return mock_coordinator


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
        mock_client = create_mock_client("192.168.1.100")
        mock_coordinator = create_mock_coordinator()

        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=['192.168.1.100']
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.TcpClient',
            return_value=mock_client
        ), patch(
            'custom_components.hass_cozylife_local_pull.DeviceCoordinator',
            return_value=mock_coordinator
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ), patch.object(
            hass.config_entries, 'async_unload_platforms', new_callable=AsyncMock, return_value=True
        ):
            result = await async_setup_entry(hass, mock_config_entry)

            assert result is True
            assert DOMAIN in hass.data
            assert mock_config_entry.entry_id in hass.data[DOMAIN]
            mock_coordinator.start.assert_called_once()

            # Clean up
            await async_unload_entry(hass, mock_config_entry)
            mock_coordinator.stop.assert_called_once()

    async def test_async_setup_entry_with_hostname_discovery(
        self, hass: HomeAssistant, mock_config_entry,
        mock_async_get_pid_list, mock_get_sn
    ):
        """Test setup entry with hostname discovery."""
        mock_client = create_mock_client("192.168.1.101")
        mock_coordinator = create_mock_coordinator()

        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=['192.168.1.101']
        ), patch(
            'custom_components.hass_cozylife_local_pull.TcpClient',
            return_value=mock_client
        ), patch(
            'custom_components.hass_cozylife_local_pull.DeviceCoordinator',
            return_value=mock_coordinator
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ), patch.object(
            hass.config_entries, 'async_unload_platforms', new_callable=AsyncMock, return_value=True
        ):
            result = await async_setup_entry(hass, mock_config_entry)

            assert result is True
            assert DOMAIN in hass.data
            assert mock_config_entry.entry_id in hass.data[DOMAIN]

            # Clean up
            await async_unload_entry(hass, mock_config_entry)

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

        mock_client = create_mock_client("192.168.1.200")
        mock_coordinator = create_mock_coordinator()

        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.TcpClient',
            return_value=mock_client
        ), patch(
            'custom_components.hass_cozylife_local_pull.DeviceCoordinator',
            return_value=mock_coordinator
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ), patch.object(
            hass.config_entries, 'async_unload_platforms', new_callable=AsyncMock, return_value=True
        ):
            result = await async_setup_entry(hass, config_entry)

            assert result is True
            assert config_entry.entry_id in hass.data[DOMAIN]

            # Clean up
            await async_unload_entry(hass, config_entry)

    async def test_async_setup_entry_no_devices(
        self, hass: HomeAssistant, mock_config_entry,
        mock_async_get_pid_list, mock_get_sn
    ):
        """Test setup entry when no devices are found."""
        mock_coordinator = create_mock_coordinator()

        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=[]
        ), patch(
            'custom_components.hass_cozylife_local_pull.DeviceCoordinator',
            return_value=mock_coordinator
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ), patch.object(
            hass.config_entries, 'async_unload_platforms', new_callable=AsyncMock, return_value=True
        ):
            # Should still return True even with no devices
            result = await async_setup_entry(hass, mock_config_entry)

            assert result is True

            # Clean up
            await async_unload_entry(hass, mock_config_entry)

    async def test_async_unload_entry(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test unloading a config entry."""
        # Setup the entry first with a mock coordinator
        mock_coordinator = create_mock_coordinator()
        hass.data[DOMAIN] = {mock_config_entry.entry_id: {'coordinator': mock_coordinator, 'tcp_client': []}}

        with patch(
            'homeassistant.config_entries.ConfigEntries.async_unload_platforms',
            return_value=True
        ):
            result = await async_unload_entry(hass, mock_config_entry)

        assert result is True
        assert mock_config_entry.entry_id not in hass.data[DOMAIN]
        mock_coordinator.stop.assert_called_once()

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

        mock_client = create_mock_client("192.168.1.100")
        mock_coordinator = create_mock_coordinator()

        with patch(
            'custom_components.hass_cozylife_local_pull.get_ip',
            return_value=['192.168.1.100']
        ), patch(
            'custom_components.hass_cozylife_local_pull.async_discover_devices',
            return_value=['192.168.1.101']
        ), patch(
            'custom_components.hass_cozylife_local_pull.TcpClient',
            return_value=mock_client
        ), patch(
            'custom_components.hass_cozylife_local_pull.DeviceCoordinator',
            return_value=mock_coordinator
        ), patch.object(
            hass.config_entries, 'async_forward_entry_setups', new_callable=AsyncMock
        ), patch.object(
            hass.config_entries, 'async_unload_platforms', new_callable=AsyncMock, return_value=True
        ):
            result = await async_setup_entry(hass, config_entry)

            assert result is True
            # Should have attempted to connect to all 3 unique IPs
            # (UDP: 192.168.1.100, Hostname: 192.168.1.101, Manual: 192.168.1.200)

            # Clean up
            await async_unload_entry(hass, config_entry)
