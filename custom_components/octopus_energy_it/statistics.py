"""Long-term statistics with the real reading dates.

Meter readings reach the API days after the energy was used, so an entity
state changes on the day of the poll, not of the consumption. To give the
Energy dashboard the right days, the cumulative readings are imported as
external statistics: the consumption between two readings is booked at the
start of the period it belongs to (local midnight of the earlier reading).

Charging sessions of EVs and chargers are imported the same way, as hourly
rows: smart and boost kWh, and an estimated Intelligent Octopus saving.

Imports are incremental and idempotent: only periods after the last stored
statistic are written, continuing from its ``sum``. Home Assistant updates,
rather than duplicates, a statistic written again for the same start.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
import itertools
import logging
import re
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ELECTRICITY = "electricity_consumption"
ELECTRICITY_COST = "electricity_cost"
GAS = "gas_consumption"
SMART_CHARGING = "smart_charging"
BOOST_CHARGING = "boost_charging"
SMART_CHARGING_SAVING = "smart_charging_saving"

_NAMES = {
    ELECTRICITY: "Octopus {account} electricity consumption",
    ELECTRICITY_COST: "Octopus {account} electricity cost",
    GAS: "Octopus {account} gas consumption",
    SMART_CHARGING: "Octopus {account} smart charging",
    BOOST_CHARGING: "Octopus {account} boost charging",
    SMART_CHARGING_SAVING: "Octopus {account} estimated smart charging saving",
}

# Session types of SmartFlexChargingSession.type
_SESSION_TYPES = {SMART_CHARGING: "SMART", BOOST_CHARGING: "BOOST"}

_HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class Cursor:
    """Last stored statistic of a series: its start and cumulative sum."""

    start: datetime | None = None
    sum: float = 0.0


def _object_id(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")


def statistic_id(account_number: str, kind: str) -> str:
    """Return the external statistic ID, e.g. ``octopus_energy_it:a_1234_gas_consumption``."""
    return f"{DOMAIN}:{_object_id(account_number)}_{kind}"


def device_series(account_number: str, device_id: str) -> str:
    """Return the series prefix of a device, used in place of an account number."""
    return f"{_object_id(account_number)}_{_object_id(device_id)}"


def _floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def session_hours(
    sessions: Iterable[dict[str, Any]],
    session_type: str,
    after: datetime | None,
    *,
    now: datetime | None = None,
) -> dict[datetime, float]:
    """Spread the kWh of finished sessions over the UTC hours they lasted.

    Only sessions of *session_type* that ended (and are not already stored,
    i.e. whose last hour is after *after*) count. Each session's energy is
    split in proportion to its overlap with every hour. The share of a new
    session that falls on or before *after* (already written) moves to the
    first free hour, so no energy is lost.
    """
    now = now or dt_util.utcnow()
    hours: dict[datetime, float] = defaultdict(float)
    for session in sessions:
        if session.get("type") != session_type:
            continue
        start = dt_util.parse_datetime(session.get("start") or "")
        end = dt_util.parse_datetime(session.get("end") or "")
        energy = session.get("energy_kwh")
        if start is None or end is None or energy is None or end > now:
            continue
        start, end = dt_util.as_utc(start), dt_util.as_utc(end)
        last_hour = _floor_hour(max(start, end - timedelta(microseconds=1)))
        if after is not None and last_hour <= after:
            continue  # imported on an earlier run
        first_free = after + _HOUR if after is not None else None
        duration = (end - start).total_seconds()
        hour = _floor_hour(start)
        while hour <= last_hour:
            if duration > 0:
                overlap = min(end, hour + _HOUR) - max(start, hour)
                share = float(energy) * overlap.total_seconds() / duration
            else:
                share = float(energy)
            target = max(hour, first_free) if first_free is not None else hour
            hours[target] += share
            hour += _HOUR
    return dict(hours)


def hourly_rows(
    hours: dict[datetime, float], cursor: Cursor, *, multiplier: float = 1.0
) -> tuple[list[dict[str, Any]], Cursor]:
    """Turn per-hour amounts into cumulative statistic rows after *cursor*."""
    rows: list[dict[str, Any]] = []
    running = cursor.sum
    for hour in sorted(hours):
        if cursor.start is not None and hour <= cursor.start:
            continue
        running += hours[hour] * multiplier
        rows.append({"start": hour, "sum": round(running, 4)})
    last_start = rows[-1]["start"] if rows else cursor.start
    return rows, Cursor(last_start, running)


def period_rows(
    points: Iterable[tuple[datetime, float]],
    cursor: Cursor,
    *,
    multiplier: float = 1.0,
) -> tuple[list[dict[str, Any]], Cursor]:
    """Turn cumulative readings into statistic rows after *cursor*.

    *points* are ``(read_at, register_value)`` pairs. Each consecutive pair
    yields one row booked at the local start of day of the earlier reading,
    with ``sum`` continuing from the cursor. A register that goes backwards
    (meter replaced or reset) contributes zero. *multiplier* converts the
    consumption, e.g. into a cost.
    """
    ordered = sorted(points, key=lambda point: point[0])
    rows: list[dict[str, Any]] = []
    running = cursor.sum
    for (prev_at, prev_value), (_at, value) in itertools.pairwise(ordered):
        start = dt_util.as_utc(dt_util.start_of_local_day(dt_util.as_local(prev_at)))
        if cursor.start is not None and start <= cursor.start:
            continue
        running += max(0.0, value - prev_value) * multiplier
        # The state is the meter register for consumption, the total for cost.
        state = value if multiplier == 1.0 else round(running, 4)
        row = {"start": start, "sum": round(running, 4), "state": state}
        if rows and rows[-1]["start"] == start:
            rows[-1] = row  # several readings on one day: one daily row
        else:
            rows.append(row)
    last_start = rows[-1]["start"] if rows else cursor.start
    return rows, Cursor(last_start, running)


def readings_to_points(
    readings: Iterable[dict[str, Any]], *, date_key: str
) -> list[tuple[datetime, float]]:
    """Return ``(read_at, value)`` pairs from processed reading dicts."""
    points = []
    for reading in readings:
        raw_date, value = reading.get(date_key), reading.get("value")
        if not isinstance(raw_date, str) or value is None:
            continue
        if "T" in raw_date:
            read_at = dt_util.parse_datetime(raw_date)
        else:  # date only (gas readings): local midnight of that day
            parsed_date = dt_util.parse_date(raw_date)
            read_at = dt_util.start_of_local_day(parsed_date) if parsed_date else None
        if read_at is None:
            continue
        points.append((dt_util.as_utc(read_at), float(value)))
    return points


class StatisticsImporter:
    """Import the statistics of one config entry, remembering each cursor."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Start with no cached cursors; they are read from the recorder once."""
        self._hass = hass
        self._cursors: dict[str, Cursor] = {}

    async def _cursor(self, stat_id: str) -> Cursor:
        if (cursor := self._cursors.get(stat_id)) is not None:
            return cursor
        last = await get_instance(self._hass).async_add_executor_job(
            get_last_statistics, self._hass, 1, stat_id, True, {"sum"}
        )
        rows = (last or {}).get(stat_id) or []
        cursor = Cursor()
        if rows:
            row = rows[0]
            cursor = Cursor(dt_util.utc_from_timestamp(row["start"]), row["sum"] or 0.0)
        self._cursors[stat_id] = cursor
        return cursor

    async def async_import(
        self,
        account_number: str,
        kind: str,
        points: list[tuple[datetime, float]],
        *,
        unit: str,
        unit_class: str | None,
        multiplier: float = 1.0,
    ) -> int:
        """Import new rows of one series; return how many were written."""
        stat_id = statistic_id(account_number, kind)
        rows, cursor = period_rows(
            points, await self._cursor(stat_id), multiplier=multiplier
        )
        return self._write(
            stat_id,
            _NAMES[kind].format(account=account_number),
            rows,
            cursor,
            unit=unit,
            unit_class=unit_class,
        )

    def _write(
        self,
        stat_id: str,
        name: str,
        rows: list[dict[str, Any]],
        cursor: Cursor,
        *,
        unit: str,
        unit_class: str | None,
    ) -> int:
        if not rows:
            return 0
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=name,
            source=DOMAIN,
            statistic_id=stat_id,
            unit_class=unit_class,
            unit_of_measurement=unit,
        )
        async_add_external_statistics(
            self._hass, metadata, [StatisticData(**row) for row in rows]
        )
        self._cursors[stat_id] = cursor
        _LOGGER.debug("Imported %d rows into %s", len(rows), stat_id)
        return len(rows)

    async def async_import_charging(
        self,
        account_number: str,
        device: dict[str, Any],
        *,
        price: float | None,
        discount: float,
    ) -> None:
        """Import smart and boost kWh of a device and the estimated saving.

        The saving is smart kWh x energy price x *discount* (a fraction): an
        estimate, since Octopus bills the lower of the device and meter kWh.
        It needs a single-rate *price*; no saving is imported without one.
        """
        sessions = device.get("chargingSessions") or []
        if not sessions:
            return
        series = device_series(account_number, device["id"])
        label = device.get("name") or account_number
        for kind, session_type in _SESSION_TYPES.items():
            stat_id = statistic_id(series, kind)
            cursor = await self._cursor(stat_id)
            rows, cursor = hourly_rows(
                session_hours(sessions, session_type, cursor.start), cursor
            )
            self._write(
                stat_id,
                _NAMES[kind].format(account=label),
                rows,
                cursor,
                unit="kWh",
                unit_class="energy",
            )

        if price is None or discount <= 0:
            return
        stat_id = statistic_id(series, SMART_CHARGING_SAVING)
        cursor = await self._cursor(stat_id)
        rows, cursor = hourly_rows(
            session_hours(sessions, "SMART", cursor.start),
            cursor,
            multiplier=price * discount,
        )
        self._write(
            stat_id,
            _NAMES[SMART_CHARGING_SAVING].format(account=label),
            rows,
            cursor,
            unit=self._hass.config.currency,
            unit_class=None,
        )

    async def async_import_account(
        self,
        account_number: str,
        account: dict[str, Any],
        *,
        smart_charging_discount: float = 0.0,
    ) -> None:
        """Import the electricity, gas and charging statistics of an account.

        *smart_charging_discount* is the Intelligent Octopus discount as a
        fraction (0.3 for 30 %).
        """
        electricity = readings_to_points(
            account.get("electricity_readings") or [], date_key="readAt"
        )
        if electricity:
            await self.async_import(
                account_number,
                ELECTRICITY,
                electricity,
                unit="kWh",
                unit_class="energy",
            )
            price = _flat_electricity_price(account)
            if price is not None:
                await self.async_import(
                    account_number,
                    ELECTRICITY_COST,
                    electricity,
                    unit=self._hass.config.currency,
                    unit_class=None,
                    multiplier=price,
                )

        gas = readings_to_points(
            account.get("gas_readings") or [], date_key="readingDate"
        )
        if gas:
            await self.async_import(
                account_number, GAS, gas, unit="m³", unit_class="volume"
            )

        price = _flat_electricity_price(account)
        for device in account.get("devices") or []:
            if isinstance(device, dict) and device.get("id"):
                await self.async_import_charging(
                    account_number,
                    device,
                    price=price,
                    discount=smart_charging_discount,
                )


def _flat_electricity_price(account: dict[str, Any]) -> float | None:
    """Return the €/kWh price of a single-rate tariff, else None.

    Daily readings cannot be split by time band, so no cost is imported for
    time-of-use (F1/F2/F3) tariffs rather than an inaccurate one.
    """
    product = account.get("current_electricity_product") or {}
    if product.get("isTimeOfUse"):
        return None
    price = account.get("electricity_consumption_charge")
    try:
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None
