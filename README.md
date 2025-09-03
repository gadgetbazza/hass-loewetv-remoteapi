# Loewe TV Integration for Home Assistant

A custom Home Assistant integration to control **Loewe Bild TVs** via their SOAP Remote API.

## Features
- Power on/off
- Volume control (set, step, mute)
- Dynamic input source discovery (HDMI/AV)
- TV channel browsing (auto-discovered)
- App launching (Netflix, YouTube, etc.)
- Extra attributes: current channel, app, and input

## Installation (HACS)
1. Go to **HACS → Integrations → Custom Repositories**.
2. Add: `https://github.com/gadgetbazza/hass-loewetv-remoteapi` with type **Integration**.
3. Install **Loewe TV**.
4. Restart Home Assistant.

## Manual Installation
Copy `custom_components/loewe_tv` to your Home Assistant `custom_components` folder.

## Configuration
Add the integration via **Settings → Devices & Services → Add Integration → Loewe TV**.

You'll be asked for:
- Host (IP address)
- Name (optional)

## Custom Logo in Lovelace
This integration provides default branding (icon + logo) for the Devices & Services view.  
If you’d like to display your **custom Loewe logo** in the dashboard instead of the default MDI television icon, you can use a `picture-entity` card.

1. Copy your `logo.png` into your Home Assistant `www` folder, e.g.:  
   `<config>/www/loewe/logo.png`

2. Reference it in Lovelace using the `/local/` path:

```yaml
type: picture-entity
entity: media_player.loewe_tv
image: /local/loewe/logo.png
```

This will show the Loewe logo instead of the default MDI icon in your dashboard card.
