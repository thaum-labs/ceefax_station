"""
Update page 503 with TV highlights over two subpages (503 and 503.2).

Primary source: TVMaze's structured GB schedule API.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, atomic_write_json, resolve_provider, FRESH_TVMAZE_SECONDS


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


POPULAR_CHANNELS: Tuple[str, ...] = ("BBC One", "BBC Two", "ITV1", "Channel 4")
TVMAZE_SCHEDULE_URL = "https://api.tvmaze.com/schedule/full"
TVMAZE_SOURCE = "TVMaze GB schedule"
TVMAZE_USER_AGENT = "CeefaxStation/1.0 (non-commercial; contact via repository)"
# Country day schedule is sparse; full feed is larger but covers BBC/ITV/C4.
# Overnight refreshes need a longer horizon than peak evening.


@dataclass(frozen=True)
class TvListing:
    channel: str
    start_utc: datetime
    end_utc: datetime | None
    title: str
    subtitle: str | None = None
    synopsis: str | None = None
    source: str = ""


def _parse_iso_utc(s: str | None) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _canonical_channel(name: str) -> str | None:
    normalized = " ".join(name.lower().replace("hd", "").split())
    if normalized.startswith("bbc one") or normalized.startswith("bbc 1"):
        return "BBC One"
    if normalized.startswith("bbc two") or normalized.startswith("bbc 2"):
        return "BBC Two"
    if normalized.startswith("itv1") or normalized == "itv":
        return "ITV1"
    if normalized.startswith("channel 4") or normalized.startswith("channel4"):
        return "Channel 4"
    aliases = {
        "bbc one": "BBC One",
        "bbc 1": "BBC One",
        "bbc two": "BBC Two",
        "bbc 2": "BBC Two",
        "itv": "ITV1",
        "itv1": "ITV1",
        "channel 4": "Channel 4",
        "channel4": "Channel 4",
    }
    return aliases.get(normalized)


def _show_from_item(item: dict) -> dict:
    """TVMaze country schedule nests show at top level; /schedule/full uses _embedded."""
    show = item.get("show")
    if isinstance(show, dict):
        return show
    embedded = item.get("_embedded") or {}
    embedded_show = embedded.get("show") if isinstance(embedded, dict) else None
    return embedded_show if isinstance(embedded_show, dict) else {}


def fetch_tvmaze_schedule(*, start_utc: datetime, end_utc: datetime) -> List[dict]:
    """Fetch BBC One/Two, ITV1, and Channel 4 from TVMaze's full schedule feed."""
    response = requests.get(
        TVMAZE_SCHEDULE_URL,
        headers={"User-Agent": TVMAZE_USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("TVMaze returned a non-list schedule")

    listings: List[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        show = _show_from_item(item)
        network = show.get("network") or {}
        web_channel = show.get("webChannel") or {}
        channel = _canonical_channel(str(network.get("name") or web_channel.get("name") or ""))
        start = _parse_iso_utc(item.get("airstamp"))
        if channel is None or start is None:
            continue
        runtime = item.get("runtime")
        end = start + timedelta(minutes=int(runtime)) if runtime else None
        # Keep programmes that overlap the window (currently airing or upcoming).
        still_on = end is None or end > start_utc
        if not (start < end_utc and still_on):
            continue
        if start + timedelta(hours=12) < start_utc:
            # Ignore very old entries that lack a usable runtime end time.
            continue
        summary = show.get("summary") or item.get("summary") or ""
        if summary:
            summary = BeautifulSoup(str(summary), "html.parser").get_text(" ", strip=True)
        listings.append(
            {
                "channel": channel,
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat() if end else None,
                "title": str(show.get("name") or "Unknown").strip(),
                "subtitle": str(item.get("name") or "").strip() or None,
                "synopsis": summary or None,
            }
        )
    if not listings:
        raise ValueError("TVMaze returned no listings for the selected channels")
    return listings


def get_tv_schedule(*, start_utc: datetime, end_utc: datetime) -> ProviderResult[List[dict]]:
    return resolve_provider(
        "tv-503",
        [(TVMAZE_SOURCE, lambda: fetch_tvmaze_schedule(start_utc=start_utc, end_utc=end_utc))],
        fresh_for_seconds=FRESH_TVMAZE_SECONDS,
    )


def _restore_listings(items: List[dict]) -> List[TvListing]:
    restored: List[TvListing] = []
    for item in items:
        start = _parse_iso_utc(item.get("start_utc"))
        if start is None:
            continue
        restored.append(
            TvListing(
                channel=str(item.get("channel") or ""),
                start_utc=start,
                end_utc=_parse_iso_utc(item.get("end_utc")),
                title=str(item.get("title") or "Unknown"),
                subtitle=item.get("subtitle"),
                synopsis=item.get("synopsis"),
                source=TVMAZE_SOURCE,
            )
        )
    return restored


def _is_sports_listing(item: TvListing) -> bool:
    sports_keywords = [
        "sport",
        "sports",
        "football",
        "match",
        "race",
        "rugby",
        "cricket",
        "tennis",
        "golf",
        "boxing",
        "f1",
        "formula 1",
        "motogp",
    ]
    blob = " ".join(
        [
            (item.title or ""),
            (item.subtitle or ""),
            (item.synopsis or ""),
        ]
    ).lower()
    return any(k in blob for k in sports_keywords)


def format_time(time_str: str) -> str:
    """Format time string to HH:MM format."""
    try:
        if ":" in time_str:
            parts = time_str.split(":")
            return f"{parts[0]}:{parts[1]}"
        return time_str
    except Exception:  # noqa: BLE001
        return time_str


def _format_listing_line(item: TvListing) -> str:
    # Display times in local time.
    t_local = item.start_utc.astimezone().strftime("%H:%M")
    channel = item.channel

    title = (item.title or "Unknown").strip()
    subtitle = (item.subtitle or "").strip()

    if subtitle and subtitle.lower() != title.lower():
        display_text = f"{title}: {subtitle}"
    else:
        display_text = title

    if len(display_text) > 28:
        display_text = display_text[:25] + "..."

    display = f"{t_local:>5}  {channel[:12]:<12} {display_text}"
    return _pad(display)


def _channel_short(name: str) -> str:
    n = (name or "").strip().lower()
    if n == "bbc one":
        return "BBC1"
    if n == "bbc two":
        return "BBC2"
    if n == "itv1":
        return "ITV1"
    if n == "channel 4":
        return "C4"
    # Fallback: keep short and upper
    return (name or "TV")[:6].upper()


def _listing_text(item: TvListing) -> str:
    """
    Human-friendly show label used in grouped pages.
    """
    title = (item.title or "Unknown").strip()
    subtitle = (item.subtitle or "").strip()
    if subtitle and subtitle.lower() != title.lower():
        txt = f"{title}: {subtitle}"
    else:
        txt = title
    return txt


def _format_grouped_entry(item: TvListing) -> str:
    # Time first, then show.
    t_local = item.start_utc.astimezone().strftime("%H:%M")
    txt = _listing_text(item)
    line = f"{t_local} - {txt}"
    if len(line) > PAGE_WIDTH:
        line = line[: PAGE_WIDTH - 3] + "..."
    return _pad(line)


def _render_grouped_sections(items: List[TvListing]) -> Dict[str, List[str]]:
    """
    Returns: channel -> list of entry lines (already padded).
    """
    out: Dict[str, List[TvListing]] = {}
    for it in items:
        out.setdefault(it.channel, []).append(it)

    sections: Dict[str, List[str]] = {}
    for ch, lst in out.items():
        lst.sort(key=lambda x: x.start_utc)

        # Collapse consecutive duplicates (same programme across adjacent slots)
        # so we don't list the same show multiple times.
        #
        # Use *title-only* for the key because some sources (notably Channel 4)
        # vary synopsis/episode metadata between contiguous slots even when the
        # show is effectively the same block.
        deduped: List[TvListing] = []
        last_key: str | None = None
        for it in lst:
            key = " ".join((it.title or "").strip().lower().split())
            if last_key is not None and key == last_key:
                continue
            deduped.append(it)
            last_key = key

        sections[ch] = [_format_grouped_entry(x) for x in deduped]
    return sections


def _section_lines(channel: str, entries: List[str]) -> List[str]:
    """
    Build a channel section:
      BBC1
      13:00 - Show
      13:30 - Show
    """
    lines: List[str] = []
    lines.append(_pad(_channel_short(channel)))
    lines.extend(entries)
    return lines


def _pack_sections_into_two_pages(
    *,
    sections: Dict[str, List[str]],
    channels: Tuple[str, ...],
    per_page: int,
) -> Tuple[List[str], List[str]]:
    """
    Pack channel sections into two pages, preserving channel order:
      BBC (1/2/3...) first, then ITV, then Channel 4.

    We only split *between* channel sections (never inside), and choose the split
    point that best balances page fullness while staying within `per_page`.

    If a section is too large to fit on a single page, it is truncated.
    """
    # Create a list of (channel, lines) in preferred channel order.
    ordered: List[Tuple[str, List[str]]] = []
    for ch in channels:
        entries = sections.get(ch, [])
        # Skip channels with no entries to keep pages dense.
        if not entries:
            continue
        ordered.append((ch, _section_lines(ch, entries)))

    # If everything is empty, return empty bodies.
    if not ordered:
        return ([], [])

    # Pre-truncate any section that can't possibly fit on one page.
    trimmed: List[Tuple[str, List[str]]] = []
    for ch, lines in ordered:
        if len(lines) > per_page:
            # Keep header + as many entries as fit; add an ellipsis line if possible.
            head = lines[:1]
            remaining = per_page - 1
            body = lines[1 : 1 + max(0, remaining)]
            if remaining >= 2:
                body = body[:-1] + [_pad("...")]
            trimmed.append((ch, head + body))
        else:
            trimmed.append((ch, lines))

    # Choose best split point between sections (preserve order).
    sizes = [len(lines) for _ch, lines in trimmed]
    total = sum(sizes)

    best_k = len(trimmed)  # all on page 1 if it fits
    best_score: float | None = None

    # k = number of sections on page 1
    for k in range(len(trimmed) + 1):
        s1 = sum(sizes[:k])
        s2 = total - s1
        if s1 > per_page or s2 > per_page:
            continue
        # Minimize difference; tie-breaker: fill page 1 slightly more.
        score = abs(s1 - s2) + (0.01 if s1 < s2 else 0.0)
        if best_score is None or score < best_score:
            best_score = score
            best_k = k

    # If nothing fits (total > 2*per_page), fall back to "fill page 1 then page 2",
    # still preserving order and dropping overflow.
    if best_score is None:
        p1: List[str] = []
        p2: List[str] = []
        n1 = 0
        n2 = 0
        for _ch, lines in trimmed:
            if n1 + len(lines) <= per_page:
                p1.extend(lines)
                n1 += len(lines)
            elif n2 + len(lines) <= per_page:
                p2.extend(lines)
                n2 += len(lines)
            else:
                continue
        return (p1[:per_page], p2[:per_page])

    p1 = []
    for _ch, lines in trimmed[:best_k]:
        p1.extend(lines)
    p2 = []
    for _ch, lines in trimmed[best_k:]:
        p2.extend(lines)
    return (p1[:per_page], p2[:per_page])


def build_tv_highlights_page(*, body_lines: List[str], window_hours: int = 4, source_note: str) -> List[str]:
    """Build page 503: TV highlights (non-sports) for the next N hours."""
    lines: List[str] = []
    lines.append(_pad("TV HIGHLIGHTS"))
    lines.append(_pad(""))

    lines.append(_pad(f"NOW - NEXT {int(window_hours)}H"))
    sep = _pad("-" * PAGE_WIDTH)
    lines.append(sep)

    if body_lines:
        for ln in body_lines[: (PAGE_HEIGHT - 8)]:
            lines.append(_pad(ln))
    else:
        lines.append(_pad("No listings found in the next"))
        lines.append(_pad(f"{int(window_hours)} hours for:"))
        lines.append(_pad(", ".join(POPULAR_CHANNELS)[:PAGE_WIDTH]))

    lines.append(_pad(""))
    lines.append(_pad(f"Channels: {', '.join(POPULAR_CHANNELS)}"[:PAGE_WIDTH]))
    lines.append(_pad("More listings: 503.2"))
    lines.append(_pad(source_note[:PAGE_WIDTH]))

    return lines[:PAGE_HEIGHT]


def build_tv_highlights_page_2(*, body_lines: List[str], window_hours: int = 4, source_note: str) -> List[str]:
    """Build page 503.2: TV highlights continuation (non-sports)."""
    lines: List[str] = []
    lines.append(_pad("TV HIGHLIGHTS (2/2)"))
    lines.append(_pad(""))

    sep = _pad("-" * PAGE_WIDTH)
    lines.append(_pad(f"NOW - NEXT {int(window_hours)}H"))
    lines.append(sep)

    if body_lines:
        for ln in body_lines[: (PAGE_HEIGHT - 8)]:
            lines.append(_pad(ln))
    else:
        lines.append(_pad("No more listings"))
        lines.append(_pad(""))

    lines.append(_pad(""))
    lines.append(_pad(f"Channels: {', '.join(POPULAR_CHANNELS)}"[:PAGE_WIDTH]))
    lines.append(_pad("Back: 503"))
    lines.append(_pad(source_note[:PAGE_WIDTH]))
    return lines[:PAGE_HEIGHT]


def _write_page(*, page: str, title: str, content: List[str], subpage: int = 1) -> Path:
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / (f"{page}.json" if int(subpage) == 1 else f"{page}_{int(subpage)}.json")

    payload = {
        "page": str(page),
        "title": title,
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": int(subpage),
        "content": content[:PAGE_HEIGHT],
    }

    atomic_write_json(page_file, payload)
    return page_file


def main() -> None:
    """
    Update:
      - page 503: TV highlights (non-sports) subpage 1
      - page 503.2: TV highlights (non-sports) subpage 2

    Both cover the next 24 hours on the 4 main channels:
      BBC One, BBC Two, ITV1, Channel 4
    (TVMaze coverage can be sparse overnight; a longer window avoids empty pages.)
    """
    now_utc = datetime.now(timezone.utc)
    end_utc = now_utc + timedelta(hours=24)

    result = get_tv_schedule(start_utc=now_utc, end_utc=end_utc)
    listings = _restore_listings(result.data)

    listings.sort(key=lambda x: x.start_utc)

    # Sports highlights page removed; we exclude sports from both TV highlight subpages.
    non_sports = [x for x in listings if not _is_sports_listing(x)]

    state = "Stale/as-of" if result.stale else "As-of"
    source_note = f"Source: TVMaze GB | {state} {result.fetched_at}"

    # Split into 2 subpages with the *same* capacity, distributing items evenly.
    # Each page layout is:
    #   4 header lines + N programme lines + 4 footer lines = PAGE_HEIGHT
    # so N = PAGE_HEIGHT - 8.
    per_page = max(1, PAGE_HEIGHT - 8)

    # Render grouped-by-channel layout, then pack sections into 2 pages.
    sections = _render_grouped_sections(non_sports)
    body1, body2 = _pack_sections_into_two_pages(sections=sections, channels=POPULAR_CHANNELS, per_page=per_page)

    p503 = _write_page(
        page="503",
        title="TV Highlights",
        content=build_tv_highlights_page(body_lines=body1, window_hours=4, source_note=source_note),
        subpage=1,
    )
    p503_2 = _write_page(
        page="503",
        title="TV Highlights",
        content=build_tv_highlights_page_2(body_lines=body2, window_hours=4, source_note=source_note),
        subpage=2,
    )

    print(f"Updated {p503} with TV highlights (next 4h, main channels)")
    print(f"Updated {p503_2} with TV highlights (page 2) (next 4h, main channels)")


if __name__ == "__main__":
    main()

