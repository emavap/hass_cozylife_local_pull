# -*- coding: utf-8 -*-
import json
import asyncio
import logging
from typing import Optional, Union, Any
from .utils import async_get_pid_list, get_sn

CMD_INFO = 0
CMD_QUERY = 2
CMD_SET = 3
CMD_LIST = [CMD_INFO, CMD_QUERY, CMD_SET]
_LOGGER = logging.getLogger(__name__)


class tcp_client(object):
    """
    Represents a device
    """
    _ip = str
    _port = 5555
    
    _device_id = str
    _pid = str
    _device_type_code = str
    _icon = str
    _device_model_name = str
    _dpid = []
    _sn = str
    
    def __init__(self, ip):
        self._ip = ip
        self._reader = None
        self._writer = None
        self._lock = asyncio.Lock()
    
    async def connect(self):
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._ip, self._port), timeout=3
            )
            await self._device_info()
            return True
        except Exception as e:
            _LOGGER.warning(f'Connection failed to {self._ip}: {e}')
            return False

    async def _close_connection(self):
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                _LOGGER.error(f'Error while closing the connection: {e}')
            self._writer = None
            self._reader = None

    @property
    def check(self) -> bool:
        return True
    
    @property
    def dpid(self):
        return self._dpid
    
    @property
    def device_model_name(self):
        return self._device_model_name
    
    @property
    def icon(self):
        return self._icon
    
    @property
    def device_type_code(self) -> str:
        return self._device_type_code
    
    @property
    def device_id(self):
        return self._device_id
    
    async def _device_info(self) -> None:
        """
        get info for device model
        """
        await self._only_send(CMD_INFO, {})
        try:
            resp = await self._reader.read(1024)
            resp_json = json.loads(resp.strip())            
        except Exception as e:
            _LOGGER.info(f'_device_info.recv.error: {e}')
            return None
        
        if resp_json.get('msg') is None or not isinstance(resp_json['msg'], dict):
            _LOGGER.info('_device_info.recv.error1')
            return None
        
        if resp_json['msg'].get('did') is None:
            _LOGGER.info('_device_info.recv.error2')
            return None

        self._device_id = resp_json['msg']['did']
        
        if resp_json['msg'].get('pid') is None:
            _LOGGER.info('_device_info.recv.error3')
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
                    self._dpid = item1['dpid']
                    break
            
            if match:
                self._device_type_code = item['c']                
                break
        
        _LOGGER.info(f"Device Info: {self._device_id}, {self._device_type_code}, {self._pid}, {self._device_model_name}")
    
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
    
    async def _send_receiver(self, cmd: int, payload: dict) -> Union[dict, Any]:
        async with self._lock:
            if not self._writer:
                if not await self.connect():
                    return {}

            try:
                self._writer.write(self._get_package(cmd, payload))
                await self._writer.drain()
                
                i = 10
                while i > 0:
                    try:
                        res = await asyncio.wait_for(self._reader.read(1024), timeout=2)
                    except asyncio.TimeoutError:
                        _LOGGER.debug("Timeout waiting for response")
                        break
                        
                    i -= 1
                    res_str = res.decode('utf-8', errors='ignore')
                    if self._sn in res_str:
                        try:
                            payload = json.loads(res_str.strip())
                        except json.JSONDecodeError:
                            continue
                            
                        if payload is None or len(payload) == 0:
                            return {}

                        if payload.get('msg') is None or not isinstance(payload['msg'], dict):
                            return {}

                        if payload['msg'].get('data') is None or not isinstance(payload['msg']['data'], dict):
                            return {}

                        return payload['msg']['data']

                return {}

            except Exception as e:
                _LOGGER.info(f'_send_receiver error: {e}')
                await self._close_connection()
                return {}
    
    async def _only_send(self, cmd: int, payload: dict) -> None:
        if not self._writer:
             pass
             
        try:
            self._writer.write(self._get_package(cmd, payload))
            await self._writer.drain()
        except Exception as e:
             _LOGGER.error(f"Send failed: {e}")

    async def control(self, payload: dict) -> bool:
        await self._only_send(CMD_SET, payload)
        return True
    
    async def query(self) -> dict:
        return await self._send_receiver(CMD_QUERY, {})