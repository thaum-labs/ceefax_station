"""Shared data-provider, fallback, cache, and atomic-write utilities."""

from __future__ import annotations

import json
import os
import tempfile
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generic, Iterable, Mapping, TypeVar

import requests


T = TypeVar("T")
FOOTBALL_DATA_API_ROOT = "https://api.football-data.org/v4"
FOOTBALL_DATA_API_KEY_ENV = "FOOTBALL_DATA_API_KEY"
_PROVIDER_ACTIVITY: dict[str, ProviderResult] = {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ceefax_root() -> Path:
    return Path(__file__).resolve().parent.parent


def provider_cache_dir() -> Path:
    configured = os.environ.get("CEEFAX_PROVIDER_CACHE")
    path = Path(configured).expanduser() if configured else _ceefax_root() / "cache" / "providers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
    digest = sha256(key.encode("utf-8")).hexdigest()[:8]
    return provider_cache_dir() / f"{safe}-{digest}.json"


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    data: T
    source: str
    fetched_at: str
    stale: bool = False
    error: str | None = None

    @property
    def status_label(self) -> str:
        if self.stale:
            return f"Cached {self.fetched_at}"
        return f"Updated {self.fetched_at}"


class ProviderUnavailable(RuntimeError):
    """Raised only when every provider fails and there is no last-good cache."""


Provider = tuple[str, Callable[[], T]]


def clear_provider_activity() -> None:
    """Clear in-process provider telemetry at the start of an update run."""
    _PROVIDER_ACTIVITY.clear()


def provider_activity_snapshot() -> dict[str, ProviderResult]:
    """Return provider results resolved during the current process run."""
    return dict(_PROVIDER_ACTIVITY)


def _record_activity(key: str, result: ProviderResult[T]) -> ProviderResult[T]:
    _PROVIDER_ACTIVITY[key] = result
    return result


def _safe_error(exc: Exception) -> str:
    """Format provider errors without leaking configured API credentials."""
    message = str(exc)
    for name, value in os.environ.items():
        upper = name.upper()
        if value and len(value) >= 4 and any(token in upper for token in ("KEY", "TOKEN", "SECRET")):
            message = message.replace(value, "[REDACTED]")
    return message


def _is_valid_default(data: object) -> bool:
    if data is None:
        return False
    if isinstance(data, (list, tuple, dict, set, str, bytes)):
        return len(data) > 0
    return True


def save_last_good(key: str, result: ProviderResult[T]) -> None:
    payload = {
        "schema": 1,
        "source": result.source,
        "fetched_at": result.fetched_at,
        "data": result.data,
    }
    atomic_write_json(_cache_path(key), payload)


def load_last_good(key: str) -> ProviderResult | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            return None
        if "data" not in payload:
            return None
        return ProviderResult(
            data=payload["data"],
            source=str(payload.get("source") or "cache"),
            fetched_at=str(payload.get("fetched_at") or "unknown"),
            stale=True,
        )
    except (OSError, ValueError, TypeError):
        return None


def resolve_provider(
    key: str,
    providers: Iterable[Provider[T]],
    *,
    is_valid: Callable[[T], bool] | None = None,
    fresh_for_seconds: float | None = None,
) -> ProviderResult[T]:
    """
    Optionally reuse a fresh last-good response, otherwise try providers in
    order and save the first valid response. Fall back indefinitely to stale
    last-good data. Provider exceptions are collected for diagnostics.
    """
    validate = is_valid or _is_valid_default
    cached = load_last_good(key)
    if cached is not None:
        try:
            if not validate(cached.data):
                cached = None
        except Exception:  # noqa: BLE001
            cached = None
    if cached is not None and fresh_for_seconds is not None:
        try:
            fetched_at = datetime.fromisoformat(cached.fetched_at.replace("Z", "+00:00"))
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
            if 0 <= age <= fresh_for_seconds:
                return _record_activity(
                    key,
                    ProviderResult(
                        data=cached.data,
                        source=cached.source,
                        fetched_at=cached.fetched_at,
                    ),
                )
        except (TypeError, ValueError):
            pass

    errors: list[str] = []
    for source, fetch in providers:
        try:
            data = fetch()
            if not validate(data):
                raise ValueError("empty or invalid response")
            result = ProviderResult(data=data, source=source, fetched_at=_utcnow_iso())
            try:
                save_last_good(key, result)
            except Exception as exc:  # noqa: BLE001
                # Cache persistence must not turn valid live data into a failed page.
                result = ProviderResult(
                    data=data,
                    source=source,
                    fetched_at=result.fetched_at,
                    error=f"cache write failed: {_safe_error(exc)}",
                )
            return _record_activity(key, result)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{source}: {_safe_error(exc)}")

    if cached is not None:
        return _record_activity(
            key,
            ProviderResult(
                data=cached.data,
                source=cached.source,
                fetched_at=cached.fetched_at,
                stale=True,
                error="; ".join(errors) or "providers unavailable",
            ),
        )
    raise ProviderUnavailable("; ".join(errors) or f"No providers configured for {key}")


def atomic_write_json(path: Path, payload: object) -> None:
    """Atomically replace a JSON file so readers never see a partial page/cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise


def require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ProviderUnavailable(f"{name} is not configured")
    return value


def fetch_football_data(
    path: str,
    *,
    params: Mapping[str, str] | None = None,
    timeout: float = 15,
) -> dict[str, Any]:
    """Fetch one authenticated football-data.org v4 JSON resource."""
    token = require_env(FOOTBALL_DATA_API_KEY_ENV)
    response = requests.get(
        f"{FOOTBALL_DATA_API_ROOT}/{path.lstrip('/')}",
        headers={"X-Auth-Token": token},
        params=dict(params or {}),
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("football-data.org returned a non-object JSON response")
    return payload
