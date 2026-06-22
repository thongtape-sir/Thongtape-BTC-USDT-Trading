from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import postgres_store


ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_HISTORY_PATH = ROOT / "data" / "portfolio_value_history.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def min_snapshot_interval() -> timedelta:
    try:
        seconds = int(os.getenv("PORTFOLIO_SNAPSHOT_MIN_INTERVAL_SECONDS", "600"))
    except ValueError:
        seconds = 600
    return timedelta(seconds=max(0, seconds))


def parse_created_at(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_portfolio_history(limit: int = 100) -> list[dict[str, Any]]:
    if postgres_store.enabled():
        try:
            rows = postgres_store.read_portfolio_values(limit)
            postgres_store.set_last_error(None)
            return rows
        except Exception as exc:
            postgres_store.set_last_error(exc)

    if not PORTFOLIO_HISTORY_PATH.exists():
        return []
    try:
        payload = json.loads(PORTFOLIO_HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload if isinstance(payload, list) else []
    return rows[:limit]


def append_portfolio_snapshot(entry: dict[str, Any]) -> dict[str, Any]:
    latest = read_portfolio_history(limit=1)
    if latest:
        latest_time = parse_created_at(latest[0].get("createdAt"))
        if latest_time and datetime.now(timezone.utc) - latest_time < min_snapshot_interval():
            return latest[0]

    record = {
        "id": str(uuid4()),
        "createdAt": utc_now(),
        **entry,
    }
    if postgres_store.enabled():
        try:
            postgres_store.append_portfolio_value(record)
            postgres_store.set_last_error(None)
            return record
        except Exception as exc:
            postgres_store.set_last_error(exc)

    PORTFOLIO_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = read_portfolio_history(limit=1000)
    history.insert(0, record)
    PORTFOLIO_HISTORY_PATH.write_text(
        json.dumps(history[:1000], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return record
