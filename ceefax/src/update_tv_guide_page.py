"""
Update page 503 with TV highlights over two subpages (503 and 503.2).

Primary sources:
- BBC One / BBC Two: BBC iPlayer Guide (scrape embedded JSON payload)
- Channel 4: Channel 4 TV Guide JSON (`/tv-guide/api`)

Fallback source (best-effort):
- ITV1: TVMaze schedule (ITV blocks plain requests in some environments)
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from .compiler import PAGE_WIDTH, PAGE_HEIGHT


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


POPULAR_CHANNELS: Tuple[str, ...] = ("BBC One", "BBC Two", "ITV1", "Channel 4")


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


def _load_json_payload_from_script_tag(*, html: str, key_hint: str) -> dict | None:
    """
    BBC iPlayer guide embeds a large JSON blob in a script tag; this helper locates and parses it.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        for sc in soup.find_all("script"):
            txt = (sc.string or sc.get_text() or "").strip()
            if not txt:
                continue
            if key_hint not in txt:
                continue
            j0 = txt.find("{")
            j1 = txt.rfind("}")
            if j0 == -1 or j1 == -1 or j1 <= j0:
                continue
            try:
                return json.loads(txt[j0 : j1 + 1])
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return None
    return None


def fetch_bbc_iplayer_channel(
    *,
    channel_key: str,
    channel_label: str,
    start_utc: datetime,
    end_utc: datetime,
) -> List[TvListing]:
    """
    Scrape BBC iPlayer guide for a single BBC channel.
    """
    url = f"https://www.bbc.co.uk/iplayer/guide/{channel_key}"
    try:
        html = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception:  # noqa: BLE001
        return []

    data = _load_json_payload_from_script_tag(html=html, key_hint="scheduledStart")
    if not data:
        return []

    schedule = (data.get("schedule") or {}) if isinstance(data, dict) else {}
    items = schedule.get("items") or []
    out: List[TvListing] = []

    for it in items:
        if not isinstance(it, dict):
            continue
        props = it.get("props") or {}
        meta = it.get("meta") or {}

        st = _parse_iso_utc(meta.get("scheduledStart"))
        en = _parse_iso_utc(meta.get("scheduledEnd"))
        if not st:
            continue
        if st < start_utc or st >= end_utc:
            continue

        title = (props.get("title") or "").strip() or "Unknown"
        subtitle = (props.get("subtitle") or "").strip() or None
        synopsis = (props.get("synopsis") or "").strip() or None

        out.append(
            TvListing(
                channel=channel_label,
                start_utc=st,
                end_utc=en,
                title=title,
                subtitle=subtitle,
                synopsis=synopsis,
                source="BBC iPlayer",
            )
        )

    out.sort(key=lambda x: x.start_utc)
    return out


def fetch_channel4(
    *,
    start_utc: datetime,
    end_utc: datetime,
) -> List[TvListing]:
    """
    Fetch Channel 4 guide via their JSON endpoint.
    """
    day = start_utc.astimezone(timezone.utc).date().isoformat()
    url = f"https://www.channel4.com/tv-guide/api/{day}"
    try:
        data = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).json()
    except Exception:  # noqa: BLE001
        return []

    ch = ((data or {}).get("channels") or {}).get("C4") or {}
    programmes = ch.get("programmes") or []
    out: List[TvListing] = []

    for p in programmes:
        if not isinstance(p, dict):
            continue
        st = _parse_iso_utc(p.get("startDate"))
        en = _parse_iso_utc(p.get("endDate"))
        if not st:
            continue
        if st < start_utc or st >= end_utc:
            continue

        title = (p.get("title") or "").strip() or "Unknown"
        synopsis = (p.get("summary") or "").strip() or None

        out.append(
            TvListing(
                channel="Channel 4",
                start_utc=st,
                end_utc=en,
                title=title,
                synopsis=synopsis,
                source="Channel4 TV Guide",
            )
        )

    out.sort(key=lambda x: x.start_utc)
    return out


def fetch_itv1_tvmaze_fallback(
    *,
    start_utc: datetime,
    end_utc: datetime,
) -> List[TvListing]:
    """
    Best-effort ITV1 listings from TVMaze (fallback only).

    ITV frequently blocks automated scraping of itv.com. This keeps ITV1 in the 4-channel set.
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        url = f"https://api.tvmaze.com/schedule?date={today}&country=GB"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001
        return []

    out: List[TvListing] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        # TVMaze airstamp -> UTC
        st = _parse_iso_utc(item.get("airstamp"))
        if not st:
            continue
        if st < start_utc or st >= end_utc:
            continue

        show = item.get("show") or {}
        network = (show.get("network") or {}).get("name") or ""
        web = (show.get("webChannel") or {}).get("name") or ""
        ch = (network or web or "").strip().lower()
        if "itv1" not in ch and ch != "itv":
            continue

        title = (show.get("name") or "").strip() or "Unknown"
        episode = (item.get("name") or "").strip() or None
        synopsis = (show.get("summary") or "").strip() or None
        # Strip HTML tags from TVMaze summary (basic).
        if synopsis and "<" in synopsis and ">" in synopsis:
            synopsis = BeautifulSoup(synopsis, "html.parser").get_text(" ", strip=True)

        out.append(
            TvListing(
                channel="ITV1",
                start_utc=st,
                end_utc=None,
                title=title,
                subtitle=episode,
                synopsis=synopsis,
                source="TVMaze (fallback)",
            )
        )

    out.sort(key=lambda x: x.start_utc)
    return out


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
    Pack channel sections into two pages while trying to keep them equally full.

    Sections are kept intact (not split across pages). If a section is too large,
    it is truncated to fit.
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

    # Greedy bin-pack into 2 pages by section size (largest first).
    trimmed.sort(key=lambda x: len(x[1]), reverse=True)
    p1: List[str] = []
    p2: List[str] = []
    p1_n = 0
    p2_n = 0

    for _ch, lines in trimmed:
        # Prefer the page with fewer lines used, but don't overflow.
        target_1 = p1_n <= p2_n
        if target_1:
            if p1_n + len(lines) <= per_page:
                p1.extend(lines)
                p1_n += len(lines)
                continue
            if p2_n + len(lines) <= per_page:
                p2.extend(lines)
                p2_n += len(lines)
                continue
        else:
            if p2_n + len(lines) <= per_page:
                p2.extend(lines)
                p2_n += len(lines)
                continue
            if p1_n + len(lines) <= per_page:
                p1.extend(lines)
                p1_n += len(lines)
                continue

        # If it doesn't fit, drop it (we already truncated oversized sections).
        # This is rare; it would mean total content exceeds 2 pages.
        continue

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

    page_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return page_file


def main() -> None:
    """
    Update:
      - page 503: TV highlights (non-sports) subpage 1
      - page 503.2: TV highlights (non-sports) subpage 2

    Both are limited to the next 4 hours and the 4 main channels:
      BBC One, BBC Two, ITV1, Channel 4
    """
    now_utc = datetime.now(timezone.utc)
    end_utc = now_utc + timedelta(hours=4)

    listings: List[TvListing] = []
    listings += fetch_bbc_iplayer_channel(channel_key="bbcone", channel_label="BBC One", start_utc=now_utc, end_utc=end_utc)
    listings += fetch_bbc_iplayer_channel(channel_key="bbctwo", channel_label="BBC Two", start_utc=now_utc, end_utc=end_utc)
    listings += fetch_channel4(start_utc=now_utc, end_utc=end_utc)
    # ITV1: fallback for now; still keeps the 4-channel requirement satisfied.
    listings += fetch_itv1_tvmaze_fallback(start_utc=now_utc, end_utc=end_utc)

    listings.sort(key=lambda x: x.start_utc)

    # Sports highlights page removed; we exclude sports from both TV highlight subpages.
    non_sports = [x for x in listings if not _is_sports_listing(x)]

    source_note = "Sources: BBC iPlayer, Channel4 TV Guide, ITV1 via TVMaze fallback"

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

