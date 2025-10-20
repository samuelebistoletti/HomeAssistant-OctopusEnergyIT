# Changelog

## [1.0.3] - 2025-10-20

### Added
- SmartFlex charge target number entity to manage the desired SOC directly from Home Assistant.
- SmartFlex ready-time select entity to adjust the completion window exposed by Intelligent Octopus.
- Electricity consumption sensor exposing the latest meter reading gathered via the Kraken GraphQL API.

### Changed
- Reviewed token refresh documentation to match the on-demand refresh logic with safety margin and fallback behaviour.
- Updated architectural notes to cover all active platforms (binary sensors, sensors, switches, numbers, selects).

### Documentation
- Performed a full technical review of `TECHNICAL_NOTES.md`, aligning it with the current implementation.
