"""Structured Guardian and BBC RSS news provider helpers."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import List

import requests


GUARDIAN_SEARCH_URL = "https://content.guardianapis.com/search"


def fetch_guardian_headlines(
    *,
    section: str,
    query: str | None = None,
    limit: int = 6,
) -> List[str]:
    api_key = (os.environ.get("GUARDIAN_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GUARDIAN_API_KEY is not configured")
    params: dict[str, str | int] = {
        "api-key": api_key,
        "section": section,
        "page-size": limit,
        "order-by": "newest",
        "show-fields": "headline",
    }
    if query:
        params["q"] = query
    response = requests.get(
        GUARDIAN_SEARCH_URL,
        params=params,
        timeout=10,
        headers={"User-Agent": "CeefaxStation/1.0"},
    )
    response.raise_for_status()
    results = (response.json().get("response") or {}).get("results") or []
    headlines = [
        str((item.get("fields") or {}).get("headline") or item.get("webTitle") or "").strip()
        for item in results
    ]
    return [headline for headline in headlines if headline][:limit]


def fetch_bbc_rss_headlines(url: str, *, limit: int = 6) -> List[str]:
    response = requests.get(
        url,
        timeout=10,
        headers={"User-Agent": "CeefaxStation/1.0"},
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    return [
        item.text.strip()
        for item in root.findall("./channel/item/title")[:limit]
        if item.text and item.text.strip()
    ]
