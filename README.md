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

## Notes
- The TV may require `RequestAccess` after power cycles. The integration retries in the background.
- Resource path defaults to `/loewe_tablet_0001`.
