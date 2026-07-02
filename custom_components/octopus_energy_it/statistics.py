"""Import electricity readings into Home Assistant long-term statistics.

The Octopus Energy IT API exposes the cumulative meter register value
together with the real reading timestamp (``readAt``), but this timestamp
typically lags behind "now" by a few days (the distributor publishes data
with a delay).

The ``electricity_last_reading`` sensor only carries this real date as an
attribute (``period_end``); the sensor *state* itself is written at coordinator
refresh time. Home Assistant's recorder always timestamps entity-based
long-term statistics with the moment the state changed, not with any
attribute on it — so the Energy dashboard would otherwise show the
consumption jump on the day the integration polled the API, not on the day
the energy was actually used.

This module bypasses that limitation by importing the cumulative reading
directly as *external statistics* (not tied to any entity), as a single
daily point placed at local midnight of the day the reading actually
belongs to:

- a consumption statistic, in kWh
- a cost statistic, in EUR (consumption delta x current base price)

Users can then select these statistics as electricity consumption / cost
source in Impostazioni -> Dashboard Energia -> Configura connessione alla
rete elettrica, instead of the entity-based sensors (which don't carry the
real reading date and can't be combined with "Utilizza un'entità con il
prezzo corrente" since they're not tied to an entity).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONSUMPTION_STAT_NAME_TEMPLATE = "Octopus {account} - Consumo elettrico (data reale)"
COST_STAT_NAME_TEMPLATE = "Octopus {account} - Costo elettrico (data reale)"

_INVALID_STAT_ID_CHARS = re.compile(r"[^a-z0-9_]+")


def _sanitize_account(account_number: str) -> str:
    """Sanitize an account number for use in a statistic_id.

    statistic_id must only contain lowercase letters, digits and
    underscores after the domain prefix (e.g. account numbers like
    'A-XXXXXX' must be sanitized).
    """
    return _INVALID_STAT_ID_CHARS.sub("_", account_number.lower()).strip("_")


def _consumption_statistic_id(account_number: str) -> str:
    return f"{DOMAIN}:{_sanitize_account(account_number)}_electricity_consumption"


def _cost_statistic_id(account_number: str) -> str:
    return f"{DOMAIN}:{_sanitize_account(account_number)}_electricity_cost"


def _select_current_product(
    products: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Return the most recent product that is currently valid.

    Mirrors the logic used by OctopusElectricityPriceSensor in sensor.py.
    """
    if not products:
        return None

    now_iso = datetime.now(UTC).isoformat()
    valid_products = [
        product
        for product in products
        if isinstance(product, dict)
        and product.get("validFrom")
        and product["validFrom"] <= now_iso
        and (not product.get("validTo") or now_iso <= product["validTo"])
    ]
    if not valid_products:
        return None

    valid_products.sort(key=lambda item: item.get("validFrom", ""), reverse=True)
    return valid_products[0]


def _current_electricity_price(account_data: dict[str, Any] | None) -> float | None:
    """Return the current base electricity price (€/kWh) for an account."""
    if not account_data:
        return None

    product = account_data.get(
        "current_electricity_product"
    ) or _select_current_product(account_data.get("products") or [])
    if not product:
        return None

    pricing = product.get("pricing") or {}
    base = pricing.get("base")
    if base is None:
        return None
    try:
        return float(str(base).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _target_local_date(reading: dict[str, Any]) -> date | None:
    """Return the local calendar day a daily reading's consumption belongs to.

    Daily readings are register snapshots taken at local midnight: the
    consumption between two consecutive snapshots (period_start ->
    period_end) belongs entirely to the day that started at
    period_start. We prefer period_start when available since it is
    unambiguous; otherwise we fall back to period_end, nudged back a day
    when it lands exactly on local midnight (which represents the END of
    the correct day, not the start of the next one).
    """
    start_raw = reading.get("start")
    if start_raw:
        start_dt = dt_util.parse_datetime(start_raw)
        if start_dt is not None:
            return dt_util.as_local(start_dt).date()

    end_raw = reading.get("end")
    if not end_raw:
        return None
    end_dt = dt_util.parse_datetime(end_raw)
    if end_dt is None:
        return None
    local_end = dt_util.as_local(end_dt)
    if local_end.hour == 0 and local_end.minute == 0:
        local_end = local_end - timedelta(hours=1)
    return local_end.date()


def _day_point(target_date: date, value: float) -> Any:
    """Return the UTC datetime for the single daily statistic point.

    A single point at local midnight of the target day. HA's long-term
    statistics have hourly granularity (there's no literal "00:00-23:59"
    block), but a point placed at local midnight is correctly attributed
    to that whole day in the daily/weekly/monthly Energy dashboard views,
    which is what matters for most users.
    """
    return dt_util.as_utc(dt_util.start_of_local_day(target_date))


def _get_recorder_imports():
    """Import recorder helpers, returning None if recorder isn't available."""
    try:
        from homeassistant.components.recorder.models import (
            StatisticData,
            StatisticMetaData,
        )
        from homeassistant.components.recorder.statistics import (
            async_add_external_statistics,
        )
    except ImportError:
        return None
    return StatisticData, StatisticMetaData, async_add_external_statistics


def _build_metadata(
    statistic_id: str,
    name: str,
    unit_of_measurement: str,
    unit_class: str,
    statistic_meta_data_cls,
):
    """Build StatisticMetaData, handling both old and new HA core APIs."""
    try:
        from homeassistant.components.recorder.models import StatisticMeanType

        return statistic_meta_data_cls(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=name,
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=unit_of_measurement,
            unit_class=unit_class,
        )
    except ImportError:
        # Older HA core versions (pre mean_type) still expect has_mean.
        return statistic_meta_data_cls(
            has_mean=False,
            has_sum=True,
            name=name,
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=unit_of_measurement,
            unit_class=unit_class,
        )


async def _async_get_last_stat(
    hass: HomeAssistant, statistic_id: str
) -> tuple[float, date | None]:
    """Return (last_sum, last_date) already stored for a statistic.

    Used both to resume the running cumulative total after a Home Assistant
    restart and to deduplicate imports: if the last stored point already
    covers today's reading date, there is nothing to import.
    Returns (0.0, None) when the statistic has no data yet.
    """
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import (
            get_last_statistics,
        )
    except ImportError:
        return 0.0, None

    def _query():
        return get_last_statistics(hass, 1, statistic_id, True, {"sum", "start"})

    try:
        result = await get_instance(hass).async_add_executor_job(_query)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not fetch last statistics for %s", statistic_id)
        return 0.0, None

    rows = result.get(statistic_id) if result else None
    if not rows:
        return 0.0, None

    row = rows[0]

    last_sum = row.get("sum")
    try:
        cumulative = float(last_sum) if last_sum is not None else 0.0
    except (TypeError, ValueError):
        cumulative = 0.0

    last_start = row.get("start")
    last_date: date | None = None
    if last_start is not None:
        try:
            last_dt = dt_util.utc_from_timestamp(float(last_start))
            last_date = dt_util.as_local(last_dt).date()
        except (TypeError, ValueError):
            last_date = None

    return cumulative, last_date


async def async_import_electricity_statistics(
    hass: HomeAssistant,
    account_number: str,
    reading: dict[str, Any] | None,
) -> None:
    """Import the latest daily electricity reading using its real date.

    Written as a single point at local midnight of the day the reading
    belongs to, so it's attributed to the correct whole day in the
    daily/weekly/monthly Energy dashboard views.

    The statistic's cumulative ``sum`` is kept relative (starting at 0 on
    the very first import for a fresh setup) rather than using the meter's
    absolute register value: writing the raw register value would make
    the Energy dashboard treat the *entire* historical meter reading as a
    single day's consumption the first time the statistic is created
    (since there is no prior point to diff against). The running total is
    bootstrapped from the last value already stored in the recorder, so it
    survives Home Assistant restarts without resetting.

    Safe to call on every coordinator refresh: it deduplicates against the
    last imported day, so repeated calls for an unchanged reading are a
    no-op.
    """
    if not reading:
        return

    delta_kwh = reading.get("value")
    if delta_kwh is None:
        return
    try:
        delta_kwh = float(delta_kwh)
    except (TypeError, ValueError):
        return

    target_date = _target_local_date(reading)
    if target_date is None:
        _LOGGER.debug(
            "Could not determine reading date for account %s", account_number
        )
        return

    statistic_id = _consumption_statistic_id(account_number)

    domain_data = hass.data.setdefault(DOMAIN, {})
    running_sums = domain_data.setdefault("_imported_consumption_sums", {})

    # Bootstrap from recorder on first call after a restart, and use the
    # stored date for deduplication — not an in-memory flag — so repeated
    # coordinator refreshes within the same day never double-count.
    if statistic_id not in running_sums:
        last_sum, last_date = await _async_get_last_stat(hass, statistic_id)
        running_sums[statistic_id] = (last_sum, last_date)

    start_value, last_imported_date = running_sums[statistic_id]
    if last_imported_date == target_date:
        return

    end_value = start_value + delta_kwh

    recorder_imports = _get_recorder_imports()
    if recorder_imports is None:
        _LOGGER.debug("Recorder not available, skipping statistics import")
        return
    statistic_data_cls, statistic_meta_data_cls, async_add_external_statistics = (
        recorder_imports
    )

    metadata = _build_metadata(
        statistic_id,
        CONSUMPTION_STAT_NAME_TEMPLATE.format(account=account_number),
        "kWh",
        "energy",
        statistic_meta_data_cls,
    )
    stats = [
        statistic_data_cls(
            start=_day_point(target_date, end_value),
            sum=round(end_value, 4),
            state=round(end_value, 4),
        )
    ]

    try:
        async_add_external_statistics(hass, metadata, stats)
    except Exception:  # noqa: BLE001 - never let this break the coordinator
        _LOGGER.exception(
            "Failed to import electricity statistics for account %s",
            account_number,
        )
        return

    running_sums[statistic_id] = (end_value, target_date)
    _LOGGER.debug(
        "Imported electricity statistic '%s' for %s "
        "(%.3f -> %.3f kWh)",
        statistic_id,
        target_date,
        start_value,
        end_value,
    )


async def async_import_electricity_cost_statistics(
    hass: HomeAssistant,
    account_number: str,
    reading: dict[str, Any] | None,
    account_data: dict[str, Any] | None,
) -> None:
    """Import the cost of the latest daily electricity reading as EUR.

    Cost is computed as (consumption delta in kWh) x (current base price
    in €/kWh), written as a single point at local midnight like the
    statistic. Since the API doesn't return a cumulative monetary total,
    the running total is bootstrapped from the last value already stored
    in the recorder (so it survives Home Assistant restarts) and kept in
    hass.data afterwards to avoid querying the recorder on every refresh.

    Safe to call on every coordinator refresh: it deduplicates against the
    last imported day, so repeated calls for an unchanged reading are a
    no-op.
    """
    if not reading:
        return

    delta_kwh = reading.get("value")
    if delta_kwh is None:
        return
    try:
        delta_kwh = float(delta_kwh)
    except (TypeError, ValueError):
        return

    price = _current_electricity_price(account_data)
    if price is None:
        _LOGGER.debug(
            "No current electricity price available for account %s, "
            "skipping cost statistics import",
            account_number,
        )
        return

    target_date = _target_local_date(reading)
    if target_date is None:
        return

    cost_statistic_id = _cost_statistic_id(account_number)

    domain_data = hass.data.setdefault(DOMAIN, {})
    running_sums = domain_data.setdefault("_imported_cost_sums", {})

    if cost_statistic_id not in running_sums:
        last_sum, last_date = await _async_get_last_stat(hass, cost_statistic_id)
        running_sums[cost_statistic_id] = (last_sum, last_date)

    previous_cumulative, last_imported_date = running_sums[cost_statistic_id]
    if last_imported_date == target_date:
        return

    new_cumulative = previous_cumulative + (delta_kwh * price)

    recorder_imports = _get_recorder_imports()
    if recorder_imports is None:
        _LOGGER.debug("Recorder not available, skipping cost statistics import")
        return
    statistic_data_cls, statistic_meta_data_cls, async_add_external_statistics = (
        recorder_imports
    )

    metadata = _build_metadata(
        cost_statistic_id,
        COST_STAT_NAME_TEMPLATE.format(account=account_number),
        "EUR",
        "monetary",
        statistic_meta_data_cls,
    )
    stats = [
        statistic_data_cls(
            start=_day_point(target_date, new_cumulative),
            sum=round(new_cumulative, 4),
            state=round(new_cumulative, 4),
        )
    ]

    try:
        async_add_external_statistics(hass, metadata, stats)
    except Exception:  # noqa: BLE001 - never let this break the coordinator
        _LOGGER.exception(
            "Failed to import electricity cost statistics for account %s",
            account_number,
        )
        return

    running_sums[cost_statistic_id] = (new_cumulative, target_date)
    _LOGGER.debug(
        "Imported electricity cost statistic '%s' for %s "
        "(+%.4f EUR, cumulative %.4f -> %.4f EUR, price=%.5f €/kWh)",
        cost_statistic_id,
        target_date,
        delta_kwh * price,
        previous_cumulative,
        new_cumulative,
        price,
    )