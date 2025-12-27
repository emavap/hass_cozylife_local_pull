# -*- coding: utf-8 -*-
import json
import asyncio
import logging
from typing import Optional, Union, Any, Dict, List
from .utils import async_get_pid_list, get_sn

CMD_INFO: int = 0
CMD_QUERY: int = 2
CMD_SET: int = 3
CMD_LIST: List[int] = [CMD_INFO, CMD_QUERY, CMD_SET]
_LOGGER = logging.getLogger(__name__)


class TcpClient:
    """Represents a CozyLife device connection."""

    _port: int = 5555

    def __init__(self, ip: str) -> None:
        """Initialize the TCP client.

        Args:
            ip: The IP address of the device.
        """
        self._ip: str = ip
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._available: bool = False

        # Device info - initialized per instance to avoid shared state
        self._device_id: str = ""
        self._pid: str = ""
        self._device_type_code: str = ""
        self._icon: str = ""
        self._device_model_name: str = ""
        self._dpid: List[str] = []
        self._sn: str = ""
        self._last_error: Optional[str] = None
    
    async def connect(self) -> bool:
        """Establish connection to device with improved error handling.

        Returns:
            True if connection was successful, False otherwise.
        """
        async with self._lock:
            return await self._connect_internal()

    async def _connect_internal(self) -> bool:
        """Internal connect method without lock (to avoid deadlock).

        This method should only be called when the lock is already held.

        Returns:
            True if connection was successful, False otherwise.
        """
        try:
            # Close existing connection if any
            if self._writer:
                await self._close_connection()

            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._ip, self._port), timeout=5
            )

            # Get device info with timeout
            await asyncio.wait_for(self._device_info(), timeout=5)

            # If dpid is still empty, try to query to get attributes
            if not self._dpid:
                _LOGGER.info(f"DPID empty for {self._ip}, querying device for attributes")
                await self._query_internal()

            self._available = True
            self._last_error = None
            _LOGGER.info(f'Successfully connected to {self._ip}')
            return True
        except asyncio.TimeoutError:
            self._available = False
            self._last_error = "Connection timeout"
            _LOGGER.warning(f'Connection timeout to {self._ip}')
            await self._close_connection()
            return False
        except Exception as e:
            self._available = False
            self._last_error = str(e)
            _LOGGER.warning(f'Connection failed to {self._ip}: {e}')
            await self._close_connection()
            return False

    async def _close_connection(self) -> None:
        """Close connection and cleanup."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                _LOGGER.debug(f'Error while closing the connection to {self._ip}: {e}')
            finally:
                self._writer = None
                self._reader = None
        self._available = False

    async def disconnect(self) -> None:
        """Public method to disconnect from device.

        Call this when unloading the integration to ensure clean shutdown.
        """
        async with self._lock:
            await self._close_connection()
            _LOGGER.debug(f"Disconnected from {self._ip}")

    def is_connected(self) -> bool:
        """Check if connection is active.

        Returns:
            True if connection is active, False otherwise.
        """
        return self._writer is not None and not self._writer.is_closing()

    @property
    def available(self) -> bool:
        """Return if device is available.

        Returns:
            True if device is available, False otherwise.
        """
        return self._available and self.is_connected()

    @property
    def check(self) -> bool:
        """Alias for available property.

        Returns:
            True if device is available, False otherwise.
        """
        return self.available

    @property
    def dpid(self) -> List[str]:
        """Return the list of data point IDs.

        Returns:
            List of data point IDs as strings.
        """
        return self._dpid

    @property
    def device_model_name(self) -> str:
        """Return the device model name.

        Returns:
            The device model name.
        """
        return self._device_model_name

    @property
    def icon(self) -> str:
        """Return the device icon.

        Returns:
            The device icon identifier.
        """
        return self._icon

    @property
    def device_type_code(self) -> str:
        """Return the device type code.

        Returns:
            The device type code (e.g., '00' for switch, '01' for light).
        """
        return self._device_type_code

    @property
    def device_id(self) -> str:
        """Return the device ID.

        Returns:
            The unique device identifier.
        """
        return self._device_id
    
    async def _device_info(self) -> None:
        """
        Get info for device model with timeout
        """
        _LOGGER.debug(f"Getting device info for {self._ip}")

        if not self._writer:
            _LOGGER.error(f"Cannot get device info for {self._ip}: no connection")
            return None

        await self._only_send(CMD_INFO, {})

        try:
            # Add timeout to read operation
            resp = await asyncio.wait_for(self._reader.read(1024), timeout=3)
            resp_json = json.loads(resp.strip())
        except asyncio.TimeoutError:
            _LOGGER.warning(f'_device_info timeout for {self._ip}')
            return None
        except json.JSONDecodeError as e:
            _LOGGER.debug(f'_device_info JSON decode error for {self._ip}: {e}')
            return None
        except Exception as e:
            _LOGGER.debug(f'_device_info.recv.error for {self._ip}: {e}')
            return None

        if resp_json.get('msg') is None or not isinstance(resp_json['msg'], dict):
            _LOGGER.debug(f'_device_info.recv.error1 for {self._ip}: Invalid response structure')
            return None

        if resp_json['msg'].get('did') is None:
            _LOGGER.debug(f'_device_info.recv.error2 for {self._ip}: Missing DID')
            return None

        self._device_id = resp_json['msg']['did']

        if resp_json['msg'].get('pid') is None:
            _LOGGER.debug(f'_device_info.recv.error3 for {self._ip}: Missing PID')
            return None

        self._pid = resp_json['msg']['pid']
        pid_list = await async_get_pid_list()

        for item in pid_list:
            match = False
            for item1 in item['m']:
                if item1['pid'] == self._pid:
                    match = True
                    self._icon = item1['i']
                    self._device_model_name = item1['n']
                    self._dpid = [str(x) for x in item1['dpid']]
                    break

            if match:
                self._device_type_code = item['c']
                break

        _LOGGER.debug(f"Device Info for {self._ip}: ID={self._device_id}, Type={self._device_type_code}, PID={self._pid}, Model={self._device_model_name}")
    
    def _get_package(self, cmd: int, payload: dict) -> bytes:
        self._sn = get_sn()
        if CMD_SET == cmd:
            message = {
                'pv': 0,
                'cmd': cmd,
                'sn': self._sn,
                'msg': {
                    'attr': [int(item) for item in payload.keys()],
                    'data': payload,
                }
            }
        elif CMD_QUERY == cmd:
            message = {
                'pv': 0,
                'cmd': cmd,
                'sn': self._sn,
                'msg': {
                    'attr': [0],
                }
            }
        elif CMD_INFO == cmd:
            message = {
                'pv': 0,
                'cmd': cmd,
                'sn': self._sn,
                'msg': {}
            }
        else:
            raise Exception('CMD is not valid')
        
        payload_str = json.dumps(message, separators=(',', ':',))
        _LOGGER.debug(f'_package={payload_str}')
        return bytes(payload_str + "\r\n", encoding='utf8')
    
    async def _send_receiver(self, cmd: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send command and wait for response with improved reliability.

        Args:
            cmd: The command type to send.
            payload: The payload data to send.

        Returns:
            The response data dictionary, or empty dict on failure.
        """
        async with self._lock:
            return await self._send_receiver_internal(cmd, payload)

    async def _send_receiver_internal(self, cmd: int, payload: Dict[str, Any]) -> Dict[str, Any]:
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
            _LOGGER.debug(f"Connection lost to {self._ip}, reconnecting...")
            if not await self._connect_internal():
                self._available = False
                return {}

        try:
            _LOGGER.debug(f"Sending command {cmd} to {self._ip} with payload {payload}")
            self._writer.write(self._get_package(cmd, payload))
            await asyncio.wait_for(self._writer.drain(), timeout=3)

            # Wait for response with improved logic
            max_attempts = 3  # Reduced from 5 for faster failure detection
            for attempt in range(max_attempts):
                try:
                    res = await asyncio.wait_for(self._reader.read(1024), timeout=2)  # Reduced from 3s
                    if not res:
                        _LOGGER.debug(f"Empty response from {self._ip}")
                        await self._close_connection()
                        break

                    res_str = res.decode('utf-8', errors='ignore')
                    _LOGGER.debug(f"Received from {self._ip}: {res_str}")

                    if self._sn in res_str:
                        try:
                            response_payload = json.loads(res_str.strip())
                        except json.JSONDecodeError:
                            _LOGGER.debug(f"JSON decode error from {self._ip}")
                            continue

                        if response_payload is None or len(response_payload) == 0:
                            return {}

                        if response_payload.get('msg') is None or not isinstance(response_payload['msg'], dict):
                            return {}

                        # Capture attr if present to populate dpid if missing
                        if 'attr' in response_payload['msg'] and isinstance(response_payload['msg']['attr'], list):
                            if not self._dpid:
                                self._dpid = [str(x) for x in response_payload['msg']['attr']]
                                _LOGGER.info(f"Discovered DPIDs from query: {self._dpid}")

                        if response_payload['msg'].get('data') is None or not isinstance(response_payload['msg']['data'], dict):
                            return {}

                        self._available = True
                        self._last_error = None
                        return response_payload['msg']['data']

                except asyncio.TimeoutError:
                    _LOGGER.debug(f"Timeout waiting for response from {self._ip} (attempt {attempt+1}/{max_attempts})")
                    if attempt == max_attempts - 1:
                        self._available = False
                        self._last_error = "Response timeout"
                    continue

            _LOGGER.warning(f"No valid response received from {self._ip}")
            self._available = False
            return {}

        except Exception as e:
            _LOGGER.warning(f'_send_receiver error for {self._ip}: {e}')
            self._available = False
            self._last_error = str(e)
            await self._close_connection()
            return {}
    
    async def _only_send(self, cmd: int, payload: Dict[str, Any]) -> None:
        """Send command without waiting for response (used internally).

        Args:
            cmd: The command type to send.
            payload: The payload data to send.
        """
        if not self._writer:
            _LOGGER.warning(f"Cannot send to {self._ip}: no connection")
            return

        try:
            _LOGGER.debug(f"Sending only command {cmd} to {self._ip}")
            self._writer.write(self._get_package(cmd, payload))
            await asyncio.wait_for(self._writer.drain(), timeout=3)
        except asyncio.TimeoutError:
            _LOGGER.error(f"Send timeout to {self._ip}")
            self._available = False
        except Exception as e:
            _LOGGER.error(f"Send failed to {self._ip}: {e}")
            self._available = False

    async def control(self, payload: Dict[str, Any]) -> bool:
        """Send control command and wait for confirmation.

        Args:
            payload: The control payload to send.

        Returns:
            True if command was sent successfully, False otherwise.
        """
        async with self._lock:
            # Check connection and reconnect if needed
            if not self.is_connected():
                _LOGGER.debug(f"Connection lost to {self._ip}, reconnecting for control...")
                if not await self._connect_internal():
                    self._available = False
                    return False

            try:
                _LOGGER.debug(f"Sending control command to {self._ip} with payload {payload}")
                self._writer.write(self._get_package(CMD_SET, payload))
                await asyncio.wait_for(self._writer.drain(), timeout=3)

                # Wait for acknowledgment with shorter timeout
                try:
                    res = await asyncio.wait_for(self._reader.read(1024), timeout=2)
                    if res:
                        res_str = res.decode('utf-8', errors='ignore')
                        _LOGGER.debug(f"Control response from {self._ip}: {res_str}")

                        # Check if response contains our serial number (acknowledgment)
                        if self._sn in res_str:
                            self._available = True
                            self._last_error = None
                            return True
                    else:
                        _LOGGER.warning(f"Empty control response from {self._ip}")
                        self._available = False
                        self._last_error = "Empty response"
                        await self._close_connection()
                        return False
                except asyncio.TimeoutError:
                    # Some devices may not send acknowledgment, but command might still work
                    _LOGGER.debug(f"No acknowledgment from {self._ip}, but command may have succeeded")
                    self._available = True
                    self._last_error = None
                    return True

                self._available = True
                self._last_error = None
                return True

            except Exception as e:
                _LOGGER.warning(f'Control command failed for {self._ip}: {e}')
                self._available = False
                self._last_error = str(e)
                await self._close_connection()
                return False

    async def query(self) -> Dict[str, Any]:
        """Query device state.

        Returns:
            The device state dictionary, or empty dict on failure.
        """
        return await self._send_receiver(CMD_QUERY, {})

    async def _query_internal(self) -> Dict[str, Any]:
        """Internal query without lock (to avoid deadlock).

        This method should only be called when the lock is already held.

        Returns:
            The device state dictionary, or empty dict on failure.
        """
        return await self._send_receiver_internal(CMD_QUERY, {})


# Backward compatibility alias
tcp_client = TcpClient
