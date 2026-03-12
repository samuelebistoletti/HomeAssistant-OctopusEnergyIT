# Changelog

## [1.2.2] - 2026-03-12

### Changed
- Updated `actions/checkout` from v4 to v6 across all CI workflows to eliminate the Node.js 20 deprecation warning (Node.js 24 becomes mandatory on GitHub Actions from June 2, 2026).

## [1.2.1] - 2026-03-10

### Added
- CI/CD security pipeline: SAST con bandit (soglia medium), audit dipendenze con pip-audit, secret scanning con gitleaks e analisi CodeQL con query pack `security-extended` — tutti eseguiti su ogni push/PR e settimanalmente.
- La release è ora bloccata se i test o la security scan falliscono (`needs: [test, security]`).

## [1.2.0] - 2026-03-10

### Fixed
- Public tariff sensors no longer stay in **Unknown** after a temporary site outage. The retry logic now uses `hass.async_call_later()` (a reliable one-shot timer) instead of manipulating `coordinator.update_interval`, which had no effect at runtime. Cached data is served while the site is down; once it recovers the coordinator is refreshed within 5 minutes automatically.
- When all accounts fail to fetch data the coordinator now raises `UpdateFailed` (marking `last_update_success=False` and surfacing the repair in the UI) instead of silently returning stale data with a green status.

### Breaking
- **Entity unique IDs changed for multi-device accounts** — this resolves a bug (issue #9) where users with two electric vehicles or charge points under the same account got duplicate entity IDs, causing one device to be silently ignored.
  - `switch.<account>_ev_charge_smart_control` → `switch.<account>_<device_id>_ev_charge_smart_control`
  - `switch.<account>_boost_charge` → `switch.<account>_<device_id>_boost_charge`
  - After updating, HA will create new entities with the correct IDs. The old orphaned entities can be removed from **Settings → Devices & Services → Entities** (filter by "unavailable").

## [1.1.0] - 2026-02-26

### Added
- Three new sensors for SmartFlex/Intelligent Octopus dispatch slots, available for all accounts with at least one smart device:
  - `sensor.octopus_<account>_ev_next_dispatch_start` – start time of the next planned charging window (`device_class: timestamp`); attributes expose `end`, `energy_kwh`, and `type`.
  - `sensor.octopus_<account>_ev_next_dispatch_end` – end time of the next planned charging window (`device_class: timestamp`); attributes expose `start`, `energy_kwh`, and `type`.
  - `sensor.octopus_<account>_ev_planned_dispatches` – count of all upcoming dispatch windows; the `dispatches` attribute contains the full sorted list (start, end, energy_kwh, type, is_active) for use in templates and dashboards. `current_start`/`current_end` are also exposed when a window is currently active.
- The timestamp sensors are natively understood by Home Assistant (relative-time display, "in X minutes/hours") and can be referenced directly in automations and Lovelace cards.

### Fixed
- Negative electricity consumption deltas are no longer propagated to the daily reading sensor. When the API returns a register value lower than the previous one (e.g. due to a meter replacement, an estimated correction, or intermittent connectivity), the delta is discarded and a warning is logged with both register values to aid diagnosis. The cumulative reading sensor (`electricity_last_reading`) is unaffected.

## [1.0.17] - 2026-02-10

### Changed
- Aligned the electricity reading date sensor identity with the normalized naming by switching its unique id to `octopus_<account>_electricity_last_reading_date`.

### Breaking
- `sensor.octopus_<account>_electricity_last_daily_reading_date` is now exposed as `sensor.octopus_<account>_electricity_last_reading_date`; update dashboards, automations, templates, and any customizations bound to the old entity id.

## [1.0.16] - 2026-02-10

### Added
- New cumulative electricity sensor `sensor.octopus_<account>_electricity_last_reading` for Home Assistant Energy dashboard (`device_class: energy`, `state_class: total_increasing`).
- Public tariff scraper now ingests PLACET offers from the Octopus public site.

### Changed
- Bundled GraphQL schema refreshed from the Kraken endpoint.
- Electricity reading nomenclature aligned in code/docs: `electricity_last_daily_reading` = daily delta, `electricity_last_reading` = cumulative meter reading.

### Fixed
- Gas last reading sensor now reports the `gas` device class to satisfy Home Assistant Energy requirements.

### Breaking
- None.

## [1.0.14] - 2026-02-04

### Documentation
- Documentation update.

## [1.0.13] - 2025-11-27

### Fixed
- Device class vehicle battery size fix

## [1.0.12] - 2025-11-27

### Changed
- Public tariff sensors are now enabled by default and retry every 5 minutes after a fetch error, restoring the hourly cadence once the site responds again.
- Public tariff documentation updated with the new retry/backoff behaviour and default-enabled entities.
- Vehicle battery capacity sensor now reports a measurement without the energy device class to align with Home Assistant’s state class rules.

## [1.0.11] - 2025-11-16

### Fixed
- Public tariff sensors keep showing the last known prices when the octopusenergy.it tariffs page is temporarily unavailable instead of flipping to `unavailable`.

## [1.0.10] - 2025-11-15

### Changed
- Public tariffs now use a dedicated hourly coordinator on the Octopus site independently from account polling, reducing noise on the Kraken APIs and ensuring consistent refreshes for every tariff sensor.

## [1.0.9] - 2025-11-14

### Fixed
- Reduced Octopus API noise for accounts without smart devices by logging the expected KT-CT-4301 warnings only once per account and demoting subsequent detections to debug level.

## [1.0.8] - 2025-11-13

### Added
- Introduced a dedicated "Octopus Energy Public Tariffs" device with per-tariff sensors (`sensor.octopus_energy_public_tariffs_<tariff_slug>`) sourced from the Octopus public site.

### Fixed
- Charge target number entity accepts the official 10–100% range with 1% increments and keeps slider values in sync with the Octopus API.

## [1.0.7] - 2025-11-10

### Changed
- Refreshed the bundled GraphQL schema and aligned all entities with a centralized translation system, delivering bilingual (IT/EN) names for POD/PDR statuses, EV SmartFlex states and ledger balances.
- Switch entities now keep their pending state until Kraken confirms the action and trigger an immediate coordinator refresh after every toggle, so the Home Assistant UI reflects backend changes without waiting for the next poll.
- Ledger balances adopt static translation keys (e.g. TV licence fee) instead of the raw labels returned by the API, ensuring consistent naming across dashboards.

### Breaking
- Removed the redundant `sensor.octopus_<account>_ev_charge_target` and `sensor.octopus_<account>_ev_ready_time` entities; use the existing number/select platforms to manage Intelligent Octopus targets and ready-by times.

### Documentation
- README files and the technical notes now reference the official developer portal, the public Kraken GraphQL endpoint, and document the new localization model.

## [1.0.6] - 2025-11-06

### Changed
- Updated the download counter to mirror the installation numbers reported by HACS analytics.

## [1.0.5] - 2025-10-27

### Added
- Gas last reading date sensor exposing the recording date from the latest cumulative reading.

### Changed
- Electricity last reading sensors renamed to highlight daily aggregation and align the entity titles with the data returned by Kraken.
- Added or refreshed explicit icons across all exposed entities to deliver consistent visuals in Home Assistant dashboards.

### Breaking
- `sensor.octopus_<account>_electricity_last_reading` and `sensor.octopus_<account>_electricity_last_reading_date` now use the IDs `sensor.octopus_<account>_electricity_last_daily_reading` and `sensor.octopus_<account>_electricity_last_daily_reading_date`; update dashboards, automations, and templates accordingly.

### Documentation
- Updated README files to document the renamed electricity sensors and the new gas reading date entity.

## [1.0.4] - 2025-10-20

### Added
- SmartFlex charge target number entity to manage the desired SOC directly from Home Assistant.
- SmartFlex ready-time select entity to adjust the completion window exposed by Intelligent Octopus.
- Electricity consumption sensor exposing the latest meter reading gathered via the Kraken GraphQL API.

### Changed
- Reviewed token refresh documentation to match the on-demand refresh logic with safety margin and fallback behaviour.
- Updated architectural notes to cover all active platforms (binary sensors, sensors, switches, numbers, selects).

### Documentation
- Performed a full technical review of `TECHNICAL_NOTES.md`, aligning it with the current implementation.
