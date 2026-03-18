"""Scraping utilities for the Octopus Energy Italy public tariffs page."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from decimal import Decimal, InvalidOperation

import aiohttp

_LOGGER = logging.getLogger(__name__)

TARIFFS_PAGE_URL = "https://octopusenergy.it/le-nostre-tariffe"
_NEXT_DATA_MARKER = '<script id="__NEXT_DATA__" type="application/json">'


def _slice_html_block(html: str, marker: str, *, max_len: int = 20000) -> str | None:
    start = html.find(marker)
    if start == -1:
        return None
    next_idx = html.find("PLACET ", start + len(marker))
    end = next_idx if next_idx != -1 else min(len(html), start + max_len)
    return html[start:end]


def _extract_value(block: str, label: str, unit: str) -> str | None:
    pattern = rf"{re.escape(label)}.*?<p[^>]*>\s*([^<]*?{re.escape(unit)})"
    match = re.search(pattern, block, re.IGNORECASE | re.DOTALL)
    if not match:
        pattern = rf"{re.escape(label)}.*?>\s*([^<]*?{re.escape(unit)})"
        match = re.search(pattern, block, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return match.group(1).replace("<!-- -->", "").strip()


def _extract_decimal(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", text)
    return match.group(1) if match else None


def _monthly_to_annual(monthly: str | None) -> str | None:
    if not monthly:
        return None
    try:
        value = Decimal(monthly.replace(",", "."))
    except InvalidOperation:
        return None
    annual = (value * Decimal(12)).quantize(Decimal("0.01"))
    return format(annual, "f")


def _find_link(block: str, token: str) -> str | None:
    match = re.search(rf"href=\"([^\"]*{re.escape(token)}[^\"]*)\"", block)
    return match.group(1) if match else None


def _extract_placet_products(html: str) -> dict[str, list[dict]]:
    products: dict[str, list[dict]] = {"electricity": [], "gas": []}
    base_url = "https://octopusenergy.it"
    placet_defs = [
        ("PLACET Fissa Domestico", "PLACET_FIXED", "PLACET_FISSA"),
        ("PLACET Variabile Domestico", "PLACET_VARIABLE", "PLACET_VARIABILE"),
    ]

    for heading, product_type, code_prefix in placet_defs:
        block = _slice_html_block(html, heading)
        if not block:
            continue
        block = block.replace("<!-- -->", "")

        # NOTE: r">\\s*Gas\\s*<" contains literal backslashes (not \s whitespace),
        # so it only matches a specific separator format that differs from plain HTML
        # "> Gas <". Normal HTML blocks never trigger gas extraction — this is
        # intentional. See TestExtractPlacetProducts in tests/test_coordinator.py.
        gas_marker = re.search(r">\\s*Gas\\s*<", block, re.IGNORECASE)
        if gas_marker:
            electricity_block = block[: gas_marker.start()]
            gas_block = block[gas_marker.start() :]
        else:
            electricity_block = block
            gas_block = ""

        elec_comm_text = _extract_value(
            electricity_block, "Commercializzazione", "€/mese"
        )
        elec_comm_monthly = _extract_decimal(elec_comm_text)
        elec_comm_annual = _monthly_to_annual(elec_comm_monthly)

        if "Variabile" in heading:
            f1_text = _extract_value(electricity_block, "Materia prima F1:", "€/kWh")
            f23_text = _extract_value(electricity_block, "Materia prima F23:", "€/kWh")
            f1_value = _extract_decimal(f1_text)
            f23_value = _extract_decimal(f23_text)
            elec_description = f"F1: {f1_text or 'n/d'}; F23: {f23_text or 'n/d'}"
            elec_params = {
                "productType": product_type,
                "annualStandingCharge": elec_comm_annual,
                "consumptionCharge": f1_value,
                "consumptionChargeF2": f23_value,
                "consumptionChargeF3": f23_value,
            }
        else:
            elec_price_text = _extract_value(
                electricity_block, "Materia prima:", "€/kWh"
            )
            elec_price = _extract_decimal(elec_price_text)
            elec_description = elec_price_text
            elec_params = {
                "productType": product_type,
                "annualStandingCharge": elec_comm_annual,
                "consumptionCharge": elec_price,
            }

        elec_link = _find_link(block, f"{code_prefix}_LUCE")
        if elec_link and elec_link.startswith("/"):
            elec_link = f"{base_url}{elec_link}"

        if elec_params.get("consumptionCharge") is not None:
            products["electricity"].append(
                {
                    "__typename": "ElectricityProductType",
                    "code": f"{code_prefix}_LUCE",
                    "displayName": f"{heading} Luce",
                    "fullName": f"{heading} Luce",
                    "description": elec_description,
                    "termsAndConditionsUrl": elec_link,
                    "params": elec_params,
                }
            )

        gas_comm_text = _extract_value(gas_block, "Commercializzazione", "€/mese")
        gas_comm_monthly = _extract_decimal(gas_comm_text)
        gas_comm_annual = _monthly_to_annual(gas_comm_monthly)
        gas_price_text = _extract_value(gas_block, "Materia prima:", "€/Smc")
        gas_price = _extract_decimal(gas_price_text)
        gas_link = _find_link(block, f"{code_prefix}_GAS")
        if gas_link and gas_link.startswith("/"):
            gas_link = f"{base_url}{gas_link}"

        if gas_price is not None:
            products["gas"].append(
                {
                    "__typename": "GasProductType",
                    "code": f"{code_prefix}_GAS",
                    "displayName": f"{heading} Gas",
                    "fullName": f"{heading} Gas",
                    "description": gas_price_text,
                    "termsAndConditionsUrl": gas_link,
                    "params": {
                        "productType": product_type,
                        "annualStandingCharge": gas_comm_annual,
                        "consumptionCharge": gas_price,
                    },
                }
            )

    return products


async def fetch_public_tariffs(
    session: aiohttp.ClientSession,
) -> dict[str, list] | None:
    """Scrape the Octopus public tariffs page to mirror frontend data."""
    try:
        async with session.get(
            TARIFFS_PAGE_URL, timeout=aiohttp.ClientTimeout(total=20)
        ) as response:
            response.raise_for_status()
            html = await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeDecodeError) as err:
        _LOGGER.error("Unable to fetch public tariffs page: %s", err)
        return None

    marker_index = html.find(_NEXT_DATA_MARKER)
    if marker_index == -1:
        _LOGGER.warning("Public tariffs page did not include __NEXT_DATA__ marker")
        return None

    data_start = html.find(">", marker_index)
    if data_start == -1:
        _LOGGER.warning("Malformed __NEXT_DATA__ script in tariffs page")
        return None

    data_start += 1
    data_end = html.find("</script>", data_start)
    if data_end == -1:
        _LOGGER.warning("Unable to locate end of __NEXT_DATA__ script")
        return None

    raw = html[data_start:data_end]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as err:
        _LOGGER.error("Unable to decode __NEXT_DATA__ payload: %s", err)
        return None

    all_products = payload.get("props", {}).get("pageProps", {}).get("products") or []

    electricity: list[dict] = []
    gas: list[dict] = []

    for product in all_products:
        if not isinstance(product, dict):
            continue
        typename = (product.get("__typename") or "").upper()
        if "GAS" in typename:
            gas.append(product)
        else:
            electricity.append(product)

    placet_products = _extract_placet_products(html)
    if placet_products["electricity"] or placet_products["gas"]:
        electricity.extend(placet_products["electricity"])
        gas.extend(placet_products["gas"])
        _LOGGER.debug(
            "Added %d PLACET electricity and %d PLACET gas products from tariffs page",
            len(placet_products["electricity"]),
            len(placet_products["gas"]),
        )

    _LOGGER.debug(
        "Fetched %d electricity and %d gas public products from octopusenergy.it",
        len(electricity),
        len(gas),
    )
    return {"electricity": electricity, "gas": gas}
