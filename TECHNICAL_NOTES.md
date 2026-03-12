# Octopus Energy Italy Integration — Technical Notes

## Architecture Overview

### API References

- Official documentation: [Octopus Energy Italy developer portal](https://developer.oeit-kraken.energy/)
- GraphQL endpoint: `https://api.oeit-kraken.energy/v1/graphql/` — accessed via `python-graphql-client`

### Key Files

| File | Role |
|------|------|
| `octopus_energy_it.py` | GraphQL API client — authentication, token refresh, all API calls |
| `__init__.py` | Integration setup, `DataUpdateCoordinator`, public tariff scraper |
| `entity.py` | Base entity classes (`OctopusCoordinatorEntity`, `OctopusPublicProductsEntity`, `OctopusDeviceScheduleMixin`) |
| `config_flow.py` | User credential validation and config flow |
| `sensor.py` | Prices, balances, meter readings, dispatch info, public tariffs |
| `switch.py` | Device suspension + boost charge switches |
| `binary_sensor.py` | Active dispatch window detection |
| `number.py` | SmartFlex charge target percentage (10–100%) |
| `select.py` | SmartFlex ready-by time selector |
| `const.py` | Domain, update intervals, token constants, debug flags |

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
        "planned_dispatches": [...],
        "completed_dispatches": [...],
        "meter_readings": {
            "electricity": [...],
            "gas": [...],
        },
    }
}
```

All keys use **snake_case**. Do not use camelCase variants (`plannedDispatches`, `meterReadings`) — they no longer exist in the codebase.

---

## Implementation Details

### Coordinator Access

All platforms must use this pattern:

```python
data = hass.data[DOMAIN][entry.entry_id]
coordinator = data["coordinator"]
api = data["api"]
```

Never create per-platform coordinators or separate GraphQL clients. The coordinator and API client are single shared instances stored in `hass.data[DOMAIN][entry.entry_id]`.

### Token Management

The `TokenManager` class in `octopus_energy_it.py` handles the full token lifecycle:

- Automatic refresh when less than 5 minutes remain before expiry
- Fallback to a fixed 50-minute interval if the token is not a decodable JWT
- Tokens are stored **in memory only** — never persisted to disk or config entry
- Never call `_get_graphql_client()` directly from platform code — always use the public API methods (e.g. `api.update_boost_charge()`) which handle automatic token refresh

### Localization and Entities

All entities expose `_attr_translation_key`. Translation files are at `translations/it.json` and `translations/en.json`. The helper functions `_normalize_supply_status` and `_normalize_ev_status` convert raw Kraken backend states into human-readable slugs.

### Switch: Unique ID and Availability

Switch entities include `<device_id>` in their `unique_id` to correctly support multiple devices (e.g. two EVs) on the same account:

- `{DOMAIN}_{account_number}_{device_id}_ev_charge_smart_control`
- `{DOMAIN}_{account_number}_{device_id}_boost_charge`

The boost switch is only created for devices with `deviceType` in `["ELECTRIC_VEHICLES", "CHARGE_POINTS"]`, and is only available when the device is `LIVE` with `SMART_CONTROL_CAPABLE`, a `BOOST` state, or currently `BOOST_CHARGING`.

### Device Schedule Mixin (number.py, select.py)

Shared logic for accessing and updating a SmartFlex device schedule lives in `OctopusDeviceScheduleMixin` (`entity.py`). It provides:

- `_current_device()` — retrieves the device dict from the coordinator
- `_current_schedule()` — first schedule entry from the `preferences` dict
- `_schedule_setting()` — schedule limits from `preferenceSetting`
- `_current_target_percentage()` / `_current_target_time()` — current values
- `_update_local_schedule()` — updates local coordinator data after a mutation, keeping the UI consistent between polls

Do not duplicate this logic in `number.py` or `select.py`.

### Public Tariffs and Retry

The scraper in `__init__.py` reads `https://octopusenergy.it/le-nostre-tariffe` every hour, extracting `__NEXT_DATA__` JSON and PLACET offers from the HTML.

The retry mechanism uses `hass.async_call_later()` (a reliable one-shot timer). **Do not** modify `coordinator.update_interval` at runtime — the change has no effect on the coordinator's already-scheduled polling.

When scraping fails:
1. If a cache exists, it is returned with a warning — sensors retain their previous value
2. A retry is scheduled after 5 minutes (`PUBLIC_PRODUCTS_RETRY_DELAY = 300`)
3. On the next successful retry, the cache is updated and the retry cancelled

`public_products_retry_unsub` is cancelled in `async_unload_entry` to prevent orphaned callbacks.

A single public device exists per HA instance (tracked via `hass.data[DOMAIN]["public_owner"]`), regardless of how many config entries are loaded.

### Main Coordinator Error Handling

When all accounts fail to fetch data, the coordinator raises `UpdateFailed` (rather than returning stale data with a green status). This sets `last_update_success=False` and surfaces the repair in the HA UI.

```python
if not all_accounts_data:
    raise UpdateFailed("Failed to fetch data for any account")
```

Accounts that fail individually are logged but do not block the fetch for other accounts.

---

## Debug Flags (const.py)

Set temporarily during debugging:

```python
LOG_API_RESPONSES = True   # logs full GraphQL responses
LOG_TOKEN_RESPONSES = True  # logs login and token refresh operations
DEBUG_ENABLED = True        # general debug flag
```

Debug logging via `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.octopus_energy_it: debug
    custom_components.octopus_energy_it.octopus_energy_it: debug
    custom_components.octopus_energy_it.switch: debug
```

---

## Tests

### Structure

Tests live in `tests/` and do not require a real Home Assistant installation — all HA dependencies are stubbed in `tests/conftest.py`.

```
tests/
├── conftest.py           # HA stubs + shared fixtures
├── test_api_client.py    # GraphQL client (82 tests)
├── test_sensor.py        # sensor logic (27 tests)
├── test_switch.py        # switches: unique_id, availability (13 tests)
├── test_binary_sensor.py # binary sensor dispatching (14 tests)
└── test_coordinator.py   # coordinator and public tariffs (58 tests)
```

### Running Tests

```bash
pip install -r requirements_test.txt
python -m pytest tests/
python -m pytest tests/ -v                   # verbose
python -m pytest tests/test_sensor.py -v    # single file
```

### Stub Infrastructure

`conftest.py` installs stubs into `sys.modules` before any integration module is imported. The critical pattern:

```python
# custom_components must be registered as a package (with __path__)
# otherwise sub-imports fail with "not a package"
_oeit = types.ModuleType("custom_components.octopus_energy_it")
_oeit.__path__ = [_oeit_path]
_oeit.__package__ = "custom_components.octopus_energy_it"
sys.modules["custom_components.octopus_energy_it"] = _oeit
```

`const.py` has no HA dependencies and is loaded directly from disk — no stub is required for it.

### Critical Coverage Areas

Tests explicitly cover:

1. **Switch unique_id correctness** — two devices of the same type produce distinct IDs
2. **Dispatch window logic** — `_effective_dispatch_window()` with active vs future vs past slots
3. **Meter reading rounding** — 3 decimal places for `electricity_last_daily_reading` and `electricity_last_reading`
4. **Public tariff retry** — cache fallback, retry scheduling, cancellation on success
5. **Token management** — JWT decode, fixed-interval fallback, expiry, validity

---

## Security

- Tokens are stored **in memory only**, never persisted
- Email and password are read from the config entry and never logged
- All API communication uses HTTPS (official Kraken endpoint)

---

## Breaking Changes

When an entity `unique_id` is changed, document it in `CHANGELOG.md` with instructions for removing orphaned entities from the HA Entity Registry. Do not add migration entries for backwards compatibility — prefer an explicit breaking change with clear user instructions.
