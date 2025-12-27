"""Tests for hostname discovery."""
import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from homeassistant.core import HomeAssistant

from custom_components.hass_cozylife_local_pull.discovery import async_discover_devices


@pytest.mark.integration
@pytest.mark.asyncio
class TestHostnameDiscovery:
    """Test hostname discovery functionality."""

    async def test_discover_devices_success(self, hass: HomeAssistant):
        """Test successful device discovery by hostname."""
        def mock_gethostbyaddr(ip):
            if ip == "192.168.1.100":
                return ("CozyLife_ABC123", [], ["192.168.1.100"])
            elif ip == "192.168.1.101":
                return ("CozyLife_DEF456", [], ["192.168.1.101"])
            raise socket.herror("Host not found")

        with patch(
            'custom_components.hass_cozylife_local_pull.discovery.async_get_source_ip',
            return_value="192.168.1.1"
        ), patch(
            'socket.gethostbyaddr',
            side_effect=mock_gethostbyaddr
        ):
            result = await async_discover_devices(hass)

        assert len(result) == 2
        assert "192.168.1.100" in result
        assert "192.168.1.101" in result

    async def test_discover_devices_no_source_ip(self, hass: HomeAssistant):
        """Test discovery when source IP cannot be determined."""
        with patch(
            'custom_components.hass_cozylife_local_pull.discovery.async_get_source_ip',
            return_value=None
        ):
            result = await async_discover_devices(hass)

        assert result == []

    async def test_discover_devices_source_ip_error(self, hass: HomeAssistant):
        """Test discovery when getting source IP raises error."""
        with patch(
            'custom_components.hass_cozylife_local_pull.discovery.async_get_source_ip',
            side_effect=Exception("Network error")
        ):
            result = await async_discover_devices(hass)

        assert result == []

    async def test_discover_devices_filters_non_cozylife(self, hass: HomeAssistant):
        """Test that non-CozyLife devices are filtered out."""
        def mock_gethostbyaddr(ip):
            if ip == "192.168.1.100":
                return ("CozyLife_ABC123", [], ["192.168.1.100"])
            elif ip == "192.168.1.101":
                return ("OtherDevice_XYZ", [], ["192.168.1.101"])
            raise socket.herror("Host not found")

        with patch(
            'custom_components.hass_cozylife_local_pull.discovery.async_get_source_ip',
            return_value="192.168.1.1"
        ), patch(
            'socket.gethostbyaddr',
            side_effect=mock_gethostbyaddr
        ):
            result = await async_discover_devices(hass)

        assert len(result) == 1
        assert "192.168.1.100" in result
        assert "192.168.1.101" not in result

    async def test_discover_devices_handles_timeout(self, hass: HomeAssistant):
        """Test that discovery handles DNS timeouts gracefully."""
        async def slow_gethostbyaddr(ip):
            await asyncio.sleep(5)  # Longer than timeout
            return ("CozyLife_ABC123", [], [ip])

        with patch(
            'custom_components.hass_cozylife_local_pull.discovery.async_get_source_ip',
            return_value="192.168.1.1"
        ), patch(
            'socket.gethostbyaddr',
            side_effect=socket.timeout()
        ):
            result = await async_discover_devices(hass)

        # Should complete without hanging
        assert isinstance(result, list)

    async def test_discover_devices_skips_source_ip(self, hass: HomeAssistant):
        """Test that discovery skips the source IP."""
        def mock_gethostbyaddr(ip):
            if ip == "192.168.1.1":
                return ("CozyLife_SOURCE", [], ["192.168.1.1"])
            elif ip == "192.168.1.100":
                return ("CozyLife_ABC123", [], ["192.168.1.100"])
            raise socket.herror("Host not found")

        with patch(
            'custom_components.hass_cozylife_local_pull.discovery.async_get_source_ip',
            return_value="192.168.1.1"
        ), patch(
            'socket.gethostbyaddr',
            side_effect=mock_gethostbyaddr
        ):
            result = await async_discover_devices(hass)

        # Should not include source IP even if it has CozyLife hostname
        assert "192.168.1.1" not in result
        assert "192.168.1.100" in result

    async def test_discover_devices_handles_herror(self, hass: HomeAssistant):
        """Test that discovery handles socket.herror gracefully."""
        with patch(
            'custom_components.hass_cozylife_local_pull.discovery.async_get_source_ip',
            return_value="192.168.1.1"
        ), patch(
            'socket.gethostbyaddr',
            side_effect=socket.herror("Host not found")
        ):
            result = await async_discover_devices(hass)

        # Should return empty list without crashing
        assert result == []

    async def test_discover_devices_concurrent_execution(self, hass: HomeAssistant):
        """Test that discovery executes checks concurrently."""
        call_count = 0
        
        def mock_gethostbyaddr(ip):
            nonlocal call_count
            call_count += 1
            if ip == "192.168.1.100":
                return ("CozyLife_ABC123", [], ["192.168.1.100"])
            raise socket.herror("Host not found")

        with patch(
            'custom_components.hass_cozylife_local_pull.discovery.async_get_source_ip',
            return_value="192.168.1.1"
        ), patch(
            'socket.gethostbyaddr',
            side_effect=mock_gethostbyaddr
        ):
            result = await async_discover_devices(hass)

        # Should have checked all 254 IPs (minus source IP = 253)
        assert call_count == 253
        assert "192.168.1.100" in result

