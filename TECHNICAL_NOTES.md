# Octopus Energy Italy Integration - Technical Documentation

## Architecture Overview

## Riferimenti API
- Documentazione ufficiale: [developer portal Octopus Energy Italy](https://developer.oeit-kraken.energy/)
- Endpoint GraphQL: [`https://api.oeit-kraken.energy/v1/graphql/`](https://api.oeit-kraken.energy/v1/graphql/) utilizzato tramite il client `python-graphql-client`

### Localization & Naming
- Tutte le entità espongono `translation_key`, consentendo a Home Assistant di visualizzare nomi e stati in italiano o inglese senza duplicare logica.
- Le funzioni `_normalize_supply_status` e `_normalize_ev_status` massaggiano gli stati restituiti da Kraken così che POD/PDR ed EV SmartFlex pubblichino sempre slug leggibili.
- I ledger con etichette poco chiare (es. canone TV) ricevono translation key dedicate per evitare di usare i nomi grezzi del backend.

### Core Components
- **Main Coordinator**: Central data coordinator using `DataUpdateCoordinator` with shared token management
- **API Client** (`octopus_energy_it.py`): Handles GraphQL authentication, token refresh, and all API calls
- **Platforms**: binary_sensor, sensor, switch, number, select - all sharing the main coordinator
- **Token Management**: On-demand refresh with a 5-minute expiry margin and robust retry handling
- **Public Tariff Device**: Single device (`Octopus Tariffe pubbliche`) shared across all config entries; sensors hook directly to it instead of per-account devices

### Key Implementation Details

#### Token Management & Authentication
- **Shared Token Strategy**: All platforms use `hass.data[DOMAIN][entry.entry_id]["coordinator"]`
- **Token Refresh Logic**: Tokens refresh on demand when near expiry (5-minute margin, 50-minute fallback when exp missing)
- **Error Handling**: 5 retry attempts with exponential backoff on login failures
- **GraphQL Client**: Centralized `_get_graphql_client()` method for consistent authentication

#### Data Flow Architecture
```
API Client (octopus_energy_it.py)
    ↓ (GraphQL + Token Management)
Main Coordinator (DataUpdateCoordinator)
    ↓ (Shared Data)
├── Binary Sensor (intelligent dispatching)
├── Sensors (price, balance, meter readings, device status)
├── Switches (device suspension, boost charge)
├── Number (SmartFlex target percentage)
└── Select (SmartFlex target ready time)
```

#### Critical Implementation Rules

1. **Coordinator Access Pattern**:
   ```python
   # CORRECT - All platforms must use this pattern
   data = hass.data[DOMAIN][entry.entry_id]
   coordinator = data["coordinator"]

   # WRONG - Never create separate coordinators for platforms
   # coordinator = SeparateCoordinator(hass, client, account)
   ```

2. **Token Sharing**:
   - Never create separate GraphQL clients in platform entities
   - Always use `self.client._get_graphql_client()` for mutations
   - Let the main API client handle all token management

3. **Data Structure**:
   ```python
   coordinator.data = {
       "account_number": {
           "devices": [...],
           "products": [...],
           "planned_dispatches": [...],
           # ... other account data
       }
   }
   ```

#### Switch Platform Specifics

##### Device Suspension Switches
- Created for each device in coordinator data
- Uses `change_device_suspension()` API method
- Pending state management with 5-minute timeout

##### Boost Charge Switches
- **CRITICAL**: Only available when Smart Charge is enabled
- Created only for devices with `deviceType` in `["ELECTRIC_VEHICLES", "CHARGE_POINTS"]`
- Uses GraphQL `updateBoostCharge` mutations
- **Availability Logic**:
  ```python
  # Device must be LIVE and either:
  # - SMART_CONTROL_CAPABLE, OR
  # - Already in BOOST state, OR
  # - Currently BOOST_CHARGING
  is_available = (
      current == "LIVE" and
      (has_smart_control or has_boost_state or has_boost_charging) and
      not is_suspended
  )
  ```

#### Number & Select Platform Specifics

##### SmartFlex Target Number
- One entity per SmartFlex-capable device exposing the charge target (`OctopusDeviceChargeTargetNumber`)
- Reads limits from `preferenceSetting.scheduleSettings` (`min`, `max`, `timeFrom`, `step`) with granularity defaulting to 1% and floor/ceiling of 10-100%
- Writes via `set_device_preferences()` to keep parity with the SmartFlex service layer
- Locally mirrors the returned schedule in coordinator data so UI stays fresh between coordinator polls

##### SmartFlex Ready-Time Select
- One entity per SmartFlex-capable device exposing the ready-by time (`OctopusDeviceTargetTimeSelect`)
- Builds options from `scheduleSettings.timeFrom/timeTo/timeStep`, defaulting to 30-minute increments when metadata is missing
- Reuses the current charge target when only the time changes, calling the same `set_device_preferences()` mutation
- Mirrors schedule updates locally using the shared coordinator to keep per-device data coherent

#### Services

##### set_device_preferences
- **Current Service**: Uses new SmartFlexDeviceInterface API
- **Parameters**: device_id, target_percentage (10-100%), target_time (04:00-17:00)
- **GraphQL Mutation**: `setDevicePreferences`
- **Validation**: Time format handling, percentage validation

#### Error Handling Patterns

1. **Token Expiry**:
   - Automatic retry with fresh token
   - Graceful degradation to cached data
   - User notification via logs

2. **GraphQL Errors**:
   - Parse error messages from response
   - Raise `HomeAssistantError` with user-friendly messages
   - Log technical details for debugging

3. **API Rate Limiting**:
   - Respect 90% of update interval before new API calls
   - Throttling mechanism in coordinator

#### Testing & Validation

##### Critical Test Scenarios
1. **Token Expiry Recovery**: Simulate expired tokens, verify auto-refresh
2. **Boost Switch Availability**: Test with/without Smart Charge enabled
3. **Service Calls**: Validate both services with various parameters
4. **Multi-Account Support**: Test with multiple Octopus accounts
5. **Error Resilience**: Network issues, API errors, malformed responses

##### Debug Settings
```yaml
logger:
  logs:
    custom_components.octopus_energy_it: debug
    custom_components.octopus_energy_it.octopus_energy_it: debug
    custom_components.octopus_energy_it.switch: debug
```

#### Performance Considerations

- **Update Interval**: 1 minute (set via `UPDATE_INTERVAL` constant)
- **API Call Throttling**: Prevents excessive requests
- **Cached Data Fallback**: Returns last known data on API failures
- **GraphQL Strategy**: Comprehensive base query plus targeted calls for dispatches and meter readings

#### Security Notes

- **Token Storage**: Tokens stored in memory only, not persisted
- **Credential Handling**: Email/password from config entry, not logged
- **GraphQL Endpoint**: Uses official Octopus Energy Kraken API
- **HTTPS Only**: All API communication over TLS

#### Migration & Compatibility

- **Breaking Changes**: Document in release notes
- **Config Migration**: Handle old config entries gracefully
- **API Versioning**: Monitor for Octopus API changes
- **Backward Compatibility**: Maintain for at least 2 major versions

#### Maintenance Checklist

1. **Regular Updates**:
   - Monitor Octopus API changes
   - Update GraphQL schema if needed
   - Test with Home Assistant core updates

2. **Code Quality**:
   - Follow Home Assistant coding standards
   - Maintain test coverage
   - Document all public APIs

3. **User Support**:
   - Clear error messages
   - Comprehensive documentation
   - Migration guides for breaking changes

## Known Issues & Workarounds

1. **Device Type Mapping**: Some devices may have unexpected `deviceType` values
2. **Time Zone Handling**: API uses UTC, local conversion needed for UI
3. **GraphQL Schema Evolution**: Monitor for field additions/deprecations

## Future Considerations

- **WebSocket Support**: Real-time updates from Octopus API
- **Advanced Scheduling**: More complex charge scheduling options
- **Energy Dashboard**: Integration with HA Energy features
- **Automation Templates**: Pre-built automations for common scenarios
- **Public Tariff Sensors**
  - Device-level scraper reads `__NEXT_DATA__` JSON from `https://octopusenergy.it/le-nostre-tariffe`
  - Only one device per integration; ownership of the device is tracked in `hass.data[DOMAIN]["public_owner"]`
  - Entities follow pattern `sensor.octopus_energy_public_tariffs_<tariff_slug>`
  - State equals `charge_f1` (float with 4 decimal places). Attributes expose `charge_f1/2/3`, `standing_charge_annual`, `terms_url`, `product_type`, etc.
  - Entities are disabled by default; enable via Entity Registry when needed.
