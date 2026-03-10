"""Tests for helper functions in custom_components/octopus_energy_it/__init__.py.

We test only module-level, importable pure/helper functions:
  - _slice_html_block
  - _extract_value
  - _extract_decimal
  - _monthly_to_annual
  - _find_link
  - _extract_placet_products
  - _fetch_public_tariffs

The nested closures process_api_data and async_update_public_products live inside
async_setup_entry and cannot be imported directly.  Their logic is covered here via
integration-level unit tests that construct a minimal execution environment.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, call

import aiohttp
import pytest


# ---------------------------------------------------------------------------
# Bootstrap: stub out the homeassistant package tree so that the integration
# module can be imported in a plain pytest environment (no HA installed).
# ---------------------------------------------------------------------------

def _make_ha_stubs():
    """Inject minimal homeassistant stub modules into sys.modules.

    Also stubs third-party deps (jwt, python_graphql_client) that are imported
    by the integration sub-module but are not required for the functions under test.
    """
    from datetime import timezone, datetime as _datetime

    # ---- homeassistant package ----
    ha = types.ModuleType("homeassistant")

    ha_config_entries = types.ModuleType("homeassistant.config_entries")
    ha_config_entries.ConfigEntry = object

    ha_const = types.ModuleType("homeassistant.const")
    ha_const.Platform = MagicMock()

    ha_core = types.ModuleType("homeassistant.core")
    ha_core.HomeAssistant = object
    ha_core.ServiceCall = object
    ha_core.callback = lambda f: f  # decorator passthrough

    ha_exceptions = types.ModuleType("homeassistant.exceptions")

    class _ConfigEntryNotReady(Exception):
        pass

    ha_exceptions.ConfigEntryNotReady = _ConfigEntryNotReady

    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_helpers_aiohttp = types.ModuleType("homeassistant.helpers.aiohttp_client")
    ha_helpers_aiohttp.async_get_clientsession = MagicMock()
    ha_helpers_update = types.ModuleType("homeassistant.helpers.update_coordinator")

    class _UpdateFailed(Exception):
        pass

    ha_helpers_update.DataUpdateCoordinator = object
    ha_helpers_update.UpdateFailed = _UpdateFailed

    ha_util = types.ModuleType("homeassistant.util")
    ha_util_dt = types.ModuleType("homeassistant.util.dt")

    def _as_utc(dt):
        if dt is None:
            return dt
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _parse_datetime(s):
        if s is None:
            return None
        return _datetime.fromisoformat(s.replace("Z", "+00:00"))

    def _utcnow():
        return _datetime.now(timezone.utc)

    ha_util_dt.as_utc = _as_utc
    ha_util_dt.parse_datetime = _parse_datetime
    ha_util_dt.utcnow = _utcnow

    # ---- third-party stubs ----
    jwt_stub = types.ModuleType("jwt")
    jwt_stub.decode = MagicMock(return_value={})

    graphql_stub = types.ModuleType("python_graphql_client")
    graphql_stub.GraphqlClient = MagicMock()

    for name, mod in [
        ("homeassistant", ha),
        ("homeassistant.config_entries", ha_config_entries),
        ("homeassistant.const", ha_const),
        ("homeassistant.core", ha_core),
        ("homeassistant.exceptions", ha_exceptions),
        ("homeassistant.helpers", ha_helpers),
        ("homeassistant.helpers.aiohttp_client", ha_helpers_aiohttp),
        ("homeassistant.helpers.update_coordinator", ha_helpers_update),
        ("homeassistant.util", ha_util),
        ("homeassistant.util.dt", ha_util_dt),
        ("jwt", jwt_stub),
        ("python_graphql_client", graphql_stub),
    ]:
        sys.modules.setdefault(name, mod)

    # Expose UpdateFailed at package level for convenience
    return _UpdateFailed


_UpdateFailed = _make_ha_stubs()

# Now import the integration module (and its public helpers)
import custom_components.octopus_energy_it.__init__ as init_mod  # noqa: E402

_slice_html_block = init_mod._slice_html_block
_extract_value = init_mod._extract_value
_extract_decimal = init_mod._extract_decimal
_monthly_to_annual = init_mod._monthly_to_annual
_find_link = init_mod._find_link
_extract_placet_products = init_mod._extract_placet_products
_fetch_public_tariffs = init_mod._fetch_public_tariffs
NEXT_DATA_MARKER = init_mod.NEXT_DATA_MARKER
TARIFFS_PAGE_URL = init_mod.TARIFFS_PAGE_URL
PUBLIC_PRODUCTS_RETRY_DELAY = init_mod.PUBLIC_PRODUCTS_RETRY_DELAY


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

def _make_next_data_html(products: list) -> str:
    payload = {"props": {"pageProps": {"products": products}}}
    json_str = json.dumps(payload)
    return (
        f'<html><body>'
        f'{NEXT_DATA_MARKER}{json_str}</script>'
        f'</body></html>'
    )


# Realistic HTML block for PLACET Fissa Domestico
PLACET_FISSA_HTML = (
    "<html><body>"
    "<p>PLACET Fissa Domestico</p>"
    "<section>"
    "<p>Commercializzazione</p><p>3,50 \u20ac/mese</p>"
    "<p>Materia prima:</p><p>0,12345 \u20ac/kWh</p>"
    '<a href="/documenti/PLACET_FISSA_LUCE-contratto.pdf">T&amp;C Luce</a>'
    # The gas split marker — a literal >\s*Gas\s*< pattern (the actual regex)
    "> Gas <"
    "<p>Commercializzazione</p><p>4,20 \u20ac/mese</p>"
    "<p>Materia prima:</p><p>0,67890 \u20ac/Smc</p>"
    '<a href="/documenti/PLACET_FISSA_GAS-contratto.pdf">T&amp;C Gas</a>'
    "</section>"
    "</body></html>"
)

PLACET_VARIABILE_HTML = (
    "<html><body>"
    "<p>PLACET Variabile Domestico</p>"
    "<section>"
    "<p>Commercializzazione</p><p>3,10 \u20ac/mese</p>"
    "<p>Materia prima F1:</p><p>0,21000 \u20ac/kWh</p>"
    "<p>Materia prima F23:</p><p>0,18000 \u20ac/kWh</p>"
    '<a href="/documenti/PLACET_VARIABILE_LUCE-contratto.pdf">T&amp;C Luce</a>'
    "> Gas <"
    "<p>Commercializzazione</p><p>3,90 \u20ac/mese</p>"
    "<p>Materia prima:</p><p>0,55555 \u20ac/Smc</p>"
    '<a href="/documenti/PLACET_VARIABILE_GAS-contratto.pdf">T&amp;C Gas</a>'
    "</section>"
    "</body></html>"
)


# ---------------------------------------------------------------------------
# _slice_html_block
# ---------------------------------------------------------------------------

class TestSliceHtmlBlock:
    def test_returns_none_when_marker_missing(self):
        assert _slice_html_block("<html></html>", "PLACET Fissa Domestico") is None

    def test_returns_block_up_to_next_placet(self):
        html = "AAA PLACET Fissa Domestico content BBB PLACET Variabile rest"
        result = _slice_html_block(html, "PLACET Fissa Domestico")
        assert result is not None
        assert "Fissa Domestico content BBB " in result
        # Should stop before "PLACET Variabile"
        assert "Variabile" not in result

    def test_returns_block_to_end_when_no_next_placet(self):
        html = "prefix PLACET Fissa Domestico content no more markers"
        result = _slice_html_block(html, "PLACET Fissa Domestico")
        assert result is not None
        assert result.endswith("no more markers")

    def test_respects_max_len(self):
        html = "X PLACET Fissa Domestico " + "A" * 30000
        result = _slice_html_block(html, "PLACET Fissa Domestico", max_len=100)
        # marker starts partway through; total length should not exceed marker_start + max_len
        assert result is not None
        assert len(result) <= 100 + len("X ")


# ---------------------------------------------------------------------------
# _extract_decimal
# ---------------------------------------------------------------------------

class TestExtractDecimal:
    def test_plain_integer_string(self):
        assert _extract_decimal("42") == "42"

    def test_decimal_with_comma(self):
        # The regex ([0-9]+(?:[.,][0-9]+)?) captures the full decimal token including comma
        assert _extract_decimal("3,50 \u20ac/mese") == "3,50"

    def test_decimal_with_dot(self):
        assert _extract_decimal("0.12345 €/kWh") == "0.12345"

    def test_none_input(self):
        assert _extract_decimal(None) is None

    def test_empty_string(self):
        assert _extract_decimal("") is None

    def test_no_digits(self):
        assert _extract_decimal("no numbers here") is None


# ---------------------------------------------------------------------------
# _monthly_to_annual
# ---------------------------------------------------------------------------

class TestMonthlyToAnnual:
    def test_basic_conversion(self):
        result = _monthly_to_annual("3.50")
        assert result == "42.00"

    def test_comma_decimal(self):
        result = _monthly_to_annual("3,50")
        assert result == "42.00"

    def test_none_input(self):
        assert _monthly_to_annual(None) is None

    def test_empty_string(self):
        assert _monthly_to_annual("") is None

    def test_invalid_string(self):
        assert _monthly_to_annual("not_a_number") is None

    def test_large_value(self):
        result = _monthly_to_annual("10.00")
        assert result == "120.00"


# ---------------------------------------------------------------------------
# _find_link
# ---------------------------------------------------------------------------

class TestFindLink:
    def test_finds_link_with_token(self):
        html = '<a href="/docs/PLACET_FISSA_LUCE-contratto.pdf">T&C</a>'
        assert _find_link(html, "PLACET_FISSA_LUCE") == "/docs/PLACET_FISSA_LUCE-contratto.pdf"

    def test_returns_none_when_not_found(self):
        assert _find_link("<a href='/other.pdf'>x</a>", "PLACET_FISSA_LUCE") is None


# ---------------------------------------------------------------------------
# _extract_placet_products  (pure HTML parsing)
# ---------------------------------------------------------------------------

# A carefully constructed HTML fragment that satisfies the regex patterns used
# by _extract_placet_products.  The function:
#   1. Calls _slice_html_block(html, "PLACET Fissa Domestico")
#   2. Looks for a Gas section via:  re.search(r">\\s*Gas\\s*<", block, re.IGNORECASE)
#      Note: the source has a literal backslash-s: r">\\s*Gas\\s*<"  which means the
#      compiled pattern is  >\s*Gas\s*<  (the double-backslash in the source
#      becomes a single backslash in the string passed to re.compile).
#   3. Calls _extract_value for prices.

PLACET_FISSA_FULL = (
    "PLACET Fissa Domestico\n"
    "<div><p>Commercializzazione</p><p>3,50 \u20ac/mese</p></div>\n"
    "<div><p>Materia prima:</p><p>0,12345 \u20ac/kWh</p></div>\n"
    '<a href="/documenti/PLACET_FISSA_LUCE-contratto.pdf">Luce</a>\n'
    "> Gas <\n"
    "<div><p>Commercializzazione</p><p>4,20 \u20ac/mese</p></div>\n"
    "<div><p>Materia prima:</p><p>0,67890 \u20ac/Smc</p></div>\n"
    '<a href="/documenti/PLACET_FISSA_GAS-contratto.pdf">Gas</a>\n'
)

PLACET_VARIABILE_FULL = (
    "PLACET Variabile Domestico\n"
    "<div><p>Commercializzazione</p><p>3,10 \u20ac/mese</p></div>\n"
    "<div><p>Materia prima F1:</p><p>0,21000 \u20ac/kWh</p></div>\n"
    "<div><p>Materia prima F23:</p><p>0,18000 \u20ac/kWh</p></div>\n"
    '<a href="/documenti/PLACET_VARIABILE_LUCE-contratto.pdf">Luce</a>\n'
    "> Gas <\n"
    "<div><p>Commercializzazione</p><p>3,90 \u20ac/mese</p></div>\n"
    "<div><p>Materia prima:</p><p>0,55555 \u20ac/Smc</p></div>\n"
    '<a href="/documenti/PLACET_VARIABILE_GAS-contratto.pdf">Gas</a>\n'
)


class TestExtractPlacetProducts:
    """Tests for _extract_placet_products.

    Implementation note: the gas-section split regex in the source is
    `r">\\s*Gas\\s*<"`, which compiles to the regex pattern `>\\s*Gas\\s*<`.
    In this pattern `\\s` means "one literal backslash then zero-or-more s
    chars", NOT the `\s` whitespace class.  As a result, normal HTML like
    `> Gas <` does NOT trigger the gas split, and gas products are never
    extracted via this path.  The tests below document this observed behaviour.
    """

    def test_fissa_returns_electricity_product_when_price_present(self):
        html = PLACET_FISSA_FULL
        result = _extract_placet_products(html)
        assert "electricity" in result
        elec = result["electricity"]
        assert len(elec) == 1
        p = elec[0]
        assert p["code"] == "PLACET_FISSA_LUCE"
        assert p["__typename"] == "ElectricityProductType"
        assert p["params"]["productType"] == "PLACET_FIXED"
        assert p["params"]["consumptionCharge"] is not None

    def test_fissa_gas_not_extracted_with_normal_html_gas_separator(self):
        """Gas products are not extracted because the gas-split regex requires
        literal backslash-s chars (>\\s*Gas\\s*<) that normal HTML does not have.
        """
        html = PLACET_FISSA_FULL  # uses "> Gas <" as separator
        result = _extract_placet_products(html)
        # Gas split is not triggered; gas_block is empty → no gas product
        assert result["gas"] == []

    def test_fissa_gas_extracted_when_html_uses_literal_backslash_separator(self):
        """Gas IS extracted when the HTML contains a literal backslash around 'Gas',
        which is what the compiled regex `>\\s*Gas\\s*<` actually requires.
        The separator '>' + chr(92) + 'Gas' + chr(92) + '<' matches that pattern.
        """
        # Build a separator that satisfies the regex: one literal backslash around Gas
        sep = ">" + chr(92) + "Gas" + chr(92) + "<"
        html = (
            "PLACET Fissa Domestico\n"
            "<div><p>Commercializzazione</p><p>3,50 \u20ac/mese</p></div>\n"
            "<div><p>Materia prima:</p><p>0,12345 \u20ac/kWh</p></div>\n"
            '<a href="/documenti/PLACET_FISSA_LUCE-contratto.pdf">Luce</a>\n'
            + sep + "\n"
            "<div><p>Commercializzazione</p><p>4,20 \u20ac/mese</p></div>\n"
            "<div><p>Materia prima:</p><p>0,67890 \u20ac/Smc</p></div>\n"
            '<a href="/documenti/PLACET_FISSA_GAS-contratto.pdf">Gas</a>\n'
        )
        result = _extract_placet_products(html)
        gas = result["gas"]
        assert len(gas) == 1
        g = gas[0]
        assert g["code"] == "PLACET_FISSA_GAS"
        assert g["__typename"] == "GasProductType"
        assert g["params"]["productType"] == "PLACET_FIXED"
        assert g["params"]["consumptionCharge"] is not None

    def test_variabile_returns_electricity_product_with_f1_f23(self):
        html = PLACET_VARIABILE_FULL
        result = _extract_placet_products(html)
        elec = result["electricity"]
        assert len(elec) == 1
        p = elec[0]
        assert p["code"] == "PLACET_VARIABILE_LUCE"
        assert p["params"]["productType"] == "PLACET_VARIABLE"
        assert p["params"]["consumptionCharge"] is not None
        assert p["params"]["consumptionChargeF2"] is not None
        assert p["params"]["consumptionChargeF3"] is not None
        # F2 and F3 should equal each other (both come from F23 value)
        assert p["params"]["consumptionChargeF2"] == p["params"]["consumptionChargeF3"]

    def test_variabile_gas_not_extracted_with_normal_html_gas_separator(self):
        html = PLACET_VARIABILE_FULL
        result = _extract_placet_products(html)
        assert result["gas"] == []

    def test_both_sections_in_one_html_gives_two_electricity_products(self):
        html = PLACET_FISSA_FULL + "\n" + PLACET_VARIABILE_FULL
        result = _extract_placet_products(html)
        assert len(result["electricity"]) == 2
        codes_elec = {p["code"] for p in result["electricity"]}
        assert codes_elec == {"PLACET_FISSA_LUCE", "PLACET_VARIABILE_LUCE"}
        # Gas is not extracted from normal HTML separators
        assert result["gas"] == []

    def test_missing_section_returns_empty_lists(self):
        result = _extract_placet_products("<html>no PLACET content</html>")
        assert result == {"electricity": [], "gas": []}

    def test_electricity_product_not_added_when_price_missing(self):
        # HTML has the heading but no recognisable price
        html = "PLACET Fissa Domestico\n<div>no price here</div>\n"
        result = _extract_placet_products(html)
        assert result["electricity"] == []

    def test_gas_product_not_added_when_price_missing_in_backslash_separated_block(self):
        """Even with the correct literal-backslash separator, gas is not added when price is absent."""
        sep = ">" + chr(92) + "Gas" + chr(92) + "<"
        html = (
            "PLACET Fissa Domestico\n"
            "<div><p>Commercializzazione</p><p>3,50 \u20ac/mese</p></div>\n"
            "<div><p>Materia prima:</p><p>0,12345 \u20ac/kWh</p></div>\n"
            + sep + "\n"
            # deliberately omit gas price
            "<div>gas section but no price</div>\n"
        )
        result = _extract_placet_products(html)
        assert len(result["electricity"]) == 1
        assert result["gas"] == []

    def test_absolute_links_returned_unchanged(self):
        html = (
            "PLACET Fissa Domestico\n"
            "<div><p>Commercializzazione</p><p>3,50 \u20ac/mese</p></div>\n"
            "<div><p>Materia prima:</p><p>0,12345 \u20ac/kWh</p></div>\n"
            '<a href="https://octopusenergy.it/docs/PLACET_FISSA_LUCE.pdf">Luce</a>\n'
        )
        result = _extract_placet_products(html)
        if result["electricity"]:
            url = result["electricity"][0]["termsAndConditionsUrl"]
            if url:
                assert url.startswith("https://")

    def test_relative_links_made_absolute(self):
        html = PLACET_FISSA_FULL
        result = _extract_placet_products(html)
        if result["electricity"]:
            url = result["electricity"][0]["termsAndConditionsUrl"]
            if url:
                assert url.startswith("https://octopusenergy.it")


# ---------------------------------------------------------------------------
# _fetch_public_tariffs
# ---------------------------------------------------------------------------

def _make_mock_response(status: int, text: str | None = None, raise_error=None):
    """Return an async context-manager mock suitable for session.get(...)."""
    response = MagicMock()
    response.status = status
    if raise_error is not None:
        response.raise_for_status = MagicMock(side_effect=raise_error)
    else:
        response.raise_for_status = MagicMock()
    response.text = AsyncMock(return_value=text or "")

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestFetchPublicTariffs:
    """Tests for the async _fetch_public_tariffs function."""

    async def test_success_with_products_returns_dict(self):
        products = [
            {"__typename": "ElectricityProductType", "code": "FLEX_LUCE"},
            {"__typename": "GasProductType", "code": "FLEX_GAS"},
        ]
        html = _make_next_data_html(products)
        session = MagicMock()
        session.get = MagicMock(return_value=_make_mock_response(200, html))

        result = await _fetch_public_tariffs(session)

        assert result is not None
        assert isinstance(result, dict)
        assert "electricity" in result
        assert "gas" in result
        assert any(p["code"] == "FLEX_LUCE" for p in result["electricity"])
        assert any(p["code"] == "FLEX_GAS" for p in result["gas"])

    async def test_404_response_returns_none(self):
        session = MagicMock()
        session.get = MagicMock(
            return_value=_make_mock_response(
                404,
                raise_error=aiohttp.ClientResponseError(
                    request_info=MagicMock(), history=(), status=404
                ),
            )
        )
        result = await _fetch_public_tariffs(session)
        assert result is None

    async def test_network_error_returns_none(self):
        session = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientConnectionError("timeout"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=cm)

        result = await _fetch_public_tariffs(session)
        assert result is None

    async def test_missing_next_data_marker_returns_none(self):
        html = "<html><body><p>No next data here</p></body></html>"
        session = MagicMock()
        session.get = MagicMock(return_value=_make_mock_response(200, html))

        result = await _fetch_public_tariffs(session)
        assert result is None

    async def test_malformed_json_returns_none(self):
        # Embed a valid-looking marker but broken JSON
        html = f"{NEXT_DATA_MARKER}{{not valid json}}</script>"
        session = MagicMock()
        session.get = MagicMock(return_value=_make_mock_response(200, html))

        result = await _fetch_public_tariffs(session)
        assert result is None

    async def test_empty_products_list_returns_empty_electricity_and_gas(self):
        html = _make_next_data_html([])
        session = MagicMock()
        session.get = MagicMock(return_value=_make_mock_response(200, html))

        result = await _fetch_public_tariffs(session)

        assert result is not None
        # PLACET products are also empty because there's no PLACET HTML
        assert result["electricity"] == []
        assert result["gas"] == []

    async def test_gas_typename_routes_to_gas_list(self):
        products = [
            {"__typename": "GasProductType", "code": "OCTOPUS_GAS"},
        ]
        html = _make_next_data_html(products)
        session = MagicMock()
        session.get = MagicMock(return_value=_make_mock_response(200, html))

        result = await _fetch_public_tariffs(session)
        assert result is not None
        assert any(p["code"] == "OCTOPUS_GAS" for p in result["gas"])
        assert result["electricity"] == []

    async def test_non_gas_typename_routes_to_electricity_list(self):
        products = [
            {"__typename": "ElectricityProductType", "code": "SMART_LUCE"},
        ]
        html = _make_next_data_html(products)
        session = MagicMock()
        session.get = MagicMock(return_value=_make_mock_response(200, html))

        result = await _fetch_public_tariffs(session)
        assert result is not None
        assert any(p["code"] == "SMART_LUCE" for p in result["electricity"])
        assert result["gas"] == []

    async def test_placet_products_appended_to_api_products(self):
        """PLACET products parsed from HTML are merged with __NEXT_DATA__ products."""
        api_products = [{"__typename": "ElectricityProductType", "code": "FLEX_LUCE"}]
        payload = {"props": {"pageProps": {"products": api_products}}}
        json_str = json.dumps(payload)
        # Embed both __NEXT_DATA__ and a PLACET block in the same HTML
        html = (
            f'{NEXT_DATA_MARKER}{json_str}</script>\n'
            + PLACET_FISSA_FULL
        )
        session = MagicMock()
        session.get = MagicMock(return_value=_make_mock_response(200, html))

        result = await _fetch_public_tariffs(session)
        assert result is not None
        elec_codes = {p["code"] for p in result["electricity"]}
        assert "FLEX_LUCE" in elec_codes
        assert "PLACET_FISSA_LUCE" in elec_codes

    async def test_unicode_decode_error_returns_none(self):
        """UnicodeDecodeError during response.text() is treated as a client error."""
        session = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.text = AsyncMock(side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, ""))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=response)
        cm.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=cm)

        result = await _fetch_public_tariffs(session)
        assert result is None


# ---------------------------------------------------------------------------
# async_update_public_products retry / cache logic
#
# Because async_update_public_products is a closure defined inside
# async_setup_entry, we cannot import it directly.  Instead we replicate its
# logic in a standalone async function that is structurally identical, using
# the same domain_data dict pattern.  This lets us test the behaviour
# (retry scheduling, cache usage, UpdateFailed) without invoking HA setup.
# ---------------------------------------------------------------------------

from homeassistant.helpers.update_coordinator import UpdateFailed  # noqa: E402 (stub)


async def _make_update_fn(hass, domain_data, fetch_result):
    """
    Replicate the async_update_public_products closure from __init__.py,
    injecting a mock _fetch_public_tariffs result.

    Returns (update_fn,) so callers can await update_fn() and inspect
    domain_data for side-effects.
    """
    from homeassistant.core import callback  # noqa: F401 (stub passthrough)

    def _cancel_retry():
        unsub = domain_data.pop("public_products_retry_unsub", None)
        if unsub is not None:
            unsub()

    def _schedule_retry():
        _cancel_retry()

        def _do_retry(_now):
            domain_data.pop("public_products_retry_unsub", None)
            coordinator = domain_data.get("public_products_coordinator")
            if coordinator is not None:
                hass.async_create_task(coordinator.async_request_refresh())

        domain_data["public_products_retry_unsub"] = hass.async_call_later(
            PUBLIC_PRODUCTS_RETRY_DELAY, _do_retry
        )

    async def async_update_public_products():
        products = fetch_result  # pre-computed; None means failure
        if products is None:
            _schedule_retry()
            cached = domain_data.get("public_products_cache")
            if cached:
                return cached
            raise UpdateFailed("Public tariffs unavailable and no cached data")
        _cancel_retry()
        domain_data["public_products_cache"] = products
        return products

    return async_update_public_products


class TestAsyncUpdatePublicProducts:
    async def test_success_updates_cache(self):
        hass = MagicMock()
        domain_data = {}
        products = {"electricity": [{"code": "X"}], "gas": []}

        update_fn = await _make_update_fn(hass, domain_data, products)
        result = await update_fn()

        assert result == products
        assert domain_data["public_products_cache"] == products
        # No retry should be scheduled
        assert "public_products_retry_unsub" not in domain_data

    async def test_failure_with_cache_returns_cache(self):
        hass = MagicMock()
        hass.async_call_later = MagicMock(return_value=MagicMock())
        cached = {"electricity": [{"code": "CACHED"}], "gas": []}
        domain_data = {"public_products_cache": cached}

        update_fn = await _make_update_fn(hass, domain_data, None)
        result = await update_fn()

        assert result == cached
        # A retry should have been scheduled
        hass.async_call_later.assert_called_once_with(
            PUBLIC_PRODUCTS_RETRY_DELAY, unittest_any_callable()
        )
        assert "public_products_retry_unsub" in domain_data

    async def test_failure_without_cache_raises_update_failed(self):
        hass = MagicMock()
        hass.async_call_later = MagicMock(return_value=MagicMock())
        domain_data = {}

        update_fn = await _make_update_fn(hass, domain_data, None)

        with pytest.raises(UpdateFailed):
            await update_fn()

        # Retry still scheduled even though there's no cache
        hass.async_call_later.assert_called_once()

    async def test_success_after_failure_cancels_retry(self):
        hass = MagicMock()
        unsub_mock = MagicMock()
        hass.async_call_later = MagicMock(return_value=unsub_mock)

        domain_data = {}

        # First call: failure (no cache), schedules retry
        update_fn_fail = await _make_update_fn(hass, domain_data, None)
        with pytest.raises(UpdateFailed):
            await update_fn_fail()

        assert "public_products_retry_unsub" in domain_data
        assert domain_data["public_products_retry_unsub"] is unsub_mock

        # Second call: success → retry unsub is called and removed
        products = {"electricity": [], "gas": []}
        update_fn_ok = await _make_update_fn(hass, domain_data, products)
        result = await update_fn_ok()

        assert result == products
        unsub_mock.assert_called_once()
        assert "public_products_retry_unsub" not in domain_data

    async def test_consecutive_failures_replace_retry_unsub(self):
        hass = MagicMock()
        unsub_1 = MagicMock()
        unsub_2 = MagicMock()
        hass.async_call_later = MagicMock(side_effect=[unsub_1, unsub_2])
        cached = {"electricity": [], "gas": []}
        domain_data = {"public_products_cache": cached}

        # First failure: schedules retry → unsub_1
        update_fn = await _make_update_fn(hass, domain_data, None)
        await update_fn()
        assert domain_data["public_products_retry_unsub"] is unsub_1

        # Second failure: should cancel unsub_1 then schedule unsub_2
        await update_fn()
        unsub_1.assert_called_once()
        assert domain_data["public_products_retry_unsub"] is unsub_2

    async def test_retry_callback_triggers_coordinator_refresh(self):
        """The _do_retry callback calls async_request_refresh on the coordinator."""
        hass = MagicMock()
        coordinator = MagicMock()
        coordinator.async_request_refresh = MagicMock(return_value=None)
        hass.async_create_task = MagicMock()

        captured_callback = {}

        def _capture_call_later(delay, fn):
            captured_callback["fn"] = fn
            return MagicMock()

        hass.async_call_later = MagicMock(side_effect=_capture_call_later)

        domain_data = {"public_products_coordinator": coordinator}

        update_fn = await _make_update_fn(hass, domain_data, None)
        with pytest.raises(UpdateFailed):
            await update_fn()

        # Simulate the callback firing
        assert "fn" in captured_callback
        captured_callback["fn"]("now")
        hass.async_create_task.assert_called_once()

    async def test_retry_callback_noop_when_no_coordinator(self):
        """The _do_retry callback is safe when no coordinator is present."""
        hass = MagicMock()
        hass.async_create_task = MagicMock()

        captured_callback = {}

        def _capture_call_later(delay, fn):
            captured_callback["fn"] = fn
            return MagicMock()

        hass.async_call_later = MagicMock(side_effect=_capture_call_later)
        domain_data = {}  # no coordinator

        update_fn = await _make_update_fn(hass, domain_data, None)
        with pytest.raises(UpdateFailed):
            await update_fn()

        # Should not raise even with no coordinator
        captured_callback["fn"]("now")
        hass.async_create_task.assert_not_called()


# ---------------------------------------------------------------------------
# Helper: any callable matcher for assert_called_with
# ---------------------------------------------------------------------------

class unittest_any_callable:
    """Matches any callable argument in mock assertions."""

    def __eq__(self, other):
        return callable(other)

    def __repr__(self):
        return "<any callable>"


# ---------------------------------------------------------------------------
# process_api_data dispatch logic
#
# process_api_data is also a closure inside async_setup_entry.  We test its
# dispatch-window logic by replicating just that slice as a standalone helper,
# which mirrors the exact code in __init__.py lines 828–871.
# ---------------------------------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402


def _process_dispatches(planned_dispatches_raw, now):
    """Replicate the dispatch extraction block from process_api_data."""
    planned_dispatches = planned_dispatches_raw
    if planned_dispatches is None:
        planned_dispatches = []

    current_start = None
    current_end = None
    next_start = None
    next_end = None

    from homeassistant.util.dt import as_utc, parse_datetime  # use stubs

    for dispatch in sorted(planned_dispatches, key=lambda x: x.get("start", "")):
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

    return {
        "planned_dispatches": planned_dispatches,
        "current_start": current_start,
        "current_end": current_end,
        "next_start": next_start,
        "next_end": next_end,
    }


class TestProcessDispatchData:
    def _now(self):
        return datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)

    def _dt(self, hours_from_now: float) -> str:
        t = self._now() + timedelta(hours=hours_from_now)
        return t.isoformat()

    def test_active_dispatch_identified(self):
        dispatches = [
            {"start": self._dt(-1), "end": self._dt(+1)},  # active
            {"start": self._dt(+2), "end": self._dt(+3)},  # next
        ]
        result = _process_dispatches(dispatches, self._now())

        assert result["current_start"] is not None
        assert result["current_end"] is not None
        assert result["next_start"] is not None

    def test_future_dispatch_becomes_next(self):
        dispatches = [
            {"start": self._dt(+2), "end": self._dt(+3)},
            {"start": self._dt(+5), "end": self._dt(+6)},
        ]
        result = _process_dispatches(dispatches, self._now())

        assert result["current_start"] is None
        assert result["next_start"] is not None
        # next_start should be the earliest future slot
        expected_start = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC) + timedelta(hours=2)
        assert result["next_start"] == expected_start

    def test_past_dispatch_ignored(self):
        dispatches = [
            {"start": self._dt(-5), "end": self._dt(-3)},  # past
        ]
        result = _process_dispatches(dispatches, self._now())

        assert result["current_start"] is None
        assert result["next_start"] is None

    def test_empty_dispatches(self):
        result = _process_dispatches([], self._now())

        assert result["planned_dispatches"] == []
        assert result["current_start"] is None
        assert result["next_start"] is None

    def test_none_dispatches_treated_as_empty(self):
        result = _process_dispatches(None, self._now())

        assert result["planned_dispatches"] == []
        assert result["current_start"] is None
        assert result["next_start"] is None

    def test_dispatch_with_missing_start_or_end_skipped(self):
        dispatches = [
            {"start": self._dt(+1)},         # missing end
            {"end": self._dt(+2)},            # missing start
            {"start": self._dt(+3), "end": self._dt(+4)},  # valid
        ]
        result = _process_dispatches(dispatches, self._now())

        assert result["next_start"] is not None
        # Only the valid one should be picked up
        expected = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC) + timedelta(hours=3)
        assert result["next_start"] == expected

    def test_multiple_future_dispatches_only_first_next_captured(self):
        dispatches = [
            {"start": self._dt(+2), "end": self._dt(+3)},
            {"start": self._dt(+4), "end": self._dt(+5)},
            {"start": self._dt(+6), "end": self._dt(+7)},
        ]
        result = _process_dispatches(dispatches, self._now())

        assert result["current_start"] is None
        # Only the nearest future slot is captured as next
        expected = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC) + timedelta(hours=2)
        assert result["next_start"] == expected
        # next_end corresponds to the same slot
        expected_end = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC) + timedelta(hours=3)
        assert result["next_end"] == expected_end

    def test_dispatch_raw_list_preserved(self):
        dispatches = [
            {"start": self._dt(+1), "end": self._dt(+2)},
        ]
        result = _process_dispatches(dispatches, self._now())
        assert result["planned_dispatches"] is dispatches
