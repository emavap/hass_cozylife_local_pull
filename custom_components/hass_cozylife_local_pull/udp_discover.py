import socket
import time
from .utils import get_sn
import logging


_LOGGER = logging.getLogger(__name__)

"""
discover device
"""


def get_ip() -> list:
    """
    get device ip with improved reliability
    :return: list
    """
    server = None
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Enable broadcasting mode
        server.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Increased timeout for better reliability (was 0.1s, now 0.5s)
        server.settimeout(0.5)
        message = '{"cmd":0,"pv":0,"sn":"' + get_sn() + '","msg":{}}'

        # Send discovery broadcast multiple times with delays
        _LOGGER.debug("Starting UDP discovery broadcast")
        for i in range(5):  # Increased from 3 to 5 attempts
            try:
                server.sendto(bytes(message, encoding='utf-8'), ('255.255.255.255', 6095))
                _LOGGER.debug(f"Sent UDP broadcast {i+1}/5")
                time.sleep(0.1)  # Increased delay between broadcasts
            except Exception as e:
                _LOGGER.warning(f"Failed to send UDP broadcast {i+1}: {e}")

        # Wait for first response with more attempts
        max_tries = 10  # Increased from 5 to 10
        first_response = False
        for i in range(max_tries):
            try:
                _, addr = server.recvfrom(1024, socket.MSG_PEEK)
                _LOGGER.debug(f'First UDP response from: {addr[0]}')
                first_response = True
                break
            except socket.timeout:
                _LOGGER.debug(f'{i+1}/{max_tries} try, waiting for first response...')
                continue
            except Exception as err:
                _LOGGER.debug(f'UDP receive error: {err}')
                continue

        if not first_response:
            _LOGGER.info('UDP discovery found no devices after waiting')
            return []

        # Collect all responses with longer timeout
        ip = []
        attempts = 0
        max_attempts = 100  # Reduced from 255 to avoid excessive waiting
        consecutive_timeouts = 0
        max_consecutive_timeouts = 3  # Stop after 3 consecutive timeouts

        while attempts < max_attempts and consecutive_timeouts < max_consecutive_timeouts:
            try:
                _, addr = server.recvfrom(1024)
                if addr[0] not in ip:
                    ip.append(addr[0])
                    _LOGGER.info(f'UDP discovered device at: {addr[0]}')
                consecutive_timeouts = 0  # Reset counter on successful receive
            except socket.timeout:
                consecutive_timeouts += 1
                _LOGGER.debug(f'UDP timeout ({consecutive_timeouts}/{max_consecutive_timeouts})')
            except Exception as e:
                _LOGGER.debug(f'UDP receive error: {e}')
                break
            attempts += 1

        _LOGGER.info(f'UDP discovery completed: found {len(ip)} device(s)')
        return ip

    except Exception as e:
        _LOGGER.error(f'UDP discovery failed with error: {e}')
        return []
    finally:
        # Ensure socket is properly closed
        if server:
            try:
                server.close()
                _LOGGER.debug("UDP socket closed")
            except Exception as e:
                _LOGGER.debug(f"Error closing UDP socket: {e}")
