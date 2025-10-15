# Octopus Energy Italy Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_energy_it.total)

This custom component uses the Italian Octopus Energy Kraken GraphQL API to expose account, tariff, supply point and smart-charging data inside Home Assistant.

*Octopus Energy® is a registered trademark of Octopus Energy Group. This project is community maintained and not affiliated with the company.*

---

## Highlights

- **Full Italian schema support** – pulls data from `account`, `ledgers`, `properties`, `supplyPoints`, `devices`, and flex dispatch GraphQL queries published at `https://api.oeit-kraken.energy/v1/graphql/`
- **Multi-account aware** – automatically discovers each account number linked to the authenticated customer and keeps the entities separated
- **Tariff intelligence** – surfaces current simple, time-of-use, or dynamic electricity products and active gas contracts with detailed pricing metadata
- **Supply monitoring** – exposes electricity POD and gas PDR status, enrolment progress, smart-meter flags and cancellation reasons as dedicated sensors
- **SmartFlex insights** – reports planned/active dispatch windows, device states and detected vehicle battery capacity for automations
- **Home Assistant native** – integrates with the entity registry, supports config entry reloads, and honours a 1-minute coordinator refresh cadence (`UPDATE_INTERVAL`)

## Prerequisites

- An active Octopus Energy Italy customer account with credentials that can log in to the Kraken customer portal
- Home Assistant 2023.12 or newer (async config flows + `python_graphql_client` dependency)
- Optional: enable debug logging in `configuration.yaml` to troubleshoot API responses:

  ```yaml
  logger:
    logs:
      custom_components.octopus_energy_it: debug
  ```

## Installation

### HACS (recommended)

1. In HACS go to **Integrations → ⋮ → Custom repositories** and add `https://github.com/samuelebistoletti/octopus_energy_it` as type *Integration*
2. Search for "Octopus Energy Italy" and install the integration
3. Restart Home Assistant when prompted
4. Add the integration from **Settings → Devices & Services → Add Integration**

### Manual

1. Copy the `custom_components/octopus_energy_it` folder into your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Configure the integration from **Settings → Devices & Services → Add Integration**

## Configuration

1. Select **Octopus Energy Italy** from the add-integration dialog
2. Enter the email and password used on the Italian Kraken portal
3. The flow validates the credentials, collects one or more account numbers and stores them in the config entry
4. Entities are created after the first successful data refresh; the coordinator updates roughly every 60 seconds

## Data Model Overview

The integration reshapes the Italian Kraken schema into Home Assistant friendly structures:

- **Accounts & Ledgers** – balance information for electricity, gas, heat and any additional ledgers
- **Properties & Supply Points** – POD / PDR identifiers, supply status, enrolment state, smart-meter flags and cancellation reasons
- **Products** – electricity and gas products with pricing, unit rates, standing charges and validity windows
- **Devices & Preferences** – SmartFlex vehicles/charge points, suspension state and supported boost actions
- **Dispatches** – current and upcoming charge windows (flex planned dispatches) plus historical results

## Entities

### Binary Sensor

- `binary_sensor.octopus_<account>_intelligent_dispatching` – `on` while a planned dispatch window is active

### Sensors

**Tariffs & Pricing**
- `sensor.octopus_<account>_electricity_price` – current €/kWh based on active electricity product or forecast
- `sensor.octopus_<account>_gas_tariff` – active gas product code with pricing metadata
- `sensor.octopus_<account>_gas_price` – gas consumption price exposed as €/kWh

**Ledger Balances**
- `sensor.octopus_<account>_electricity_balance`
- `sensor.octopus_<account>_gas_balance`
- `sensor.octopus_<account>_heat_balance`
- `sensor.octopus_<account>_<ledger>_balance` – automatically created for every additional ledger returned by Kraken

**Supply Points**
- `sensor.octopus_<account>_electricity_supply_status` – status, enrolment state, smart-meter flag and cancellation reason for the POD
- `sensor.octopus_<account>_gas_supply_status` – status and metadata for the gas PDR
- `sensor.octopus_<account>_gas_pdr` – exposed PDR identifier
- `sensor.octopus_<account>_gas_supply_point_id` – internal gas supply point ID reported by Kraken

**Gas Contracts**
- `sensor.octopus_<account>_gas_contract_start`
- `sensor.octopus_<account>_gas_contract_end`
- `sensor.octopus_<account>_gas_contract_days_until_expiry`

**SmartFlex Windows**
- `sensor.octopus_<account>_dispatch_current_start`
- `sensor.octopus_<account>_dispatch_current_end`
- `sensor.octopus_<account>_dispatch_next_start`
- `sensor.octopus_<account>_dispatch_next_end`

**Devices & Vehicles**
- `sensor.octopus_<account>_device_status` – current device smart-control state, suspension flag and metadata
- `sensor.octopus_<account>_vehicle_battery_size` – detected battery capacity (kWh) for connected vehicles (disabled by default)

> **Tip:** Dispatch window and vehicle battery sensors are created disabled in the entity registry. Enable only those you need.

### Switches

- `switch.octopus_<account>_device_smart_control` – toggles smart control (suspension) for the primary device
- `switch.octopus_<account>_<device_name>_boost_charge` – instant boost charge switch for devices that support the SmartFlex boost action

### Service

- `octopus_energy_it.set_device_preferences`
  - `device_id`: Device identifier from the sensor attributes (required)
  - `target_percentage`: 20–100 value in 5% steps (required)
  - `target_time`: Completion time (`HH:MM`, 04:00–17:00) (required)

## Troubleshooting

- Use Home Assistant **Developer Tools → Logs** to inspect warnings about token refresh or API errors
- Set `LOG_API_RESPONSES` / `LOG_TOKEN_RESPONSES` in `custom_components/octopus_energy_it/const.py` to `True` for verbose output (only recommended temporarily)
- If no entities appear, confirm that at least one account exposes electricity or gas products in the Italian Kraken portal

---

Documentazione aggiornata per lo schema GraphQL di Octopus Energy Italia (Kraken).
