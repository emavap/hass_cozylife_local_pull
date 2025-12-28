"""Fixtures for CozyLife Local integration tests."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hass_cozylife_local_pull.const import DOMAIN


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "custom_components.hass_cozylife_local_pull.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_udp_socket():
    """Mock UDP socket for discovery tests."""
    mock_socket = MagicMock()
    mock_socket.settimeout = MagicMock()
    mock_socket.setsockopt = MagicMock()
    mock_socket.sendto = MagicMock()
    mock_socket.close = MagicMock()
    return mock_socket


@pytest.fixture
def mock_tcp_connection():
    """Mock TCP connection for client tests."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.is_closing = MagicMock(return_value=False)
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_writer.write = MagicMock()
    return mock_reader, mock_writer


@pytest.fixture
def mock_device_info_response():
    """Mock device info response."""
    return json.dumps({
        "cmd": 0,
        "pv": 0,
        "sn": "1234567890",
        "msg": {
            "did": "test_device_123",
            "pid": "test_pid_001"
        }
    }).encode('utf-8')


@pytest.fixture
def mock_query_response():
    """Mock query response."""
    return json.dumps({
        "cmd": 2,
        "pv": 0,
        "sn": "1234567890",
        "msg": {
            "attr": [1, 2, 3, 4, 5, 6],
            "data": {
                "1": 255,  # on
                "2": 0,    # work mode
                "3": 500,  # color temp
                "4": 512,  # brightness
                "5": 180,  # hue
                "6": 500   # saturation
            }
        }
    }).encode('utf-8')


@pytest.fixture
def mock_pid_list():
    """Mock PID list from API."""
    return [
        {
            "c": "01",  # Light type
            "m": [
                {
                    "pid": "test_pid_001",
                    "n": "Test Light",
                    "i": "icon_light",
                    "dpid": [1, 2, 3, 4, 5, 6]
                }
            ]
        },
        {
            "c": "00",  # Switch type
            "m": [
                {
                    "pid": "test_pid_002",
                    "n": "Test Switch",
                    "i": "icon_switch",
                    "dpid": [1]
                }
            ]
        }
    ]


@pytest.fixture
def mock_config_entry():
    """Mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={"ips": "192.168.1.100"},
        entry_id="test_entry_id",
        title="CozyLife Local",
    )


@pytest.fixture
def mock_async_get_pid_list(mock_pid_list):
    """Mock async_get_pid_list function."""
    with patch(
        "custom_components.hass_cozylife_local_pull.tcp_client.async_get_pid_list",
        return_value=mock_pid_list,
    ), patch(
        "custom_components.hass_cozylife_local_pull.async_get_pid_list",
        new_callable=AsyncMock,
        return_value=mock_pid_list,
    ) as mock:
        yield mock


@pytest.fixture
def mock_get_sn():
    """Mock get_sn function to return consistent serial numbers."""
    with patch(
        "custom_components.hass_cozylife_local_pull.tcp_client.get_sn",
        return_value="1234567890",
    ) as mock:
        yield mock

