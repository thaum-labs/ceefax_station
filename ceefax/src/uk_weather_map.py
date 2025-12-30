from typing import List, Dict, Tuple

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .weather_map import fetch_wttr, WeatherSummary


# Rough UK "map" layout positions (row, col) for each city label
REGIONS: Dict[str, Tuple[str, int, int]] = {
    "Inverness": ("Inverness,UK", 4, 6),
    "Newcastle": ("Newcastle upon Tyne,UK", 7, 24),
    "Birmingham": ("Birmingham,UK", 11, 24),
    "London": ("London,UK", 14, 30),
    "Frome": ("Frome,UK", 17, 22),
    "Cardiff": ("Cardiff,UK", 15, 10),
}


def _blank_frame() -> List[List[str]]:
    """Create a blank PAGE_HEIGHT x PAGE_WIDTH character grid."""
    return [list(" " * PAGE_WIDTH) for _ in range(PAGE_HEIGHT)]


def _put_text(buf: List[List[str]], row: int, col: int, text: str) -> None:
    """Write text into the buffer at (row, col) without wrapping."""
    if row < 0 or row >= PAGE_HEIGHT:
        return
    for i, ch in enumerate(text):
        c = col + i
        if 0 <= c < PAGE_WIDTH:
            buf[row][c] = ch


def build_uk_weather_map() -> List[str]:
    """
    Build a Ceefax-style UK weather map as PAGE_HEIGHT lines.

    Each region is shown as a small boxed "tile":

        +-----------+
        |  7C  ☁   |
        | Light Cl |
        +-----------+

    arranged roughly in the pattern of the UK.
    """
    buf = _blank_frame()

    # Title bar at top
    title = "UK WEATHER FOR TONIGHT"
    _put_text(buf, 0, 0, title.center(PAGE_WIDTH))

    # Fetch summaries for each region with error handling
    summaries: Dict[str, WeatherSummary] = {}
    for name, (query, _row, _col) in REGIONS.items():
        try:
            summaries[name] = fetch_wttr(query)
        except Exception as e:
            # Create a fallback summary if fetch fails
            from .weather_map import WeatherSummary
            print(f"Warning: Failed to fetch weather for {name} ({query}): {e}")
            summaries[name] = WeatherSummary(
                location=name,
                temp_c="?",
                feels_like_c="?",
                description="Data unavailable",
                wind_kph="?",
                wind_dir="?",
                icon="☁",
            )

    # ASCII-art UK outline used as background (from asciiart.website),
    # centred horizontally to fit PAGE_WIDTH.
    ascii_map = [
        "             z   $b$$F",
        "            F\"  4$$P\"",
        "             r *$$$\".c...",
        "             %-4$$$$$$$$\"",
        "              J$*$$$$$$P",
        "             ^r4$$$$$$\"",
        "               *f*$$*\"",
        "             \".4 *$$$$$$.",
        "       4ee%.e.  .$$$$$$$$r",
        "      4$$$$$$b  P$**)$$$$b",
        "   e..4$$$$$$$\"     $$$$$$c.",
        "   3$$$$$$$$*\"   \"  ^\"$$$$$$c",
        "  *$$$$$$$$$.        *$$$$$$$.",
        "   ..$$$$$$$L    c ..J$$$$$$$b",
        "   d\"$$$$$$$F   .@$$$$$$$$$$$P\"..",
        "..$$$$$$$$$$      d$$$$$$$$$$$$$$$",
        "=$$$$$$P\"\" \"    .e$$$$$$$$$$$$$$$$",
        "  *\"\"          $**$$$$$$$$$$$$$$*",
        "                   \"\".$$$$$$$$$C .",
        "                .z$$$$$$$$$$$$$$\"\"",
        "               .$$$*\"^**\"  \"",
        "             =P\"  \"",
    ]
    start_row = 1
    for i, line in enumerate(ascii_map):
        row = start_row + i
        if row >= PAGE_HEIGHT:
            break
        text = line.center(PAGE_WIDTH)
        _put_text(buf, row, 0, text[:PAGE_WIDTH])

    # Helper to draw a 4x13 tile at (top_row, left_col)
    def draw_tile(row: int, col: int, s: WeatherSummary, label: str) -> None:
        w = 13
        top = "+" + "-" * (w - 2) + "+"
        bottom = top

        # Show temperature + small icon and a short condition line.
        # Icon may be unicode; if terminal/font can't render it, it will still degrade gracefully.
        temp = f"{s.temp_c}C"
        icon = (s.icon or "").strip()
        temp_icon = f"{temp} {icon}".strip()
        temp_line = temp_icon[: w - 2].ljust(w - 2)
        cond = s.description.split(",")[0][: w - 2]
        cond_line = cond.ljust(w - 2)

        _put_text(buf, row, col, top)
        _put_text(buf, row + 1, col, "|" + temp_line + "|")
        _put_text(buf, row + 2, col, "|" + cond_line + "|")
        _put_text(buf, row + 3, col, bottom)

        # Region label just under the box
        _put_text(buf, row + 4, col, label[:w].center(w))

    # Place tiles in a rough UK layout (coords tuned for 50x30)
    tile_layout = {
        "Inverness":  (3, 4,  "SCOTLAND"),
        "Newcastle":  (6, 24, "N ENGLAND"),
        "Cardiff":    (13, 6, "WALES"),
        "Birmingham": (11, 22, "MIDLANDS"),
        "London":     (15, 30, "LONDON"),
        "Frome":      (18, 22, "FROME"),
    }

    for name, (top_row, left_col, label) in tile_layout.items():
        s = summaries[name]
        draw_tile(top_row, left_col, s, label)

    # Footer similar to classic Ceefax pages
    footer1 = "From wttr.in (unofficial)"
    footer2 = "News   Sport   Travel   Main Menu"
    _put_text(buf, PAGE_HEIGHT - 3, 0, footer1[:PAGE_WIDTH])
    _put_text(buf, PAGE_HEIGHT - 2, 0, footer2[:PAGE_WIDTH])

    return ["".join(line) for line in buf]


