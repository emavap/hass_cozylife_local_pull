# CozyLife Local for Home Assistant

A custom integration for controlling CozyLife devices (lights, switches, plugs) locally over the network. This integration communicates directly with devices, avoiding cloud dependency for control.

## Features

- **Local Control**: Controls devices directly over the local network.
- **Automatic Discovery**: Automatically finds CozyLife devices on your network.
- **Manual Configuration**: Supports manually specifying device IP addresses.
- **Supported Devices**:
  - RGBCW Lights
  - CW Lights
  - Switches & Plugs

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant.
2. Go to "Integrations" > "Custom repositories".
3. Add this repository URL and select "Integration".
4. Search for "CozyLife Local" and install it.
5. Restart Home Assistant.

### Manual Installation

1. Download the `custom_components/hass_cozylife_local_pull` folder from this repository.
2. Copy it to your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings** > **Devices & Services**.
2. Click **Add Integration**.
3. Search for **CozyLife Local**.
4. Follow the prompts. You can optionally enter IP addresses of your devices if discovery fails.

## Troubleshooting

- **Device not found**: Ensure the device is on the same network subnet. Try manually entering the IP address during setup.
- **Logs**: Enable debug logging to see detailed communication information.

Add this to your `configuration.yaml` to enable debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.hass_cozylife_local_pull: debug
```

## Credits

Maintained by JoshAtticus.
Based on the original work for CozyLife integration.
