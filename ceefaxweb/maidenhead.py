from __future__ import annotations

import math


def maidenhead_to_latlon(grid: str) -> tuple[float, float] | None:
    """
    Convert Maidenhead locator (2-10 chars) to (lat, lon) at the *center* of the square.
    Supports: AA, AA00, AA00aa, AA00aa00, ...
    """
    if not grid:
        return None
    g = "".join(ch for ch in grid.strip() if ch.isalnum())
    if len(g) < 2:
        return None
    g = g.upper()

    # Base: field (A-R)
    A = ord("A")
    lon = -180.0 + (ord(g[0]) - A) * 20.0
    lat = -90.0 + (ord(g[1]) - A) * 10.0

    # Square (0-9)
    if len(g) >= 4 and g[2].isdigit() and g[3].isdigit():
        lon += int(g[2]) * 2.0
        lat += int(g[3]) * 1.0

    # Subsquare (a-x) -> 24 divisions
    if len(g) >= 6 and g[4].isalpha() and g[5].isalpha():
        lon += (ord(g[4].lower()) - ord("a")) * (2.0 / 24.0)
        lat += (ord(g[5].lower()) - ord("a")) * (1.0 / 24.0)

    # Extended square digits (0-9) -> 10 divisions of subsquare
    if len(g) >= 8 and g[6].isdigit() and g[7].isdigit():
        lon += int(g[6]) * ((2.0 / 24.0) / 10.0)
        lat += int(g[7]) * ((1.0 / 24.0) / 10.0)

    # Center of the final square size
    # Determine last cell size based on precision.
    if len(g) >= 8:
        dlon = (2.0 / 24.0) / 10.0
        dlat = (1.0 / 24.0) / 10.0
    elif len(g) >= 6:
        dlon = 2.0 / 24.0
        dlat = 1.0 / 24.0
    elif len(g) >= 4:
        dlon = 2.0
        dlat = 1.0
    else:
        dlon = 20.0
        dlat = 10.0

    lon += dlon / 2.0
    lat += dlat / 2.0

    # Clamp
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    # Round slightly for stable JSON/UI
    return (float(round(lat, 6)), float(round(lon, 6)))


def maidenhead_bbox(grid: str) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """
    Return (SW(lat,lon), NE(lat,lon)) bounds for a Maidenhead square.
    Supports 2/4/6/8 chars; for other lengths, uses the nearest lower precision.
    """
    if not grid:
        return None
    g = "".join(ch for ch in grid.strip() if ch.isalnum())
    if len(g) < 2:
        return None
    g = g.upper()

    # Determine precision we can actually interpret.
    if len(g) >= 8:
        n = 8
    elif len(g) >= 6:
        n = 6
    elif len(g) >= 4:
        n = 4
    else:
        n = 2
    g = g[:n]

    A = ord("A")
    lon = -180.0 + (ord(g[0]) - A) * 20.0
    lat = -90.0 + (ord(g[1]) - A) * 10.0
    dlon = 20.0
    dlat = 10.0

    if n >= 4 and g[2].isdigit() and g[3].isdigit():
        lon += int(g[2]) * 2.0
        lat += int(g[3]) * 1.0
        dlon = 2.0
        dlat = 1.0

    if n >= 6 and g[4].isalpha() and g[5].isalpha():
        lon += (ord(g[4].lower()) - ord("a")) * (2.0 / 24.0)
        lat += (ord(g[5].lower()) - ord("a")) * (1.0 / 24.0)
        dlon = 2.0 / 24.0
        dlat = 1.0 / 24.0

    if n >= 8 and g[6].isdigit() and g[7].isdigit():
        lon += int(g[6]) * ((2.0 / 24.0) / 10.0)
        lat += int(g[7]) * ((1.0 / 24.0) / 10.0)
        dlon = (2.0 / 24.0) / 10.0
        dlat = (1.0 / 24.0) / 10.0

    sw = (float(round(lat, 6)), float(round(lon, 6)))
    ne = (float(round(lat + dlat, 6)), float(round(lon + dlon, 6)))
    return (sw, ne)


def latlon_to_maidenhead(lat: float, lon: float, precision: int = 6) -> str:
    """
    Convert (lat, lon) to Maidenhead locator.
    precision: 2, 4, 6, or 8 characters (default 6 = subsquare precision)
    """
    # Normalize longitude to -180..180
    lon = ((lon + 180) % 360) - 180
    # Normalize latitude to -90..90
    lat = max(-90, min(90, lat))
    
    # Field (A-R, 18 divisions)
    lon += 180
    lat += 90
    field_lon = int(lon / 20)
    field_lat = int(lat / 10)
    grid = chr(ord("A") + field_lon) + chr(ord("A") + field_lat)
    
    if precision >= 4:
        # Square (0-9, 10 divisions)
        lon_remainder = lon % 20
        lat_remainder = lat % 10
        square_lon = int(lon_remainder / 2)
        square_lat = int(lat_remainder / 1)
        grid += str(square_lon) + str(square_lat)
    
    if precision >= 6:
        # Subsquare (a-x, 24 divisions)
        lon_remainder = lon % 20
        lat_remainder = lat % 10
        square_lon_remainder = (lon_remainder % 2) / 2.0
        square_lat_remainder = (lat_remainder % 1) / 1.0
        subsquare_lon = int(square_lon_remainder * 24)
        subsquare_lat = int(square_lat_remainder * 24)
        grid += chr(ord("a") + subsquare_lon) + chr(ord("a") + subsquare_lat)
    
    if precision >= 8:
        # Extended square (0-9, 10 divisions)
        lon_remainder = lon % 20
        lat_remainder = lat % 10
        square_lon_remainder = (lon_remainder % 2) / 2.0
        square_lat_remainder = (lat_remainder % 1) / 1.0
        subsquare_lon_remainder = (square_lon_remainder * 24) % 1
        subsquare_lat_remainder = (square_lat_remainder * 24) % 1
        extended_lon = int(subsquare_lon_remainder * 10)
        extended_lat = int(subsquare_lat_remainder * 10)
        grid += str(extended_lon) + str(extended_lat)
    
    return grid.upper()[:precision]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


