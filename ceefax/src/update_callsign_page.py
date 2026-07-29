"""
Update page 700 with callsign information from PSK Reporter.

Fetches recent spots and statistics for the user's callsign from PSK Reporter.
"""
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .paths import ceefax_root, pages_dir
from .providers import ProviderResult, atomic_write_json, resolve_provider


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def get_callsign_from_config() -> Optional[str]:
    """Get callsign from radio_config.json."""
    try:
        config_file = ceefax_root() / "radio_config.json"
        if config_file.exists():
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
            return config_data.get("callsign")
    except Exception:  # noqa: BLE001
        pass
    return None


def get_grid_from_config() -> Optional[str]:
    """Get Maidenhead grid square from radio_config.json."""
    try:
        config_file = ceefax_root() / "radio_config.json"
        if config_file.exists():
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
            grid = config_data.get("grid")
            return (grid or "").strip().upper() or None
    except Exception:  # noqa: BLE001
        pass
    return None


def fetch_psk_reporter_data(callsign: str) -> Optional[ET.Element]:
    """
    Fetch callsign data from PSK Reporter.
    
    PSK Reporter API endpoint: https://retrieve.pskreporter.info/query
    Returns XML data.
    
    Note: PSK Reporter has rate limiting. We'll handle 503 errors gracefully.
    """
    try:
        # PSK Reporter query API
        url = "https://retrieve.pskreporter.info/query"
        
        # Query parameters for recent spots
        # Try both sender and receiver queries to get more data
        # First try: spots where this callsign was the sender (transmitter)
        params = {
            "senderCallsign": callsign,
            "flowStartSeconds": "-86400",
            "rptlimit": "50",
            "rronly": "1",
            "noactive": "1",
        }
        
        headers = {
            "User-Agent": "Ceefax Station/1.0 (Amateur Radio)",
            "Accept": "application/xml",
            "Referer": "https://pskreporter.info/"
        }
        
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        
        # Check for rate limiting
        if resp.status_code == 503:
            # Try to parse error message
            try:
                error_data = resp.json()
                error_msg = error_data.get("message", "Rate limited")
                print(f"PSK Reporter rate limited: {error_msg}")
            except Exception:
                print("PSK Reporter rate limited (503)")
            return None
        
        resp.raise_for_status()
        
        # Check content type - might be JSON error or XML
        content_type = resp.headers.get("content-type", "").lower()
        if "json" in content_type:
            # Might be an error response in JSON
            try:
                error_data = resp.json()
                error_msg = error_data.get("message", "Unknown error")
                print(f"PSK Reporter API error: {error_msg}")
                return None
            except Exception:
                pass
        
        # PSK Reporter returns XML
        root = ET.fromstring(resp.content)
        return root
        
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching PSK Reporter data: {e}")
        return None
    except ET.ParseError as e:
        print(f"XML parse error: {e}")
        print(f"Response content (first 200 chars): {resp.text[:200] if 'resp' in locals() else 'N/A'}")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"Error fetching PSK Reporter data: {e}")
        return None


def fetch_last_report_days(callsign: str) -> Optional[int]:
    """
    Retained for API compatibility.

    HTML scraping is deliberately disabled; PSK Reporter's structured XML query API
    is the only remote source used by this updater.
    """
    return None


def parse_psk_data(root: ET.Element, callsign: str) -> Dict:
    """Parse PSK Reporter XML data into useful statistics."""
    stats = {
        "callsign": callsign,
        "total_spots": 0,
        "recent_contacts": [],
        "bands_used": [],
        "modes_used": [],
        "last_spot_time": None,
        "countries": set(),
    }
    
    try:
        # Prefer real spot reports over "activeReceiver" summaries.
        # activeReceiver can be noisy and may include entries that aren't actually
        # spots for the requested sender callsign.
        reports = root.findall(".//receptionReport")
        if not reports:
            # Fallback (older schema)
            reports = root.findall(".//receptionReports/receptionReport")

        # Strict time handling:
        # - Only accept spots with a valid Unix timestamp (seconds)
        # - Filter to last 24 hours for display
        now_ts = int(datetime.utcnow().timestamp())
        cutoff = now_ts - 24 * 60 * 60

        def _base_call(cs: str) -> str:
            return cs.split("/")[0].strip().upper()

        want = _base_call(callsign)

        def _parse_ts(ts_str: str) -> Optional[int]:
            ts_str = (ts_str or "").strip()
            if not ts_str:
                return None
            try:
                ts_val = int(float(ts_str))
            except Exception:  # noqa: BLE001
                return None
            # Handle milliseconds
            if ts_val > 10_000_000_000:
                ts_val = int(ts_val / 1000)
            # Reject non-epoch-ish values
            if ts_val < 1_000_000_000:
                return None
            # Reject future timestamps (clock skew etc.)
            if ts_val > now_ts + 3600:
                return None
            return ts_val

        filtered: List[ET.Element] = []
        latest_any_ts: Optional[int] = None
        for r in reports:
            sender = _base_call((r.get("senderCallsign") or r.get("sender") or ""))
            if sender != want:
                continue
            # flowStartSeconds is unix epoch seconds in PSK Reporter
            ts_val = _parse_ts(r.get("flowStartSeconds") or r.get("time") or r.get("timestamp") or "")
            if ts_val is not None:
                latest_any_ts = ts_val if latest_any_ts is None else max(latest_any_ts, ts_val)
            # Only include in "last 24h" if we have a valid timestamp and it's recent
            if ts_val is None or ts_val < cutoff:
                continue
            filtered.append(r)

        # If we couldn't find receptionReport entries, fall back to activeReceiver,
        # but ONLY if they look like they're tied to the sender and are within 24h.
        if not filtered and not reports:
            receivers = root.findall(".//activeReceiver")
            for r in receivers:
                ts_val = _parse_ts(r.get("flowStartSeconds") or "")
                if ts_val is not None:
                    latest_any_ts = ts_val if latest_any_ts is None else max(latest_any_ts, ts_val)
                if ts_val is None or ts_val < cutoff:
                    continue
                filtered.append(r)

        # Sort by timestamp descending if available
        def _ts(elem: ET.Element) -> int:
            ts_str = (elem.get("flowStartSeconds") or elem.get("time") or elem.get("timestamp") or "").strip()
            try:
                return int(float(ts_str)) if ts_str else 0
            except Exception:  # noqa: BLE001
                return 0

        filtered.sort(key=_ts, reverse=True)

        stats["total_spots"] = len(filtered)
        stats["last_spot_time"] = latest_any_ts

        # Process recent spots
        for receiver in filtered[:10]:  # Top 10 most recent
            contact = {}
            
            # Extract XML attributes
            contact["receiver"] = (
                receiver.get("receiverCallsign")
                or receiver.get("receiver")
                or receiver.get("callsign")
                or "?"
            )
            contact["frequency"] = receiver.get("frequency", "") or receiver.get("freq", "")
            contact["mode"] = receiver.get("mode", "") or receiver.get("modeName", "")
            # SNR might be in different attributes
            contact["snr"] = receiver.get("snr") or receiver.get("signalReport") or receiver.get("signal") or "?"
            contact["country"] = receiver.get("DXCC") or receiver.get("region") or receiver.get("country") or ""
            contact["locator"] = receiver.get("locator", "")
            # Get timestamp if available
            contact["time"] = receiver.get("flowStartSeconds", "")
            
            # Calculate band from frequency
            if contact["frequency"]:
                try:
                    freq_hz = float(contact["frequency"])
                    freq_mhz = freq_hz / 1000000
                    if freq_mhz < 2:
                        band = "160m"
                    elif freq_mhz < 4:
                        band = "80m"
                    elif freq_mhz < 7.5:
                        band = "40m"
                    elif freq_mhz < 10.2:
                        band = "30m"
                    elif freq_mhz < 14.5:
                        band = "20m"
                    elif freq_mhz < 18.2:
                        band = "17m"
                    elif freq_mhz < 21.5:
                        band = "15m"
                    elif freq_mhz < 24.9:
                        band = "12m"
                    elif freq_mhz < 30:
                        band = "10m"
                    elif freq_mhz < 54:
                        band = "6m"
                    elif freq_mhz < 148:
                        band = "2m"
                    elif freq_mhz < 450:
                        band = "70cm"
                    else:
                        band = f"{freq_mhz:.1f}MHz"
                    contact["band"] = band
                    if band not in stats["bands_used"]:
                        stats["bands_used"].append(band)
                except (ValueError, TypeError):
                    contact["band"] = "?"
            
            if contact["mode"] and contact["mode"] not in stats["modes_used"]:
                stats["modes_used"].append(contact["mode"])
            
            if contact["country"]:
                stats["countries"].add(contact["country"])
            
            stats["recent_contacts"].append(contact)
        
        stats["countries"] = sorted(list(stats["countries"]))[:5]  # Top 5 countries
        
    except Exception as e:  # noqa: BLE001
        print(f"Error parsing PSK data: {e}")
    
    return stats


def _fetch_normalized_psk_data(callsign: str) -> Dict:
    root = fetch_psk_reporter_data(callsign)
    if root is None:
        raise RuntimeError("PSK Reporter XML API unavailable")
    return parse_psk_data(root, callsign)


def resolve_callsign_data(callsign: str) -> ProviderResult[Dict]:
    """Resolve normalized XML API data, isolated by configured callsign."""
    normalized = callsign.strip().upper()
    cache_key = "".join(ch if ch.isalnum() else "-" for ch in normalized)
    return resolve_provider(
        f"callsign-700-{cache_key}",
        [("PSK Reporter XML API", lambda: _fetch_normalized_psk_data(normalized))],
        is_valid=lambda data: isinstance(data, dict)
        and str(data.get("callsign", "")).upper() == normalized
        and isinstance(data.get("recent_contacts"), list),
        fresh_for_seconds=5 * 60,
    )


def build_callsign_page(
    callsign: str,
    result: ProviderResult[Dict] | None = None,
) -> List[str]:
    """Build callsign information page."""
    lines: List[str] = []
    lines.append(_pad("CALLSIGN INFORMATION"))
    
    sep = _pad("-" * PAGE_WIDTH)
    lines.append(_pad(f"CALLSIGN: {callsign.upper()}"))
    
    # Add grid square if available
    grid = get_grid_from_config()
    if grid:
        lines.append(_pad(f"GRID: {grid}"))

    result = result or resolve_callsign_data(callsign)
    lines.append(_pad(f"Source: {result.source}"))
    stale = " | STALE" if result.stale else ""
    lines.append(_pad(f"As-of: {result.fetched_at}{stale}"))
    lines.append(sep)

    stats = result.data

    def _format_age(seconds_ago: int) -> str:
        if seconds_ago < 0:
            seconds_ago = 0
        if seconds_ago < 60:
            return f"{seconds_ago}s ago"
        if seconds_ago < 3600:
            return f"{seconds_ago // 60}m ago"
        if seconds_ago < 86400:
            return f"{seconds_ago // 3600}h ago"
        return f"{seconds_ago // 86400} days ago"

    lines.append(_pad("RECENT ACTIVITY"))
    lines.append(sep)
    lines.append(_pad(f"Total Spots (24h): {stats['total_spots']}"))

    last_ts = stats.get("last_spot_time")
    if isinstance(last_ts, int) and last_ts > 0:
        age_s = int(datetime.utcnow().timestamp() - last_ts)
        lines.append(_pad(f"Last seen: {_format_age(age_s)}"))

    if stats["total_spots"] == 0:
        if isinstance(last_ts, int) and last_ts > 0:
            days_ago = int((datetime.utcnow().timestamp() - last_ts) / 86400)
            lines.append(_pad(f"Monitoring {callsign.upper()} (last report {days_ago} days ago)"))
        else:
            lines.append(_pad(f"Monitoring {callsign.upper()} (no recent reports)"))
        lines.append(_pad(""))
    else:
        if stats["bands_used"]:
            bands_str = ", ".join(stats["bands_used"][:5])
            lines.append(_pad(f"Bands Used: {bands_str[:PAGE_WIDTH-13]}"))

        if stats["modes_used"]:
            modes_str = ", ".join(stats["modes_used"][:5])
            lines.append(_pad(f"Modes: {modes_str[:PAGE_WIDTH-7]}"))

        if stats["countries"]:
            countries_str = ", ".join(stats["countries"])
            lines.append(_pad(f"Countries: {countries_str[:PAGE_WIDTH-11]}"))

        lines.append(_pad(""))
        if stats["recent_contacts"]:
            lines.append(_pad("RECENT SPOTS"))
            lines.append(sep)
            for contact in stats["recent_contacts"][:6]:
                receiver = str(contact.get("receiver", "?"))[:10]
                band = str(contact.get("band", "?"))[:6]
                mode = str(contact.get("mode", "?"))[:5]
                country = str(contact.get("country", ""))[:12]
                line = (
                    f"{receiver:<10} {band:<6} {mode:<5} {country}"
                    if country
                    else f"{receiver:<10} {band:<6} {mode:<5}"
                )
                lines.append(_pad(line[:PAGE_WIDTH]))

    lines.append(_pad(""))
    lines.append(_pad("(pskreporter.info)"))
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 700 with callsign information."""
    page_file = pages_dir() / "700.json"
    
    # Get callsign from config
    callsign = get_callsign_from_config()
    
    if not callsign:
        # Create a placeholder page if no callsign is set
        grid = get_grid_from_config()
        content = [
            _pad("CALLSIGN INFORMATION"),
        ]
        if grid:
            content.append(_pad(f"GRID: {grid}"))
        content.extend([
            _pad("-" * PAGE_WIDTH),
            _pad(""),
            _pad("No callsign configured."),
            _pad(""),
            _pad("Set your callsign in the"),
            _pad("update process to see"),
            _pad("PSK Reporter data here."),
            _pad(""),
            _pad("Source: PSK Reporter"),
        ])
        print(f"Updated {page_file} with callsign placeholder (no callsign set)")
    else:
        result = resolve_callsign_data(callsign)
        content = build_callsign_page(callsign, result)
        print(f"Updated {page_file} with callsign data for {callsign}")
    
    page = {
        "page": "700",
        "title": "Callsign Info",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)


if __name__ == "__main__":
    main()

