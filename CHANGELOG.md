# Changelog

## [1.0.7] - 2025-11-06

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
