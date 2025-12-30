"""
Master script to update all live data pages at once.

This script calls all individual update scripts to refresh:
- Weather pages (101, 102, 103)
- News pages (200, 201, 202)
- Sports pages (300, 301, 302, 303, 304, 305)
- Finance/Travel pages (400, 401, 402)
- Entertainment pages (500, 501, 502, 503, 504)
- Fun/Games pages (600, 601, 602, 603)
- Radio page (700)
- System pages (900, 901, 902, 903)

Includes retry logic for failed updates (max 2 retries).
"""
import sys
import time
import io
import contextlib
from datetime import datetime, timezone
from typing import Callable, Tuple, Optional, Dict, List, Any

from . import (
    update_about_page,
    update_ascii_art_page,
    update_callsign_page,
    update_exchange_rates_page,
    update_fact_page,
    update_film_picks_page,
    update_fixtures_page,
    update_football_page,
    update_football_scores_page,
    update_joke_page,
    update_lottery_page,
    update_news_page,
    update_on_this_day_page,
    update_other_sports_page,
    update_quote_page,
    update_quiz_page,
    update_travel_page,
    update_tv_guide_page,
    update_uk_news_page,
    update_uk_weather_page,
    update_weather_map_page,
    update_weather_page,
    update_world_news_page,
    update_system_logs_page,
    update_system_status_page,
)


MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 3

# --- Console UI helpers (Scoop-style progress, encoding-safe) ---
def _supports_text(s: str) -> bool:
    """
    Return True if stdout encoding can represent `s` without throwing.
    """
    try:
        enc = (getattr(sys.stdout, "encoding", None) or "utf-8")
        s.encode(enc, errors="strict")
        return True
    except Exception:  # noqa: BLE001
        return False


# Prefer nice unicode glyphs when supported; otherwise use ASCII.
_GLYPH_OK = "✓" if _supports_text("✓") else "OK"
_GLYPH_FAIL = "✗" if _supports_text("✗") else "X"
_GLYPH_RUN = "·" if _supports_text("·") else "."


def _box(status: str) -> str:
    """
    status: pending | running | ok | fail
    """
    if status == "pending":
        return "[ ]"
    if status == "running":
        return f"[{_GLYPH_RUN}]"
    if status == "ok":
        return f"[{_GLYPH_OK}]"
    if status == "fail":
        return f"[{_GLYPH_FAIL}]"
    return "[?]"


def _legend() -> str:
    return f"{_box('pending')} pending  {_box('ok')} ok  {_box('fail')} fail"


def _run_quiet(func: Callable[[], None]) -> Tuple[bool, str, str]:
    """
    Run `func()` while capturing stdout/stderr so `update_all` output stays clean.

    Returns:
      (ok, stdout_text, stderr_text)
    """
    out = io.StringIO()
    err = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            func()
        return (True, out.getvalue(), err.getvalue())
    except Exception:  # noqa: BLE001
        return (False, out.getvalue(), err.getvalue())


def _tail(text: str, n: int = 8) -> str:
    lines = [ln.rstrip("\r") for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max(1, int(n)) :])
# Global variables to store user preferences
_user_location: Optional[Tuple[str, str]] = None  # (name, query) format
_user_callsign: Optional[str] = None
_user_frequency: Optional[str] = None


def persist_radio_config(callsign: Optional[str], frequency: Optional[str] = None, grid: Optional[str] = None) -> None:
    """
    Write ceefax/radio_config.json for the viewer / start page.
    Safe to call in non-interactive scheduled runs.
    
    Args:
        callsign: Callsign to save
        frequency: Optional frequency to save
        grid: Optional Maidenhead grid square to save (only if not already set in config)
    """
    if not callsign:
        return
    try:
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        config_file = root / "radio_config.json"
        
        # Read existing config to preserve grid if already set
        existing_data = {}
        if config_file.exists():
            try:
                existing_data = json.loads(config_file.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        
        config_data = {"callsign": callsign}
        if frequency:
            config_data["frequency"] = frequency
        
        # Only set grid if:
        # 1. Grid is provided AND
        # 2. No grid is already set in existing config (don't overwrite user's manual setting)
        if grid and not existing_data.get("grid"):
            config_data["grid"] = grid.strip().upper()
        elif existing_data.get("grid"):
            # Preserve existing grid
            config_data["grid"] = existing_data["grid"]
        
        config_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        # Never fail page updates due to config persistence issues.
        return


def auto_detect_location_silent() -> Tuple[str, str]:
    """
    Non-interactive location detection for scheduled runs.
    Returns (name, query) where query is suitable for wttr.in.
    Also saves detected grid square to radio_config.json if available.
    """
    try:
        from .update_weather_page import get_location_from_ip, get_location_from_timezone

        location = get_location_from_ip()
        if not location:
            location = get_location_from_timezone()
        if location:
            detected_grid = None
            if len(location) == 4:
                _lat, _lon, city, detected_grid = location
            else:
                _lat, _lon, city = location
            city_name = city.split(",")[0] if "," in city else city
            # Default to UK for better wttr.in compatibility
            
            # Save detected grid to config if available (only if not already set)
            if detected_grid:
                try:
                    import json
                    from pathlib import Path as PathLib
                    root = PathLib(__file__).resolve().parent.parent
                    config_file = root / "radio_config.json"
                    if config_file.exists():
                        config_data = json.loads(config_file.read_text(encoding="utf-8"))
                        callsign = config_data.get("callsign")
                        if callsign:
                            persist_radio_config(callsign, config_data.get("frequency"), detected_grid)
                            print(f"Saved detected grid square {detected_grid} to radio_config.json")
                except Exception as e:  # noqa: BLE001
                    # Don't fail if grid saving fails, but log for debugging
                    print(f"Note: Could not save grid to config: {e}")
            
            return (city_name, f"{city_name},UK")  # Use UK instead of GB for better wttr.in compatibility
    except Exception:  # noqa: BLE001
        pass
    return ("London", "London,UK")  # Use UK instead of GB for better wttr.in compatibility


def prime_user_settings(
    *,
    callsign: Optional[str] = None,
    frequency: Optional[str] = None,
    location: Optional[Tuple[str, str]] = None,
    auto_location: bool = True,
) -> None:
    """
    Prime cached user settings so `update_all()` can run without prompts.
    """
    global _user_callsign, _user_frequency, _user_location

    if callsign is not None:
        _user_callsign = callsign
    if frequency is not None:
        _user_frequency = frequency
    if location is not None:
        _user_location = location
    elif auto_location and _user_location is None:
        _user_location = auto_detect_location_silent()

    # Ensure the viewer/start page can show the callsign.
    persist_radio_config(_user_callsign, _user_frequency)


def update_with_retry(
    name: str, update_func: Callable[[], None], max_retries: int = MAX_RETRIES
) -> Tuple[bool, str, float]:
    """
    Attempt to update a page with retries on failure.
    
    Returns:
        (success: bool, message: str)
    """
    last_error = None
    
    duration_s: float = 0.0

    # Quiet mode: suppress print output from individual update scripts so this
    # progress UI stays clean (Scoop-style).
    quiet = True

    for attempt in range(max_retries + 1):
        try:
            # Scoop-ish: show one line per attempt, update it with final status.
            if attempt == 0:
                print(f"{_box('pending')} {name}", end="", flush=True)
            else:
                print(
                    f"{_box('pending')} {name}  (retry {attempt + 1}/{max_retries + 1})",
                    end="",
                    flush=True,
                )
            
            t0 = time.perf_counter()
            if quiet:
                ok, out_txt, err_txt = _run_quiet(update_func)
                if not ok:
                    # Re-raise with a helpful tail for the UI/summary.
                    raise RuntimeError(_tail(err_txt or out_txt) or "Updater failed")  # noqa: TRY003
            else:
                update_func()
            duration_s = time.perf_counter() - t0
            # Overwrite the same line with success and a duration.
            print(f"\r{_box('ok')} {name}  ({duration_s:.2f}s)".ljust(90))
            return (True, "Success", duration_s)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt < max_retries:
                # Wait before retrying
                print(f"\r{_box('fail')} {name}  (retrying in {RETRY_DELAY_SECONDS}s)".ljust(90))
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                # Final attempt failed
                print(f"\r{_box('fail')} {name}  Error: {last_error}".ljust(90))
                return (False, last_error, duration_s)
    
    return (False, last_error or "Unknown error", duration_s)


# Recommended specific frequencies per band (display + config persistence).
# We keep the *band name* inside the persisted string so the website band filter
# (LIKE %2m%) continues to work even when the frequency is a concrete MHz value.
#
# Format: "<MHz> (<band>)"
AMATEUR_BAND_RECOMMENDED_FREQ = {
    # HF
    "80m": "3.580 MHz (80m)",
    "40m": "7.040 MHz (40m)",
    "30m": "10.147 MHz (30m)",
    "20m": "14.105 MHz (20m)",
    "17m": "18.105 MHz (17m)",
    "15m": "21.105 MHz (15m)",
    "12m": "24.930 MHz (12m)",
    "10m": "28.120 MHz (10m)",
    # VHF/UHF
    "6m": "50.200 MHz (6m)",
    "2m": "144.800 MHz (2m)",
    "70cm": "433.500 MHz (70cm)",
}

# Keep a grouped view for the CLI picker order.
AMATEUR_BANDS = {
    "HF": ["80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"],
    "VHF": ["6m", "2m"],
    "UHF": ["70cm"],
}


def get_user_callsign_and_frequency() -> Tuple[Optional[str], Optional[str]]:
    """
    Get user's radio call sign and frequency.
    Returns (callsign, frequency) tuple.
    """
    global _user_callsign, _user_frequency
    
    # If we already asked, use cached values
    if _user_callsign is not None and _user_frequency is not None:
        return (_user_callsign, _user_frequency)
    
    print()
    print("=" * 60)
    print("RADIO SETUP")
    print("=" * 60)
    print("Enter your amateur radio call sign and frequency")
    print("(This will be displayed in the header)")
    print()
    
    # Get call sign
    while True:
        try:
            callsign_input = input("Enter your call sign (e.g., 'G1ABC' or 'M0XYZ'): ").strip().upper()
            if callsign_input:
                # Basic validation - should start with G, M, or 2E for UK
                if callsign_input[0] in ['G', 'M', '2'] or len(callsign_input) >= 3:
                    _user_callsign = callsign_input
                    print(f"{_GLYPH_OK} Call sign: {_user_callsign}")
                    break
                else:
                    print(f"{_GLYPH_FAIL} Invalid call sign format. Please try again.")
            else:
                print(f"{_GLYPH_FAIL} Call sign cannot be empty. Please try again.")
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_GLYPH_FAIL} Input cancelled. Skipping call sign.")
            _user_callsign = None
            _user_frequency = None
            return (None, None)
    
    # Get frequency
    print()
    print("Select frequency band:")
    print()
    
    # Display available bands
    band_options = []
    option_num = 1
    
    print("HF Bands:")
    for band_name in AMATEUR_BANDS["HF"]:
        freq_label = AMATEUR_BAND_RECOMMENDED_FREQ.get(band_name, band_name)
        print(f"  {option_num}. {band_name:4s} - {freq_label}")
        band_options.append(("HF", band_name, freq_label))
        option_num += 1
    
    print()
    print("VHF Bands:")
    for band_name in AMATEUR_BANDS["VHF"]:
        freq_label = AMATEUR_BAND_RECOMMENDED_FREQ.get(band_name, band_name)
        print(f"  {option_num}. {band_name:4s} - {freq_label}")
        band_options.append(("VHF", band_name, freq_label))
        option_num += 1
    
    print()
    print("UHF Bands:")
    for band_name in AMATEUR_BANDS["UHF"]:
        freq_label = AMATEUR_BAND_RECOMMENDED_FREQ.get(band_name, band_name)
        print(f"  {option_num}. {band_name:4s} - {freq_label}")
        band_options.append(("UHF", band_name, freq_label))
        option_num += 1
    
    print()
    print(f"  {option_num}. Enter custom frequency")
    
    while True:
        try:
            choice = input(f"\nSelect option (1-{option_num}): ").strip()
            if choice.isdigit():
                choice_num = int(choice)
                if 1 <= choice_num <= len(band_options):
                    band_type, band_name, freq_label = band_options[choice_num - 1]
                    # Persist the concrete frequency string.
                    _user_frequency = str(freq_label)
                    print(f"{_GLYPH_OK} Frequency: {_user_frequency}")
                    break
                elif choice_num == option_num:
                    # Custom frequency
                    custom_freq = input("Enter frequency (e.g., '145.500 MHz'): ").strip()
                    if custom_freq:
                        _user_frequency = custom_freq
                        print(f"{_GLYPH_OK} Frequency: {_user_frequency}")
                        break
                    else:
                        print(f"{_GLYPH_FAIL} Frequency cannot be empty. Please try again.")
                else:
                    print(f"{_GLYPH_FAIL} Invalid option. Please enter 1-{option_num}.")
            else:
                print(f"{_GLYPH_FAIL} Invalid input. Please enter a number 1-{option_num}.")
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_GLYPH_FAIL} Input cancelled. Skipping frequency.")
            _user_frequency = None
            break
    
    # Save call sign (and optional frequency) to a config file for the viewer to access.
    # We persist the callsign even if the user skips frequency so the start page can
    # still render "{{users callsign}}" correctly.
    if _user_callsign:
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        config_file = root / "radio_config.json"
        config_data = {"callsign": _user_callsign}
        if _user_frequency:
            config_data["frequency"] = _user_frequency
        config_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    
    return (_user_callsign, _user_frequency)


# ISO 3166-1 alpha-3 to alpha-2 country code mapping
# (alpha-3 is what we store, alpha-2 is what wttr.in uses)
# Note: wttr.in prefers "UK" over "GB" for better compatibility
ALPHA3_TO_ALPHA2 = {
    "GBR": "UK",  # Use UK instead of GB for better wttr.in compatibility
    "USA": "US",
    "CAN": "CA",
    "AUS": "AU",
    "NZL": "NZ",
    "IRL": "IE",
    "FRA": "FR",
    "DEU": "DE",
    "ESP": "ES",
    "ITA": "IT",
    "NLD": "NL",
    "BEL": "BE",
    "PRT": "PT",
    "CHE": "CH",
    "AUT": "AT",
    "SWE": "SE",
    "NOR": "NO",
    "DNK": "DK",
    "FIN": "FI",
    "POL": "PL",
    "CZE": "CZ",
    "HUN": "HU",
    "ROU": "RO",
    "GRC": "GR",
    "TUR": "TR",
    "RUS": "RU",
    "UKR": "UA",
    "JPN": "JP",
    "CHN": "CN",
    "KOR": "KR",
    "IND": "IN",
    "THA": "TH",
    "SGP": "SG",
    "MYS": "MY",
    "IDN": "ID",
    "PHL": "PH",
    "VNM": "VN",
    "ZAF": "ZA",
    "EGY": "EG",
    "KEN": "KE",
    "MEX": "MX",
    "BRA": "BR",
    "ARG": "AR",
    "CHL": "CL",
    "COL": "CO",
    "PER": "PE",
    "VEN": "VE",
    "ISR": "IL",
    "SAU": "SA",
    "ARE": "AE",
    "QAT": "QA",
    "KWT": "KW",
}

# ISO 3166-1 alpha-3 country codes (common countries) - for display
COUNTRIES = {
    "GBR": "United Kingdom",
    "USA": "United States",
    "CAN": "Canada",
    "AUS": "Australia",
    "NZL": "New Zealand",
    "IRL": "Ireland",
    "FRA": "France",
    "DEU": "Germany",
    "ESP": "Spain",
    "ITA": "Italy",
    "NLD": "Netherlands",
    "BEL": "Belgium",
    "PRT": "Portugal",
    "CHE": "Switzerland",
    "AUT": "Austria",
    "SWE": "Sweden",
    "NOR": "Norway",
    "DNK": "Denmark",
    "FIN": "Finland",
    "POL": "Poland",
    "CZE": "Czech Republic",
    "HUN": "Hungary",
    "ROU": "Romania",
    "GRC": "Greece",
    "TUR": "Turkey",
    "RUS": "Russia",
    "UKR": "Ukraine",
    "JPN": "Japan",
    "CHN": "China",
    "KOR": "South Korea",
    "IND": "India",
    "THA": "Thailand",
    "SGP": "Singapore",
    "MYS": "Malaysia",
    "IDN": "Indonesia",
    "PHL": "Philippines",
    "VNM": "Vietnam",
    "ZAF": "South Africa",
    "EGY": "Egypt",
    "KEN": "Kenya",
    "MEX": "Mexico",
    "BRA": "Brazil",
    "ARG": "Argentina",
    "CHL": "Chile",
    "COL": "Colombia",
    "PER": "Peru",
    "VEN": "Venezuela",
    "ISR": "Israel",
    "SAU": "Saudi Arabia",
    "ARE": "United Arab Emirates",
    "QAT": "Qatar",
    "KWT": "Kuwait",
}


def get_user_location() -> Optional[Tuple[str, str]]:
    """
    Get user's location - either manually entered or auto-detected.
    Returns (name, query) tuple like ("London", "London,GBR") or None.
    """
    global _user_location
    
    # If we already asked, use cached value
    if _user_location is not None:
        return _user_location
    
    print()
    print("=" * 60)
    print("LOCATION SETUP")
    print("=" * 60)
    print("Would you like to enter your location manually?")
    print("(This will be used for page 101 weather)")
    print("  Y = Enter location manually")
    print("  N = Use automatic detection")
    print()
    
    while True:
        try:
            response = input("Enter location manually? (Y/N): ").strip().upper()
            if response == 'Y':
                print()
                location_input = input("Enter your city/location (e.g., 'London', 'Los Angeles', 'Sydney'): ").strip()
                if location_input:
                    # Now ask for country
                    print()
                    print("Select your country:")
                    print()
                    
                    # Display countries in columns for better readability
                    country_list = sorted(COUNTRIES.items(), key=lambda x: x[1])  # Sort by country name
                    country_codes = []
                    option_num = 1
                    
                    # Display in 2 columns
                    for i in range(0, len(country_list), 2):
                        code1, name1 = country_list[i]
                        line = f"  {option_num:2d}. {name1:<30} ({code1})"
                        country_codes.append((code1, name1))
                        option_num += 1
                        
                        if i + 1 < len(country_list):
                            code2, name2 = country_list[i + 1]
                            line += f"  {option_num:2d}. {name2:<30} ({code2})"
                            country_codes.append((code2, name2))
                            option_num += 1
                        print(line)
                    
                    print()
                    print(f"  {option_num}. Enter custom country code")
                    
                    while True:
                        try:
                            country_choice = input(f"\nSelect country (1-{option_num}): ").strip()
                            if country_choice.isdigit():
                                choice_num = int(country_choice)
                                if 1 <= choice_num <= len(country_codes):
                                    country_code_alpha3, country_name = country_codes[choice_num - 1]
                                    # Convert alpha-3 to alpha-2 for weather API (wttr.in uses alpha-2)
                                    country_code_alpha2 = ALPHA3_TO_ALPHA2.get(country_code_alpha3, country_code_alpha3)
                                    query = f"{location_input},{country_code_alpha2}"
                                    name = location_input.strip()
                                    _user_location = (name, query)
                                    print(f"{_GLYPH_OK} Using location: {name}, {country_name} (ISO: {country_code_alpha3})")
                                    return _user_location
                                elif choice_num == option_num:
                                    # Custom country code
                                    custom_code = input("Enter ISO 3166-1 alpha-3 country code (e.g., 'USA', 'GBR'): ").strip().upper()
                                    if len(custom_code) == 3 and custom_code.isalpha():
                                        # Convert alpha-3 to alpha-2 for weather API
                                        country_code_alpha2 = ALPHA3_TO_ALPHA2.get(custom_code, custom_code)
                                        query = f"{location_input},{country_code_alpha2}"
                                        name = location_input.strip()
                                        _user_location = (name, query)
                                        print(f"{_GLYPH_OK} Using location: {name} (ISO: {custom_code})")
                                        return _user_location
                                    else:
                                        print(f"{_GLYPH_FAIL} Invalid country code. Must be 3 letters (e.g., 'USA', 'GBR').")
                                else:
                                    print(f"{_GLYPH_FAIL} Invalid option. Please enter 1-{option_num}.")
                            else:
                                print(f"{_GLYPH_FAIL} Invalid input. Please enter a number 1-{option_num}.")
                        except (EOFError, KeyboardInterrupt):
                            print(f"\n{_GLYPH_FAIL} Input cancelled.")
                            return None
                else:
                    print(f"{_GLYPH_FAIL} Invalid input. Please try again.")
            elif response == 'N':
                print("Using automatic location detection...")
                # Use auto-detection from update_weather_page
                from .update_weather_page import get_location_from_ip, get_location_from_timezone
                
                location = None
                method = "unknown"
                
                # Try IP geolocation first
                print("  Trying IP geolocation...", end=" ")
                location = get_location_from_ip()
                if location:
                    method = "IP geolocation"
                    print(_GLYPH_OK)
                else:
                    print(_GLYPH_FAIL)
                    # Try timezone-based approximation
                    print("  Trying timezone-based detection...", end=" ")
                    location = get_location_from_timezone()
                    if location:
                        method = "timezone"
                        print(_GLYPH_OK)
                    else:
                        print(_GLYPH_FAIL)
                
                if location:
                    detected_grid = None
                    if len(location) == 4:
                        lat, lon, city, detected_grid = location
                        if detected_grid:
                            print(f"  Maidenhead Grid: {detected_grid}")
                    else:
                        lat, lon, city = location
                    # Extract city name from "City,Country" format
                    city_name = city.split(",")[0] if "," in city else city
                    # Try to detect country from the location data
                    country_part = city.split(",")[1] if "," in city else ""
                    # Default to UK if country not detected or UK detected
                    if not country_part or "UK" in country_part.upper() or "United Kingdom" in country_part:
                        query = f"{city_name},UK"  # Use UK for better wttr.in compatibility
                    else:
                        # Try to find matching country code
                        country_upper = country_part.upper().strip()
                        # Simple mapping for common cases
                        if "US" in country_upper or "USA" in country_upper or "United States" in country_part:
                            query = f"{city_name},US"
                        elif "CA" in country_upper or "CAN" in country_upper or "Canada" in country_part:
                            query = f"{city_name},CA"
                        else:
                            # Default to GB for UK locations, otherwise try the country as-is
                            query = f"{city_name},{country_part}"
                    _user_location = (city_name, query)
                    
                    # Optionally save detected grid to config (only if not already set)
                    if detected_grid and _user_callsign:
                        persist_radio_config(_user_callsign, _user_frequency, detected_grid)
                    
                    print(f"{_GLYPH_OK} Detected location via {method}: {city_name}")
                    return _user_location
                else:
                    print(f"{_GLYPH_FAIL} Could not detect location automatically.")
                    print("  Using default: London, UK")
                    _user_location = ("London", "London,UK")  # Use UK instead of GB
                    return _user_location
            else:
                print(f"{_GLYPH_FAIL} Please enter Y for Yes or N for No.")
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_GLYPH_FAIL} Input cancelled. Using default: London, UK")
            _user_location = ("London", "London,UK")  # Use UK instead of GB
            return _user_location


def update_all() -> None:
    """Update all live data pages with retry logic."""
    global _user_location
    
    print("=" * 60)
    print("CEEFAX - Updating All Live Data Pages")
    print(f"Retry: {MAX_RETRIES} attempts, {RETRY_DELAY_SECONDS}s delay")
    print(f"Progress: {_legend()}")
    print("=" * 60)
    
    # Get user call sign and frequency BEFORE location
    user_callsign, user_frequency = get_user_callsign_and_frequency()
    
    # Get user location after call sign/frequency
    user_loc = get_user_location()
    
    print()
    print("=" * 60)
    print("UPDATING PAGES")
    print("=" * 60)
    print()

    # Create wrapper for Local Weather that uses user location
    def update_local_weather_with_location():
        update_weather_page.main(user_location=user_loc)

    updates = [
        ("UK Weather (101)", update_uk_weather_page.main),
        ("Local Weather (102)", update_local_weather_with_location),
        ("Weather Map (103)", update_weather_map_page.main),
        ("News Headlines (200)", update_news_page.main),
        ("World News (201)", update_world_news_page.main),
        ("UK News (202)", update_uk_news_page.main),
        ("Sports Headlines (300) & League Tables (302, 303)", update_football_page.main),
        ("Football Live Scores (301)", update_football_scores_page.main),
        ("Fixtures & Results (304)", update_fixtures_page.main),
        ("Other Sports (305)", update_other_sports_page.main),
        ("Exchange Rates (400)", update_exchange_rates_page.main),
        ("Travel Info (401)", update_travel_page.main),
        ("Lottery Results (402)", update_lottery_page.main),
        ("Fact of the Day (500)", update_fact_page.main),
        ("Quote of the Day (501)", update_quote_page.main),
        ("On This Day (502)", update_on_this_day_page.main),
        ("TV Highlights (503.1/503.2)", update_tv_guide_page.main),
        ("Film Picks (504)", update_film_picks_page.main),
        ("Joke of the Day (600)", update_joke_page.main),
        ("Callsign Info (700)", update_callsign_page.main),
        ("ASCII Art (601)", update_ascii_art_page.main),
        ("Daily Quiz (602)", update_quiz_page.main),
        ("About (900)", update_about_page.main),
    ]

    success_count = 0
    error_count = 0
    failed_updates = []

    # Changelog entries for this run (persisted to activity_log.json)
    run_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_entries: List[Dict[str, Any]] = []
    update_durations: List[float] = []
    update_ok: Dict[str, bool] = {}

    for name, update_func in updates:
        success, message, duration_s = update_with_retry(name, update_func)
        update_ok[name] = success
        if success:
            success_count += 1
            if duration_s > 0:
                update_durations.append(duration_s)
            run_entries.append(
                {"ts": run_ts, "msg": f"{name} OK ({duration_s:.2f}s)"}
            )
        else:
            error_count += 1
            failed_updates.append((name, message))
            run_entries.append({"ts": run_ts, "msg": f"{name} FAIL"})

    print()
    print("=" * 60)
    print(f"Update complete: {success_count} succeeded, {error_count} failed")
    if failed_updates:
        print()
        print("Failed updates:")
        for name, error in failed_updates:
            print(f"  - {name}: {error[:60]}...")
    print("=" * 60)

    # Update System Logs page (902) with changelog + performance metrics.
    avg_update = (sum(update_durations) / len(update_durations)) if update_durations else None
    mem_bytes = update_system_logs_page.get_process_memory_bytes()
    update_system_logs_page.write_system_logs_page(
        run_entries=run_entries,
        avg_update_seconds=avg_update,
        process_memory_bytes=mem_bytes,
    )

    # Update System Status page (901) with data-source health derived from the run.
    def _all_ok(keys: List[str]) -> Tuple[bool, str]:
        ok = all(update_ok.get(k, False) for k in keys)
        return (ok, "OK" if ok else "FAIL")

    feed_status = {
        "Weather (wttr.in)": _all_ok(["UK Weather (101)", "Local Weather (102)", "Weather Map (103)"]),
        "News (BBC RSS)": _all_ok(["News Headlines (200)", "World News (201)", "UK News (202)"]),
        "Sport (BBC)": _all_ok(
            [
                "Sports Headlines (300) & League Tables (302, 303)",
                "Football Live Scores (301)",
                "Fixtures & Results (304)",
                "Other Sports (305)",
            ]
        ),
        "Exchange Rates": _all_ok(["Exchange Rates (400)"]),
        "Travel (TFL)": _all_ok(["Travel Info (401)"]),
        "TV (TV Guide)": _all_ok(["TV Highlights (503.1/503.2)"]),
        "Film Picks": _all_ok(["Film Picks (504)"]),
        "Lottery": _all_ok(["Lottery Results (402)"]),
        "Entertainment APIs": _all_ok(
            ["Fact of the Day (500)", "Quote of the Day (501)", "On This Day (502)", "Joke of the Day (600)", "Daily Quiz (602)"]
        ),
        "PSK Reporter": _all_ok(["Callsign Info (700)"]),
    }
    update_system_status_page.write_system_status_page(feed_status=feed_status, last_update_iso=run_ts)


if __name__ == "__main__":
    try:
        update_all()
    except KeyboardInterrupt:
        print("\n\nUpdate cancelled by user")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\n\nFatal error: {exc}")
        sys.exit(1)

