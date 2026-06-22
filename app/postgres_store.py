from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

LAST_ERROR: str | None = None
RETRY_AFTER: datetime | None = None
INITIALIZED = False


def database_url() -> str | None:
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    if "sslmode=" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}sslmode=require"


def configured() -> bool:
    return bool(database_url())


def enabled() -> bool:
    return configured() and (RETRY_AFTER is None or datetime.now(timezone.utc) >= RETRY_AFTER)


def set_last_error(exc: Exception | str | None) -> None:
    global LAST_ERROR, RETRY_AFTER
    if exc is None:
        LAST_ERROR = None
        RETRY_AFTER = None
        return
    LAST_ERROR = str(exc)
    RETRY_AFTER = datetime.now(timezone.utc) + timedelta(seconds=60)


def retry_after_iso() -> str | None:
    return RETRY_AFTER.isoformat() if RETRY_AFTER else None


def status() -> dict[str, Any]:
    return {
        "postgresEnabled": configured(),
        "postgresAvailable": enabled(),
        "lastError": LAST_ERROR,
        "retryAfter": retry_after_iso(),
    }


def connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("DATABASE_URL is set but psycopg is not installed. Run pip install -r requirements.txt.") from exc

    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg.connect(url, connect_timeout=5)


def jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def init_db() -> None:
    global INITIALIZED
    if INITIALIZED:
        return
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
            cur.execute(
                """
                create table if not exists portfolio_value_history (
                  id bigserial primary key,
                  created_at timestamptz not null default now(),
                  total_value_usdt numeric,
                  base_value_usdt numeric,
                  quote_value_usdt numeric,
                  payload jsonb
                )
                """
            )
            cur.execute("create index if not exists idx_order_history_created_at on order_history (created_at desc)")
            cur.execute("create index if not exists idx_bot_run_log_created_at on bot_run_log (created_at desc)")
            cur.execute(
                "create index if not exists idx_portfolio_value_history_created_at on portfolio_value_history (created_at desc)"
            )
    INITIALIZED = True
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


def append_portfolio_value(record: dict[str, Any]) -> None:
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
                """
                insert into portfolio_value_history
                  (created_at, total_value_usdt, base_value_usdt, quote_value_usdt, payload)
                values (%s, %s, %s, %s, %s)
                """,
                (
                    created_at_dt,
                    record.get("totalValueUsdt"),
                    record.get("baseValueUsdt"),
                    record.get("quoteValueUsdt"),
                    jsonb(record),
                ),
            )


def read_portfolio_values(limit: int = 100) -> list[dict[str, Any]]:
    if not enabled():
        return []
    init_db()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select payload from portfolio_value_history order by created_at desc, id desc limit %s",
                (limit,),
            )
            return [row[0] for row in cur.fetchall()]
