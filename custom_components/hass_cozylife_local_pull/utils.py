# -*- coding: utf-8 -*-
"""Utility functions for CozyLife integration."""
import json
import time
import asyncio
import aiohttp
import logging
from typing import List, Dict, Any, Optional
from .const import (
    API_DOMAIN,
    LANG
)

_LOGGER = logging.getLogger(__name__)

# Supported languages for the API
SUPPORTED_LANGUAGES = frozenset(['zh', 'en', 'es', 'pt', 'ja', 'ru', 'nl', 'ko', 'fr', 'de'])

# Cache for PID list - protected by lock for thread safety
_CACHE_PID: List[Dict[str, Any]] = []
_CACHE_LOCK: asyncio.Lock = asyncio.Lock()


def get_sn() -> str:
    """Generate a unique serial number based on current timestamp.

    Returns:
        A string representation of the current timestamp in milliseconds.
    """
    return str(int(round(time.time() * 1000)))


async def async_get_pid_list(lang: str = 'en') -> List[Dict[str, Any]]:
    """Fetch the product ID list from the CozyLife API.

    Args:
        lang: The language code for device names (default: 'en').

    Returns:
        A list of product information dictionaries.
    """
    global _CACHE_PID

    async with _CACHE_LOCK:
        if _CACHE_PID:
            return _CACHE_PID

        if lang not in SUPPORTED_LANGUAGES:
            _LOGGER.debug(f'Unsupported lang={lang}, using default lang={LANG}')
            lang = LANG

        url = f'http://{API_DOMAIN}/api/v2/device_product/model'
        params = {'lang': lang}

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as res:
                    if res.status != 200:
                        _LOGGER.warning(f'get_pid_list failed with status {res.status}')
                        return []
                    content = await res.text()
                    try:
                        pid_list = json.loads(content)
                    except json.JSONDecodeError as e:
                        _LOGGER.warning(f'get_pid_list JSON decode error: {e}')
                        return []
        except asyncio.TimeoutError:
            _LOGGER.warning('get_pid_list request timed out')
            return []
        except aiohttp.ClientError as e:
            _LOGGER.warning(f'get_pid_list HTTP error: {e}')
            return []
        except Exception as e:
            _LOGGER.warning(f'get_pid_list unexpected error: {e}')
            return []

        # Validate response structure
        if not isinstance(pid_list, dict):
            return []

        if pid_list.get('ret') != '1':
            return []

        info = pid_list.get('info')
        if not isinstance(info, dict):
            return []

        result = info.get('list')
        if not isinstance(result, list):
            return []

        _CACHE_PID = result
        return _CACHE_PID
