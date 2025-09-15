# Loewe TV Remote API (Home Assistant)

Custom integration for Loewe Bild/SL420-era TVs using the Remote API via SOAP over HTTP.

## Features
- UI setup (config flow)
- Pairing (RequestAccess) with client caching
- DataUpdateCoordinator polling (`GetCurrentStatus`, `GetCurrentService`)
- Media player: volume step, RC-key injection
- Sensors: Standby State, Current Source, HDR Player State
- Diagnostics

## Installation (HACS)
1. Go to **HACS → Integrations → Custom Repositories**.
2. Add: `https://github.com/gadgetbazza/hass-loewetv-remoteapi` with type **Integration**.
3. Install **Loewe TV**.
4. Restart Home Assistant.

## Manual Installation
1. Copy `custom_components/loewe_tv` into your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.
3. Add integration: **Settings → Devices & Services → Add Integration → Loewe TV Remote API**.

## Logging (optional)
```yaml
logger:
  default: info
  logs:
    custom_components.loewe_tv: debug
```

## About Me & This Integration
This is my first attempt at building a Home Assistant device integration.  Despite being in the software industry for some 30+ years, I have no python skills but do understand the general principles of code and hopefully I've used that to good effect here.  The Loewe TV is super picky about it's Soap API constructs, computers are typically fickle about case and construct, but the Loewe is not consistent across it's methods making it somewhat challenging and requiring a lot of packet traces on the network to get this to where it is now.  I will admit to using ChatGPT to help with the python syntax and HA device integration constructs, so here's hoping that this will all work for anyone else wanting to use this.  If you have any issues or feedback, please feel free to create a ticket and I will assist when I can.

Cheers, Barry

<a href="https://www.buymeacoffee.com/gadgetbazza" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

## Notes
- The TV may require `RequestAccess` after power cycles. The integration retries in the background.
- Resource path defaults to `/loewe_tablet_0001`.
