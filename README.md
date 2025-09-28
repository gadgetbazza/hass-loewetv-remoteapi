# Loewe TV (Home Assistant Integration)

Custom integration for **Loewe Bild / SL420-era TVs** using the Loewe Remote API (SOAP over HTTP).

---

## Features

### Media Player
- Power on/off (WOL + RC key)
- Volume control (fine step, absolute volume, mute toggle)
- Source selection (HDMI, AV, tuner etc)
- Channel up / down

### Remote
- Exposes a full `remote` entity
- Supports RC key injection (numeric codes or symbolic names)

### Buttons
- Optional button entities (disabled by default) for:
  - Volume Up / Down, Mute
  - Menu, Back, Info, Home
  - Red / Green / Yellow / Blue keys

### Sensors
- Current Service (channel or source)

### Diagnostics
- Device info (Chassis, SW version, MACs)
- Config + options redacted where needed

---

## Installation

### HACS (recommended)
1. Open **HACS → Integrations → Custom Repositories**.
2. Add:  
   ```
   https://github.com/gadgetbazza/hass-loewe-remoteapi
   ```
   with type **Integration**.
3. Install **Loewe TV**.
4. Restart Home Assistant.

### Manual Installation
1. Copy `custom_components/loewe` into your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & Services → Add Integration → Loewe TV**.

---

## Configuration
- Fully UI-based (config flow), just enter the IP address of your TV.
- Performs `RequestAccess` handshake on first setup.
- Resource path defaults to `/loewe_tablet_0001`.
- MAC address is captured for WOL.

---

## Logging (optional)

Enable debug logs for troubleshooting:

```yaml
logger:
  default: info
  logs:
    custom_components.loewe: debug
```

---

## Notes
- The TV may require `RequestAccess` again after certain power cycles.  
- The integration retries automatically in the background.  

---

## Support
- Please report issues or feedback via [GitHub Issues](https://github.com/gadgetbazza/hass-loewe-remoteapi/issues).
- Contributions welcome!

---

## About
This is my first HA integration. I’ve worked in software for 30+ years but I’m new to Python and Home Assistant’s integration framework.  
Special thanks to packet traces, trial & error, and ChatGPT for getting this into shape.  

Cheers,  
Barry  

<a href="https://www.buymeacoffee.com/gadgetbazza" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;">
</a>
