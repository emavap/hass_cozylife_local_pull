# -*- coding: utf-8 -*-
"""Utility functions for CozyLife integration."""
from __future__ import annotations

import json
import time
import aiohttp
import logging
from typing import Any, TYPE_CHECKING

from .const import (
    API_DOMAIN,
    DOMAIN,
    LANG,
    CACHE_PID_LIST,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Supported languages for the API
SUPPORTED_LANGUAGES = frozenset(["zh", "en", "es", "pt", "ja", "ru", "nl", "ko", "fr", "de"])


def get_sn() -> str:
    """Generate a unique serial number based on current timestamp.

    Returns:
        A string representation of the current timestamp in milliseconds.
    """
    return str(int(round(time.time() * 1000)))


async def async_get_pid_list(
    hass: HomeAssistant | None = None,
    lang: str = "en",
) -> list[dict[str, Any]]:
    """Fetch the product ID list from the CozyLife API.

    Uses hass.data for caching when hass is provided, otherwise uses a simple
    module-level cache (less preferred but maintains backward compatibility).

    Args:
        hass: The Home Assistant instance (optional, for caching).
        lang: The language code for device names (default: 'en').

    Returns:
        A list of product information dictionaries.
    """
    # Check cache first
    if hass is not None:
        hass.data.setdefault(DOMAIN, {})
        cached = hass.data[DOMAIN].get(CACHE_PID_LIST)
        if cached:
            return cached

    if lang not in SUPPORTED_LANGUAGES:
        _LOGGER.debug("Unsupported lang=%s, using default lang=%s", lang, LANG)
        lang = LANG

    url = f"http://{API_DOMAIN}/api/v2/device_product/model"
    params = {"lang": lang}

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as res:
                if res.status != 200:
                    _LOGGER.warning("get_pid_list failed with status %s", res.status)
                    return []
                content = await res.text()
                try:
                    pid_list = json.loads(content)
                except json.JSONDecodeError as e:
                    _LOGGER.warning("get_pid_list JSON decode error: %s", e)
                    return []
    except TimeoutError:
        _LOGGER.warning("get_pid_list request timed out")
        return []
    except aiohttp.ClientError as e:
        _LOGGER.warning("get_pid_list HTTP error: %s", e)
        return []
    except Exception as e:
        _LOGGER.warning("get_pid_list unexpected error: %s", e)
        return []

    # Validate response structure
    if not isinstance(pid_list, dict):
        return []

    if pid_list.get("ret") != "1":
        return []

    info = pid_list.get("info")
    if not isinstance(info, dict):
        return []

    result = info.get("list")
    if not isinstance(result, list):
        return []

    # Store in hass.data cache if available
    if hass is not None:
        hass.data[DOMAIN][CACHE_PID_LIST] = result

    return result
