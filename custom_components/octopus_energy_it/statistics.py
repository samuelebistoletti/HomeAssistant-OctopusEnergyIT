"""Long-term statistics with the real reading dates.

Meter readings reach the API days after the energy was used, so an entity
state changes on the day of the poll, not of the consumption. To give the
Energy dashboard the right days, the cumulative readings are imported as
external statistics: the consumption between two readings is booked at the
start of the period it belongs to (local midnight of the earlier reading).

Imports are incremental and idempotent: only periods after the last stored
statistic are written, continuing from its ``sum``. Home Assistant updates,
rather than duplicates, a statistic written again for the same start.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
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

_NAMES = {
    ELECTRICITY: "Octopus {account} electricity consumption",
    ELECTRICITY_COST: "Octopus {account} electricity cost",
    GAS: "Octopus {account} gas consumption",
}


@dataclass(frozen=True)
class Cursor:
    """Last stored statistic of a series: its start and cumulative sum."""

    start: datetime | None = None
    sum: float = 0.0


def statistic_id(account_number: str, kind: str) -> str:
    """Return the external statistic ID, e.g. ``octopus_energy_it:a_1234_gas_consumption``."""
    account = re.sub(r"[^a-z0-9_]+", "_", account_number.lower()).strip("_")
    return f"{DOMAIN}:{account}_{kind}"


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
        if not rows:
            return 0
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=_NAMES[kind].format(account=account_number),
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

    async def async_import_account(
        self, account_number: str, account: dict[str, Any]
    ) -> None:
        """Import electricity, electricity cost and gas statistics of an account."""
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
