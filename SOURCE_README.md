# GRIT Hub Home Assistant custom integration

> Imported source documentation retained for reference and sanitised for public
> repository use.

This is a Home Assistant custom integration generated from the pasted GRIT Hub Swagger/OpenAPI HTML.

## What it does

- Config flow via **Settings > Devices & services > Add Integration > GRIT Hub**.
- Bearer token authentication.
- Local/cloud polling against your configured GRIT Hub base URL.
- Creates diagnostic hub entities.
- Discovers device collections for RFID, solenoid, latch, collector, powerbank, gate, air quality, pressure, presence, scanner, trigger, XTND/R and related GRIT device types where the API returns list data.
- Creates switches for controllable devices that expose `/state/{onOff}` style endpoints.
- Creates covers for gate devices.
- Creates refresh/locate buttons.
- Provides bounded services for device commands, refreshes and locate operations.

## Install

1. Copy `custom_components/grit_hub` into your Home Assistant `/config/custom_components/` folder.
2. Restart Home Assistant.
3. Add the integration from the UI.
4. Enter:
   - Base URL, e.g. `https://your-grit-server.example` or your local hub URL.
   - Bearer token, without the word `Bearer`.
   - SSL verification setting.

## Dependencies

No extra Python packages are required. It uses Home Assistant's built-in `aiohttp`, config entries, coordinators and entity platforms.

## Main services

### `grit_hub.device_command`

Calls:

```text
/api/command/{deviceType}/{id}/{commandName}/{action}/{remoteType}
```

### `grit_hub.refresh_device`

Calls `/api/device/refresh/{type}/{id}` and refreshes HA state.

### `grit_hub.locate_device`

Calls `/api/device/locate/{type}/{id}`.

## Notes

The pasted Swagger HTML showed the API catalogue but not full schemas/examples for every response body. This integration is intentionally defensive: it normalises common list shapes such as `items`, `data`, `results`, `devices`, and `records`. Raw device objects remain internal; entities expose only `status`, `state`, and `mode` diagnostic attributes when present.

If a GRIT endpoint returns a different shape, check the entity attributes or HA logs, then adjust `api.normalise_list()` or the relevant platform mapping.
