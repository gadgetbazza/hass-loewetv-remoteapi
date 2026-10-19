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
- State is `playing` while tuned to a TV channel or playing a recording, `on` for other inputs and `off` in standby
- **Playing a recording:** play, pause, stop, and fast-forward / rewind (HA's next / previous track; each press steps the speed up, play returns to normal speed). Content type `episode`. A recording started from HA's media browser also shows its title, channel and artwork; one started on the TV itself shows as "Recording", because the TV doesn't say which recording is playing. The TV doesn't report pause either, so `paused` is what HA last sent. Stop ends the recording and opens the TV's main menu over the input it was last on, as the remote's stop key does; the media player then reports that input
- Media browser with **Favourites**, **All channels** and **Inputs**; select a channel to switch to it
- **Recordings** in the media browser: the DR+ recorder's recordings (title, channel, date, length, thumbnail); select one to play it on the TV. Thumbnails are the [programme artwork](#programme-artwork) from TMDB when set up and matched; otherwise the TV's own thumbnail, a frame from the start that the TV only makes once the recording has been played
- **Guide** in the media browser: about a week of programmes per channel from the TV's own guide, with **Record** (and **Watch** for what's on now) on each programme (see [Programme guide](#programme-guide))

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
| Recorder / player | `play`, `pause`, `stop`, `rewind` (`rew`), `fast_forward` (`ff`), `record` (`rec`). Sent in the TV's separate `l2700-hdr` key alphabet |

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
  - Menu, Back, Info, Home, arrow keys, OK
  - Red / Green / Yellow / Blue keys

### Sensors
- **Current Service**: the channel name, or the input name (e.g. HDMI 1)
- **Current Programme**: the programme on the current channel, with start/end times, description and next programme as attributes
- **Scheduled Recordings**: the number of recording timers on the TV's DR+ recorder; the `recordings` attribute lists each one (title, channel, start, end, `repeat` (`weekdays`, `daily`, `weekly` or `series`), whether it is recording now or in conflict, and `series_episode` for the episode timers a series recording creates), and `recording_now` is true while one is recording. Read every 5 minutes, and straight after `loewe.record`

### Binary sensors
- **Recording**: on while the TV's DR+ recorder is recording, with the recording's `title` and `channel` as attributes

### Services
- `loewe.refresh_sources`: re-read the AV inputs and channel lists from the TV (e.g. after a channel scan or renaming an input). Channels and inputs are otherwise loaded once at startup.
- `loewe.channel_up` / `loewe.channel_down`: step through the TV's channels.
- `loewe.record`: programme a recording on the TV's DR+ recorder (see [Recording](#recording)).
- `loewe.get_guide`: return a channel's programmes from the TV's guide (see [Programme guide](#programme-guide)).

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

### Recording
On TVs with a DR+ recorder (a built-in or USB disk), `loewe.record` programmes a recording timer:

```yaml
# The programme after this one on the channel the TV is showing
action: loewe.record
target:
  entity_id: media_player.lounge_tv
data:
  programme: next          # or "current": from now until the programme ends
```

```yaml
# A channel at a set time, every weekday
action: loewe.record
target:
  entity_id: media_player.lounge_tv
data:
  channel: "BBC TWO"       # name, favourite number or locator
  start: "2026-10-19 18:30"
  duration: "00:30:00"     # or end: "2026-10-19 19:00"
  repeat: weekdays         # or daily; leave out for a one-off
```

- `programme` (current/next) uses the channel the TV is showing, or the `channel` given. For
  anything later, pick it in the media browser's [Guide](#programme-guide), or give a start time.
- The TV titles these timers "Recording"; the integration shows the programme's title from the
  guide instead, and the finished recording gets the programme's title on the TV.
- Repeats: the TV's API only offers **weekdays** (Mon-Fri) and **daily**. Weekly and series
  recordings can only be set up on the TV itself.
- Timers can't be changed or cancelled through the API: do that in the TV's timer list.
- The TV accepting a timer doesn't guarantee it will record (a clash with another timer can need
  sorting out on the TV). The **Scheduled Recordings** sensor shows what the TV actually has.
- A "Record next" button for a dashboard:

```yaml
type: button
name: Record next
icon: mdi:record-rec
tap_action:
  action: perform-action
  perform_action: loewe.record
  target:
    entity_id: media_player.lounge_tv
  data:
    programme: next
```

### Programme guide
The media browser's **Guide** folder lists your favourite channels (all channels if you have no
favourites). Open a channel, then a day, to see its programmes. Open a programme for its description
and **Record** (plus **Watch** while it is on). Recording from the guide sends a confirmation to the phone of the person who asked (the companion-app phone their person entity tracks; nothing is sent otherwise). Programmes already set to record are marked ● (the media panel keeps pages it has shown, so go up a level or reload to see a new ●). The
guide is the TV's own, read from it on demand (cached for 10 minutes), so it covers what the TV's
guide covers, usually about a week.

`loewe.get_guide` returns the same data for automations or custom cards:

```yaml
action: loewe.get_guide
target:
  entity_id: media_player.lounge_tv
data:
  channel: "BBC TWO"   # default: the channel the TV is showing
  hours: 24            # how far ahead
response_variable: guide
```

`guide.programmes` is a list of `title`, `description`, `start` and `end` (local ISO times).

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
