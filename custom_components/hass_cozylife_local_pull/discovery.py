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
    except Exception:
        return []

    if not source_ip:
        return []
    
    # Assume /24 subnet
    base_ip = ".".join(source_ip.split(".")[:3])
    ips_to_scan = [f"{base_ip}.{i}" for i in range(1, 255)]
    
    found_ips = []
    
    async def check_ip(ip_addr):
        # Skip own IP?
        if ip_addr == source_ip:
            return

        try:
            loop = asyncio.get_running_loop()
            # gethostbyaddr is blocking, run in executor
            try:
                host_info = await loop.run_in_executor(None, socket.gethostbyaddr, ip_addr)
                hostname = host_info[0]
                if hostname and hostname.startswith("CozyLife_"):
                    _LOGGER.info(f"Found CozyLife device by hostname at {ip_addr}: {hostname}")
                    found_ips.append(ip_addr)
            except socket.herror:
                # Host not found
                pass
            except Exception as e:
                _LOGGER.debug(f"Error resolving {ip_addr}: {e}")
                
        except Exception as e:
            _LOGGER.debug(f"Error checking {ip_addr}: {e}")

    # Run checks in parallel
    # Limit concurrency to avoid overwhelming the resolver or creating too many threads
    semaphore = asyncio.Semaphore(50)
    
    async def sem_check_ip(ip):
        async with semaphore:
            await check_ip(ip)

    tasks = [sem_check_ip(ip) for ip in ips_to_scan]
    await asyncio.gather(*tasks)
    
    return found_ips
