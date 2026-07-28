"""Update page 400 using ECB reference data served by Frankfurter."""
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, atomic_write_json, resolve_provider


EXCHANGE_API = "https://api.frankfurter.app/latest"
EXCHANGE_SOURCE = "Frankfurter (ECB data)"
TARGET_CURRENCIES = ("GBP", "USD", "JPY", "CHF", "CAD", "AUD")


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def fetch_exchange_rates() -> Dict[str, float]:
    """Fetch EUR ECB rates and derive all displayed GBP cross-rates."""
    response = requests.get(
        EXCHANGE_API,
        params={"from": "EUR", "to": ",".join(TARGET_CURRENCIES)},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    eur_rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(eur_rates, dict) or not eur_rates.get("GBP"):
        raise ValueError("Frankfurter response omitted the GBP reference rate")
    gbp_per_eur = float(eur_rates["GBP"])
    rates = {"GBP": 1.0, "EUR": 1.0 / gbp_per_eur}
    for code in TARGET_CURRENCIES:
        if code != "GBP" and code in eur_rates:
            rates[code] = float(eur_rates[code]) / gbp_per_eur
    if not all(code in rates for code in ("USD", "EUR", "JPY")):
        raise ValueError("Frankfurter response omitted required currencies")
    return rates


def get_exchange_rates() -> ProviderResult[Dict[str, float]]:
    return resolve_provider("exchange-400", [(EXCHANGE_SOURCE, fetch_exchange_rates)])


def build_exchange_rates_page(result: ProviderResult[Dict[str, float]] | None = None) -> List[str]:
    result = result or get_exchange_rates()
    rates = result.data
    lines: List[str] = []
    lines.append(_pad("EXCHANGE RATES"))

    lines.append(_pad(""))
    lines.append(_pad("GBP (British Pound)"))
    sep = _pad("-" * PAGE_WIDTH)
    lines.append(sep)

    # Major currencies
    major_currencies = {
        "USD": "$",
        "EUR": "€",
        "JPY": "¥",
        "CHF": "Fr",
        "CAD": "$",
        "AUD": "$",
    }

    for code, symbol in major_currencies.items():
        if code in rates:
            rate = rates[code]
            if code == "JPY":
                # JPY is typically shown with more precision
                rate_str = f"{rate:.2f}"
            else:
                rate_str = f"{rate:.2f}"
            lines.append(_pad(f"{code:3}  {symbol}{rate_str}"))

    lines.append(_pad(""))
    lines.append(_pad("MAJOR CURRENCIES"))
    lines.append(sep)

    # Cross rates
    if "USD" in rates and "EUR" in rates:
        eur_usd = rates["EUR"] / rates["USD"] if rates["USD"] != 0 else 0
        lines.append(_pad(f"EUR/USD  ${eur_usd:.2f}"))

    if "USD" in rates and "JPY" in rates:
        usd_jpy = rates["JPY"] / rates["USD"] if rates["USD"] != 0 else 0
        lines.append(_pad(f"USD/JPY  ¥{usd_jpy:.2f}"))

    if "EUR" in rates:
        lines.append(_pad(f"GBP/EUR  €{rates['EUR']:.2f}"))

    lines.append(_pad(""))
    state = "Stale/as-of" if result.stale else "As-of"
    lines.append(_pad(f"{state}: {result.fetched_at}"))
    lines.append(_pad(f"Source: {EXCHANGE_SOURCE}"))

    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 400 with latest exchange rates."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "400.json"

    result = get_exchange_rates()
    content = build_exchange_rates_page(result)

    page = {
        "page": "400",
        "title": "Exchange Rates",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }

    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with latest exchange rates")


if __name__ == "__main__":
    main()

