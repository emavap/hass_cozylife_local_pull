"""Tests for TCP client."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.hass_cozylife_local_pull.tcp_client import tcp_client, CMD_INFO, CMD_QUERY, CMD_SET


@pytest.mark.unit
@pytest.mark.asyncio
class TestTCPClient:
    """Test TCP client functionality."""

    async def test_connect_success(self, mock_tcp_connection, mock_device_info_response, 
                                   mock_async_get_pid_list, mock_get_sn):
        """Test successful connection to device."""
        mock_reader, mock_writer = mock_tcp_connection
        mock_reader.read = AsyncMock(return_value=mock_device_info_response)

        with patch('asyncio.open_connection', return_value=(mock_reader, mock_writer)):
            client = tcp_client("192.168.1.100")
            result = await client.connect()

        assert result is True
        assert client.available is True
        assert client.device_id == "test_device_123"
        assert client._pid == "test_pid_001"

    async def test_connect_timeout(self):
        """Test connection timeout."""
        with patch('asyncio.open_connection', side_effect=asyncio.TimeoutError()):
            client = tcp_client("192.168.1.100")
            result = await client.connect()

        assert result is False
        assert client.available is False

    async def test_connect_failure(self):
        """Test connection failure."""
        with patch('asyncio.open_connection', side_effect=OSError("Connection refused")):
            client = tcp_client("192.168.1.100")
            result = await client.connect()

        assert result is False
        assert client.available is False
        assert "Connection refused" in client._last_error

    async def test_is_connected(self, mock_tcp_connection):
        """Test is_connected method."""
        mock_reader, mock_writer = mock_tcp_connection
        
        client = tcp_client("192.168.1.100")
        assert client.is_connected() is False

        client._writer = mock_writer
        assert client.is_connected() is True

        mock_writer.is_closing = MagicMock(return_value=True)
        assert client.is_connected() is False

    async def test_query_success(self, mock_tcp_connection, mock_query_response,
                                mock_async_get_pid_list, mock_get_sn):
        """Test successful query."""
        mock_reader, mock_writer = mock_tcp_connection
        mock_reader.read = AsyncMock(return_value=mock_query_response)

        client = tcp_client("192.168.1.100")
        client._reader = mock_reader
        client._writer = mock_writer
        client._available = True

        result = await client.query()

        assert result is not None
        assert result.get('1') == 255  # on
        assert result.get('4') == 512  # brightness

    async def test_query_reconnect_on_disconnect(self, mock_tcp_connection, 
                                                 mock_device_info_response,
                                                 mock_query_response,
                                                 mock_async_get_pid_list, mock_get_sn):
        """Test query reconnects when disconnected."""
        mock_reader, mock_writer = mock_tcp_connection
        
        # First call returns device info, second returns query response
        mock_reader.read = AsyncMock(side_effect=[mock_device_info_response, mock_query_response])

        with patch('asyncio.open_connection', return_value=(mock_reader, mock_writer)):
            client = tcp_client("192.168.1.100")
            # Start with no connection
            client._writer = None
            
            result = await client.query()

        assert result is not None
        assert client.available is True

    async def test_control_success(self, mock_tcp_connection, mock_get_sn):
        """Test successful control command."""
        mock_reader, mock_writer = mock_tcp_connection
        
        # Mock response with matching serial number
        response = json.dumps({
            "cmd": 3,
            "sn": "1234567890",
            "msg": {"result": "ok"}
        }).encode('utf-8')
        mock_reader.read = AsyncMock(return_value=response)

        client = tcp_client("192.168.1.100")
        client._reader = mock_reader
        client._writer = mock_writer
        client._available = True

        result = await client.control({'1': 255})

        assert result is True
        assert client.available is True

    async def test_control_timeout(self, mock_tcp_connection, mock_get_sn):
        """Test control command with timeout."""
        mock_reader, mock_writer = mock_tcp_connection
        mock_reader.read = AsyncMock(side_effect=asyncio.TimeoutError())

        client = tcp_client("192.168.1.100")
        client._reader = mock_reader
        client._writer = mock_writer
        client._available = True

        # Should still return True as some devices don't send acknowledgment
        result = await client.control({'1': 255})

        assert result is True

    async def test_control_reconnect_on_disconnect(self, mock_tcp_connection,
                                                   mock_device_info_response,
                                                   mock_get_sn,
                                                   mock_async_get_pid_list):
        """Test control reconnects when disconnected."""
        mock_reader, mock_writer = mock_tcp_connection
        
        response = json.dumps({
            "cmd": 3,
            "sn": "1234567890",
            "msg": {"result": "ok"}
        }).encode('utf-8')
        
        mock_reader.read = AsyncMock(side_effect=[mock_device_info_response, response])

        with patch('asyncio.open_connection', return_value=(mock_reader, mock_writer)):
            client = tcp_client("192.168.1.100")
            client._writer = None  # Start disconnected
            
            result = await client.control({'1': 255})

        assert result is True
        assert client.available is True

    async def test_close_connection(self, mock_tcp_connection):
        """Test connection closing."""
        mock_reader, mock_writer = mock_tcp_connection

        client = tcp_client("192.168.1.100")
        client._reader = mock_reader
        client._writer = mock_writer
        client._available = True

        await client._close_connection()

        assert client._writer is None
        assert client._reader is None
        assert client.available is False
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_called_once()

    async def test_get_package_set_command(self, mock_get_sn):
        """Test package generation for SET command."""
        client = tcp_client("192.168.1.100")
        
        payload = {'1': 255, '4': 512}
        package = client._get_package(CMD_SET, payload)

        assert isinstance(package, bytes)
        package_str = package.decode('utf-8')
        assert '"cmd":3' in package_str
        assert '"sn":"1234567890"' in package_str
        assert '"attr":[1,4]' in package_str
        assert package_str.endswith('\r\n')

    async def test_get_package_query_command(self, mock_get_sn):
        """Test package generation for QUERY command."""
        client = tcp_client("192.168.1.100")
        
        package = client._get_package(CMD_QUERY, {})

        package_str = package.decode('utf-8')
        assert '"cmd":2' in package_str
        assert '"attr":[0]' in package_str

    async def test_get_package_info_command(self, mock_get_sn):
        """Test package generation for INFO command."""
        client = tcp_client("192.168.1.100")
        
        package = client._get_package(CMD_INFO, {})

        package_str = package.decode('utf-8')
        assert '"cmd":0' in package_str
        assert '"msg":{}' in package_str

