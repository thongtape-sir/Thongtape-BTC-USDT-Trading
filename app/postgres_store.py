from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

LAST_ERROR: str | None = None


def database_url() -> str | None:
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    if "sslmode=" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}sslmode=require"


def enabled() -> bool:
    return bool(database_url())


def set_last_error(exc: Exception | str | None) -> None:
    global LAST_ERROR
    LAST_ERROR = None if exc is None else str(exc)


def status() -> dict[str, Any]:
    return {
        "postgresEnabled": enabled(),
        "lastError": LAST_ERROR,
    }


def connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("DATABASE_URL is set but psycopg is not installed. Run pip install -r requirements.txt.") from exc

    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg.connect(url, connect_timeout=10)


def jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def init_db() -> None:
    if not enabled():
        return

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists bot_config (
                  id text primary key default 'default',
                  config jsonb not null,
                  updated_at timestamptz not null default now()
                )
                """
            )
            cur.execute(
                """
                create table if not exists order_history (
                  id bigserial primary key,
                  created_at timestamptz not null default now(),
                  payload jsonb not null
                )
                """
            )
            cur.execute(
                """
                create table if not exists bot_run_log (
                  id bigserial primary key,
                  created_at timestamptz not null default now(),
                  trigger text,
                  status text,
                  reason text,
                  payload jsonb
                )
                """
            )
            cur.execute("create index if not exists idx_order_history_created_at on order_history (created_at desc)")
            cur.execute("create index if not exists idx_bot_run_log_created_at on bot_run_log (created_at desc)")
    set_last_error(None)


def read_bot_config() -> dict[str, Any] | None:
    if not enabled():
        return None
    init_db()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select config from bot_config where id = 'default'")
            row = cur.fetchone()
            return row[0] if row else None


def write_bot_config(config: dict[str, Any]) -> None:
    if not enabled():
        return
    init_db()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into bot_config (id, config, updated_at)
                values ('default', %s, now())
                on conflict (id) do update
                  set config = excluded.config,
                      updated_at = now()
                """,
                (jsonb(config),),
            )


def read_order_history(limit: int = 1000) -> list[dict[str, Any]]:
    if not enabled():
        return []
    init_db()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select payload from order_history order by created_at desc, id desc limit %s", (limit,))
            return [row[0] for row in cur.fetchall()]


def append_order_history(record: dict[str, Any]) -> None:
    if not enabled():
        return
    init_db()
    created_at = record.get("createdAt")
    try:
        created_at_dt = datetime.fromisoformat(str(created_at))
    except (TypeError, ValueError):
        created_at_dt = datetime.now(timezone.utc)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into order_history (created_at, payload) values (%s, %s)",
                (created_at_dt, jsonb(record)),
            )


def append_bot_run_log(trigger: str, status: str, reason: str | None, payload: dict[str, Any]) -> None:
    if not enabled():
        return
    init_db()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into bot_run_log (trigger, status, reason, payload)
                values (%s, %s, %s, %s)
                """,
                (trigger, status, reason, jsonb(payload)),
            )
