"""Constants for CozyLife Local integration."""

DOMAIN = "hass_cozylife_local_pull"

# Network configuration
TCP_PORT = 5555
UDP_DISCOVERY_PORT = 6095

# Device type codes (http://doc.doit/project-5/doc-8/)
SWITCH_TYPE_CODE = "00"
LIGHT_TYPE_CODE = "01"
SOCKET_TYPE_CODE = "02"  # Smart plug/socket - works like a switch
# All supported device types
SUPPORT_DEVICE_CATEGORY = [SWITCH_TYPE_CODE, LIGHT_TYPE_CODE, SOCKET_TYPE_CODE]
# Device types that behave like switches (on/off only)
SWITCH_LIKE_TYPES = [SWITCH_TYPE_CODE, SOCKET_TYPE_CODE]

# Data point IDs (http://doc.doit/project-5/doc-8/)
DPID_SWITCH = "1"
DPID_WORK_MODE = "2"
DPID_TEMP = "3"
DPID_BRIGHT = "4"
DPID_HUE = "5"
DPID_SAT = "6"

# Legacy aliases for backward compatibility
SWITCH = DPID_SWITCH
WORK_MODE = DPID_WORK_MODE
TEMP = DPID_TEMP
BRIGHT = DPID_BRIGHT
HUE = DPID_HUE
SAT = DPID_SAT

LIGHT_DPID = [DPID_SWITCH, DPID_WORK_MODE, DPID_TEMP, DPID_BRIGHT, DPID_HUE, DPID_SAT]
SWITCH_DPID = [DPID_SWITCH]

# Conversion factors
# Device uses 0-1000 for brightness, Home Assistant uses 0-255
BRIGHTNESS_SCALE = 4  # HA_brightness * 4 = device_brightness
# Device uses 0-1000 for saturation, Home Assistant uses 0-100
SATURATION_SCALE = 10  # HA_saturation * 10 = device_saturation

# Color temperature range (in Kelvin)
MIN_COLOR_TEMP_KELVIN = 2000
MAX_COLOR_TEMP_KELVIN = 6500

# API configuration
LANG = "en"
API_DOMAIN = "api-us.doiting.com"

# Connection timeout defaults (in seconds)
# These can be overridden via config/options flow
# Increased timeouts for better reliability with slow devices
DEFAULT_CONNECTION_TIMEOUT = 10  # Increased from 5s - some devices are slow to respond
DEFAULT_COMMAND_TIMEOUT = 5  # Increased from 3s
DEFAULT_RESPONSE_TIMEOUT = 5  # Increased from 3s

# Config keys for timeouts
CONF_CONNECTION_TIMEOUT = "connection_timeout"
CONF_COMMAND_TIMEOUT = "command_timeout"
CONF_RESPONSE_TIMEOUT = "response_timeout"

# Legacy constants for backward compatibility
CONNECTION_TIMEOUT = DEFAULT_CONNECTION_TIMEOUT
COMMAND_TIMEOUT = DEFAULT_COMMAND_TIMEOUT
RESPONSE_TIMEOUT = DEFAULT_RESPONSE_TIMEOUT

# Retry configuration
MAX_RETRY_ATTEMPTS = 5  # Increased from 3 - more retries for reading responses
INITIAL_RETRY_DELAY = 0.5  # Reduced from 1.0 - faster initial retry
MAX_RETRY_DELAY = 15.0  # Reduced from 30.0 - don't wait too long
RETRY_BACKOFF_FACTOR = 1.5  # Reduced from 2.0 - gentler backoff

# Periodic reconnection interval (in seconds)
RECONNECT_INTERVAL = 60  # How often to try reconnecting unavailable devices

# Connection health monitoring
HEALTH_CHECK_INTERVAL = 30  # How often to check connection health (seconds)
CONNECTION_IDLE_TIMEOUT = 120  # Close connections idle longer than this (seconds)
MAX_CONSECUTIVE_FAILURES = 3  # Mark unavailable after this many consecutive failures

# Polling configuration
DEFAULT_SCAN_INTERVAL = 30  # Default polling interval in seconds
MIN_SCAN_INTERVAL = 10  # Minimum allowed polling interval
MAX_SCAN_INTERVAL = 300  # Maximum allowed polling interval
CONF_SCAN_INTERVAL = "scan_interval"

# Re-discovery configuration
# Periodic re-discovery helps detect devices that changed IP address
REDISCOVERY_INTERVAL = 300  # Re-scan network every 5 minutes
REDISCOVERY_ON_FAILURE_THRESHOLD = 5  # Trigger re-discovery after this many consecutive failures

# Application-level heartbeat configuration
# Heartbeat keeps connections alive and detects dead connections faster than TCP keep-alive
HEARTBEAT_INTERVAL = 60  # Send heartbeat query every 60 seconds
HEARTBEAT_TIMEOUT = 5  # Timeout for heartbeat response

# Persistent connection configuration
# These settings control the always-on receive loop that listens for device push updates
RECEIVE_LOOP_TIMEOUT = 30.0  # Timeout for receive loop read (allows periodic checks)
RECEIVE_LOOP_RETRY_DELAY = 5.0  # Delay before retrying receive loop after error

# Smart reconnection configuration
# When a device goes offline, we keep trying to reconnect indefinitely
# The reconnection uses exponential backoff but never gives up completely
RECONNECT_MIN_INTERVAL = 5  # Minimum time between reconnection attempts (seconds)
RECONNECT_MAX_INTERVAL = 300  # Maximum backoff interval (5 minutes)
RECONNECT_BACKOFF_FACTOR = 1.5  # Backoff multiplier
DEVICE_OFFLINE_THRESHOLD = 3  # Number of failures before marking device offline
DEVICE_REDISCOVERY_INTERVAL = 120  # How often to trigger re-discovery for offline devices (seconds)

# Device state constants
DEVICE_STATE_ONLINE = "online"
DEVICE_STATE_OFFLINE = "offline"
DEVICE_STATE_CONNECTING = "connecting"
DEVICE_STATE_UNKNOWN = "unknown"

# Dispatcher signal prefixes
SIGNAL_DEVICE_STATE = f"{DOMAIN}_device_state"  # Signal for device state updates
SIGNAL_DEVICE_CONNECTED = f"{DOMAIN}_device_connected"  # Signal when device connects
SIGNAL_DEVICE_DISCONNECTED = f"{DOMAIN}_device_disconnected"  # Signal when device disconnects

# Cache keys for hass.data
CACHE_PID_LIST = "pid_list"
CACHE_DEVICE_REGISTRY = "device_registry"  # Maps device_id -> device info including IP