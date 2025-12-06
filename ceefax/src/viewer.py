import curses
from datetime import datetime
from typing import List

from .config import load_config
from .compiler import Page, load_all_pages, compile_page_to_matrix


def _draw_page(
    stdscr: "curses._CursesWindow",
    page: Page,
    matrix: List[str],
    index: int,
    total: int,
) -> None:
    stdscr.clear()
    max_y, max_x = stdscr.getmaxyx()

    # Require at least 40x24 area
    if max_y < 24 or max_x < 40:
        msg = "Terminal too small. Need at least 40x24."
        stdscr.addstr(0, 0, msg[: max_x - 1])
        stdscr.refresh()
        return

    # Center the 40x24 frame
    offset_y = max((max_y - 24) // 2, 0)
    offset_x = max((max_x - 40) // 2, 0)

    # Build Ceefax-style header line (ignore matrix[0], construct our own)
    # Example: "CEEFAX 100 NEWS HEADLINES     12:34 06 DEC"
    now = datetime.now()
    clock = now.strftime("%H:%M %d %b").upper()  # e.g. "12:34 06 DEC"
    title = (page.title or "").upper()[:20]
    page_num = (page.page or "").rjust(3)
    header_text = f"CEEFAX {page_num} {title:<20}{clock:>9}"
    header_text = header_text[:40].ljust(40)

    # Colours
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_YELLOW, curses.COLOR_BLUE)   # header
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # body (classic Ceefax yellow text)
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)     # RED
        curses.init_pair(4, curses.COLOR_GREEN, curses.COLOR_BLACK)   # GREEN
        curses.init_pair(5, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # YELLOW
        curses.init_pair(6, curses.COLOR_BLUE, curses.COLOR_BLACK)    # BLUE

        header_attr = curses.color_pair(1) | curses.A_BOLD
        body_attr = curses.color_pair(2)
    else:
        header_attr = curses.A_BOLD
        body_attr = curses.A_NORMAL

    # Header (row 0)
    stdscr.addstr(offset_y, offset_x, header_text[:40], header_attr)

    # ASCII-art "CEEFAX PI" logo area below header.
    if curses.has_colors():
        art_attr = header_attr  # yellow on blue, bold
    else:
        art_attr = curses.A_BOLD

    # Simple, readable ASCII banner for "CEEFAX PI", constrained to 40 cols.
    ceefax_art = [
        "████████████████████████████████████████",
        "██          CEEFAX PI                 ██",
        "████████████████████████████████████████",
    ]

    art_row = offset_y + 1
    for i, line in enumerate(ceefax_art):
        row = art_row + i
        if row >= offset_y + 24:
            break
        stdscr.addstr(row, offset_x, line[:40].ljust(40), art_attr)

    # Remaining lines: show from matrix[1:] (timestamp + content),
    # formatted with a bold heading and blue rule beneath it.
    start_row = art_row + len(ceefax_art)

    # matrix[1] is timestamp; matrix[2:] is content
    if len(matrix) > 1:
        stdscr.addstr(start_row, offset_x, matrix[1][:40], body_attr)
    content_lines = matrix[2:24]

    current_row = start_row + 1

    # First content line as bold section heading
    if content_lines:
        heading = content_lines[0]
        stdscr.addstr(current_row, offset_x, heading[:40], body_attr | curses.A_BOLD)
        current_row += 1

        # Blue horizontal rule under heading (or underline fallback)
        rule_text = "-" * 40
        if curses.has_colors():
            rule_attr = curses.color_pair(6)
        else:
            rule_attr = curses.A_UNDERLINE
        stdscr.addstr(current_row, offset_x, rule_text, rule_attr)
        current_row += 1

        # Remaining content below rule
        for line in content_lines[1:]:
            if current_row >= offset_y + 24:
                break
            stdscr.addstr(current_row, offset_x, line[:40], body_attr)
            current_row += 1

    # "Fastext" bar one line above bottom
    fastext_y = max_y - 2
    if fastext_y > offset_y + 24:
        if curses.has_colors():
            x = 0
            labels = [
                (" RED ", curses.color_pair(3) | curses.A_BOLD),
                (" GREEN ", curses.color_pair(4) | curses.A_BOLD),
                (" YELLOW ", curses.color_pair(5) | curses.A_BOLD),
                (" BLUE ", curses.color_pair(6) | curses.A_BOLD),
            ]
            for text, attr in labels:
                if x >= max_x - 1:
                    break
                stdscr.addstr(fastext_y, x, text[: max_x - 1 - x], attr)
                x += len(text)
        else:
            stdscr.addstr(fastext_y, 0, "RED  GREEN  YELLOW  BLUE"[: max_x - 1])

    # Status line at bottom
    status = f"Page {page.page_id}  ({index + 1}/{total})  n/p: next/prev  r: reload  q: quit"
    stdscr.attron(curses.A_REVERSE)
    stdscr.addstr(max_y - 1, 0, status[: max_x - 1])
    stdscr.attroff(curses.A_REVERSE)

    stdscr.refresh()


def _viewer_loop(stdscr: "curses._CursesWindow", pages: List[Page]) -> None:
    curses.curs_set(0)  # hide cursor
    stdscr.nodelay(False)
    stdscr.keypad(True)

    idx = 0

    def compile_all() -> List[List[str]]:
        return [compile_page_to_matrix(p) for p in pages]

    matrices = compile_all()

    while True:
        if not pages:
            stdscr.clear()
            stdscr.addstr(0, 0, "No pages loaded. Press q to quit.")
            stdscr.refresh()
        else:
            page = pages[idx]
            matrix = matrices[idx]
            _draw_page(stdscr, page, matrix, idx, len(pages))

        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            break
        if ch in (ord("n"), curses.KEY_RIGHT, curses.KEY_NPAGE):
            if pages:
                idx = (idx + 1) % len(pages)
        elif ch in (ord("p"), curses.KEY_LEFT, curses.KEY_PPAGE):
            if pages:
                idx = (idx - 1) % len(pages)
        elif ch in (ord("r"), ord("R")):
            # Reload pages from disk
            cfg = load_config()
            new_pages = load_all_pages(cfg.general.page_dir)
            if new_pages:
                pages[:] = new_pages
                matrices[:] = compile_all()
                idx = 0


def main() -> None:
    """
    Launch a simple Ceefax-style viewer in the terminal using curses.
    """
    config = load_config()
    pages = load_all_pages(config.general.page_dir)

    # We pass pages by reference so reload can update in-place.
    def runner(stdscr: "curses._CursesWindow") -> None:
        _viewer_loop(stdscr, pages)

    curses.wrapper(runner)


if __name__ == "__main__":
    main()


