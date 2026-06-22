from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import postgres_store


ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_HISTORY_PATH = ROOT / "data" / "portfolio_value_history.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
