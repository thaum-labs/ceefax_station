"""Best-effort email notifications for tracker log uploads (Resend).

Enabled when RESEND_API_KEY is set. Never raises into the ingest path.
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests


RESEND_API_URL = "https://api.resend.com/emails"

# In-process cooldown so a busy uploader does not flood the inbox.
_last_notify_at: dict[str, float] = {}
_warned_not_configured = False


def notify_config() -> dict[str, Any]:
    """Return resolved notify settings (empty api_key means disabled)."""
    api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    to_raw = (os.environ.get("CEEFAXWEB_NOTIFY_TO") or "tobias.j.franklin@gmail.com").strip()
    # Resend allows delivered@resend.dev without verifying your own domain.
    from_addr = (
        os.environ.get("CEEFAXWEB_NOTIFY_FROM") or "Ceefax Station <delivered@resend.dev>"
    ).strip()
    cooldown = float(os.environ.get("CEEFAXWEB_NOTIFY_COOLDOWN_SECONDS") or "120")
    recipients = [part.strip() for part in to_raw.split(",") if part.strip()]
    return {
        "api_key": api_key,
        "to": recipients,
        "from": from_addr,
        "cooldown_seconds": max(0.0, cooldown),
        "enabled": bool(api_key and recipients and from_addr),
    }


def _should_skip_source(source_path: str | None) -> bool:
    src = (source_path or "").strip().lower()
    return src.startswith("sample:")


def _cooldown_key(callsign: str | None, reason: str) -> str:
    return f"{(callsign or 'UNKNOWN').upper()}|{reason}"


def _under_cooldown(key: str, cooldown_seconds: float) -> bool:
    if cooldown_seconds <= 0:
        return False
    last = _last_notify_at.get(key)
    if last is None:
        return False
    return (time.monotonic() - last) < cooldown_seconds


def build_upload_email(
    *,
    reason: str,
    uploader_callsign: str | None,
    uploader_grid: str | None,
    source_path: str | None,
    log: dict[str, Any],
) -> tuple[str, str]:
    """Return (subject, plain-text body) for an ingest notification."""
    kind = str(log.get("kind") or "")
    if kind == "ceefax_tx_report":
        station = str(log.get("station_callsign") or uploader_callsign or "UNKNOWN").upper()
        pages = log.get("page_ids") if isinstance(log.get("page_ids"), list) else []
        subject = f"Ceefax upload: TX from {station}"
        detail_lines = [
            f"Type: TX report",
            f"Station: {station}",
            f"Grid: {log.get('station_grid') or uploader_grid or '-'}",
            f"Frequency: {log.get('frequency') or '-'}",
            f"Pages ({len(pages)}): {', '.join(str(p) for p in pages[:20]) or '-'}",
            f"TX id: {log.get('tx_id') or '-'}",
        ]
    else:
        listener = str(log.get("listener_callsign") or uploader_callsign or "UNKNOWN").upper()
        heard = str(log.get("station_callsign") or "-").upper() if log.get("station_callsign") else "-"
        decoded = log.get("pages_decoded") if isinstance(log.get("pages_decoded"), dict) else {}
        subject = f"Ceefax upload: RX from {listener}"
        detail_lines = [
            f"Type: RX / listen report",
            f"Listener: {listener}",
            f"Grid: {log.get('listener_grid') or uploader_grid or '-'}",
            f"Heard TX: {heard}",
            f"Frequency: {log.get('frequency') or '-'}",
            f"Pages decoded: {len(decoded)}",
            f"TX id: {log.get('tx_id') or '-'}",
        ]

    body = "\n".join(
        [
            "A station uploaded data to ceefaxstation.com.",
            "",
            *detail_lines,
            f"Uploader callsign: {uploader_callsign or '-'}",
            f"Uploader grid: {uploader_grid or '-'}",
            f"Source: {source_path or '-'}",
            f"Ingest reason: {reason}",
            "",
            "Map: https://ceefaxstation.com/",
        ]
    )
    return subject, body


def notify_upload(
    *,
    reason: str,
    uploader_callsign: str | None,
    uploader_grid: str | None,
    source_path: str | None,
    log: dict[str, Any],
    session: Any | None = None,
) -> dict[str, Any]:
    """
    Send an upload notification email via Resend.

    Returns a status dict; never raises.
    """
    try:
        if _should_skip_source(source_path):
            return {"ok": False, "skipped": "sample"}

        cfg = notify_config()
        if not cfg["enabled"]:
            global _warned_not_configured
            if not _warned_not_configured:
                print("Warning: upload notify skipped (RESEND_API_KEY not configured)")
                _warned_not_configured = True
            return {"ok": False, "skipped": "not_configured"}

        key = _cooldown_key(uploader_callsign, reason)
        if _under_cooldown(key, cfg["cooldown_seconds"]):
            return {"ok": False, "skipped": "cooldown"}

        subject, text = build_upload_email(
            reason=reason,
            uploader_callsign=uploader_callsign,
            uploader_grid=uploader_grid,
            source_path=source_path,
            log=log,
        )
        http = session or requests
        resp = http.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "from": cfg["from"],
                "to": cfg["to"],
                "subject": subject,
                "text": text,
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            print(f"Warning: upload notify failed HTTP {resp.status_code}: {resp.text[:300]}")
            return {"ok": False, "error": f"http_{resp.status_code}"}

        _last_notify_at[key] = time.monotonic()
        return {"ok": True, "status_code": resp.status_code}
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: upload notify error: {exc}")
        return {"ok": False, "error": str(exc)}
