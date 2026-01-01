"""UDP device discovery for CozyLife devices."""
from __future__ import annotations

import contextlib
import json
import logging
import socket
import time

from .const import UDP_DISCOVERY_PORT
from .utils import get_sn

_LOGGER = logging.getLogger(__name__)

# Discovery configuration
# Increased timeouts and attempts for better device discovery
# Some devices respond slowly, especially on congested networks
BROADCAST_ADDRESS = "255.255.255.255"
BROADCAST_ATTEMPTS = 8  # Increased from 5 - more chances for devices to hear us
BROADCAST_DELAY = 0.2  # Increased from 0.1 - give devices more time to process
SOCKET_TIMEOUT = 1.0  # Increased from 0.5 - longer wait for slow devices
MAX_FIRST_RESPONSE_TRIES = 15  # Increased from 10 - wait longer for first response
MAX_RECEIVE_ATTEMPTS = 150  # Increased from 100 - collect more responses
MAX_CONSECUTIVE_TIMEOUTS = 5  # Increased from 3 - be more patient


@contextlib.contextmanager
def _create_udp_socket(timeout: float = SOCKET_TIMEOUT):
    """Create and configure a UDP broadcast socket.

    Args:
        timeout: Socket timeout in seconds.

    Yields:
        Configured UDP socket.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        yield sock
    finally:
        sock.close()
        _LOGGER.debug("UDP socket closed")


def _build_discovery_message() -> bytes:
    """Build the UDP discovery message.

    Returns:
        Encoded discovery message as bytes.
    """
    message = {
        "cmd": 0,
        "pv": 0,
        "sn": get_sn(),
        "msg": {},
    }
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


def get_ip() -> list[str]:
    """Discover CozyLife device IPs via UDP broadcast.

    Sends UDP broadcast messages and collects responses from CozyLife devices
    on the local network.

    Returns:
        List of discovered device IP addresses.
    """
    try:
        with _create_udp_socket() as sock:
            return _discover_devices(sock)
    except Exception as e:
        _LOGGER.error("UDP discovery failed with error: %s", e)
        return []


def _discover_devices(sock: socket.socket) -> list[str]:
    """Perform device discovery on the given socket.

    Args:
        sock: Configured UDP socket.

    Returns:
        List of discovered device IP addresses.
    """
    message = _build_discovery_message()

    # Send discovery broadcast multiple times with delays
    _LOGGER.debug("Starting UDP discovery broadcast")
    for i in range(BROADCAST_ATTEMPTS):
        try:
            sock.sendto(message, (BROADCAST_ADDRESS, UDP_DISCOVERY_PORT))
            _LOGGER.debug("Sent UDP broadcast %d/%d", i + 1, BROADCAST_ATTEMPTS)
            time.sleep(BROADCAST_DELAY)
        except Exception as e:
            _LOGGER.warning("Failed to send UDP broadcast %d: %s", i + 1, e)

    # Give devices a moment to prepare responses after last broadcast
    time.sleep(0.5)

    # Wait for first response
    if not _wait_for_first_response(sock):
        _LOGGER.info("UDP discovery found no devices after waiting")
        return []

    # Collect all responses
    discovered_ips = _collect_responses(sock)
    _LOGGER.info("UDP discovery completed: found %d device(s)", len(discovered_ips))
    return discovered_ips


def _wait_for_first_response(sock: socket.socket) -> bool:
    """Wait for the first UDP response.

    Args:
        sock: Configured UDP socket.

    Returns:
        True if a response was received, False otherwise.
    """
    for i in range(MAX_FIRST_RESPONSE_TRIES):
        try:
            _, addr = sock.recvfrom(1024, socket.MSG_PEEK)
            _LOGGER.debug("First UDP response from: %s", addr[0])
            return True
        except socket.timeout:
            _LOGGER.debug("%d/%d try, waiting for first response...", i + 1, MAX_FIRST_RESPONSE_TRIES)
        except Exception as err:
            _LOGGER.debug("UDP receive error: %s", err)
    return False


def _collect_responses(sock: socket.socket) -> list[str]:
    """Collect all UDP responses from devices.

    Args:
        sock: Configured UDP socket.

    Returns:
        List of unique device IP addresses.
    """
    ips: list[str] = []
    attempts = 0
    consecutive_timeouts = 0

    while attempts < MAX_RECEIVE_ATTEMPTS and consecutive_timeouts < MAX_CONSECUTIVE_TIMEOUTS:
        try:
            _, addr = sock.recvfrom(1024)
            ip = addr[0]
            if ip not in ips:
                ips.append(ip)
                _LOGGER.info("UDP discovered device at: %s", ip)
            consecutive_timeouts = 0
        except socket.timeout:
            consecutive_timeouts += 1
            _LOGGER.debug(
                "UDP timeout (%d/%d)", consecutive_timeouts, MAX_CONSECUTIVE_TIMEOUTS
            )
        except Exception as e:
            _LOGGER.debug("UDP receive error: %s", e)
            break
        attempts += 1

    return ips
