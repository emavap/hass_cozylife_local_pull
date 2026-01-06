# -*- coding: utf-8 -*-
"""TCP client for CozyLife device communication."""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from .const import (
    DOMAIN,
    TCP_PORT,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_RESPONSE_TIMEOUT,
    MAX_RETRY_ATTEMPTS,
    INITIAL_RETRY_DELAY,
    MAX_RETRY_DELAY,
    RETRY_BACKOFF_FACTOR,
    MAX_CONSECUTIVE_FAILURES,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    REDISCOVERY_ON_FAILURE_THRESHOLD,
    RECEIVE_LOOP_TIMEOUT,
    RECEIVE_LOOP_RETRY_DELAY,
    RECONNECT_MIN_INTERVAL,
    RECONNECT_MAX_INTERVAL,
    RECONNECT_BACKOFF_FACTOR,
    DEVICE_OFFLINE_THRESHOLD,
    DEVICE_STATE_ONLINE,
    DEVICE_STATE_OFFLINE,
    DEVICE_STATE_CONNECTING,
    DEVICE_STATE_UNKNOWN,
    SIGNAL_DEVICE_STATE,
    SIGNAL_DEVICE_CONNECTED,
    SIGNAL_DEVICE_DISCONNECTED,
)
from .utils import async_get_pid_list, get_sn

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# Command types
CMD_INFO: int = 0
CMD_QUERY: int = 2
CMD_SET: int = 3

_LOGGER = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    """Data class representing CozyLife device information."""

    device_id: str = ""
    device_name: str = ""  # User-given name from device
    pid: str = ""
    device_type_code: str = ""
    icon: str = ""
    device_model_name: str = ""
    dpid: list[str] = field(default_factory=list)


class TcpClient:
    """Represents a CozyLife device connection with automatic reconnection.

    This client maintains a persistent connection with the device and runs a
    continuous receive loop to listen for push updates. When the connection
    is lost, it automatically attempts to reconnect with exponential backoff.
    """

    def __init__(
        self,
        ip: str,
        hass: HomeAssistant | None = None,
        connection_timeout: float | None = None,
        command_timeout: float | None = None,
        response_timeout: float | None = None,
    ) -> None:
        """Initialize the TCP client.

        Args:
            ip: The IP address of the device.
            hass: Optional Home Assistant instance for caching.
            connection_timeout: Timeout for establishing connection (seconds).
            command_timeout: Timeout for sending commands (seconds).
            response_timeout: Timeout for waiting for responses (seconds).
        """
        self._ip: str = ip
        self._hass: HomeAssistant | None = hass
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._available: bool = False
        self._read_buffer: str = ""  # Buffer for partial responses

        # Configurable timeouts with defaults
        self._connection_timeout: float = connection_timeout or DEFAULT_CONNECTION_TIMEOUT
        self._command_timeout: float = command_timeout or DEFAULT_COMMAND_TIMEOUT
        self._response_timeout: float = response_timeout or DEFAULT_RESPONSE_TIMEOUT

        # Device info
        self._info: DeviceInfo = DeviceInfo()
        self._sn: str = ""
        self._last_error: str | None = None

        # Retry state for exponential backoff
        self._retry_count: int = 0
        self._next_retry_time: float = 0.0

        # Connection health tracking
        self._consecutive_failures: int = 0
        self._last_successful_communication: float = 0.0
        self._last_activity: float = 0.0

        # Persistent connection state
        self._device_state: str = DEVICE_STATE_UNKNOWN
        self._receive_loop_task: asyncio.Task | None = None
        self._is_closing: bool = False
        self._state_callbacks: list[Callable[[str, dict[str, Any]], None]] = []
        self._last_state: dict[str, Any] = {}  # Cached last known state

        # Reconnection backoff state (used by receive loop for reconnection)
        self._reconnect_delay: float = RECONNECT_MIN_INTERVAL
        self._last_ip_change_check: float = 0.0

    async def connect(self, force: bool = False) -> bool:
        """Establish connection to device with improved error handling.

        Args:
            force: If True, ignore backoff timer and attempt connection immediately.

        Returns:
            True if connection was successful, False otherwise.
        """
        async with self._lock:
            if force:
                # Reset backoff timer to allow immediate connection attempt
                self._next_retry_time = 0.0
            return await self._connect_internal()

    async def _connect_internal(self) -> bool:
        """Internal connect method without lock (to avoid deadlock).

        This method should only be called when the lock is already held.
        Implements exponential backoff for retry attempts.

        Returns:
            True if connection was successful, False otherwise.
        """
        # Check if we should wait before retrying (exponential backoff)
        current_time = time.monotonic()
        if current_time < self._next_retry_time:
            wait_time = self._next_retry_time - current_time
            _LOGGER.debug(
                "Waiting %.1f seconds before retry for %s", wait_time, self._ip
            )
            return False

        # Try to connect with a few quick retries for transient failures
        max_quick_retries = 3
        for attempt in range(max_quick_retries):
            try:
                # Close existing connection if any
                if self._writer:
                    await self._close_connection()

                _LOGGER.debug(
                    "Connecting to %s (attempt %d/%d)...",
                    self._ip, attempt + 1, max_quick_retries
                )

                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self._ip, TCP_PORT),
                    timeout=self._connection_timeout,
                )

                # Enable TCP keep-alive to detect dead connections
                self._configure_socket_keepalive()

                # Get device info with timeout
                await asyncio.wait_for(self._device_info(), timeout=self._connection_timeout)

                # If dpid is still empty, try to query to get attributes
                if not self._info.dpid:
                    _LOGGER.info("DPID empty for %s, querying device for attributes", self._ip)
                    await self._query_internal()

                self._available = True
                self._last_error = None
                self._retry_count = 0  # Reset on successful connection
                self._next_retry_time = 0.0
                self._consecutive_failures = 0  # Reset failure counter
                self._last_successful_communication = time.monotonic()
                self._last_activity = time.monotonic()
                self._set_device_state(DEVICE_STATE_ONLINE)  # Set online immediately
                _LOGGER.info("Successfully connected to %s (device_id=%s, type=%s)",
                           self._ip, self._info.device_id, self._info.device_type_code)
                return True

            except TimeoutError:
                _LOGGER.debug("Connection timeout to %s (attempt %d/%d)",
                            self._ip, attempt + 1, max_quick_retries)
                if attempt < max_quick_retries - 1:
                    await asyncio.sleep(0.5)  # Brief delay before retry
                    continue
                self._handle_connection_failure("Connection timeout")
                return False
            except ConnectionRefusedError:
                _LOGGER.debug("Connection refused by %s (attempt %d/%d)",
                            self._ip, attempt + 1, max_quick_retries)
                if attempt < max_quick_retries - 1:
                    await asyncio.sleep(0.5)
                    continue
                self._handle_connection_failure("Connection refused")
                return False
            except OSError as e:
                # Network unreachable, host unreachable, etc.
                _LOGGER.debug("Network error connecting to %s: %s (attempt %d/%d)",
                            self._ip, e, attempt + 1, max_quick_retries)
                if attempt < max_quick_retries - 1:
                    await asyncio.sleep(0.5)
                    continue
                self._handle_connection_failure(f"Network error: {e}")
                return False
            except Exception as e:
                _LOGGER.debug("Unexpected error connecting to %s: %s", self._ip, e)
                self._handle_connection_failure(str(e))
                return False

        return False

    def _handle_connection_failure(self, error: str) -> None:
        """Handle connection failure with exponential backoff.

        Args:
            error: Error message describing the failure.
        """
        self._last_error = error
        self._retry_count = min(self._retry_count + 1, MAX_RETRY_ATTEMPTS)
        self._consecutive_failures += 1

        # Only mark device unavailable after consecutive failures threshold
        # This prevents brief network hiccups from causing unavailable state
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            if self._available:
                _LOGGER.warning(
                    "Device %s marked unavailable after %d consecutive failures",
                    self._ip,
                    self._consecutive_failures,
                )
            self._available = False

        # Calculate next retry time with exponential backoff
        delay = min(
            INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** (self._retry_count - 1)),
            MAX_RETRY_DELAY,
        )
        self._next_retry_time = time.monotonic() + delay

        _LOGGER.debug(
            "Connection failed to %s: %s (failures: %d, retry %d/%d, next in %.1fs)",
            self._ip,
            error,
            self._consecutive_failures,
            self._retry_count,
            MAX_RETRY_ATTEMPTS,
            delay,
        )

    def _configure_socket_keepalive(self) -> None:
        """Configure TCP keep-alive on the socket to detect dead connections.

        Keep-alive sends periodic probes to detect if the connection is still alive.
        This helps detect when a device goes offline without properly closing the connection.
        """
        if not self._writer:
            return

        try:
            # Get the underlying socket
            sock = self._writer.get_extra_info("socket")
            if sock is None:
                _LOGGER.debug("Could not get socket for keep-alive configuration")
                return

            # Enable TCP keep-alive
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            # Platform-specific keep-alive settings
            # These values determine how quickly we detect a dead connection
            if hasattr(socket, "TCP_KEEPIDLE"):
                # Linux: time before first probe (seconds)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
            if hasattr(socket, "TCP_KEEPINTVL"):
                # Linux: interval between probes (seconds)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            if hasattr(socket, "TCP_KEEPCNT"):
                # Linux: number of failed probes before connection is considered dead
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)

            # macOS uses TCP_KEEPALIVE instead of TCP_KEEPIDLE
            if hasattr(socket, "TCP_KEEPALIVE"):
                # macOS: time before first probe (seconds)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 30)

            _LOGGER.debug("TCP keep-alive enabled for %s", self._ip)

        except Exception as e:
            # Keep-alive is optional, don't fail the connection if it doesn't work
            _LOGGER.debug("Could not configure TCP keep-alive for %s: %s", self._ip, e)

    async def _close_connection(self) -> None:
        """Close connection and cleanup."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                _LOGGER.debug("Error while closing the connection to %s: %s", self._ip, e)
            finally:
                self._writer = None
                self._reader = None
        self._read_buffer = ""  # Clear buffer on disconnect
        # Note: Don't set _available = False here - let failure tracking handle it

    async def disconnect(self) -> None:
        """Public method to disconnect from device.

        Call this when unloading the integration to ensure clean shutdown.
        """
        async with self._lock:
            await self._close_connection()
            self._retry_count = 0
            self._next_retry_time = 0.0
            self._consecutive_failures = 0
            _LOGGER.debug("Disconnected from %s", self._ip)

    def is_connected(self) -> bool:
        """Check if connection is active.

        Returns:
            True if connection is active, False otherwise.
        """
        return self._writer is not None and not self._writer.is_closing()

    def _mark_communication_success(self) -> None:
        """Mark that communication was successful.

        This resets failure counters, retry state, and updates timing information.
        Should be called after any successful device communication.
        """
        self._available = True
        self._last_error = None
        self._consecutive_failures = 0
        self._retry_count = 0  # Reset retry count on success
        self._next_retry_time = 0.0  # Clear backoff timer on success
        self._last_successful_communication = time.monotonic()
        self._last_activity = time.monotonic()

    def _mark_communication_failure(self, error: str) -> None:
        """Mark that communication failed.

        Args:
            error: Error message describing the failure.
        """
        self._last_error = error
        self._consecutive_failures += 1
        self._last_activity = time.monotonic()

        # Only mark unavailable after consecutive failures threshold
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            if self._available:
                _LOGGER.warning(
                    "Device %s marked unavailable after %d consecutive failures: %s",
                    self._ip,
                    self._consecutive_failures,
                    error,
                )
            self._available = False

    @property
    def last_successful_communication(self) -> float:
        """Return timestamp of last successful communication.

        Returns:
            Monotonic timestamp of last success, or 0 if never communicated.
        """
        return self._last_successful_communication

    @property
    def consecutive_failures(self) -> int:
        """Return count of consecutive communication failures.

        Returns:
            Number of consecutive failures.
        """
        return self._consecutive_failures

    @property
    def needs_rediscovery(self) -> bool:
        """Check if this device has failed enough times to warrant re-discovery.

        When a device has many consecutive failures, it may have changed IP address.
        This property indicates that a network re-scan might help find the device.

        Returns:
            True if re-discovery should be attempted.
        """
        return (
            not self._available
            and self._consecutive_failures >= REDISCOVERY_ON_FAILURE_THRESHOLD
        )

    @property
    def available(self) -> bool:
        """Return if device is available.

        The availability is based on the last successful communication,
        not the current connection state. This prevents flapping when
        the TCP connection is temporarily closed between polls.

        Returns:
            True if device is available, False otherwise.
        """
        return self._available

    @property
    def check(self) -> bool:
        """Alias for available property (deprecated).

        Returns:
            True if device is available, False otherwise.
        """
        return self.available

    @property
    def dpid(self) -> list[str]:
        """Return the list of data point IDs.

        Returns:
            List of data point IDs as strings.
        """
        return self._info.dpid

    @property
    def device_model_name(self) -> str:
        """Return the device model name.

        Returns:
            The device model name.
        """
        return self._info.device_model_name

    @property
    def device_name(self) -> str:
        """Return the user-given device name.

        Returns:
            The user-given device name, or empty string if not set.
        """
        return self._info.device_name

    @property
    def icon(self) -> str:
        """Return the device icon.

        Returns:
            The device icon identifier.
        """
        return self._info.icon

    @property
    def device_type_code(self) -> str:
        """Return the device type code.

        Returns:
            The device type code (e.g., '00' for switch, '01' for light).
        """
        return self._info.device_type_code

    @property
    def device_id(self) -> str:
        """Return the device ID.

        Returns:
            The unique device identifier.
        """
        return self._info.device_id

    @property
    def info(self) -> DeviceInfo:
        """Return the full device info object.

        Returns:
            The DeviceInfo dataclass.
        """
        return self._info

    @property
    def last_error(self) -> str | None:
        """Return the last error message.

        Returns:
            The last error message, or None if no error.
        """
        return self._last_error

    async def _device_info(self) -> None:
        """Get info for device model with timeout."""
        _LOGGER.debug("Getting device info for %s", self._ip)

        if not self._writer:
            _LOGGER.error("Cannot get device info for %s: no connection", self._ip)
            return

        await self._only_send(CMD_INFO, {})

        try:
            resp = await asyncio.wait_for(
                self._reader.read(1024), timeout=self._command_timeout
            )
            resp_str = resp.decode("utf-8", errors="ignore")
            _LOGGER.debug("Device info raw response from %s: %s", self._ip, resp_str.replace("\n", "\\n").replace("\r", "\\r"))

            # Handle newline-delimited JSON - take first valid JSON line
            resp_json = None
            for line in resp_str.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    resp_json = json.loads(line)
                    if isinstance(resp_json, dict) and resp_json.get("msg"):
                        break
                except json.JSONDecodeError:
                    continue

            if not resp_json:
                _LOGGER.debug("_device_info: No valid JSON response from %s", self._ip)
                return

        except TimeoutError:
            _LOGGER.warning("_device_info timeout for %s", self._ip)
            return
        except Exception as e:
            _LOGGER.debug("_device_info.recv.error for %s: %s", self._ip, e)
            return

        msg = resp_json.get("msg")
        if msg is None or not isinstance(msg, dict):
            _LOGGER.debug("_device_info: Invalid response structure for %s", self._ip)
            return

        if msg.get("did") is None:
            _LOGGER.debug("_device_info: Missing DID for %s", self._ip)
            return

        self._info.device_id = msg["did"]
        self._info.device_name = msg.get("name", "")
        _LOGGER.debug("Device response for %s: %s", self._ip, msg)

        # Try to get device type from 'dtp' field directly (some devices provide it)
        if msg.get("dtp"):
            self._info.device_type_code = msg["dtp"]
            _LOGGER.debug("Got device type code from dtp field: %s", self._info.device_type_code)

        if msg.get("pid") is None:
            _LOGGER.debug("_device_info: Missing PID for %s, using dtp if available", self._ip)
            # Don't return - we might still have dtp
        else:
            self._info.pid = msg["pid"]

            # Try to look up device info from PID list
            pid_list = await async_get_pid_list(self._hass)

            for item in pid_list:
                match = False
                for model in item.get("m", []):
                    if model.get("pid") == self._info.pid:
                        match = True
                        self._info.icon = model.get("i", "")
                        self._info.device_model_name = model.get("n", "")
                        self._info.dpid = [str(x) for x in model.get("dpid", [])]
                        break

                if match:
                    # Only override device_type_code if not already set from dtp
                    if not self._info.device_type_code:
                        self._info.device_type_code = item.get("c", "")
                    break

        # If we still don't have device_type_code, try to infer from dpid
        if not self._info.device_type_code and self._info.dpid:
            # Lights typically have brightness (4), temp (3), hue (5), sat (6)
            # Switches typically only have switch (1)
            if any(d in self._info.dpid for d in ["3", "4", "5", "6"]):
                self._info.device_type_code = "01"  # Light
                _LOGGER.info("Inferred device type 'light' from dpid for %s", self._ip)
            else:
                self._info.device_type_code = "00"  # Switch
                _LOGGER.info("Inferred device type 'switch' from dpid for %s", self._ip)

        _LOGGER.debug(
            "Device Info for %s: ID=%s, Name=%s, Type=%s, PID=%s, Model=%s",
            self._ip,
            self._info.device_id,
            self._info.device_name,
            self._info.device_type_code,
            self._info.pid,
            self._info.device_model_name,
        )

    def _get_package(self, cmd: int, payload: dict[str, Any]) -> bytes:
        """Build a command package to send to the device.

        Args:
            cmd: The command type.
            payload: The payload data.

        Returns:
            Encoded package as bytes.

        Raises:
            ValueError: If the command type is invalid.
        """
        self._sn = get_sn()

        if cmd == CMD_SET:
            message = {
                "pv": 0,
                "cmd": cmd,
                "sn": self._sn,
                "msg": {
                    "attr": [int(item) for item in payload.keys()],
                    "data": payload,
                },
            }
        elif cmd == CMD_QUERY:
            message = {
                "pv": 0,
                "cmd": cmd,
                "sn": self._sn,
                "msg": {"attr": [0]},
            }
        elif cmd == CMD_INFO:
            message = {
                "pv": 0,
                "cmd": cmd,
                "sn": self._sn,
                "msg": {},
            }
        else:
            raise ValueError(f"Invalid command type: {cmd}")

        payload_str = json.dumps(message, separators=(",", ":"))
        _LOGGER.debug("_package=%s", payload_str)
        return (payload_str + "\r\n").encode("utf-8")

    async def _send_receiver(self, cmd: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Send command and wait for response with improved reliability.

        Args:
            cmd: The command type to send.
            payload: The payload data to send.

        Returns:
            The response data dictionary, or empty dict on failure.
        """
        async with self._lock:
            return await self._send_receiver_internal(cmd, payload)

    def _parse_json_lines(self, data: str, target_sn: str) -> dict[str, Any] | None:
        """Parse newline-delimited JSON and find the response matching our SN.

        CozyLife devices send responses as newline-delimited JSON. A single read
        may contain multiple JSON objects or partial data. This method properly
        handles splitting on newlines and finding the matching response.

        Args:
            data: Raw string data that may contain multiple JSON objects.
            target_sn: The serial number we're looking for.

        Returns:
            The parsed JSON object matching our SN, or None if not found.
        """
        # Split on common line delimiters (device uses \r\n but handle both)
        lines = data.replace("\r\n", "\n").replace("\r", "\n").split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Quick check if our SN is in this line before parsing
            if target_sn not in line:
                continue

            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                # This line is not valid JSON, skip it
                _LOGGER.debug(
                    "Skipping invalid JSON line from %s (length: %d)",
                    self._ip,
                    len(line),
                )
                continue

        return None

    async def _send_receiver_internal(
        self, cmd: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Internal send/receive without lock (to avoid deadlock).

        This method should only be called when the lock is already held.

        Args:
            cmd: The command type to send.
            payload: The payload data to send.

        Returns:
            The response data dictionary, or empty dict on failure.
        """
        # Check connection and reconnect if needed
        if not self.is_connected():
            _LOGGER.debug("Connection lost to %s, reconnecting...", self._ip)
            if not await self._connect_internal():
                return {}

        # Try to send, reconnecting once if it fails
        try:
            _LOGGER.debug("Sending command %d to %s with payload %s", cmd, self._ip, payload)
            self._writer.write(self._get_package(cmd, payload))
            await asyncio.wait_for(self._writer.drain(), timeout=self._command_timeout)
        except Exception as send_error:
            _LOGGER.debug("Send failed to %s: %s, reconnecting and retrying...", self._ip, send_error)
            await self._close_connection()
            if not await self._connect_internal():
                return {}
            # Retry send after reconnect
            try:
                self._writer.write(self._get_package(cmd, payload))
                await asyncio.wait_for(self._writer.drain(), timeout=self._command_timeout)
            except Exception as retry_error:
                _LOGGER.warning("Send retry failed to %s: %s", self._ip, retry_error)
                self._mark_communication_failure(str(retry_error))
                await self._close_connection()
                return {}

        try:

            # Wait for response with retry logic for timeouts
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    res = await asyncio.wait_for(
                        self._reader.read(1024), timeout=self._response_timeout
                    )
                    if not res:
                        _LOGGER.debug("Empty response from %s, connection may be closed", self._ip)
                        self._mark_communication_failure("Empty response")
                        await self._close_connection()
                        return {}

                    res_str = res.decode("utf-8", errors="ignore")
                    _LOGGER.debug("Received from %s: %s", self._ip, res_str.replace(chr(10), '\\n').replace(chr(13), '\\r'))

                    # Add to buffer for handling partial responses
                    self._read_buffer += res_str

                    # Check if response contains our serial number
                    if self._sn in self._read_buffer:
                        # Parse newline-delimited JSON to find our response
                        response_payload = self._parse_json_lines(self._read_buffer, self._sn)

                        # Clear buffer after successful parse
                        self._read_buffer = ""

                        if not response_payload:
                            _LOGGER.debug("No valid JSON with our SN found from %s", self._ip)
                            continue

                        msg = response_payload.get("msg")
                        if msg is None or not isinstance(msg, dict):
                            return {}

                        # Capture attr if present to populate dpid if missing
                        if "attr" in msg and isinstance(msg["attr"], list):
                            if not self._info.dpid:
                                self._info.dpid = [str(x) for x in msg["attr"]]
                                _LOGGER.info("Discovered DPIDs from query: %s", self._info.dpid)

                        data = msg.get("data")
                        if data is None or not isinstance(data, dict):
                            return {}

                        # Success! Mark communication as successful
                        self._mark_communication_success()
                        return data
                    else:
                        # Response received but wrong serial number - stale data, try again
                        _LOGGER.debug(
                            "Response from %s with different SN, reading again", self._ip
                        )
                        # Keep buffer for next read in case of fragmented response
                        continue

                except TimeoutError:
                    _LOGGER.debug(
                        "Timeout waiting for response from %s (attempt %d/%d)",
                        self._ip,
                        attempt + 1,
                        MAX_RETRY_ATTEMPTS,
                    )
                    # Clear buffer on timeout
                    self._read_buffer = ""
                    # Only mark failure on final attempt
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        self._mark_communication_failure("Response timeout")
                        return {}
                    continue

            # All retry attempts exhausted
            self._read_buffer = ""  # Clear buffer
            _LOGGER.debug("No valid response received from %s after %d attempts", self._ip, MAX_RETRY_ATTEMPTS)
            self._mark_communication_failure("No valid response")
            return {}

        except Exception as e:
            _LOGGER.warning("_send_receiver error for %s: %s", self._ip, e)
            self._read_buffer = ""  # Clear buffer on error
            self._mark_communication_failure(str(e))
            await self._close_connection()
            return {}

    async def _only_send(self, cmd: int, payload: dict[str, Any]) -> None:
        """Send command without waiting for response (used internally).

        Args:
            cmd: The command type to send.
            payload: The payload data to send.
        """
        if not self._writer:
            _LOGGER.warning("Cannot send to %s: no connection", self._ip)
            return

        try:
            _LOGGER.debug("Sending only command %d to %s", cmd, self._ip)
            self._writer.write(self._get_package(cmd, payload))
            await asyncio.wait_for(self._writer.drain(), timeout=self._command_timeout)
            self._last_activity = time.monotonic()
        except TimeoutError:
            _LOGGER.debug("Send timeout to %s", self._ip)
            self._mark_communication_failure("Send timeout")
        except Exception as e:
            _LOGGER.debug("Send failed to %s: %s", self._ip, e)
            self._mark_communication_failure(str(e))

    async def control(self, payload: dict[str, Any]) -> bool:
        """Send control command.

        When persistent connection is active, this just sends the command
        without waiting for response (the receive loop handles responses).
        Otherwise, waits for acknowledgment.

        Args:
            payload: The control payload to send.

        Returns:
            True if command was sent successfully, False otherwise.
        """
        # Check if persistent connection is active
        persistent_mode = (
            self._receive_loop_task is not None
            and not self._receive_loop_task.done()
        )

        async with self._lock:
            # Check connection and reconnect if needed
            if not self.is_connected():
                _LOGGER.debug("Connection lost to %s, reconnecting for control...", self._ip)
                if not await self._connect_internal():
                    return False

            # Try to send, reconnecting once if it fails
            try:
                _LOGGER.debug("Sending control command to %s with payload %s", self._ip, payload)
                self._writer.write(self._get_package(CMD_SET, payload))
                await asyncio.wait_for(self._writer.drain(), timeout=self._command_timeout)
            except Exception as send_error:
                _LOGGER.debug("Control send failed to %s: %s, reconnecting and retrying...", self._ip, send_error)
                await self._close_connection()
                if not await self._connect_internal():
                    return False
                # Retry send after reconnect
                try:
                    self._writer.write(self._get_package(CMD_SET, payload))
                    await asyncio.wait_for(self._writer.drain(), timeout=self._command_timeout)
                except Exception as retry_error:
                    _LOGGER.warning("Control retry failed to %s: %s", self._ip, retry_error)
                    self._mark_communication_failure(str(retry_error))
                    await self._close_connection()
                    return False

            # In persistent mode, don't wait for response - receive loop handles it
            if persistent_mode:
                _LOGGER.debug("Control sent to %s (persistent mode, no response wait)", self._ip)
                self._last_activity = time.monotonic()
                return True

            # Non-persistent mode: wait for acknowledgment
            try:
                res = await asyncio.wait_for(
                    self._reader.read(1024), timeout=self._response_timeout
                )
                if res:
                    res_str = res.decode("utf-8", errors="ignore")
                    _LOGGER.debug(
                        "Control response from %s: %s",
                        self._ip,
                        res_str.replace(chr(10), '\\n').replace(chr(13), '\\r')
                    )

                    # Parse newline-delimited JSON to find our response
                    # Device may send multiple JSON objects in one response
                    response_payload = self._parse_json_lines(res_str, self._sn)

                    if response_payload:
                        # Found our response
                        self._mark_communication_success()
                        return True
                    else:
                        # Response received but our SN not found - may be stale data
                        # Consider command successful since device responded
                        _LOGGER.debug(
                            "Response from %s with different SN, assuming success", self._ip
                        )
                        self._mark_communication_success()
                        return True
                else:
                    _LOGGER.debug("Empty control response from %s", self._ip)
                    self._mark_communication_failure("Empty response")
                    await self._close_connection()
                    return False
            except TimeoutError:
                # Some devices may not send acknowledgment, but command might still work
                _LOGGER.debug(
                    "No acknowledgment from %s, but command may have succeeded", self._ip
                )
                # Don't mark as failure - command likely worked
                self._last_activity = time.monotonic()
                return True
            except Exception as e:
                _LOGGER.warning("Control command failed for %s: %s", self._ip, e)
                self._mark_communication_failure(str(e))
                await self._close_connection()
                return False

    async def query(self) -> dict[str, Any]:
        """Query device state.

        When persistent connection is active, returns cached state to avoid
        conflicts with the receive loop. Otherwise, performs direct query.

        Returns:
            The device state dictionary, or empty dict on failure.
        """
        # If persistent connection is running, use cached state
        # The receive loop keeps it updated via push notifications
        if self._receive_loop_task is not None and not self._receive_loop_task.done():
            if self._last_state:
                _LOGGER.debug("Using cached state for %s: %s", self._ip, self._last_state)
                return self._last_state.copy()
            # No cached state yet, fall through to direct query
            _LOGGER.debug("No cached state for %s, doing direct query", self._ip)

        return await self._send_receiver(CMD_QUERY, {})

    async def _query_internal(self) -> dict[str, Any]:
        """Internal query without lock (to avoid deadlock).

        This method should only be called when the lock is already held.

        Returns:
            The device state dictionary, or empty dict on failure.
        """
        return await self._send_receiver_internal(CMD_QUERY, {})

    async def heartbeat(self) -> bool:
        """Send a heartbeat to keep connection alive and verify device responsiveness.

        This uses a query command as the heartbeat since CozyLife devices
        don't have a dedicated ping command. The query is lightweight and
        also updates our cached state.

        Returns:
            True if heartbeat succeeded, False if device is unresponsive.
        """
        # Check if heartbeat is needed based on last activity
        time_since_activity = time.monotonic() - self._last_activity
        if time_since_activity < HEARTBEAT_INTERVAL:
            # Recent activity, no heartbeat needed
            _LOGGER.debug(
                "Skipping heartbeat for %s, last activity %.1fs ago",
                self._ip,
                time_since_activity,
            )
            return True

        _LOGGER.debug("Sending heartbeat to %s", self._ip)

        try:
            # Use a shorter timeout for heartbeat to detect issues quickly
            original_response_timeout = self._response_timeout
            self._response_timeout = min(self._response_timeout, HEARTBEAT_TIMEOUT)

            try:
                result = await self.query()
                if result:
                    _LOGGER.debug("Heartbeat successful for %s", self._ip)
                    return True
                else:
                    _LOGGER.debug("Heartbeat failed for %s: empty response", self._ip)
                    return False
            finally:
                self._response_timeout = original_response_timeout

        except Exception as e:
            _LOGGER.debug("Heartbeat exception for %s: %s", self._ip, e)
            return False

    def needs_heartbeat(self) -> bool:
        """Check if this device needs a heartbeat.

        Returns:
            True if heartbeat should be sent (connection idle too long).
        """
        if not self.is_connected():
            return False
        time_since_activity = time.monotonic() - self._last_activity
        return time_since_activity >= HEARTBEAT_INTERVAL

    # =========================================================================
    # Persistent Connection and Receive Loop Methods
    # =========================================================================

    @property
    def device_state(self) -> str:
        """Return the current device state.

        Returns:
            One of DEVICE_STATE_ONLINE, DEVICE_STATE_OFFLINE, DEVICE_STATE_CONNECTING, DEVICE_STATE_UNKNOWN.
        """
        return self._device_state

    @property
    def last_state(self) -> dict[str, Any]:
        """Return the last known device state.

        Returns:
            Dictionary of data point values from the last successful query.
        """
        return self._last_state.copy()

    @property
    def ip(self) -> str:
        """Return the current IP address.

        Returns:
            The IP address this client is connected to.
        """
        return self._ip

    def register_state_callback(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Register a callback for state updates.

        The callback will be called whenever the device state changes or
        when new data is received from the device.

        Args:
            callback: Function(device_id, state_dict) to call on updates.

        Returns:
            A function to unregister the callback.
        """
        self._state_callbacks.append(callback)

        def unregister():
            if callback in self._state_callbacks:
                self._state_callbacks.remove(callback)

        return unregister

    def _dispatch_state(self, state: dict[str, Any]) -> None:
        """Dispatch state update to all registered callbacks.

        Args:
            state: The new state dictionary.
        """
        if state:
            self._last_state.update(state)

        for callback in self._state_callbacks:
            try:
                callback(self._info.device_id, self._last_state)
            except Exception as e:
                _LOGGER.warning(
                    "Error in state callback for %s: %s", self._ip, e
                )

    def _set_device_state(self, new_state: str) -> None:
        """Set the device state and log the transition.

        Args:
            new_state: The new device state.
        """
        if self._device_state != new_state:
            old_state = self._device_state
            self._device_state = new_state
            _LOGGER.info(
                "Device %s (%s) state: %s -> %s",
                self._info.device_id or "unknown",
                self._ip,
                old_state,
                new_state,
            )

    async def start_persistent_connection(self) -> None:
        """Start the persistent connection and receive loop.

        This method starts the background tasks that maintain the connection
        and listen for device updates. Call this after initial connect() to
        enable push-style updates.
        """
        if self._is_closing:
            _LOGGER.debug("Cannot start persistent connection for %s: closing", self._ip)
            return

        if self._receive_loop_task is not None and not self._receive_loop_task.done():
            _LOGGER.debug("Receive loop already running for %s", self._ip)
            return

        _LOGGER.info("Starting persistent connection for %s", self._ip)
        self._is_closing = False
        self._receive_loop_task = asyncio.create_task(self._receive_loop())

    async def stop_persistent_connection(self) -> None:
        """Stop the persistent connection and all background tasks.

        Call this when unloading the integration or when the device should
        no longer be monitored.
        """
        _LOGGER.info("Stopping persistent connection for %s", self._ip)
        self._is_closing = True

        # Cancel receive loop (reconnection is now integrated into receive loop)
        if self._receive_loop_task is not None:
            self._receive_loop_task.cancel()
            try:
                await self._receive_loop_task
            except asyncio.CancelledError:
                pass
            self._receive_loop_task = None

        # Close connection
        await self.disconnect()
        self._set_device_state(DEVICE_STATE_OFFLINE)

    async def _receive_loop(self) -> None:
        """Continuous loop that manages connection and receives data.

        This loop runs as long as the client is active and handles:
        - Establishing and re-establishing connections
        - Receiving push updates from the device
        - Detecting connection loss
        - Automatic reconnection with exponential backoff
        """
        _LOGGER.debug("Receive loop started for %s", self._ip)

        while not self._is_closing:
            try:
                # Phase 1: Ensure we're connected
                if not self.is_connected():
                    self._set_device_state(DEVICE_STATE_CONNECTING)

                    # Try to connect (non-blocking reconnection attempt)
                    try:
                        connected = await self.connect(force=True)
                        if connected:
                            _LOGGER.info(
                                "Receive loop connected to %s (%s)",
                                self._ip,
                                self._info.device_id or "unknown",
                            )
                            self._set_device_state(DEVICE_STATE_ONLINE)
                            self._reconnect_delay = RECONNECT_MIN_INTERVAL

                            # Query current state after connection
                            state = await self.query()
                            if state:
                                self._dispatch_state(state)
                        else:
                            # Connection failed, wait with backoff then try again
                            self._set_device_state(DEVICE_STATE_OFFLINE)
                            _LOGGER.debug(
                                "Receive loop connect failed for %s, waiting %.1fs",
                                self._ip,
                                self._reconnect_delay,
                            )
                            await asyncio.sleep(self._reconnect_delay)
                            self._reconnect_delay = min(
                                self._reconnect_delay * RECONNECT_BACKOFF_FACTOR,
                                RECONNECT_MAX_INTERVAL,
                            )
                            continue
                    except Exception as e:
                        _LOGGER.debug("Receive loop connect error for %s: %s", self._ip, e)
                        self._set_device_state(DEVICE_STATE_OFFLINE)
                        await asyncio.sleep(self._reconnect_delay)
                        self._reconnect_delay = min(
                            self._reconnect_delay * RECONNECT_BACKOFF_FACTOR,
                            RECONNECT_MAX_INTERVAL,
                        )
                        continue

                # Phase 2: Read data from connection
                self._set_device_state(DEVICE_STATE_ONLINE)

                try:
                    # Check if reader is still valid
                    if not self._reader:
                        _LOGGER.debug("Reader gone for %s, will reconnect", self._ip)
                        await self._close_connection()
                        continue

                    data = await asyncio.wait_for(
                        self._reader.read(1024),
                        timeout=RECEIVE_LOOP_TIMEOUT,
                    )

                    if not data:
                        # Empty read means connection closed by remote
                        _LOGGER.debug("Empty read from %s, connection closed", self._ip)
                        self._mark_communication_failure("Connection closed by device")
                        await self._close_connection()
                        continue

                    # Process received data
                    await self._process_received_data(data)
                    self._mark_communication_success()

                except TimeoutError:
                    # No data received within timeout - this is normal for idle connections
                    # Send a heartbeat to verify connection is still alive
                    if self.needs_heartbeat():
                        _LOGGER.debug("Sending heartbeat for %s", self._ip)
                        if not await self._send_heartbeat_internal():
                            # Heartbeat failed, connection may be dead
                            _LOGGER.debug("Heartbeat failed for %s, will reconnect", self._ip)
                            await self._close_connection()
                            continue

                except (ConnectionError, OSError) as e:
                    # Connection error during read
                    _LOGGER.debug("Connection error for %s: %s", self._ip, e)
                    self._mark_communication_failure(str(e))
                    await self._close_connection()
                    continue

            except asyncio.CancelledError:
                _LOGGER.debug("Receive loop cancelled for %s", self._ip)
                break
            except Exception as e:
                _LOGGER.warning("Receive loop unexpected error for %s: %s", self._ip, e)
                await self._close_connection()
                await asyncio.sleep(RECEIVE_LOOP_RETRY_DELAY)

        _LOGGER.debug("Receive loop ended for %s", self._ip)

    async def _process_received_data(self, data: bytes) -> None:
        """Process data received from the device.

        This parses incoming JSON messages and dispatches state updates
        to registered callbacks.

        Args:
            data: Raw bytes received from the device.
        """
        try:
            data_str = data.decode("utf-8", errors="ignore")
            _LOGGER.debug(
                "Received push data from %s: %s",
                self._ip,
                data_str.replace("\n", "\\n").replace("\r", "\\r"),
            )

            # Parse newline-delimited JSON
            for line in data_str.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                line = line.strip()
                if not line:
                    continue

                try:
                    parsed = json.loads(line)
                    if not isinstance(parsed, dict):
                        continue

                    msg = parsed.get("msg")
                    if msg and isinstance(msg, dict):
                        data_payload = msg.get("data")
                        if data_payload and isinstance(data_payload, dict):
                            _LOGGER.debug(
                                "Push state update from %s: %s",
                                self._ip,
                                data_payload,
                            )
                            self._mark_communication_success()
                            self._dispatch_state(data_payload)

                except json.JSONDecodeError:
                    continue

        except Exception as e:
            _LOGGER.debug("Error processing received data from %s: %s", self._ip, e)

    async def _send_heartbeat_internal(self) -> bool:
        """Send heartbeat query without using the public query method.

        This is used within the receive loop to avoid lock contention.

        Returns:
            True if heartbeat succeeded.
        """
        try:
            if not self._writer or self._writer.is_closing():
                return False

            # Send a query command
            self._writer.write(self._get_package(CMD_QUERY, {}))
            await asyncio.wait_for(self._writer.drain(), timeout=self._command_timeout)
            self._last_activity = time.monotonic()
            return True
        except Exception as e:
            _LOGGER.debug("Heartbeat send failed for %s: %s", self._ip, e)
            return False

    def update_ip(self, new_ip: str) -> bool:
        """Update the device IP address.

        This is called when re-discovery finds the device at a new IP.
        The connection will be reset to use the new IP.

        Args:
            new_ip: The new IP address for this device.

        Returns:
            True if the IP was changed, False if it was the same.
        """
        if new_ip == self._ip:
            return False

        old_ip = self._ip
        self._ip = new_ip
        _LOGGER.info(
            "Device %s IP changed: %s -> %s",
            self._info.device_id or "unknown",
            old_ip,
            new_ip,
        )

        # Reset retry state for fresh connection attempt
        self._retry_count = 0
        self._next_retry_time = 0.0
        self._reconnect_delay = RECONNECT_MIN_INTERVAL

        return True

    async def reconnect_with_new_ip(self, new_ip: str) -> bool:
        """Reconnect to the device at a new IP address.

        Args:
            new_ip: The new IP address.

        Returns:
            True if reconnection succeeded.
        """
        if not self.update_ip(new_ip):
            # Same IP, just try to reconnect
            pass

        # Close existing connection
        await self._close_connection()

        # Try to connect
        return await self.connect(force=True)


# Backward compatibility alias
tcp_client = TcpClient
