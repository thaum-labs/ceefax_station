"""
Update page 301 with ASCII art of the day.
"""
from datetime import datetime
from pathlib import Path
from typing import List

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import atomic_write_json


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def _center_art_block(art: List[str], width: int = PAGE_WIDTH) -> List[str]:
    """
    Center ASCII art as a single block.

    Per-line centering causes jitter if the source art has different leading spaces
    per line. This normalizes by trimming common indentation first, then centers
    based on the widest visible line.
    """
    # Trim trailing whitespace for stable width calculations
    raw = [line.rstrip("\n").rstrip() for line in art]
    # Drop fully empty lines at the edges
    while raw and not raw[0].strip():
        raw.pop(0)
    while raw and not raw[-1].strip():
        raw.pop()
    if not raw:
        return [_pad("")]

    # Remove common leading indentation across non-empty lines
    non_empty = [l for l in raw if l.strip()]
    min_lead = min(len(l) - len(l.lstrip(" ")) for l in non_empty) if non_empty else 0
    trimmed = [l[min_lead:] if len(l) >= min_lead else l for l in raw]

    max_len = max(len(l) for l in trimmed) if trimmed else 0
    max_len = min(max_len, width)
    left_pad = max(0, (width - max_len) // 2)

    centered: List[str] = []
    for line in trimmed:
        visible = line[:max_len]
        centered.append(_pad((" " * left_pad) + visible))
    return centered


def get_ascii_art() -> List[str]:
    """
    Get ASCII art based on day of week (rotates through different art).

    Pieces are sized for the Ceefax page: PAGE_WIDTH (50) by at most
    PAGE_HEIGHT - 6 (~17) lines after header/footer chrome.
    """
    day_of_week = datetime.now().weekday()

    # Different ASCII art for each day — denser detail, still pure ASCII.
    # Keep each piece within PAGE_WIDTH and PAGE_HEIGHT-6 so it is not clipped.
    art_collection = [
        # Monday - Cat
        [
            "      |\\      _,,,---,,_",
            "ZZZzz /,`.-'`'    -.  ;-;;,_",
            "     |,4-  ) )-,_. ,\\ (  `'-'",
            "    '---''(_/--'  `-'\\_)",
        ],
        # Tuesday - Dog
        [
            "         ,-.___,-.",
            "        /  .   .  \\",
            "       /     Y     \\",
            "      |   \\  ^  /   |",
            "       \\   `---'   /",
            "        `--.   .--'",
            "           |   |",
            "          /|   |\\",
            "         (_|___|_)",
        ],
        # Wednesday - Star
        [
            "              .",
            "             ,O,",
            "            ,OOO,",
            "      'oooooOOOOOooooo'",
            "        `OOOOOOOOOOO`",
            "          `OOOOOOO`",
            "          OOO` `OOO",
            "         OOO'   `OOO",
            "        OOO'     `OOO",
            "       O'           `O",
        ],
        # Thursday - Heart
        [
            "       .:::.   .:::. ",
            "     .:::::::.:::::::. ",
            "    ::::::::::::::::::: ",
            "    ':::::::::::::::::' ",
            "      ':::::::::::::' ",
            "        ':::::::::' ",
            "          ':::::' ",
            "            ':' ",
        ],
        # Friday - Tree
        [
            "            /\\",
            "           /\\*\\",
            "          /\\O\\*\\",
            "         /*/\\/\\/\\",
            "        /\\O\\/\\*\\/\\",
            "       /\\*\\/\\*\\/\\/\\",
            "      /\\O\\/\\/*/\\/O/\\",
            "     /\\/*/\\O\\/\\*/\\/\\",
            "    /\\O\\/\\/*/\\/\\/O/\\",
            "            ||",
            "           /||\\",
            "          ////\\\\\\",
        ],
        # Saturday - Rocket
        [
            "             /\\",
            "            //\\\\",
            "           ///\\\\\\",
            "           |||||",
            "           |[o]|",
            "           |||||",
            "          /|||||\\",
            "         //|||||\\\\",
            "        ///|||||\\\\\\",
            "           |||||",
            "          /\\/|\\/\\",
            "         /__/|\\__\\",
            "            /|\\",
            "           / | \\",
            "          '  |  '",
        ],
        # Sunday - Sun
        [
            "            \\   |   /",
            "             \\  |  /",
            "           ---\\ | /---",
            "                .-. ",
            "           --- (   ) ---",
            "                '-' ",
            "           ---/ | \\---",
            "             /  |  \\",
            "            /   |   \\",
        ],
    ]

    return art_collection[day_of_week]


def build_ascii_art_page() -> List[str]:
    """Build ASCII art of the day page."""
    lines: List[str] = []
    lines.append(_pad("ASCII ART OF THE DAY"))
    lines.append(_pad("-" * PAGE_WIDTH))
    
    art = get_ascii_art()

    centered_block = _center_art_block(art, width=PAGE_WIDTH)

    # Keep the "box" compact: no vertical centering to full PAGE_HEIGHT.
    # This makes the art sit close to the top and avoids a huge empty panel.
    max_art_height = max(0, PAGE_HEIGHT - 6)  # header+sep+sep+footer safety
    centered_block = centered_block[:max_art_height]

    lines.append(_pad(""))  # small top padding inside the box
    lines.extend(centered_block)
    lines.append(_pad(""))  # small bottom padding inside the box
    lines.append(_pad("-" * PAGE_WIDTH))
    lines.append(_pad(""))
    lines.append(_pad("Source: Generated"))
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 601 with ASCII art of the day."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "601.json"
    
    content = build_ascii_art_page()
    
    page = {
        "page": "601",
        "title": "ASCII Art of the Day",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with ASCII art of the day")


if __name__ == "__main__":
    main()

