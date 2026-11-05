# Octopus Energy Italy — Home Assistant integration

Custom Home Assistant integration (HACS) for Octopus Energy Italy. It polls the Kraken GraphQL API (`cloud_polling`) and exposes sensors, binary sensors, switches, numbers and selects for accounts, tariffs, meter readings and smart-charging devices.

This file is shared with every contributor and with any automated agent working on the repo. Keep it short, factual and free of personal or machine-specific content. Deep architecture notes live in `TECHNICAL_NOTES.md`: read it before changing the coordinator, token handling, entities or tests.

## Commands

```bash
pip install -r requirements_test.txt   # test deps (HA is stubbed, no HA install needed)
python -m pytest tests/                # full suite, must stay green
bash scripts/lint                      # ruff format + ruff check --fix (the only formatter/linter)
docker-compose up                      # local HA at http://localhost:8123, config in config/
```

## Layout

- `custom_components/octopus_energy_it/`: the integration
  - `octopus_energy_it.py`: GraphQL API client and `TokenManager`
  - `__init__.py`: setup, coordinator, services
  - `data_processor.py`: turns raw API data into coordinator data (pure, testable)
  - `tariff_scraper.py`: public tariff HTML scraping
  - `sensor.py`, `binary_sensor.py`, `switch.py`, `number.py`, `select.py`, `entity.py`: platforms
  - `strings.json`, `translations/en.json`, `translations/it.json`: user-facing text
- `tests/`: pytest + pytest-asyncio; `conftest.py` stubs Home Assistant in `sys.modules`
- `.github/workflows/`: tests, security (bandit, pip-audit), hassfest, HACS, release

## Rules

- One shared coordinator and API client per entry, from `hass.data[DOMAIN][entry.entry_id]`. Never create per-platform coordinators or GraphQL clients, and never call `_get_graphql_client()` from platform code.
- Tokens live in memory only. Never log credentials; token logging is masked to the first 8 characters.
- Datetimes: use HA `as_utc(parse_datetime(...))`, not `datetime.fromisoformat` or string comparison.
- Parallel per-device API calls use `asyncio.gather(..., return_exceptions=True)` and log per-device failures as warnings.
- All user-facing strings, including exception messages, go through translation keys in `strings.json` and both translation files. Code, comments and docstrings are in English.
- Tests: in test modules use `sys.modules.setdefault(...)`, never direct assignment, so the conftest stubs are not overwritten. Add or update tests for any logic change.
- Changing an entity `unique_id` is a breaking change: document it in `CHANGELOG.md` with orphan-entity cleanup steps. No backwards-compatibility migrations.
- Debug flags in `const.py` (`DEBUG_ENABLED`, `LOG_API_RESPONSES`, `LOG_TOKEN_RESPONSES`) must be `False` in any commit.

## Decisions (do not re-litigate without a new reason)

- `UPDATE_INTERVAL = 1` minute is intentional; the maintainer confirmed there is no rate-limit risk.
- The shallow copy in `_update_local_schedule` is the intended coordinator pattern.

## Release

Bumping `version` in `custom_components/octopus_energy_it/manifest.json` on `main` triggers `tag-and-release.yaml`: tests and security checks run, then the tag, release ZIP and GitHub release are created from the matching `CHANGELOG.md` section. Update `CHANGELOG.md` in the same change, and never bump the version unless asked.

## Known open items

- Each update cycle makes separate electricity and gas reading calls per meter (possible N+1); needs an API schema review before refactoring.
- Device lookups are O(N) scans; acceptable at current device counts.
