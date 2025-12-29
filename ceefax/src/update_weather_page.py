"""
Update page 102 with local weather based on user's IP location.

Uses IP geolocation to find nearby towns and displays weather for them.
"""
import json
import time
from pathlib import Path
from typing import List, Tuple, Optional

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .weather_map import fetch_wttr, WeatherSummary


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)

def _center_pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.center(PAGE_WIDTH)

def _wrap_center(text: str, width: int = PAGE_WIDTH) -> List[str]:
    words = text.split()
    if not words:
        return [_center_pad("")]
    lines: List[str] = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
            continue
        if len(cur) + 1 + len(w) <= width:
            cur = f"{cur} {w}"
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return [(_center_pad(l) if len(l) <= width else _pad(l)) for l in lines]


def _ascii_icon(desc: str) -> List[str]:
    """
    Return 3-line ASCII weather icon matching wttr.in format.
    These are the actual icons used by wttr.in for weather display.
    """
    desc_lower = desc.lower()
    
    # Partly cloudy must be checked BEFORE generic cloud/overcast
    if "partly" in desc_lower and "cloud" in desc_lower:
        return [
            "   \\  /      ",
            " _ /\"\".-.    ",
            "   \\_(   ).  ",
            "    /(___(__) "
        ]
    
    # Clear/Sunny
    if "sun" in desc_lower or "clear" in desc_lower:
        return [
            "    \\   /    ",
            "     .-.     ",
            "  -- (   ) -- ",
            "     `-’     ",
        ]
    
    # Rain/Shower
    if "rain" in desc_lower or "shower" in desc_lower or "drizzle" in desc_lower:
        return [
            "     .-.     ",
            "    (   ).   ",
            "   (___(__)  ",
            "    ‘ ‘ ‘ ‘  ",
        ]
    
    # Cloudy/Overcast
    if "cloud" in desc_lower or "overcast" in desc_lower:
        return [
            "     .--.    ",
            "  .-(    ).  ",
            " (___.__)__) ",
            "             ",
        ]
    
    # Snow
    if "snow" in desc_lower or "sleet" in desc_lower:
        return [
            "     .-.     ",
            "    (   )    ",
            "   (___(__)  ",
            "    * * * *  ",
        ]
    
    # Fog/Mist
    if "fog" in desc_lower or "mist" in desc_lower or "haze" in desc_lower:
        return [
            " _ - _ - _ - ",
            "  _ - _ - _  ",
            " _ - _ - _ - ",
            "             ",
        ]
    
    # Default (cloudy)
    return [
        "     .--.    ",
        "  .-(    ).  ",
        " (___.__)__) ",
        "             ",
    ]


def get_location_from_ip() -> Optional[Tuple[float, float, str, Optional[str]]]:
    """
    Get user's location from their IP address using whatsmylocator.co.uk-style approach.
    Uses reliable IP geolocation and calculates Maidenhead grid square.
    Returns (latitude, longitude, city_name, maidenhead_grid) or None if all methods fail.
    """
    import sys
    from pathlib import Path
    
    # Add ceefaxweb to path to import maidenhead functions
    repo_root = Path(__file__).resolve().parent.parent.parent
    ceefaxweb_path = repo_root / "ceefaxweb"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    
    try:
        from ceefaxweb.maidenhead import latlon_to_maidenhead
    except ImportError:
        # Fallback if import fails
        latlon_to_maidenhead = None
    
    # Try multiple IP geolocation services as fallbacks
    # Using more reliable services similar to whatsmylocator.co.uk approach
    services = [
        # Service 1: ip-api.com (free, no API key, reliable)
        {
            "url": "http://ip-api.com/json/?fields=lat,lon,city,country,regionName",
            "parser": lambda d: (
                d.get("lat"),
                d.get("lon"),
                f"{d.get('city', 'Unknown')}, {d.get('regionName', '')}, {d.get('country', '')}".strip(", "),
            ) if d.get("status") == "success" and d.get("lat") and d.get("lon") else None
        },
        # Service 2: ipapi.co (free tier, reliable)
        {
            "url": "https://ipapi.co/json/",
            "parser": lambda d: (
                float(d.get("latitude", 0)) if d.get("latitude") else None,
                float(d.get("longitude", 0)) if d.get("longitude") else None,
                f"{d.get('city', 'Unknown')}, {d.get('region', '')}, {d.get('country_name', '')}".strip(", "),
            ) if d.get("latitude") and d.get("longitude") else None
        },
        # Service 3: ip-api.com alternative endpoint
        {
            "url": "https://ip-api.com/json/",
            "parser": lambda d: (
                d.get("lat"),
                d.get("lon"),
                f"{d.get('city', 'Unknown')}, {d.get('regionName', '')}, {d.get('country', '')}".strip(", "),
            ) if d.get("status") == "success" and d.get("lat") and d.get("lon") else None
        },
    ]
    
    for service in services:
        try:
            resp = requests.get(service["url"], timeout=5, headers={"User-Agent": "CeefaxStation/1.0"})
            resp.raise_for_status()
            data = resp.json()
            
            # Handle array responses (some services return arrays)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            
            result = service["parser"](data)
            if result and result[0] is not None and result[1] is not None:
                lat, lon, city = result
                # Calculate Maidenhead grid square from coordinates
                grid = None
                if latlon_to_maidenhead:
                    try:
                        grid = latlon_to_maidenhead(float(lat), float(lon), precision=6)
                    except Exception:  # noqa: BLE001
                        pass
                return (float(lat), float(lon), city, grid)
        except Exception:  # noqa: BLE001
            continue
    
    return None


def get_location_from_timezone() -> Optional[Tuple[float, float, str]]:
    """
    Approximate location based on system timezone.
    Returns (latitude, longitude, city_name) or None if timezone detection fails.
    Uses UTC offset to approximate region.
    """
    try:
        import time
        from datetime import datetime
        
        # Get UTC offset in hours
        now = datetime.now()
        utc_offset = now.astimezone().utcoffset()
        if utc_offset:
            offset_hours = utc_offset.total_seconds() / 3600
        else:
            # Fallback: use time.timezone
            offset = time.timezone if (time.daylight == 0) else time.altzone
            offset_hours = -offset / 3600  # Note: time.timezone is opposite sign
        
        # Map UTC offsets to approximate major cities
        # This is a rough approximation based on common timezones
        # Check in order of specificity
        offset_ranges = [
            # UK/Ireland (UTC+0 or UTC+1 for BST) - check first for UK users
            ((0, 1), ("London", 51.5074, -0.1278, "UK")),
            # Eastern US (UTC-5 or UTC-4 for DST)
            ((-5, -4), ("New York", 40.7128, -74.0060, "")),
            # Central US (UTC-6 or UTC-5)
            ((-6, -5), ("Chicago", 41.8781, -87.6298, "")),
            # Pacific US (UTC-8 or UTC-7)
            ((-8, -7), ("Los Angeles", 34.0522, -118.2437, "")),
            # Western/Central Europe (UTC+1 or UTC+2 for DST)
            ((1, 2), ("Paris", 48.8566, 2.3522, "")),
            # Japan (UTC+9)
            ((9, 9), ("Tokyo", 35.6762, 139.6503, "")),
            # China (UTC+8)
            ((8, 8), ("Shanghai", 31.2304, 121.4737, "")),
            # Australia East (UTC+10 or UTC+11)
            ((10, 11), ("Sydney", -33.8688, 151.2093, "")),
        ]
        
        # Check if offset matches any known region
        for (min_offset, max_offset), (city, lat, lon, country) in offset_ranges:
            if min_offset <= offset_hours <= max_offset:
                country_suffix = f",{country}" if country else ""
                return (lat, lon, f"{city}{country_suffix}")
        
        # Default: if offset is close to UK time (UTC+0 or UTC+1), assume UK
        if -1 <= offset_hours <= 2:
            return (51.5074, -0.1278, "London,UK")
            
    except Exception:  # noqa: BLE001
        pass
    
    return None


def get_nearby_towns(lat: float, lon: float, base_city: str, count: int = 6) -> List[Tuple[str, str]]:
    """
    Get nearby towns/cities for weather display.
    
    For UK locations, returns a mix of the user's city and nearby major towns.
    For non-UK, falls back to major UK cities.
    """
    # Major UK towns/cities that are likely nearby any UK location
    # Note: Bristol, Leeds, Sheffield, Liverpool removed per user request
    uk_towns = [
        ("London", "London,UK"),
        ("Birmingham", "Birmingham,UK"),
        ("Manchester", "Manchester,UK"),
        ("Newcastle", "Newcastle upon Tyne,UK"),
        ("Nottingham", "Nottingham,UK"),
        ("Leicester", "Leicester,UK"),
        ("Coventry", "Coventry,UK"),
        ("Cardiff", "Cardiff,UK"),
        ("Edinburgh", "Edinburgh,UK"),
        ("Glasgow", "Glasgow,UK"),
        ("Belfast", "Belfast,UK"),
        ("Southampton", "Southampton,UK"),
        ("Portsmouth", "Portsmouth,UK"),
        ("Brighton", "Brighton,UK"),
        ("Reading", "Reading,UK"),
        ("Oxford", "Oxford,UK"),
        ("Cambridge", "Cambridge,UK"),
        ("Norwich", "Norwich,UK"),
        ("Exeter", "Exeter,UK"),
        ("Plymouth", "Plymouth,UK"),
        ("Bath", "Bath,UK"),
        ("Salisbury", "Salisbury,UK"),
        ("Yeovil", "Yeovil,UK"),
        ("Taunton", "Taunton,UK"),
        ("Frome", "Frome,UK"),
    ]
    
    # If we have a base city, try to include it first
    result = []
    if base_city and "UK" in base_city:
        # Extract city name from "City,UK" format
        city_name = base_city.split(",")[0]
        result.append((city_name, base_city))
    
    # Add nearby towns (for now, we'll use a simple approach:
    # include the user's city + a selection of nearby major towns)
    # In a more sophisticated version, you could calculate distances
    # and pick the closest ones
    
    # Add a mix of nearby towns (prioritizing those likely to be nearby)
    for town_name, town_query in uk_towns:
        if len(result) >= count:
            break
        # Skip if already added (user's city)
        if town_query not in [q for _, q in result]:
            result.append((town_name, town_query))
    
    return result[:count]


def build_single_location_weather_page(name: str, query: str) -> List[str]:
    """Build a single location weather page with detailed forecast."""
    lines: List[str] = []
    
    try:
        summary: WeatherSummary = fetch_wttr(query)
        icon_lines = _ascii_icon(summary.description)

        # Centered title
        lines.append(_center_pad(""))
        lines.append(_center_pad(f"{name.upper()} WEATHER"))
        lines.append(_center_pad(""))

        # Centered current conditions block
        lines.append(_center_pad(f"Temp {summary.temp_c}C (feels {summary.feels_like_c}C)"))
        lines.append(_center_pad(""))

        # Centered icon (no box)
        for icon_line in icon_lines:
            lines.append(_center_pad(icon_line))

        lines.append(_center_pad(""))
        lines.append(_center_pad(summary.description.upper()[:PAGE_WIDTH]))
        lines.append(_center_pad(f"Wind {summary.wind_kph} km/h {summary.wind_dir}".upper()[:PAGE_WIDTH]))
        lines.append(_center_pad(""))
        
        # Detailed forecast
        # Today
        today_text = f"Today: {summary.today_desc or summary.description}"
        if summary.today_max != "?" and summary.today_min != "?":
            today_text += f" Max {summary.today_max}C, Min {summary.today_min}C."
        else:
            today_text += f" Temp {summary.temp_c}C."
        lines.extend(_wrap_center(today_text))
        
        # Tonight
        if summary.tonight_desc:
            tonight_text = f"Tonight: {summary.tonight_desc}"
            if summary.tonight_min != "?":
                tonight_text += f" Min around {summary.tonight_min}C."
            lines.extend(_wrap_center(tonight_text))
        else:
            tonight_text = f"Tonight: Mostly {summary.description.lower()}"
            if summary.today_min != "?":
                tonight_text += f" Min around {summary.today_min}C."
            lines.extend(_wrap_center(tonight_text))
        
        # Tomorrow
        if summary.tomorrow_desc:
            tomorrow_text = f"Tomorrow: {summary.tomorrow_desc}"
            lines.extend(_wrap_center(tomorrow_text))
        else:
            lines.append(_center_pad("Tomorrow: Forecast unavailable"))
        
    except Exception as e:  # noqa: BLE001
        lines.append(_center_pad(""))
        lines.append(_center_pad(name.upper() + " WEATHER"))
        lines.append(_center_pad(""))
        lines.append(_center_pad(f"Error fetching data: {str(e)[:PAGE_WIDTH-20]}"))

    lines.append(_center_pad(""))
    lines.append(_center_pad("Data source: wttr.in (unofficial)"))

    return lines[:PAGE_HEIGHT]

def build_local_weather_page(cities: List[Tuple[str, str]]) -> List[str]:
    """Build local weather page using same format as page 101."""
    lines: List[str] = []
    lines.append(_pad("LOCAL WEATHER FORECAST"))

    for name, query in cities:
        try:
            summary: WeatherSummary = fetch_wttr(query)
            icon_lines = _ascii_icon(summary.description)

            lines.append(_pad(""))
            lines.append(_pad(name.upper().center(PAGE_WIDTH)))

            # Format with boxed icon like wttr.in: Temp, then boxed icon, then description and wind
            temp_line = f"                 Temp {summary.temp_c}C (feels {summary.feels_like_c}C)             "
            lines.append(_pad(temp_line))
            lines.append(_pad(""))

            # Box the icon with box-drawing characters (like wttr.in)
            # Icon lines are typically 12-14 chars wide, box adds 2 chars on each side
            # Find the widest icon line to determine box width
            max_icon_width = max(len(line) for line in icon_lines)
            box_width = max(14, max_icon_width + 2)  # At least 14, or icon width + 2
            
            # Top of box
            top_box = "┌" + "─" * (box_width - 2) + "┐"
            lines.append(_pad(top_box.center(PAGE_WIDTH)))
            
            # Icon lines inside box (centered within the box)
            for icon_line in icon_lines:
                # Center the icon line within the box
                icon_padding = (box_width - 2 - len(icon_line)) // 2
                padded_icon = " " * icon_padding + icon_line + " " * (box_width - 2 - len(icon_line) - icon_padding)
                boxed_line = "│" + padded_icon + "│"
                lines.append(_pad(boxed_line.center(PAGE_WIDTH)))
            
            # Bottom of box
            bottom_box = "└" + "─" * (box_width - 2) + "┘"
            lines.append(_pad(bottom_box.center(PAGE_WIDTH)))
            
            # Description and wind below the box
            lines.append(_pad(""))
            desc_snippet = summary.description[: max(0, PAGE_WIDTH - 5)]
            lines.append(_pad(desc_snippet.center(PAGE_WIDTH)))
            wind_text = f"Wind {summary.wind_kph} km/h {summary.wind_dir}"
            lines.append(_pad(wind_text.center(PAGE_WIDTH)))
        except Exception:  # noqa: BLE001
            lines.append(_pad(""))
            lines.append(_pad(name.upper().center(PAGE_WIDTH)))
            lines.append(_pad(f"{name}: Error fetching data"))

    lines.append(_pad(""))
    lines.append(_pad("Data source: wttr.in (unofficial)"))

    return lines[:PAGE_HEIGHT]


def main(user_location: Optional[Tuple[str, str]] = None) -> None:
    """
    Fetch live weather for user's location (from IP or manually entered).
    Write into page 102 (single page, no subpages).
    
    Args:
        user_location: Optional tuple of (name, query) for user's manually entered location.
                      If provided, this will be used instead of IP detection.
    """
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"

    # Determine user's location
    if user_location:
        # Use manually entered location
        name, query = user_location
        print(f"Using manually entered location: {name} (query: {query})")
    else:
        # Get user's location - try multiple methods
        location = None
        method = "unknown"
        
        # Method 1: Try IP geolocation (multiple services)
        location = get_location_from_ip()
        if location:
            method = "IP geolocation"
            lat, lon, base_city, grid = location
            if grid:
                print(f"Detected location via {method}: {base_city} (lat: {lat}, lon: {lon}, grid: {grid})")
            else:
                print(f"Detected location via {method}: {base_city} (lat: {lat}, lon: {lon})")
        else:
            # Method 2: Try timezone-based approximation
            location = get_location_from_timezone()
            if location:
                method = "timezone"
                if len(location) == 4:
                    lat, lon, base_city, grid = location
                else:
                    lat, lon, base_city = location
                    grid = None
                print(f"Detected location via {method}: {base_city} (lat: {lat}, lon: {lon})")
        
        if location:
            if len(location) == 4:
                lat, lon, base_city, grid = location
            else:
                lat, lon, base_city = location
                grid = None
            # Extract city name and create query
            city_name = base_city.split(",")[0] if "," in base_city else base_city
            # Try to determine country code from location
            country_part = base_city.split(",")[1] if "," in base_city else ""
            if not country_part or "UK" in country_part.upper() or "United Kingdom" in country_part:
                query = f"{city_name},GB"
            else:
                # Try to find matching country code
                country_upper = country_part.upper().strip()
                if "US" in country_upper or "USA" in country_upper or "United States" in country_part:
                    query = f"{city_name},US"
                elif "CA" in country_upper or "CAN" in country_upper or "Canada" in country_part:
                    query = f"{city_name},CA"
                else:
                    query = f"{city_name},{country_part}" if country_part else f"{city_name},GB"
            name = city_name
        else:
            print("Could not detect location (tried IP geolocation and timezone), using default: London, UK")
            name = "London"
            query = "London,GB"

    # Create only ONE page (102.json) with user's location
    page_lines = build_single_location_weather_page(name, query)
    page_file = pages_dir / "102.json"
    page_data = {
        "page": "102",
        "title": f"{name} Weather",
        "timestamp": "From wttr.in (live)",
        "subpage": 1,
        "content": page_lines,
    }
    page_file.write_text(json.dumps(page_data, indent=2), encoding="utf-8")
    print(f"Updated {page_file} with {name} weather")


if __name__ == "__main__":
    main()
