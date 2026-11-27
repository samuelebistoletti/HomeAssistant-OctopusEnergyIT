"""Tests for the external statistics import (issues #19 and #21)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.octopus_energy_it import statistics as stats_mod
from custom_components.octopus_energy_it.statistics import (
    Cursor,
    StatisticsImporter,
    hourly_rows,
    period_rows,
    readings_to_points,
    session_hours,
    statistic_id,
)

ROME = ZoneInfo("Europe/Rome")


def _local_midnight(year, month, day):
    return datetime(year, month, day, tzinfo=ROME).astimezone(UTC)


def _points(*values, start_day=1, month=11):
    """Daily midnight snapshots: values[i] read at local midnight of day start+i."""
    return [
        (_local_midnight(2026, month, start_day + i), value)
        for i, value in enumerate(values)
    ]


class TestStatisticId:
    def test_sanitises_account_number(self):
        assert (
            statistic_id("A-1234ABCD", "gas_consumption")
            == "octopus_energy_it:a_1234abcd_gas_consumption"
        )


class TestPeriodRows:
    def test_consumption_is_booked_on_the_day_it_was_used(self):
        rows, cursor = period_rows(_points(100.0, 110.0, 125.0), Cursor())

        assert [row["start"] for row in rows] == [
            _local_midnight(2026, 11, 1),
            _local_midnight(2026, 11, 2),
        ]
        assert [row["sum"] for row in rows] == [10.0, 25.0]
        assert [row["state"] for row in rows] == [110.0, 125.0]
        assert cursor == Cursor(_local_midnight(2026, 11, 2), 25.0)

    def test_continues_after_cursor_without_rewriting_old_days(self):
        cursor = Cursor(_local_midnight(2026, 11, 1), 500.0)
        rows, new_cursor = period_rows(_points(100.0, 110.0, 125.0), cursor)

        assert [row["start"] for row in rows] == [_local_midnight(2026, 11, 2)]
        assert rows[0]["sum"] == 515.0
        assert new_cursor.sum == 515.0

    def test_nothing_new_returns_same_cursor(self):
        cursor = Cursor(_local_midnight(2026, 11, 2), 25.0)
        rows, new_cursor = period_rows(_points(100.0, 110.0, 125.0), cursor)

        assert rows == []
        assert new_cursor == cursor

    def test_register_going_backwards_counts_as_zero(self):
        rows, _ = period_rows(_points(100.0, 5.0, 8.0), Cursor())

        assert [row["sum"] for row in rows] == [0.0, 3.0]

    def test_unsorted_input_is_sorted(self):
        points = _points(100.0, 110.0, 125.0)
        rows, _ = period_rows(list(reversed(points)), Cursor())

        assert [row["sum"] for row in rows] == [10.0, 25.0]

    def test_multiplier_converts_to_cost_and_state_is_the_total(self):
        rows, _ = period_rows(_points(100.0, 110.0), Cursor(), multiplier=0.25)

        assert rows[0]["sum"] == 2.5
        assert rows[0]["state"] == 2.5

    def test_two_readings_on_one_day_make_one_row(self):
        points = [
            (_local_midnight(2026, 11, 1), 100.0),
            (datetime(2026, 11, 1, 12, tzinfo=ROME).astimezone(UTC), 104.0),
            (_local_midnight(2026, 11, 2), 110.0),
        ]
        rows, _ = period_rows(points, Cursor())

        assert len(rows) == 1
        assert rows[0]["sum"] == 10.0

    def test_dst_change_keeps_local_midnight(self):
        # 25 Oct 2026: Italy leaves summer time; the day is 25 hours long.
        rows, _ = period_rows(_points(100.0, 110.0, start_day=25, month=10), Cursor())

        assert rows[0]["start"] == _local_midnight(2026, 10, 25)
        assert rows[0]["start"].astimezone(ROME).hour == 0


class TestReadingsToPoints:
    def test_datetime_and_date_only_readings(self):
        points = readings_to_points(
            [
                {"readAt": "2026-11-01T23:00:00+00:00", "value": 10.0},
                {"readingDate": "2026-11-03", "value": 3},
            ],
            date_key="readAt",
        ) + readings_to_points(
            [{"readingDate": "2026-11-03", "value": 3}], date_key="readingDate"
        )

        assert points == [
            (datetime(2026, 11, 1, 23, tzinfo=UTC), 10.0),
            (_local_midnight(2026, 11, 3), 3.0),
        ]

    def test_invalid_entries_are_skipped(self):
        assert (
            readings_to_points(
                [{"readAt": None, "value": 1}, {"readAt": "x", "value": None}],
                date_key="readAt",
            )
            == []
        )


# ---------------------------------------------------------------------------
# StatisticsImporter
# ---------------------------------------------------------------------------


def _hass():
    return SimpleNamespace(config=SimpleNamespace(currency="EUR"))


def _electricity(*values):
    return [
        {"readAt": point.isoformat(), "value": value}
        for point, value in _points(*values)
    ]


@pytest.fixture
def recorder():
    """Patch the recorder API; ``last`` holds what get_last_statistics returns."""
    state = SimpleNamespace(last={}, added=[])
    instance = MagicMock()

    async def _executor(func, *args):
        return state.last

    instance.async_add_executor_job = AsyncMock(side_effect=_executor)
    with (
        patch.object(stats_mod, "get_instance", return_value=instance),
        patch.object(
            stats_mod,
            "async_add_external_statistics",
            side_effect=lambda hass, meta, rows: state.added.append((meta, rows)),
        ),
    ):
        yield state


class TestStatisticsImporter:
    async def test_imports_electricity_and_cost_for_flat_tariff(self, recorder):
        account = {
            "electricity_readings": _electricity(100.0, 110.0),
            "electricity_consumption_charge": 0.2,
            "current_electricity_product": {"isTimeOfUse": False},
        }
        await StatisticsImporter(_hass()).async_import_account("A-1", account)

        (energy_meta, energy_rows), (cost_meta, cost_rows) = recorder.added
        assert (
            energy_meta["statistic_id"]
            == "octopus_energy_it:a_1_electricity_consumption"
        )
        assert energy_meta["unit_of_measurement"] == "kWh"
        assert energy_meta["unit_class"] == "energy"
        assert energy_meta["has_sum"] is True
        assert energy_rows[0]["sum"] == 10.0
        assert cost_meta["unit_of_measurement"] == "EUR"
        assert cost_meta["unit_class"] is None
        assert cost_rows[0]["sum"] == pytest.approx(2.0)

    async def test_no_cost_for_time_of_use_tariff(self, recorder):
        account = {
            "electricity_readings": _electricity(100.0, 110.0),
            "electricity_consumption_charge": 0.2,
            "current_electricity_product": {"isTimeOfUse": True},
        }
        await StatisticsImporter(_hass()).async_import_account("A-1", account)

        assert [meta["statistic_id"] for meta, _ in recorder.added] == [
            "octopus_energy_it:a_1_electricity_consumption"
        ]

    async def test_gas_statistics_in_cubic_metres(self, recorder):
        account = {
            "gas_readings": [
                {"readingDate": "2026-09-01", "value": 1000.0},
                {"readingDate": "2026-10-01", "value": 1040.5},
            ]
        }
        await StatisticsImporter(_hass()).async_import_account("A-1", account)

        ((meta, rows),) = recorder.added
        assert meta["unit_of_measurement"] == "m³"
        assert meta["unit_class"] == "volume"
        assert rows[0]["start"] == _local_midnight(2026, 9, 1)
        assert rows[0]["sum"] == 40.5

    async def test_resumes_from_recorder_and_caches_cursor(self, recorder):
        stat_id = "octopus_energy_it:a_1_electricity_consumption"
        recorder.last = {
            stat_id: [{"start": _local_midnight(2026, 11, 1).timestamp(), "sum": 900.0}]
        }
        importer = StatisticsImporter(_hass())
        account = {"electricity_readings": _electricity(100.0, 110.0, 125.0)}

        await importer.async_import_account("A-1", account)
        await importer.async_import_account("A-1", account)  # nothing new

        ((_meta, rows),) = recorder.added
        assert [row["sum"] for row in rows] == [915.0]
        # The recorder is queried once; later polls use the cached cursor.
        assert (
            stats_mod.get_instance.return_value.async_add_executor_job.await_count == 1
        )

    async def test_nothing_to_import_without_readings(self, recorder):
        await StatisticsImporter(_hass()).async_import_account("A-1", {})
        assert recorder.added == []


# ---------------------------------------------------------------------------
# Charging sessions (issue #36)
# ---------------------------------------------------------------------------

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def _utc(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def _session(start, end, kwh, kind="SMART"):
    return {
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "energy_kwh": kwh,
        "type": kind,
    }


class TestSessionHours:
    def test_energy_is_spread_over_the_hours_in_proportion(self):
        # 22:30-00:30: a quarter, a half and a quarter of the time.
        sessions = [_session(_utc(5, 22, 30), _utc(6, 0, 30), 8.0)]
        assert session_hours(sessions, "SMART", None, now=NOW) == {
            _utc(5, 22): pytest.approx(2.0),
            _utc(5, 23): pytest.approx(4.0),
            _utc(6, 0): pytest.approx(2.0),
        }

    def test_session_ending_on_the_hour_does_not_touch_the_next_hour(self):
        sessions = [_session(_utc(5, 1), _utc(5, 3), 4.0)]
        assert session_hours(sessions, "SMART", None, now=NOW) == {
            _utc(5, 1): pytest.approx(2.0),
            _utc(5, 2): pytest.approx(2.0),
        }

    def test_only_finished_sessions_of_the_type_count(self):
        sessions = [
            _session(_utc(5, 1), _utc(5, 2), 1.0, kind="BOOST"),
            _session(_utc(5, 3), None, 5.0),  # still charging
            _session(_utc(27, 11), _utc(27, 13), 5.0),  # ends after now
            {"start": None, "end": None, "energy_kwh": 1.0, "type": "SMART"},
            _session(_utc(5, 4), _utc(5, 5), None),
            _session(_utc(5, 6), _utc(5, 7), 2.0),
        ]
        assert session_hours(sessions, "SMART", None, now=NOW) == {
            _utc(5, 6): pytest.approx(2.0)
        }
        assert session_hours(sessions, "BOOST", None, now=NOW) == {
            _utc(5, 1): pytest.approx(1.0)
        }

    def test_sessions_already_stored_are_skipped(self):
        sessions = [
            _session(_utc(5, 1), _utc(5, 3), 4.0),  # last hour 02:00, stored
            _session(_utc(5, 4), _utc(5, 5), 3.0),
        ]
        assert session_hours(sessions, "SMART", _utc(5, 2), now=NOW) == {
            _utc(5, 4): pytest.approx(3.0)
        }

    def test_share_before_the_cursor_moves_to_the_first_free_hour(self):
        # Stored up to 02:00; a new session started at 02:30.
        sessions = [_session(_utc(5, 2, 30), _utc(5, 3, 30), 2.0)]
        assert session_hours(sessions, "SMART", _utc(5, 2), now=NOW) == {
            _utc(5, 3): pytest.approx(2.0)
        }

    def test_sessions_in_the_same_hour_add_up(self):
        sessions = [
            _session(_utc(5, 3, 0), _utc(5, 3, 30), 1.0),
            _session(_utc(5, 3, 32), _utc(5, 4, 0), 0.5),
        ]
        assert session_hours(sessions, "SMART", None, now=NOW) == {
            _utc(5, 3): pytest.approx(1.5)
        }

    def test_zero_length_session_books_its_energy(self):
        sessions = [_session(_utc(5, 3, 10), _utc(5, 3, 10), 0.4)]
        assert session_hours(sessions, "SMART", None, now=NOW) == {
            _utc(5, 3): pytest.approx(0.4)
        }


class TestHourlyRows:
    def test_rows_are_cumulative_from_the_cursor(self):
        rows, cursor = hourly_rows(
            {_utc(5, 2): 1.0, _utc(5, 1): 2.0}, Cursor(_utc(5, 0), 10.0)
        )
        assert rows == [
            {"start": _utc(5, 1), "sum": 12.0},
            {"start": _utc(5, 2), "sum": 13.0},
        ]
        assert cursor == Cursor(_utc(5, 2), 13.0)

    def test_hours_up_to_the_cursor_are_not_rewritten(self):
        rows, cursor = hourly_rows({_utc(5, 1): 2.0}, Cursor(_utc(5, 1), 10.0))
        assert rows == []
        assert cursor == Cursor(_utc(5, 1), 10.0)

    def test_multiplier_turns_kwh_into_money(self):
        rows, _ = hourly_rows({_utc(5, 1): 10.0}, Cursor(), multiplier=0.04)
        assert rows == [{"start": _utc(5, 1), "sum": pytest.approx(0.4)}]


def _charging_account(price=0.2, time_of_use=False):
    return {
        "electricity_consumption_charge": price,
        "current_electricity_product": {"isTimeOfUse": time_of_use},
        "devices": [
            {
                "id": "00000000-AB",
                "name": "Trydan",
                "chargingSessions": [
                    _session(_utc(5, 1), _utc(5, 3), 10.0),
                    _session(_utc(5, 4), _utc(5, 5), 1.0, kind="BOOST"),
                ],
            }
        ],
    }


class TestChargingStatistics:
    async def test_smart_boost_and_saving_series(self, recorder):
        with patch.object(stats_mod.dt_util, "utcnow", return_value=NOW):
            await StatisticsImporter(_hass()).async_import_account(
                "A-1", _charging_account(), smart_charging_discount=0.3
            )

        series = {meta["statistic_id"]: (meta, rows) for meta, rows in recorder.added}
        prefix = "octopus_energy_it:a_1_00000000_ab_"
        smart_meta, smart_rows = series[prefix + "smart_charging"]
        assert smart_meta["name"] == "Octopus Trydan smart charging"
        assert smart_meta["unit_of_measurement"] == "kWh"
        assert smart_meta["unit_class"] == "energy"
        assert [row["sum"] for row in smart_rows] == [5.0, 10.0]

        _boost_meta, boost_rows = series[prefix + "boost_charging"]
        assert [row["sum"] for row in boost_rows] == [1.0]

        saving_meta, saving_rows = series[prefix + "smart_charging_saving"]
        assert saving_meta["unit_of_measurement"] == "EUR"
        assert saving_meta["unit_class"] is None
        # 10 kWh x 0.20 EUR/kWh x 30 %
        assert saving_rows[-1]["sum"] == pytest.approx(0.6)

    async def test_no_saving_without_a_single_rate_price(self, recorder):
        with patch.object(stats_mod.dt_util, "utcnow", return_value=NOW):
            await StatisticsImporter(_hass()).async_import_account(
                "A-1",
                _charging_account(time_of_use=True),
                smart_charging_discount=0.3,
            )

        ids = [meta["statistic_id"] for meta, _ in recorder.added]
        assert not any(i.endswith("smart_charging_saving") for i in ids)
        assert any(i.endswith("smart_charging") for i in ids)

    async def test_no_saving_with_a_zero_discount(self, recorder):
        with patch.object(stats_mod.dt_util, "utcnow", return_value=NOW):
            await StatisticsImporter(_hass()).async_import_account(
                "A-1", _charging_account(), smart_charging_discount=0.0
            )

        ids = [meta["statistic_id"] for meta, _ in recorder.added]
        assert not any(i.endswith("smart_charging_saving") for i in ids)

    async def test_second_poll_imports_only_new_sessions(self, recorder):
        importer = StatisticsImporter(_hass())
        account = _charging_account()
        with patch.object(stats_mod.dt_util, "utcnow", return_value=NOW):
            await importer.async_import_account(
                "A-1", account, smart_charging_discount=0.3
            )
            recorder.added.clear()
            await importer.async_import_account(
                "A-1", account, smart_charging_discount=0.3
            )
            assert recorder.added == []

            account["devices"][0]["chargingSessions"].append(
                _session(_utc(6, 1), _utc(6, 2), 4.0)
            )
            await importer.async_import_account(
                "A-1", account, smart_charging_discount=0.3
            )

        series = {meta["statistic_id"]: rows for meta, rows in recorder.added}
        smart = series["octopus_energy_it:a_1_00000000_ab_smart_charging"]
        assert smart == [{"start": _utc(6, 1), "sum": 14.0}]

    async def test_devices_without_sessions_are_ignored(self, recorder):
        account = {"devices": [{"id": "hp", "chargingSessions": []}, {"id": None}]}
        await StatisticsImporter(_hass()).async_import_account(
            "A-1", account, smart_charging_discount=0.3
        )
        assert recorder.added == []
