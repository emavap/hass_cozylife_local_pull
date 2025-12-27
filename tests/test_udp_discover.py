"""Tests for UDP discovery."""
import socket
from unittest.mock import MagicMock, patch
import pytest

from custom_components.hass_cozylife_local_pull.udp_discover import get_ip


@pytest.mark.unit
class TestUDPDiscovery:
    """Test UDP discovery functionality."""

    def test_get_ip_success(self, mock_udp_socket):
        """Test successful UDP discovery."""
        # Mock socket responses
        mock_udp_socket.recvfrom = MagicMock(
            side_effect=[
                (b'{"msg":{}}', ('192.168.1.100', 6095)),  # First response (MSG_PEEK)
                (b'{"msg":{}}', ('192.168.1.100', 6095)),  # First device
                (b'{"msg":{}}', ('192.168.1.101', 6095)),  # Second device
                socket.timeout(),  # Timeout to end collection
            ]
        )

        with patch('socket.socket', return_value=mock_udp_socket):
            result = get_ip()

        assert len(result) == 2
        assert '192.168.1.100' in result
        assert '192.168.1.101' in result
        mock_udp_socket.close.assert_called_once()

    def test_get_ip_no_devices(self, mock_udp_socket):
        """Test UDP discovery when no devices respond."""
        # Mock socket to always timeout
        mock_udp_socket.recvfrom = MagicMock(side_effect=socket.timeout())

        with patch('socket.socket', return_value=mock_udp_socket):
            result = get_ip()

        assert result == []
        mock_udp_socket.close.assert_called_once()

    def test_get_ip_duplicate_ips(self, mock_udp_socket):
        """Test that duplicate IPs are filtered."""
        mock_udp_socket.recvfrom = MagicMock(
            side_effect=[
                (b'{"msg":{}}', ('192.168.1.100', 6095)),  # First response (MSG_PEEK)
                (b'{"msg":{}}', ('192.168.1.100', 6095)),  # First device
                (b'{"msg":{}}', ('192.168.1.100', 6095)),  # Duplicate
                (b'{"msg":{}}', ('192.168.1.101', 6095)),  # Second device
                socket.timeout(),
            ]
        )

        with patch('socket.socket', return_value=mock_udp_socket):
            result = get_ip()

        assert len(result) == 2
        assert result.count('192.168.1.100') == 1

    def test_get_ip_socket_error(self, mock_udp_socket):
        """Test handling of socket errors."""
        mock_udp_socket.sendto = MagicMock(side_effect=OSError("Network error"))

        with patch('socket.socket', return_value=mock_udp_socket):
            result = get_ip()

        assert result == []
        mock_udp_socket.close.assert_called_once()

    def test_get_ip_consecutive_timeouts(self, mock_udp_socket):
        """Test that discovery stops after consecutive timeouts."""
        mock_udp_socket.recvfrom = MagicMock(
            side_effect=[
                (b'{"msg":{}}', ('192.168.1.100', 6095)),  # First response (MSG_PEEK)
                (b'{"msg":{}}', ('192.168.1.100', 6095)),  # First device
                socket.timeout(),  # First timeout
                socket.timeout(),  # Second timeout
                socket.timeout(),  # Third timeout - should stop here
                (b'{"msg":{}}', ('192.168.1.101', 6095)),  # This shouldn't be reached
            ]
        )

        with patch('socket.socket', return_value=mock_udp_socket):
            result = get_ip()

        assert len(result) == 1
        assert '192.168.1.100' in result

    def test_get_ip_broadcast_sent(self, mock_udp_socket):
        """Test that broadcast messages are sent correctly."""
        mock_udp_socket.recvfrom = MagicMock(side_effect=socket.timeout())

        with patch('socket.socket', return_value=mock_udp_socket), \
             patch('custom_components.hass_cozylife_local_pull.udp_discover.get_sn', return_value='123456'):
            get_ip()

        # Should send 5 broadcast messages
        assert mock_udp_socket.sendto.call_count == 5
        
        # Check broadcast address
        for call in mock_udp_socket.sendto.call_args_list:
            args, kwargs = call
            assert args[1] == ('255.255.255.255', 6095)

    def test_get_ip_socket_options_set(self, mock_udp_socket):
        """Test that socket options are set correctly."""
        mock_udp_socket.recvfrom = MagicMock(side_effect=socket.timeout())

        with patch('socket.socket', return_value=mock_udp_socket):
            get_ip()

        # Check that socket options were set
        assert mock_udp_socket.setsockopt.call_count >= 2
        
        # Verify SO_REUSEADDR and SO_BROADCAST were set
        calls = mock_udp_socket.setsockopt.call_args_list
        so_reuseaddr_set = any(
            call[0][0] == socket.SOL_SOCKET and call[0][1] == socket.SO_REUSEADDR
            for call in calls
        )
        so_broadcast_set = any(
            call[0][0] == socket.SOL_SOCKET and call[0][1] == socket.SO_BROADCAST
            for call in calls
        )
        
        assert so_reuseaddr_set
        assert so_broadcast_set

    def test_get_ip_timeout_set(self, mock_udp_socket):
        """Test that socket timeout is set correctly."""
        mock_udp_socket.recvfrom = MagicMock(side_effect=socket.timeout())

        with patch('socket.socket', return_value=mock_udp_socket):
            get_ip()

        # Verify timeout was set to 0.5 seconds
        mock_udp_socket.settimeout.assert_called_with(0.5)

