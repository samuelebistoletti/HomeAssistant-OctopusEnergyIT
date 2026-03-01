# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant custom integration for Octopus Energy Italy. Domain: `octopus_energy_it`. Communicates with the official Kraken GraphQL API at `https://api.oeit-kraken.energy/v1/graphql/` via `python-graphql-client`.

## Commands

```bash
# Install dev dependencies
bash scripts/setup

# Format and lint (ruff format + ruff check --fix)
bash scripts/lint

# Run local Home Assistant instance (http://localhost:8123)
docker-compose up
docker-compose logs -f homeassistant
```

There is no automated test suite — validation is done manually via the local Home Assistant dev container.

## Architecture

All code lives in `custom_components/octopus_energy_it/`. Key files:

| File | Role |
|------|------|
| `octopus_energy_it.py` | GraphQL API client — auth, token refresh, all API calls |
| `__init__.py` | Integration setup, `DataUpdateCoordinator`, public tariff scraper |
| `entity.py` | Base entity classes (`OctopusCoordinatorEntity`, `OctopusPublicProductsEntity`) |
| `config_flow.py` | User auth/credential validation during setup |
| `sensor.py` | Prices, balance, meter readings, dispatch info, public tariffs |
| `switch.py` | Device suspension + boost charge switches |
| `binary_sensor.py` | Intelligent dispatch window detection |
| `number.py` | SmartFlex charge target (10–100%) |
| `select.py` | SmartFlex ready-by time selector |
| `const.py` | Domain, update interval, token constants, debug flags |

### Data Flow

```
ConfigEntry (email + password)
    → OctopusEnergyIT API client (octopus_energy_it.py)
    → OctopusEnergyITDataUpdateCoordinator (__init__.py)
    → All platforms (sensor, switch, binary_sensor, number, select)
```

### Coordinator Data Structure

```python
coordinator.data = {
    "account_number": {
        "devices": [...],
        "products": [...],
        "ledgers": [...],
        "properties": [...],
        "plannedDispatches": [...],
        "meterReadings": {...},
    }
}
```

### Critical Patterns

**Always access coordinator via:**
```python
data = hass.data[DOMAIN][entry.entry_id]
coordinator = data["coordinator"]
api = data["api"]
```

Never create per-platform coordinators or separate GraphQL clients. All platforms share the single coordinator and API client instance stored in `hass.data[DOMAIN][entry.entry_id]`.

**Token management** is handled entirely inside `OctopusEnergyIT` — tokens refresh automatically when within 5 minutes of expiry (or after 50 minutes if expiry is unknown). Tokens live in memory only.

**Entity naming** — always use `translation_key`/`_attr_translation_key`. Translation files are at `translations/it.json` and `translations/en.json`.

### Public Tariffs

A separate hourly coordinator in `__init__.py` scrapes `https://octopusenergy.it/le-nostre-tariffe`, extracting `__NEXT_DATA__` JSON + PLACET offers from HTML. Creates sensors named `sensor.octopus_energy_public_tariffs_<tariff_slug>` under a single shared device. Only one `public_owner` entry exists in `hass.data[DOMAIN]` regardless of how many config entries are loaded.

### Boost Charge Switch Availability

The boost switch is only created for devices with `deviceType` in `["ELECTRIC_VEHICLES", "CHARGE_POINTS"]`, and is only available when the device is `LIVE` and has `SMART_CONTROL_CAPABLE`, a `BOOST` state, or is currently `BOOST_CHARGING`.

### Debug Flags (const.py)

Set temporarily when debugging:
- `LOG_API_RESPONSES = True` — logs full GraphQL responses
- `LOG_TOKEN_RESPONSES = True` — logs token operations
- `DEBUG_ENABLED = True` — general debug flag

### Debug Logging (configuration.yaml)

```yaml
logger:
  logs:
    custom_components.octopus_energy_it: debug
```

## Release Process

1. Bump version in `manifest.json`
2. Add entry to `CHANGELOG.md`
3. Push to `main` — GitHub Actions auto-creates the git tag, ZIP, and GitHub Release
