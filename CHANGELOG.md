# Changelog

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
