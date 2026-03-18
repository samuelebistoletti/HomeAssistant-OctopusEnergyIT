"""Process raw API responses into structured coordinator data."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util.dt import as_utc, parse_datetime, utcnow

_LOGGER = logging.getLogger(__name__)


def _select_current_product(products_list: list[dict]) -> dict | None:
    """Pick the most recent product that is currently valid."""
    if not products_list:
        return None

    now = utcnow()
    valid_products = []
    for p in products_list:
        vf_str = p.get("validFrom")
        if not vf_str:
            continue
        vf = as_utc(parse_datetime(vf_str))
        if vf is None or vf > now:
            continue
        vt_str = p.get("validTo")
        if vt_str:
            vt = as_utc(parse_datetime(vt_str))
            if vt is not None and now > vt:
                continue
        valid_products.append(p)

    if not valid_products:
        return None

    valid_products.sort(
        key=lambda p: as_utc(parse_datetime(p.get("validFrom", ""))) or now,
        reverse=True,
    )
    return valid_products[0]


async def process_api_data(
    data: dict[str, Any],
    account_number: str,
    api: Any,
    available_products: dict[str, Any],
) -> dict[str, Any]:
    """Process raw API response into structured coordinator data."""
    if not data:
        return {}

    result_data: dict[str, Any] = {
        account_number: {
            "account_number": account_number,
            "account": {},
            "electricity_balance": 0,
            "planned_dispatches": [],
            "completed_dispatches": [],
            "property_ids": [],
            "properties": [],
            "devices": [],
            "devices_raw": [],
            "products": [],
            "products_raw": [],
            "gas_products": [],
            "vehicle_battery_size_in_kwh": None,
            "current_start": None,
            "current_end": None,
            "next_start": None,
            "next_end": None,
            "ledgers": [],
            "electricity_pod": None,
            "electricity_supply_point_id": None,
            "electricity_property_id": None,
            "gas_pdr": None,
            "gas_property_id": None,
            "electricity_supply_status": None,
            "electricity_enrolment_status": None,
            "electricity_enrolment_start": None,
            "electricity_supply_start": None,
            "electricity_is_smart_meter": None,
            "electricity_cancellation_reason": None,
            "electricity_supply_point": None,
            "electricity_contract_start": None,
            "electricity_contract_end": None,
            "electricity_contract_days_until_expiry": None,
            "electricity_terms_url": None,
            "electricity_annual_standing_charge": None,
            "electricity_consumption_charge": None,
            "electricity_consumption_charge_f2": None,
            "electricity_consumption_charge_f3": None,
            "electricity_consumption_units": None,
            "electricity_annual_standing_charge_units": None,
            "gas_supply_status": None,
            "gas_enrolment_status": None,
            "gas_enrolment_start": None,
            "gas_supply_start": None,
            "gas_is_smart_meter": None,
            "gas_cancellation_reason": None,
            "gas_supply_point": None,
            "gas_terms_url": None,
            "gas_annual_standing_charge": None,
            "gas_annual_standing_charge_units": None,
            "gas_consumption_units": None,
            "current_electricity_product": None,
            "electricity_agreements": [],
            "current_gas_product": None,
            "gas_agreements": [],
            "electricity_last_reading": None,
            "gas_last_reading": None,
            "available_products": available_products or {},
        }
    }

    account_data = data.get("account", {})

    _LOGGER.debug(
        "Processing API data - fields available: %s",
        list(data.keys()) if data else [],
    )

    if account_data and isinstance(account_data, dict):
        result_data[account_number]["account"] = account_data
        result_data[account_number]["properties"] = account_data.get("properties", [])
        _LOGGER.debug("Account data fields: %s", list(account_data.keys()))
    else:
        _LOGGER.warning("Account data is missing or invalid: %s", account_data)
        return result_data

    # Extract ALL ledger data
    ledgers = account_data.get("ledgers", [])
    result_data[account_number]["ledgers"] = ledgers

    electricity_balance_eur = 0
    gas_balance_eur = 0
    heat_balance_eur = 0
    other_ledgers: dict[str, float] = {}

    for ledger in ledgers:
        ledger_type = ledger.get("ledgerType")
        balance_cents = ledger.get("balance", 0)
        balance_eur = balance_cents / 100
        normalized_type = (ledger_type or "").upper()

        if normalized_type.endswith("ELECTRICITY_LEDGER"):
            electricity_balance_eur = balance_eur
        elif normalized_type.endswith("GAS_LEDGER"):
            gas_balance_eur = balance_eur
        elif normalized_type.endswith("HEAT_LEDGER"):
            heat_balance_eur = balance_eur
        else:
            other_ledgers[ledger_type] = balance_eur
            _LOGGER.debug(
                "Found additional ledger type: %s with balance: %.2f EUR",
                ledger_type,
                balance_eur,
            )

    result_data[account_number]["electricity_balance"] = electricity_balance_eur
    result_data[account_number]["gas_balance"] = gas_balance_eur
    result_data[account_number]["heat_balance"] = heat_balance_eur
    result_data[account_number]["other_ledgers"] = other_ledgers

    _LOGGER.debug(
        "Processed %d ledgers for account %s: elec=%.2f, gas=%.2f, heat=%.2f, other=%d",
        len(ledgers),
        account_number,
        electricity_balance_eur,
        gas_balance_eur,
        heat_balance_eur,
        len(other_ledgers),
    )

    # Extract supply point identifiers for electricity
    electricity_property_id = None
    first_electricity_supply_point = None
    for property_data in account_data.get("properties", []) or []:
        supply_points = property_data.get("electricitySupplyPoints") or []
        if supply_points:
            first_electricity_supply_point = supply_points[0]
            electricity_property_id = property_data.get("id")
            break

    electricity_pod = None
    electricity_supply_id = None
    if first_electricity_supply_point:
        electricity_pod = first_electricity_supply_point.get("pod")
        electricity_supply_id = first_electricity_supply_point.get("id")
        result_data[account_number]["electricity_supply_point"] = (
            first_electricity_supply_point
        )
        result_data[account_number]["electricity_supply_status"] = (
            first_electricity_supply_point.get("status")
        )
        result_data[account_number]["electricity_enrolment_status"] = (
            first_electricity_supply_point.get("enrolmentStatus")
        )
        result_data[account_number]["electricity_enrolment_start"] = (
            first_electricity_supply_point.get("enrolmentStartDate")
        )
        result_data[account_number]["electricity_supply_start"] = (
            first_electricity_supply_point.get("supplyStartDate")
        )
        result_data[account_number]["electricity_is_smart_meter"] = (
            first_electricity_supply_point.get("isSmartMeter")
        )
        result_data[account_number]["electricity_cancellation_reason"] = (
            first_electricity_supply_point.get("cancellationReason")
        )
        agreements = api.flatten_connection(
            first_electricity_supply_point.get("agreements")
        )
        simplified_agreements = []
        for agreement in agreements or []:
            if not isinstance(agreement, dict):
                continue
            product = agreement.get("product") or {}
            simplified_agreements.append(
                {
                    "id": agreement.get("id"),
                    "valid_from": agreement.get("validFrom"),
                    "valid_to": agreement.get("validTo"),
                    "is_active": agreement.get("isActive"),
                    "product_code": product.get("code"),
                    "product_name": product.get("displayName")
                    or product.get("fullName"),
                }
            )
        result_data[account_number]["electricity_agreements"] = simplified_agreements

    result_data[account_number]["electricity_pod"] = electricity_pod
    result_data[account_number]["electricity_supply_point_id"] = electricity_supply_id
    result_data[account_number]["electricity_property_id"] = electricity_property_id

    if electricity_property_id and electricity_pod:

        def _parse_read_at(entry: dict) -> datetime | None:
            timestamp = entry.get("readAt")
            if not timestamp:
                return None
            try:
                return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                return None

        latest_measurements = await api.fetch_electricity_measurements(
            electricity_property_id,
            electricity_pod,
            last=2,
        )
        if latest_measurements:
            sorted_latest = sorted(
                latest_measurements,
                key=lambda item: (
                    _parse_read_at(item) or datetime.min.replace(tzinfo=UTC)
                ),
            )
            latest = sorted_latest[-1]
            previous = sorted_latest[-2] if len(sorted_latest) > 1 else None

            latest_entry: dict[str, Any] = {
                "value": None,
                "start": previous.get("readAt") if previous else None,
                "end": latest.get("readAt"),
                "unit": latest.get("unit") or "kWh",
                "source": latest.get("source"),
                "start_register_value": previous.get("value") if previous else None,
                "end_register_value": latest.get("value"),
            }
            if (
                previous
                and previous.get("value") is not None
                and latest.get("value") is not None
            ):
                delta = latest["value"] - previous["value"]
                if delta < 0:
                    _LOGGER.warning(
                        "Negative elec delta (%.2f kWh) for account %s: "
                        "start=%.2f end=%.2f — discarded.",
                        delta,
                        account_number,
                        previous["value"],
                        latest["value"],
                    )
                else:
                    latest_entry["value"] = delta

            result_data[account_number]["electricity_last_reading"] = latest_entry

    # Extract gas supply point
    gas_property_id = None
    first_gas_supply_point = None
    for property_data in account_data.get("properties", []) or []:
        supply_points = property_data.get("gasSupplyPoints") or []
        if supply_points:
            first_gas_supply_point = supply_points[0]
            gas_property_id = property_data.get("id")
            break

    gas_pdr = None
    if first_gas_supply_point:
        gas_pdr = first_gas_supply_point.get("pdr")
        result_data[account_number]["gas_supply_point"] = first_gas_supply_point
        result_data[account_number]["gas_supply_status"] = (
            first_gas_supply_point.get("status")
        )
        result_data[account_number]["gas_enrolment_status"] = (
            first_gas_supply_point.get("enrolmentStatus")
        )
        result_data[account_number]["gas_enrolment_start"] = (
            first_gas_supply_point.get("enrolmentStartDate")
        )
        result_data[account_number]["gas_supply_start"] = (
            first_gas_supply_point.get("supplyStartDate")
        )
        result_data[account_number]["gas_is_smart_meter"] = (
            first_gas_supply_point.get("isSmartMeter")
        )
        result_data[account_number]["gas_cancellation_reason"] = (
            first_gas_supply_point.get("cancellationReason")
        )
        agreements = api.flatten_connection(first_gas_supply_point.get("agreements"))
        simplified_agreements = []
        for agreement in agreements or []:
            if not isinstance(agreement, dict):
                continue
            product = agreement.get("product") or {}
            simplified_agreements.append(
                {
                    "id": agreement.get("id"),
                    "valid_from": agreement.get("validFrom"),
                    "valid_to": agreement.get("validTo"),
                    "is_active": agreement.get("isActive"),
                    "product_code": product.get("code"),
                    "product_name": product.get("displayName")
                    or product.get("fullName"),
                }
            )
        result_data[account_number]["gas_agreements"] = simplified_agreements

    result_data[account_number]["gas_pdr"] = gas_pdr
    result_data[account_number]["gas_property_id"] = gas_property_id

    if gas_pdr:
        latest_gas_readings = await api.fetch_gas_meter_readings(
            account_number,
            gas_pdr,
            first=1,
        )
        if latest_gas_readings:
            result_data[account_number]["gas_last_reading"] = latest_gas_readings[0]

    # Extract property IDs
    property_ids = [prop.get("id") for prop in account_data.get("properties", [])]
    result_data[account_number]["property_ids"] = property_ids

    # Handle device-related data
    devices = data.get("devices", [])
    result_data[account_number]["devices"] = devices
    result_data[account_number]["devices_raw"] = list(devices)

    # Extract vehicle battery size if available
    vehicle_battery_size = None
    for device in devices:
        if device.get("vehicleVariant") and device["vehicleVariant"].get("batterySize"):
            try:
                vehicle_battery_size = float(device["vehicleVariant"]["batterySize"])
                break
            except (ValueError, TypeError):
                pass
    result_data[account_number]["vehicle_battery_size_in_kwh"] = vehicle_battery_size

    # Handle dispatch data
    planned_dispatches = data.get("plannedDispatches") or []
    result_data[account_number]["planned_dispatches"] = planned_dispatches

    completed_dispatches = data.get("completedDispatches") or []
    result_data[account_number]["completed_dispatches"] = completed_dispatches

    # Calculate current and next dispatches
    now = utcnow()
    current_start = None
    current_end = None
    next_start = None
    next_end = None

    for dispatch in sorted(planned_dispatches, key=lambda x: x.get("start", "")):
        try:
            start_str = dispatch.get("start")
            end_str = dispatch.get("end")

            if not start_str or not end_str:
                continue

            start = as_utc(parse_datetime(start_str))
            end = as_utc(parse_datetime(end_str))

            if start <= now <= end:
                current_start = start
                current_end = end
            elif now < start and not next_start:
                next_start = start
                next_end = end

        except (ValueError, TypeError) as e:
            _LOGGER.warning(
                "Error parsing dispatch dates: %s — %s", dispatch, str(e)
            )

    result_data[account_number]["current_start"] = current_start
    result_data[account_number]["current_end"] = current_end
    result_data[account_number]["next_start"] = next_start
    result_data[account_number]["next_end"] = next_end

    # Electricity products
    products = data.get("products") or []
    if products:
        _LOGGER.debug(
            "Found %d electricity products for account %s",
            len(products),
            account_number,
        )
    else:
        _LOGGER.warning(
            "No electricity products for account %s; registering fallback tariff",
            account_number,
        )
        products = [
            {
                "code": "FALLBACK_ELECTRICITY",
                "description": "Fallback electricity tariff",
                "name": "Fallback Electricity Tariff",
                "displayName": "Fallback Electricity Tariff",
                "validFrom": None,
                "validTo": None,
                "agreementId": None,
                "productType": None,
                "isTimeOfUse": False,
                "type": "Simple",
                "timeslots": [],
                "termsAndConditionsUrl": None,
                "pricing": {
                    "base": 0.30,
                    "f2": None,
                    "f3": None,
                    "units": "EUR/kWh",
                    "annualStandingCharge": None,
                    "annualStandingChargeUnits": None,
                },
                "params": {},
                "rawPrices": {},
                "supplyPoint": {},
                "unitRateForecast": [],
                "grossRate": "30",
            }
        ]

    result_data[account_number]["products"] = products
    result_data[account_number]["products_raw"] = products

    current_electricity_product = _select_current_product(products)
    result_data[account_number]["current_electricity_product"] = (
        current_electricity_product
    )
    if current_electricity_product:
        result_data[account_number]["electricity_contract_start"] = (
            current_electricity_product.get("validFrom")
        )
        result_data[account_number]["electricity_contract_end"] = (
            current_electricity_product.get("validTo")
        )
        pricing = current_electricity_product.get("pricing") or {}
        result_data[account_number]["electricity_annual_standing_charge"] = (
            pricing.get("annualStandingCharge")
        )
        result_data[account_number]["electricity_annual_standing_charge_units"] = (
            pricing.get("annualStandingChargeUnits")
        )
        result_data[account_number]["electricity_consumption_charge"] = pricing.get(
            "base"
        )
        result_data[account_number]["electricity_consumption_charge_f2"] = pricing.get(
            "f2"
        )
        result_data[account_number]["electricity_consumption_charge_f3"] = pricing.get(
            "f3"
        )
        result_data[account_number]["electricity_consumption_units"] = pricing.get(
            "units"
        )
        result_data[account_number]["electricity_terms_url"] = (
            current_electricity_product.get("termsAndConditionsUrl")
        )

        valid_to = current_electricity_product.get("validTo")
        if valid_to:
            end_date = as_utc(parse_datetime(valid_to))
            if end_date is not None:
                days_diff = (end_date - utcnow()).days
                result_data[account_number][
                    "electricity_contract_days_until_expiry"
                ] = max(0, days_diff)

    # Gas products
    gas_products = data.get("gas_products") or []
    if gas_products:
        _LOGGER.debug(
            "Found %d gas products for account %s", len(gas_products), account_number
        )
    else:
        _LOGGER.debug("No gas products found for account %s", account_number)

    result_data[account_number]["gas_products"] = gas_products

    gas_price = None
    gas_contract_start = None
    gas_contract_end = None
    gas_contract_days_until_expiry = None

    current_gas_product = _select_current_product(gas_products)
    result_data[account_number]["current_gas_product"] = current_gas_product
    if current_gas_product:
        pricing = current_gas_product.get("pricing") or {}
        base_rate = pricing.get("base") if isinstance(pricing, dict) else None
        if base_rate is not None:
            gas_price = base_rate
        else:
            gross_rate_str = current_gas_product.get("grossRate")
            if gross_rate_str is not None:
                try:
                    gas_price = float(gross_rate_str) / 100.0
                except (ValueError, TypeError):
                    gas_price = None

        result_data[account_number]["gas_terms_url"] = current_gas_product.get(
            "termsAndConditionsUrl"
        )
        if isinstance(pricing, dict):
            result_data[account_number]["gas_annual_standing_charge"] = pricing.get(
                "annualStandingCharge"
            )
            result_data[account_number]["gas_annual_standing_charge_units"] = (
                pricing.get("annualStandingChargeUnits")
            )
            result_data[account_number]["gas_consumption_units"] = pricing.get("units")

        gas_contract_start = current_gas_product.get("validFrom")
        gas_contract_end = current_gas_product.get("validTo")

        if gas_contract_end:
            end_date = as_utc(parse_datetime(gas_contract_end))
            if end_date is not None:
                gas_contract_days_until_expiry = max(0, (end_date - utcnow()).days)

    result_data[account_number]["gas_price"] = gas_price
    result_data[account_number]["gas_contract_start"] = gas_contract_start
    result_data[account_number]["gas_contract_end"] = gas_contract_end
    result_data[account_number]["gas_contract_days_until_expiry"] = (
        gas_contract_days_until_expiry
    )

    return result_data
