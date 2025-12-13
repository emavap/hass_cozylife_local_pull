# -*- coding: utf-8 -*-
import json
import time
import aiohttp
import logging
from .const import (
    API_DOMAIN,
    LANG
)
_LOGGER = logging.getLogger(__name__)


def get_sn() -> str:
    """
    message sn
    :return: str
    """
    return str(int(round(time.time() * 1000)))


# cache get_pid_list result for many calls
_CACHE_PID = []


async def async_get_pid_list(lang='en') -> list:
    """
    http://doc.doit/project-12/doc-95/
    :param lang:
    :return:
    """
    global _CACHE_PID
    if len(_CACHE_PID) != 0:
        return _CACHE_PID
    
    if lang not in ['zh', 'en', 'es', 'pt', 'ja', 'ru', 'pt', 'nl', 'ko', 'fr', 'de',]:
        _LOGGER.info(f'not support lang={lang}, will set lang={LANG}')
        lang = LANG

    url = f'http://{API_DOMAIN}/api/v2/device_product/model'
    params = {'lang': lang}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=3) as res:
                if res.status != 200:
                    _LOGGER.info('get_pid_list.result is none')
                    return []
                content = await res.text()
                try:
                    pid_list = json.loads(content)
                except:
                    _LOGGER.info('get_pid_list.result is not json')
                    return []
    except Exception as e:
        _LOGGER.info(f'get_pid_list error: {e}')
        return []
    
    if pid_list.get('ret') is None:
        return []
    
    if '1' != pid_list['ret']:
        return []
    
    if pid_list.get('info') is None or type(pid_list.get('info')) is not dict:
        return []
    
    if pid_list['info'].get('list') is None or type(pid_list['info']['list']) is not list:
        return []
    
    _CACHE_PID = pid_list['info']['list']    
    return _CACHE_PID
