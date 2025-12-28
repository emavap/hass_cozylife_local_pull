"""Hostname-based device discovery for CozyLife devices."""
from __future__ import annotations

import asyncio
import logging
import socket

from homeassistant.components.network import async_get_source_ip
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Discovery configuration
HOSTNAME_PREFIX = "CozyLife_"
DNS_LOOKUP_TIMEOUT = 1.0  # seconds per IP (reduced for faster discovery)
MAX_CONCURRENT_LOOKUPS = 50  # Reduced to avoid network congestion


async def async_discover_devices(hass: HomeAssistant) -> list[str]:
    """Discover devices by scanning the network for hostnames starting with CozyLife_.

    Args:
        hass: The Home Assistant instance.

    Returns:
        List of discovered device IP addresses.
    """
    try:
        source_ip = await async_get_source_ip(hass)
    except Exception as e:
        _LOGGER.debug("Could not get source IP: %s", e)
        return []

    if not source_ip:
        _LOGGER.debug("No source IP available for hostname discovery")
        return []

    # Assume /24 subnet
    base_ip = ".".join(source_ip.split(".")[:3])
    ips_to_scan = [f"{base_ip}.{i}" for i in range(1, 255)]

    found_ips: list[str] = []

    async def check_ip(ip_addr: str) -> None:
        """Check if IP has CozyLife hostname with timeout."""
        # Skip own IP
        if ip_addr == source_ip:
            return

        try:
            loop = asyncio.get_running_loop()
            # gethostbyaddr is blocking, run in executor with timeout
            host_info = await asyncio.wait_for(
                loop.run_in_executor(None, socket.gethostbyaddr, ip_addr),
                timeout=DNS_LOOKUP_TIMEOUT,
            )
            hostname = host_info[0]
            if hostname and hostname.startswith(HOSTNAME_PREFIX):
                _LOGGER.info(
                    "Found CozyLife device by hostname at %s: %s", ip_addr, hostname
                )
                # asyncio is single-threaded, list append is safe without lock
                found_ips.append(ip_addr)
        except TimeoutError:
            # Timeout is expected for most IPs
            pass
        except socket.herror:
            # Host not found - expected for most IPs
            pass
        except Exception as e:
            # Log only unexpected errors
            if "timed out" not in str(e).lower():
                _LOGGER.debug("Error resolving %s: %s", ip_addr, e)

    # Run checks in parallel with concurrency limit
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LOOKUPS)

    async def sem_check_ip(ip: str) -> None:
        async with semaphore:
            await check_ip(ip)

    _LOGGER.debug("Starting hostname discovery scan on %s.0/24", base_ip)
    tasks = [sem_check_ip(ip) for ip in ips_to_scan]
    await asyncio.gather(*tasks, return_exceptions=True)

    _LOGGER.info("Hostname discovery completed: found %d device(s)", len(found_ips))
    return found_ips
