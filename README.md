# CozyLife Local for Home Assistant

A Home Assistant custom integration for **local control** of CozyLife smart devices. Communicate directly with your devices over the local network—no cloud dependency required.

## Features

- **100% Local Control** - Direct TCP communication with devices on your LAN
- **Multi-Method Discovery** - Automatic device detection via UDP broadcast and hostname scanning
- **Fast & Responsive** - Optimistic state updates for instant UI feedback
- **Manual Configuration** - Optionally specify device IP addresses if discovery fails
- **Device Registry Integration** - Proper device grouping in Home Assistant

### Supported Devices

- **RGBCW Lights** - On/Off, Brightness, Color Temperature (2000K-6500K), HS Color
- **CW Lights** - On/Off, Brightness, Color Temperature
- **Dimmable Lights** - On/Off, Brightness
- **Switches & Plugs** - On/Off

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **⋮** → **Custom repositories**
3. Add this repository URL and select **Integration**
4. Search for "CozyLife Local" and install
5. Restart Home Assistant

### Manual Installation

1. Download the `custom_components/hass_cozylife_local_pull` folder
2. Copy to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **CozyLife**
4. Optionally enter device IP addresses (comma-separated) if automatic discovery doesn't find all devices

## How It Works

The integration discovers devices using two methods:

1. **UDP Broadcast** - Sends discovery packets to find devices responding on port 6095
2. **Hostname Scanning** - Scans your /24 subnet for devices with hostnames starting with `CozyLife_`

Once discovered, devices are controlled via TCP on port 5555 using the CozyLife local protocol.

## Troubleshooting

### Device Not Found

- Ensure the device is on the same network subnet as Home Assistant
- Try manually entering the device's IP address in the integration options
- Check that your network allows UDP broadcast and TCP connections

### Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.hass_cozylife_local_pull: debug
```

## Development

### Running Tests

```bash
docker-compose -f docker-compose.test.yml up --build
```

## Credits

Maintained by [@JoshAtticus](https://github.com/JoshAtticus)
