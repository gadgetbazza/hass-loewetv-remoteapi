# Loewe TV (Home Assistant Integration)

Custom integration for **Loewe Bild / SL420-era TVs** using the Loewe Remote API (SOAP over HTTP).

---

## Features

### Media Player
- Power on/off (WOL + RC key)
- Volume control (fine step, absolute volume, mute toggle)
- Source selection (HDMI, AV, tuner etc)
- Now playing: channel name, programme title, duration/progress and next programme (from the TV's EPG)
- Optional programme artwork from [TMDB](https://www.themoviedb.org/) (see [Programme artwork](#programme-artwork))
- State is `playing` while tuned to a TV channel, `on` for other inputs and `off` in standby
- Media browser with **Favourites**, **All channels** and **Inputs**; select a channel to switch to it

### Remote
- Exposes a full `remote` entity
- Supports RC key injection (numeric codes or symbolic names)
- On/off follows the TV; `remote.turn_on` / `turn_off` wake the TV and put it into standby
- `num_repeats` and `delay_secs` are supported; `hold_secs` is not (the TV treats a held key as a single press)

Key names for `remote.send_command` (case-insensitive), or any numeric l2700 key code:

| Group | Keys |
|---|---|
| Power | `power` (toggle), `power_on`, `power_off` |
| Navigation | `up`, `down`, `left`, `right`, `ok`, `menu`, `back`, `end` (exit), `media` (home), `info` |
| Volume / channels | `vol_up`, `vol_down`, `mute`, `prog_up`, `prog_down`, `0`–`9` |
| Colour keys | `red`, `green`, `yellow`, `blue` |
| TV features | `epg`, `epg_star`, `ttx`, `recordings` (DR+ archive), `timer`, `tv_mode`, `radio_mode`, `radio`, `pip`, `pip_hash`, `pic`, `sound`, `aspect` |
| Inputs | `hdmi1`–`hdmi4`, `av1`–`av3`, `avs`, `vga`, `comp`, `video`, `spdif_in` |

Aliases: `volume_up`/`volume_down`, `channel_up`/`channel_down`, `guide` (epg), `select`/`enter` (ok), `home` (media), `exit` (end), `text`/`teletext` (ttx), `on_off` (power), `dr_archive` (recordings).

```yaml
action: remote.send_command
target:
  entity_id: remote.lounge_tv
data:
  command: [channel_up, info]
```

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

### Programme artwork
The TV's guide has programme titles but no pictures. With a free TMDB API key the integration looks each programme title up on The Movie Database and shows its artwork on the media player.

1. Create an account at [themoviedb.org](https://www.themoviedb.org/), then go to **Settings → API** and request a developer key.
2. Copy the **API Key** (not the longer API Read Access Token).
3. In Home Assistant go to **Settings → Devices & services → Loewe TV → Configure** and paste it in. Clear the field to turn artwork off.

Only exact title matches are used, so films, dramas and well-known series get artwork, while news, sport and local programmes usually show none. The key is stored in Home Assistant's config entry and is redacted from diagnostics.

---

## Dashboard example

A remote control card that brings the media player and remote together, with the programme
artwork filling the card behind the controls. It uses three popular frontend cards, all installable
from HACS:

- [mini-media-player](https://github.com/kalkih/mini-media-player): power, volume, source and now playing
- [Universal Remote Card](https://github.com/Nerwyn/android-tv-card): the keys
- [card-mod](https://github.com/thomasloven/lovelace-card-mod): the artwork background (`custom:mod-card`)

Replace `lounge_tv` with your own entity names (it appears three times).

```yaml
type: custom:mod-card
card_mod:
  style: |
    {% set tv = 'media_player.lounge_tv' %}
    {# Optional: TV inputs whose artwork comes from another media player, e.g. {'HDMI 1': 'media_player.apple_tv'} #}
    {% set inputs = {} %}
    {% set pic = state_attr(inputs.get(state_attr(tv, 'source')) or tv, 'entity_picture') %}
    ha-card { position: relative; overflow: hidden; background: var(--card-background-color); }
    ha-card > * { position: relative; z-index: 1;
      --ha-card-background: transparent; --ha-card-border-width: 0; --ha-card-box-shadow: none;
      {% if pic %}
      --primary-text-color: #fff; --secondary-text-color: #eee; --paper-item-icon-color: #eee;
      --pad-color: #fff; --pad-ring: rgba(255,255,255,.35); --pad-centre: rgba(255,255,255,.25);
      text-shadow: 0 1px 3px rgba(0,0,0,.9);
      {% endif %} }
    {% if pic %}
    ha-card::before { content: ''; position: absolute; inset: 0;
      background: linear-gradient(rgba(0,0,0,.30), rgba(0,0,0,.45)), url('{{ pic }}') center / cover; }
    {% endif %}
card:
  type: vertical-stack
  cards:
    - type: custom:mini-media-player
      entity: media_player.lounge_tv
      artwork: none          # the artwork is the card background instead
      info: scroll
      source: icon
      volume_stateless: true
    - type: custom:universal-remote-card
      platform: Generic Remote
      remote_id: remote.lounge_tv
      rows:
        - [back, home, menu, recordings]
        - [circlepad]
        - [channel_down, guide, info, channel_up]
        - [red, green, yellow, blue]
      custom_actions:
        - type: circlepad
          name: circlepad
          tap_action: {action: key, key: ok}
          up: {icon: mdi:chevron-up, tap_action: {action: key, key: up}, hold_action: {action: repeat}}
          down: {icon: mdi:chevron-down, tap_action: {action: key, key: down}, hold_action: {action: repeat}}
          left: {icon: mdi:chevron-left, tap_action: {action: key, key: left}, hold_action: {action: repeat}}
          right: {icon: mdi:chevron-right, tap_action: {action: key, key: right}, hold_action: {action: repeat}}
          # see-through d-pad so the artwork shows behind it: white over artwork,
          # the theme's colours (readable in light and dark mode) without
          styles: |
            :host(remote-circlepad) { width: 250px; --icon-size: min(48px, 12vw);
              --icon-color: var(--pad-color, var(--primary-text-color)); }
            .circlepad { background: transparent; outline: 2px solid var(--pad-ring, var(--divider-color)); }
            #center::part(button) { background: var(--pad-centre, var(--secondary-background-color)); outline: none; }
        - {type: button, name: back, icon: mdi:keyboard-backspace, tap_action: {action: key, key: end}}
        - {type: button, name: home, icon: mdi:home, tap_action: {action: key, key: media}}
        - {type: button, name: menu, icon: mdi:menu, tap_action: {action: key, key: menu}}
        - {type: button, name: recordings, icon: mdi:filmstrip-box-multiple, tap_action: {action: key, key: recordings}}
        - {type: button, name: channel_down, icon: mdi:minus-box, tap_action: {action: key, key: prog_down}}
        - {type: button, name: guide, icon: mdi:television-guide, tap_action: {action: key, key: epg}}
        - {type: button, name: info, icon: mdi:information-outline, tap_action: {action: key, key: info}}
        - {type: button, name: channel_up, icon: mdi:plus-box, tap_action: {action: key, key: prog_up}}
        - {type: button, name: red, icon: mdi:square-rounded, tap_action: {action: key, key: red}, styles: ":host { --icon-color: #d32f2f; }"}
        - {type: button, name: green, icon: mdi:square-rounded, tap_action: {action: key, key: green}, styles: ":host { --icon-color: #388e3c; }"}
        - {type: button, name: yellow, icon: mdi:square-rounded, tap_action: {action: key, key: yellow}, styles: ":host { --icon-color: #fbc02d; }"}
        - {type: button, name: blue, icon: mdi:square-rounded, tap_action: {action: key, key: blue}, styles: ":host { --icon-color: #1976d2; }"}
```

The background follows whatever the TV shows: on a TV channel, the programme artwork when
[Programme artwork](#programme-artwork) is set up. On an HDMI input the TV itself knows only the input,
so to show the artwork of the box plugged into it (Apple TV, Sky, a games console…) list it in
`inputs` at the top of the style, keyed by the input's name as it appears in the TV's source list.
With no artwork the card is plain, and the d-pad follows your theme. Any key from the
[Remote](#remote) table can be added the same way. `recordings` opens the DR+ archive on TVs with a
recorder; drop it from `rows` if yours has none. Without card-mod, use the inner `vertical-stack` on
its own and set `artwork: cover` on the media player.

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
- Programme artwork uses the TMDB API but is not endorsed or certified by TMDB.

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
