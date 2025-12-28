"""Constants for CozyLife Local integration."""

DOMAIN = "hass_cozylife_local_pull"

# Network configuration
TCP_PORT = 5555
UDP_DISCOVERY_PORT = 6095

# Device type codes (http://doc.doit/project-5/doc-8/)
SWITCH_TYPE_CODE = "00"
LIGHT_TYPE_CODE = "01"
SUPPORT_DEVICE_CATEGORY = [SWITCH_TYPE_CODE, LIGHT_TYPE_CODE]

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

# Connection timeouts (in seconds)
# Optimized for local network - devices typically respond in <100ms
CONNECTION_TIMEOUT = 3
COMMAND_TIMEOUT = 1
RESPONSE_TIMEOUT = 0.5

# Retry configuration
MAX_RETRY_ATTEMPTS = 2  # Reduced for faster failure detection
INITIAL_RETRY_DELAY = 0.5  # seconds
MAX_RETRY_DELAY = 10.0  # seconds
RETRY_BACKOFF_FACTOR = 2.0

# Cache keys for hass.data
CACHE_PID_LIST = "pid_list"