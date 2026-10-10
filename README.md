# Loewe TV (Home Assistant Integration)

Custom integration for **Loewe Bild / SL420-era TVs** using the Loewe Remote API (SOAP over HTTP).

---

## Features

### Media Player
- Power on/off (WOL + RC key)
- Volume control (fine step, absolute volume, mute toggle)
- Source selection (HDMI, AV, tuner etc)
- Now playing: channel name, programme title, duration/progress and next programme (from the TV's EPG)
- State is `playing` while tuned to a TV channel, `on` for other inputs and `off` in standby
- Media browser with **Favourites**, **All channels** and **Inputs**; select a channel to switch to it

### Remote
- Exposes a full `remote` entity
- Supports RC key injection (numeric codes or symbolic names)
- On/off follows the TV; `remote.turn_on` / `turn_off` wake the TV and put it into standby
- `num_repeats` and `delay_secs` are supported; `hold_secs` is not (the TV treats a held key as a single press)

### Buttons
- Optional button entities (disabled by default) for:
  - Volume Up / Down, Mute, Channel Up / Down
  - Menu, Back, Info, Home, arrow keys
  - Red / Green / Yellow / Blue keys

### Sensors
- **Current Service**: the channel name, or the input name (e.g. HDMI 1)
- **Current Programme**: the programme on the current channel, with start/end times, description and next programme as attributes

### Services
- `loewe.refresh_sources`: re-read the AV inputs and channel lists from the TV (e.g. after a channel scan or renaming an input). Channels and inputs are otherwise loaded once at startup.
- `loewe.channel_up` / `loewe.channel_down`: step through the TV's channels.

### Switching channels from automations
`media_player.play_media` accepts a channel name, a favourites number or a channel locator:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.lounge_tv
data:
  media_content_type: channel
  media_content_id: "BBC TWO"   # or "2" for favourite number 2
```

### Diagnostics
- Device info (Chassis, SW version, MACs)
- Config + options redacted where needed

---

## Installation

### HACS (recommended)
1. Open **HACS → Integrations → Custom Repositories**.
2. Add:  
   ```
   https://github.com/gadgetbazza/hass-loewetv-remoteapi
   ```
   with type **Integration**.
3. Go back to **HACS → Integration**, search for **Loewe TV Remote API**, click the three dots and choose download.
4. Restart Home Assistant.
5. Add the integration via **Settings → Devices & Services → Add Integration → Loewe TV Remote API**.
6. Enter the IP address of your TV and press **Submit**.  (Your TV set will need to be powered on during this step)

### Manual Installation
1. Copy `custom_components/loewe` into your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & Services → Add Integration → Loewe TV Remote API**.
4. Enter the IP address of your TV and press **Submit**.  (Your TV set will need to be powered on during this step)

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
- The TV may need to `RequestAccess` again after certain power cycles, the integration automatically retries this in the background.  
- Programme information comes from the TV's own EPG. Right after a channel change the TV can take a moment to provide it: changes made from Home Assistant show the programme within a couple of seconds, changes made with the TV's remote on the next poll (up to 10 seconds).
- Channel logos are not shown: the TVs tested report logo URLs but do not serve them.

---

## Support
- Please report issues or feedback via [GitHub Issues](https://github.com/gadgetbazza/hass-loewetv-remoteapi/issues).
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
