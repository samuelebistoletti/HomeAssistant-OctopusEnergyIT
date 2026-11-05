"""Tests for custom_components/octopus_energy_it/data_processor.py.

Covers:
  - _select_current_product
  - process_api_data (ledger extraction, supply-point parsing, dispatch windows,
    product selection, gas/electricity readings, fallback tariff)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# conftest._install_stubs() already ran; HA stubs are in sys.modules.
from custom_components.octopus_energy_it.data_processor import (
    _select_current_product,
    build_electricity_reading,
    device_battery_size_kwh,
    device_model,
    process_api_data,
)

_UTC = UTC


def _iso(dt: datetime) -> str:
    return dt.isoformat()


_NOW = datetime(2026, 3, 18, 12, 0, 0, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# _select_current_product
# ---------------------------------------------------------------------------


class TestSelectCurrentProduct:
    """Tests for _select_current_product."""

    _PATCH = "custom_components.octopus_energy_it.data_processor.utcnow"

    def _call(self, products, now=_NOW):
        with patch(self._PATCH, return_value=now):
            return _select_current_product(products)

    def test_empty_list_returns_none(self):
        assert self._call([]) is None

    def test_none_list_returns_none(self):
        # The function guard: `if not products_list: return None`
        assert self._call(None) is None

    def test_product_without_validfrom_is_skipped(self):
        products = [{"code": "X", "validFrom": None}]
        assert self._call(products) is None

    def test_future_validfrom_is_skipped(self):
        future = _iso(_NOW + timedelta(days=1))
        products = [{"code": "X", "validFrom": future}]
        assert self._call(products) is None

    def test_expired_product_is_skipped(self):
        past_start = _iso(_NOW - timedelta(days=10))
        past_end = _iso(_NOW - timedelta(days=1))
        products = [{"code": "X", "validFrom": past_start, "validTo": past_end}]
        assert self._call(products) is None

    def test_current_product_returned(self):
        start = _iso(_NOW - timedelta(days=5))
        products = [{"code": "ACTIVE", "validFrom": start}]
        result = self._call(products)
        assert result is not None
        assert result["code"] == "ACTIVE"

    def test_product_valid_until_future_returned(self):
        start = _iso(_NOW - timedelta(days=5))
        end = _iso(_NOW + timedelta(days=30))
        products = [{"code": "ACTIVE", "validFrom": start, "validTo": end}]
        result = self._call(products)
        assert result is not None
        assert result["code"] == "ACTIVE"

    def test_most_recent_valid_product_selected(self):
        """When multiple products are valid, the one with the latest validFrom wins."""
        older = _iso(_NOW - timedelta(days=30))
        newer = _iso(_NOW - timedelta(days=5))
        products = [
            {"code": "OLD", "validFrom": older},
            {"code": "NEW", "validFrom": newer},
        ]
        result = self._call(products)
        assert result["code"] == "NEW"

    def test_product_starting_exactly_now_is_current(self):
        products = [{"code": "NOW", "validFrom": _iso(_NOW)}]
        result = self._call(products)
        assert result is not None
        assert result["code"] == "NOW"

    def test_product_expiring_exactly_now_is_still_current(self):
        start = _iso(_NOW - timedelta(days=1))
        products = [{"code": "EXPIRING", "validFrom": start, "validTo": _iso(_NOW)}]
        # validTo == now → vt is not > now so the product passes the filter
        result = self._call(products)
        assert result is not None
        assert result["code"] == "EXPIRING"


# ---------------------------------------------------------------------------
# Helpers for process_api_data tests
# ---------------------------------------------------------------------------

ACCOUNT = "A-TEST1234"


def _make_api(
    electricity_measurements=None,
    gas_readings=None,
    flatten_connection=None,
):
    """Return a mock OctopusEnergyIT API with sensible defaults."""
    api = MagicMock()
    api.fetch_electricity_measurements = AsyncMock(
        return_value=electricity_measurements or []
    )
    api.fetch_gas_meter_readings = AsyncMock(return_value=gas_readings or [])
    api.flatten_connection = flatten_connection or (lambda x: x or [])
    return api


def _minimal_account_data(
    *,
    electricity_supply_points=None,
    gas_supply_points=None,
    ledgers=None,
    properties_extra=None,
):
    """Build a minimal fetch_all_data response."""
    props = [
        {
            "id": "prop-001",
            "electricitySupplyPoints": electricity_supply_points or [],
            "gasSupplyPoints": gas_supply_points or [],
        }
    ]
    if properties_extra:
        props.extend(properties_extra)
    return {
        "account": {
            "id": "acc-001",
            "ledgers": ledgers or [],
            "properties": props,
        },
        "products": [],
        "gas_products": [],
        "devices": [],
        "plannedDispatches": [],
        "completedDispatches": [],
    }


# ---------------------------------------------------------------------------
# process_api_data — basic structure
# ---------------------------------------------------------------------------


class TestProcessApiDataStructure:
    """Tests that process_api_data returns the expected top-level shape."""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        api = _make_api()
        result = await process_api_data({}, ACCOUNT, api, {})
        assert result == {}

    @pytest.mark.asyncio
    async def test_missing_account_key_returns_scaffold(self):
        """Data without 'account' key returns scaffold and logs warning."""
        api = _make_api()
        data = {"products": [], "devices": []}
        result = await process_api_data(data, ACCOUNT, api, {})
        # Should return the default scaffold (early return after warning)
        assert ACCOUNT in result

    @pytest.mark.asyncio
    async def test_result_keyed_by_account_number(self):
        api = _make_api()
        data = _minimal_account_data()
        result = await process_api_data(data, ACCOUNT, api, {})
        assert ACCOUNT in result

    @pytest.mark.asyncio
    async def test_account_number_field_populated(self):
        api = _make_api()
        data = _minimal_account_data()
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["account_number"] == ACCOUNT


# ---------------------------------------------------------------------------
# process_api_data — ledger extraction
# ---------------------------------------------------------------------------


class TestProcessApiDataLedgers:
    @pytest.mark.asyncio
    async def test_electricity_balance_extracted(self):
        api = _make_api()
        data = _minimal_account_data(
            ledgers=[{"balance": 4250, "ledgerType": "ELECTRICITY_LEDGER"}]
        )
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_balance"] == pytest.approx(42.50)

    @pytest.mark.asyncio
    async def test_gas_balance_extracted(self):
        api = _make_api()
        data = _minimal_account_data(
            ledgers=[{"balance": 900, "ledgerType": "GAS_LEDGER"}]
        )
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["gas_balance"] == pytest.approx(9.00)

    @pytest.mark.asyncio
    async def test_heat_balance_extracted(self):
        api = _make_api()
        data = _minimal_account_data(
            ledgers=[{"balance": 600, "ledgerType": "HEAT_LEDGER"}]
        )
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["heat_balance"] == pytest.approx(6.00)

    @pytest.mark.asyncio
    async def test_multiple_ledgers_parsed(self):
        api = _make_api()
        data = _minimal_account_data(
            ledgers=[
                {"balance": 4250, "ledgerType": "ELECTRICITY_LEDGER"},
                {"balance": 900, "ledgerType": "GAS_LEDGER"},
            ]
        )
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_balance"] == pytest.approx(42.50)
        assert result[ACCOUNT]["gas_balance"] == pytest.approx(9.00)

    @pytest.mark.asyncio
    async def test_other_ledger_goes_to_other_ledgers(self):
        api = _make_api()
        data = _minimal_account_data(
            ledgers=[{"balance": 100, "ledgerType": "REWARDS_LEDGER"}]
        )
        result = await process_api_data(data, ACCOUNT, api, {})
        assert "REWARDS_LEDGER" in result[ACCOUNT]["other_ledgers"]
        assert result[ACCOUNT]["other_ledgers"]["REWARDS_LEDGER"] == pytest.approx(1.00)

    @pytest.mark.asyncio
    async def test_no_ledgers_gives_zero_balances(self):
        api = _make_api()
        data = _minimal_account_data(ledgers=[])
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_balance"] == 0
        assert result[ACCOUNT]["gas_balance"] == 0


# ---------------------------------------------------------------------------
# process_api_data — electricity supply point
# ---------------------------------------------------------------------------


class TestProcessApiDataElectricitySupplyPoint:
    _SUPPLY_POINT = {
        "id": "esp-001",
        "pod": "IT001E12345678901",
        "status": "ACTIVE",
        "enrolmentStatus": "ENROLLED",
        "enrolmentStartDate": "2023-01-01",
        "supplyStartDate": "2023-01-15",
        "cancellationReason": None,
        "isSmartMeter": True,
        "agreements": [],
    }

    @pytest.mark.asyncio
    async def test_pod_extracted(self):
        api = _make_api()
        data = _minimal_account_data(electricity_supply_points=[self._SUPPLY_POINT])
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_pod"] == "IT001E12345678901"

    @pytest.mark.asyncio
    async def test_supply_point_id_extracted(self):
        api = _make_api()
        data = _minimal_account_data(electricity_supply_points=[self._SUPPLY_POINT])
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_supply_point_id"] == "esp-001"

    @pytest.mark.asyncio
    async def test_enrolment_status_extracted(self):
        api = _make_api()
        data = _minimal_account_data(electricity_supply_points=[self._SUPPLY_POINT])
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_enrolment_status"] == "ENROLLED"

    @pytest.mark.asyncio
    async def test_smart_meter_flag_extracted(self):
        api = _make_api()
        data = _minimal_account_data(electricity_supply_points=[self._SUPPLY_POINT])
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_is_smart_meter"] is True

    @pytest.mark.asyncio
    async def test_no_supply_points_gives_none_pod(self):
        api = _make_api()
        data = _minimal_account_data(electricity_supply_points=[])
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_pod"] is None


# ---------------------------------------------------------------------------
# process_api_data — fallback tariff
# ---------------------------------------------------------------------------


class TestProcessApiDataFallbackTariff:
    @pytest.mark.asyncio
    async def test_no_products_leaves_products_empty(self):
        api = _make_api()
        data = _minimal_account_data()
        data["products"] = []
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["products"] == []
        assert result[ACCOUNT]["current_electricity_product"] is None
        assert result[ACCOUNT]["has_electricity_tariff"] is False

    @pytest.mark.asyncio
    async def test_with_products_sets_has_electricity_tariff(self):
        api = _make_api()
        data = _minimal_account_data()
        data["products"] = [
            {
                "code": "FLEX",
                "validFrom": _iso(_NOW - timedelta(days=5)),
                "validTo": None,
                "pricing": {"base": 0.25, "f2": None, "f3": None, "units": "EUR/kWh"},
            }
        ]
        result = await process_api_data(data, ACCOUNT, api, {})
        codes = [p["code"] for p in result[ACCOUNT]["products"]]
        assert "FLEX" in codes
        assert result[ACCOUNT]["has_electricity_tariff"] is True


# ---------------------------------------------------------------------------
# process_api_data — dispatch windows
# ---------------------------------------------------------------------------


class TestProcessApiDataDispatches:
    _PATCH = "custom_components.octopus_energy_it.data_processor.utcnow"

    @pytest.mark.asyncio
    async def test_active_dispatch_sets_current_start_end(self):
        api = _make_api()
        data = _minimal_account_data()
        data["plannedDispatches"] = [
            {
                "start": _iso(_NOW - timedelta(hours=1)),
                "end": _iso(_NOW + timedelta(hours=1)),
            }
        ]
        with patch(self._PATCH, return_value=_NOW):
            result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["current_start"] is not None
        assert result[ACCOUNT]["current_end"] is not None

    @pytest.mark.asyncio
    async def test_future_dispatch_sets_next_start_end(self):
        api = _make_api()
        data = _minimal_account_data()
        data["plannedDispatches"] = [
            {
                "start": _iso(_NOW + timedelta(hours=2)),
                "end": _iso(_NOW + timedelta(hours=3)),
            }
        ]
        with patch(self._PATCH, return_value=_NOW):
            result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["current_start"] is None
        assert result[ACCOUNT]["next_start"] is not None

    @pytest.mark.asyncio
    async def test_no_dispatches_gives_none_windows(self):
        api = _make_api()
        data = _minimal_account_data()
        data["plannedDispatches"] = []
        with patch(self._PATCH, return_value=_NOW):
            result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["current_start"] is None
        assert result[ACCOUNT]["next_start"] is None


# ---------------------------------------------------------------------------
# process_api_data — electricity contract expiry
# ---------------------------------------------------------------------------


class TestProcessApiDataContractExpiry:
    _PATCH = "custom_components.octopus_energy_it.data_processor.utcnow"

    @pytest.mark.asyncio
    async def test_contract_days_until_expiry_calculated(self):
        api = _make_api()
        data = _minimal_account_data()
        expiry = _NOW + timedelta(days=10)
        data["products"] = [
            {
                "code": "EXPIRING",
                "validFrom": _iso(_NOW - timedelta(days=5)),
                "validTo": _iso(expiry),
                "pricing": {"base": 0.25, "units": "EUR/kWh"},
            }
        ]
        with patch(self._PATCH, return_value=_NOW):
            result = await process_api_data(data, ACCOUNT, api, {})
        days = result[ACCOUNT]["electricity_contract_days_until_expiry"]
        assert days == 10

    @pytest.mark.asyncio
    async def test_expired_contract_gives_zero_days(self):
        api = _make_api()
        data = _minimal_account_data()
        data["products"] = [
            {
                "code": "EXPIRED",
                "validFrom": _iso(_NOW - timedelta(days=30)),
                "validTo": _iso(_NOW - timedelta(days=1)),
                "pricing": {"base": 0.25, "units": "EUR/kWh"},
            }
        ]
        with patch(self._PATCH, return_value=_NOW):
            result = await process_api_data(data, ACCOUNT, api, {})
        # No current product (expired), so days_until_expiry stays None
        assert result[ACCOUNT]["electricity_contract_days_until_expiry"] is None

    @pytest.mark.asyncio
    async def test_no_validto_gives_none_expiry(self):
        api = _make_api()
        data = _minimal_account_data()
        data["products"] = [
            {
                "code": "OPEN",
                "validFrom": _iso(_NOW - timedelta(days=5)),
                "validTo": None,
                "pricing": {"base": 0.25, "units": "EUR/kWh"},
            }
        ]
        with patch(self._PATCH, return_value=_NOW):
            result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_contract_days_until_expiry"] is None


# ---------------------------------------------------------------------------
# process_api_data — devices and vehicle battery
# ---------------------------------------------------------------------------


class TestProcessApiDataDevices:
    @pytest.mark.asyncio
    async def test_devices_populated(self):
        api = _make_api()
        data = _minimal_account_data()
        data["devices"] = [{"id": "dev-001", "name": "My EV"}]
        result = await process_api_data(data, ACCOUNT, api, {})
        assert len(result[ACCOUNT]["devices"]) == 1
        assert result[ACCOUNT]["devices"][0]["id"] == "dev-001"

    @pytest.mark.asyncio
    async def test_vehicle_battery_size_extracted(self):
        api = _make_api()
        data = _minimal_account_data()
        data["devices"] = [{"id": "dev-001", "vehicleBatterySize": "64.5"}]
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["vehicle_battery_size_in_kwh"] == pytest.approx(64.5)

    @pytest.mark.asyncio
    async def test_vehicle_battery_size_legacy_variant_shape(self):
        api = _make_api()
        data = _minimal_account_data()
        data["devices"] = [{"id": "dev-001", "vehicleVariant": {"batterySize": 75.0}}]
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["vehicle_battery_size_in_kwh"] == pytest.approx(75.0)

    @pytest.mark.asyncio
    async def test_battery_size_skips_devices_without_one(self):
        api = _make_api()
        data = _minimal_account_data()
        data["devices"] = [
            {"id": "charger", "deviceType": "CHARGE_POINTS"},
            {"id": "ev", "vehicleBatterySize": 77},
        ]
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["vehicle_battery_size_in_kwh"] == pytest.approx(77.0)

    @pytest.mark.asyncio
    async def test_no_vehicle_gives_none_battery(self):
        api = _make_api()
        data = _minimal_account_data()
        data["devices"] = [{"id": "dev-001"}]
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["vehicle_battery_size_in_kwh"] is None

    @pytest.mark.asyncio
    async def test_invalid_battery_size_handled(self):
        api = _make_api()
        data = _minimal_account_data()
        data["devices"] = [
            {"id": "dev-001", "vehicleVariant": {"batterySize": "not-a-number"}}
        ]
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["vehicle_battery_size_in_kwh"] is None


# ---------------------------------------------------------------------------
# process_api_data — electricity last reading
# ---------------------------------------------------------------------------


class TestProcessApiDataElectricityReading:
    _SUPPLY_POINT = {
        "id": "esp-001",
        "pod": "IT001E12345678901",
        "status": "ACTIVE",
        "enrolmentStatus": "ENROLLED",
        "enrolmentStartDate": "2023-01-01",
        "supplyStartDate": "2023-01-15",
        "cancellationReason": None,
        "isSmartMeter": True,
        "agreements": [],
    }

    @pytest.mark.asyncio
    async def test_positive_delta_stored(self):
        t1 = _iso(_NOW - timedelta(hours=2))
        t2 = _iso(_NOW - timedelta(hours=1))
        measurements = [
            {"readAt": t1, "value": 100.0, "unit": "kWh", "source": "SMART"},
            {"readAt": t2, "value": 101.5, "unit": "kWh", "source": "SMART"},
        ]
        api = _make_api(electricity_measurements=measurements)
        data = _minimal_account_data(electricity_supply_points=[self._SUPPLY_POINT])
        result = await process_api_data(data, ACCOUNT, api, {})
        reading = result[ACCOUNT]["electricity_last_reading"]
        assert reading is not None
        assert reading["value"] == pytest.approx(1.5)

    @pytest.mark.asyncio
    async def test_negative_delta_discarded(self):
        t1 = _iso(_NOW - timedelta(hours=2))
        t2 = _iso(_NOW - timedelta(hours=1))
        measurements = [
            {"readAt": t1, "value": 200.0, "unit": "kWh", "source": "SMART"},
            {"readAt": t2, "value": 190.0, "unit": "kWh", "source": "SMART"},
        ]
        api = _make_api(electricity_measurements=measurements)
        data = _minimal_account_data(electricity_supply_points=[self._SUPPLY_POINT])
        result = await process_api_data(data, ACCOUNT, api, {})
        reading = result[ACCOUNT]["electricity_last_reading"]
        # Negative delta → value should be None (discarded)
        assert reading["value"] is None

    @pytest.mark.asyncio
    async def test_no_measurements_gives_none_reading(self):
        api = _make_api(electricity_measurements=[])
        data = _minimal_account_data(electricity_supply_points=[self._SUPPLY_POINT])
        result = await process_api_data(data, ACCOUNT, api, {})
        assert result[ACCOUNT]["electricity_last_reading"] is None


# ---------------------------------------------------------------------------
# process_api_data — available_products passed through
# ---------------------------------------------------------------------------


class TestProcessApiDataAvailableProducts:
    @pytest.mark.asyncio
    async def test_available_products_stored(self):
        api = _make_api()
        data = _minimal_account_data()
        available = {"electricity": [{"code": "FLEX_LUCE"}], "gas": []}
        result = await process_api_data(data, ACCOUNT, api, available)
        assert result[ACCOUNT]["available_products"] == available

    @pytest.mark.asyncio
    async def test_none_available_products_defaults_to_empty_dict(self):
        api = _make_api()
        data = _minimal_account_data()
        result = await process_api_data(data, ACCOUNT, api, None)
        assert result[ACCOUNT]["available_products"] == {}


# ---------------------------------------------------------------------------
# SmartFlex vehicle helpers (vehicleVariant is deprecated by the API)
# ---------------------------------------------------------------------------


class TestVehicleHelpers:
    def test_battery_size_prefers_current_field(self):
        device = {"vehicleBatterySize": "60", "vehicleVariant": {"batterySize": 50}}
        assert device_battery_size_kwh(device) == pytest.approx(60.0)

    def test_battery_size_none_when_missing_or_invalid(self):
        assert device_battery_size_kwh({}) is None
        assert device_battery_size_kwh({"vehicleBatterySize": "n/a"}) is None

    def test_model_combines_make_and_model(self):
        assert device_model({"make": "Tesla", "model": "Model 3"}) == "Tesla Model 3"

    def test_model_falls_back_to_legacy_variant(self):
        assert device_model({"vehicleVariant": {"model": "ID.3"}}) == "ID.3"

    def test_model_none_when_unknown(self):
        assert device_model({"make": None, "model": ""}) is None


# ---------------------------------------------------------------------------
# build_electricity_reading (issue #26: negative deltas across registers)
# ---------------------------------------------------------------------------

POD = "IT001E00000001"


def _m(value, read_at, register="R1", supply_point=POD, quality="ACTUAL"):
    return {
        "value": value,
        "readAt": read_at,
        "unit": "kWh",
        "source": "DSO",
        "registerId": register,
        "readingQuality": quality,
        "supplyPointId": supply_point,
    }


class TestBuildElectricityReading:
    def test_delta_between_two_readings_of_same_register(self):
        entry = build_electricity_reading(
            [_m(100.0, "2026-11-01T00:00:00Z"), _m(112.5, "2026-11-02T00:00:00Z")],
            POD,
            "A-1",
        )
        assert entry["value"] == pytest.approx(12.5)
        assert entry["start"] == "2026-11-01T00:00:00Z"
        assert entry["end_register_value"] == 112.5
        assert entry["register_id"] == "R1"

    def test_readings_are_sorted_by_time(self):
        entry = build_electricity_reading(
            [_m(112.5, "2026-11-02T00:00:00Z"), _m(100.0, "2026-11-01T00:00:00Z")],
            POD,
            "A-1",
        )
        assert entry["value"] == pytest.approx(12.5)

    def test_issue_26_other_register_is_not_subtracted(self):
        # Values from the report: 34284.06 then 28198.24 on a different register.
        entry = build_electricity_reading(
            [
                _m(34270.00, "2026-10-07T00:00:00Z", register="R1"),
                _m(34284.06, "2026-10-08T00:00:00Z", register="R1"),
                _m(28198.24, "2026-10-08T00:00:00Z", register="R2"),
                _m(28210.00, "2026-10-09T00:00:00Z", register="R2"),
            ],
            POD,
            "A-1",
        )
        assert entry["register_id"] == "R2"
        assert entry["value"] == pytest.approx(11.76)

    def test_readings_of_another_supply_point_are_ignored(self):
        entry = build_electricity_reading(
            [
                _m(4403.98, "2026-10-08T00:00:00Z"),
                _m(1567.54, "2026-10-09T00:00:00Z", supply_point="PDR-GAS"),
            ],
            POD,
            "A-1",
        )
        assert entry["end_register_value"] == 4403.98
        assert entry["value"] is None

    def test_negative_delta_on_same_register_is_discarded(self):
        entry = build_electricity_reading(
            [_m(200.0, "2026-11-01T00:00:00Z"), _m(150.0, "2026-11-02T00:00:00Z")],
            POD,
            "A-1",
        )
        assert entry["value"] is None
        assert entry["end_register_value"] == 150.0

    def test_single_reading_has_no_delta(self):
        entry = build_electricity_reading(
            [_m(100.0, "2026-11-01T00:00:00Z")], POD, "A-1"
        )
        assert entry["value"] is None
        assert entry["start"] is None

    def test_same_timestamp_is_not_a_previous_reading(self):
        entry = build_electricity_reading(
            [_m(100.0, "2026-11-01T00:00:00Z"), _m(100.0, "2026-11-01T00:00:00Z")],
            POD,
            "A-1",
        )
        assert entry["value"] is None

    def test_missing_metadata_is_treated_as_one_register(self):
        older = _m(10.0, "2026-11-01T00:00:00Z", register=None, supply_point=None)
        newer = _m(11.0, "2026-11-02T00:00:00Z", register=None, supply_point=None)
        entry = build_electricity_reading([older, newer], POD, "A-1")
        assert entry["value"] == pytest.approx(1.0)

    def test_no_usable_measurements_returns_none(self):
        assert build_electricity_reading([], POD, "A-1") is None
        assert (
            build_electricity_reading(
                [{"value": None, "readAt": "2026-11-01T00:00:00Z"}], POD, "A-1"
            )
            is None
        )
