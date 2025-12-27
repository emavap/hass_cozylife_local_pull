import asyncio
import socket
import logging
from homeassistant.components.network import async_get_source_ip
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

async def async_discover_devices(hass: HomeAssistant) -> list[str]:
    """Discover devices by scanning the network for hostnames starting with CozyLife_."""
    try:
        source_ip = await async_get_source_ip(hass)
    except Exception as e:
        _LOGGER.debug(f"Could not get source IP: {e}")
        return []

    if not source_ip:
        _LOGGER.debug("No source IP available for hostname discovery")
        return []

    # Assume /24 subnet
    base_ip = ".".join(source_ip.split(".")[:3])
    ips_to_scan = [f"{base_ip}.{i}" for i in range(1, 255)]

    found_ips = []

    async def check_ip(ip_addr):
        """Check if IP has CozyLife hostname with timeout"""
        # Skip own IP
        if ip_addr == source_ip:
            return

        try:
            loop = asyncio.get_running_loop()
            # gethostbyaddr is blocking, run in executor with timeout
            try:
                # Add timeout to prevent hanging on slow DNS lookups
                host_info = await asyncio.wait_for(
                    loop.run_in_executor(None, socket.gethostbyaddr, ip_addr),
                    timeout=2.0  # 2 second timeout per IP
                )
                hostname = host_info[0]
                if hostname and hostname.startswith("CozyLife_"):
                    _LOGGER.info(f"Found CozyLife device by hostname at {ip_addr}: {hostname}")
                    found_ips.append(ip_addr)
            except asyncio.TimeoutError:
                # Timeout is expected for most IPs
                pass
            except socket.herror:
                # Host not found - expected for most IPs
                pass
            except Exception as e:
                # Log only unexpected errors
                if "timed out" not in str(e).lower():
                    _LOGGER.debug(f"Error resolving {ip_addr}: {e}")

        except Exception as e:
            _LOGGER.debug(f"Error checking {ip_addr}: {e}")

    # Run checks in parallel with higher concurrency for faster scanning
    # Increased from 50 to 100 since we have timeouts now
    semaphore = asyncio.Semaphore(100)

    async def sem_check_ip(ip):
        async with semaphore:
            await check_ip(ip)

    _LOGGER.debug(f"Starting hostname discovery scan on {base_ip}.0/24")
    tasks = [sem_check_ip(ip) for ip in ips_to_scan]
    await asyncio.gather(*tasks, return_exceptions=True)

    _LOGGER.info(f"Hostname discovery completed: found {len(found_ips)} device(s)")
    return found_ips
