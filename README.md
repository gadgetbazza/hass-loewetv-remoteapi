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
