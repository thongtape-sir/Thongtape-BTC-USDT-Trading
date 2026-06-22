from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from .binance_client import d, money
from . import postgres_store

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "data" / "order_history.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_history(
    side: str | None = None,
    status: str | None = None,
    source: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    if postgres_store.enabled():
        try:
            history = postgres_store.read_order_history()
            postgres_store.set_last_error(None)
            return filter_history(history, side=side, status=status, source=source, limit=limit)
        except Exception as exc:
            postgres_store.set_last_error(exc)

    if not HISTORY_PATH.exists():
        return []
    try:
        payload = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    history = payload if isinstance(payload, list) else []
    return filter_history(history, side=side, status=status, source=source, limit=limit)


def append_history(entry: dict[str, Any]) -> dict[str, Any]:
    record = {
        "id": str(uuid4()),
        "createdAt": utc_now(),
        **entry,
    }
    if postgres_store.enabled():
        try:
            postgres_store.append_order_history(record)
            postgres_store.set_last_error(None)
            return record
        except Exception as exc:
            postgres_store.set_last_error(exc)

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = read_history()
    history.insert(0, record)
    HISTORY_PATH.write_text(json.dumps(history[:1000], ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def summarize_history(current_price: Decimal | None = None) -> dict[str, Any]:
    history = read_history(limit=1000)
    live_orders = [item for item in history if item.get("status") == "submitted"]
    dry_runs = [item for item in history if item.get("status") == "dry_run"]
    blocked = [item for item in history if item.get("status") == "blocked"]
    failed = [item for item in history if item.get("status") == "failed"]

    buy_qty = Decimal("0")
    buy_cost = Decimal("0")
    sell_qty = Decimal("0")
    sell_proceeds = Decimal("0")
    fees_usdt = Decimal("0")

    for item in live_orders:
        side = item.get("side")
        qty = d(item.get("executedQty"))
        quote = d(item.get("cummulativeQuoteQty"))
        fees_usdt += d(item.get("estimatedFeeUsdt"))
        if side == "BUY":
            buy_qty += qty
            buy_cost += quote
        elif side == "SELL":
            sell_qty += qty
            sell_proceeds += quote

    net_qty = buy_qty - sell_qty
    realized_like = sell_proceeds - ((buy_cost / buy_qty) * sell_qty if buy_qty > 0 else Decimal("0")) - fees_usdt
    open_cost = (buy_cost / buy_qty) * net_qty if buy_qty > 0 and net_qty > 0 else Decimal("0")
    mark_value = net_qty * current_price if current_price is not None and net_qty > 0 else Decimal("0")
    unrealized_like = mark_value - open_cost if current_price is not None and net_qty > 0 else Decimal("0")

    return {
        "liveOrderCount": len(live_orders),
        "dryRunCount": len(dry_runs),
        "blockedCount": len(blocked),
        "failedCount": len(failed),
        "buyQtyBase": float(buy_qty),
        "buyQtyEth": float(buy_qty),
        "buyCostUsdt": money(buy_cost),
        "sellQtyBase": float(sell_qty),
        "sellQtyEth": float(sell_qty),
        "sellProceedsUsdt": money(sell_proceeds),
        "netQtyBase": float(net_qty),
        "netQtyEth": float(net_qty),
        "estimatedFeesUsdt": money(fees_usdt),
        "estimatedRealizedUsdt": money(realized_like),
        "estimatedUnrealizedUsdt": money(unrealized_like),
        "estimatedTotalUsdt": money(realized_like + unrealized_like),
        "note": "สรุปนี้คำนวณจาก order ที่ส่งผ่านแอปนี้เท่านั้น ไม่รวม order ที่ส่งจาก Binance โดยตรง",
    }


def extract_execution(order_result: dict[str, Any]) -> dict[str, Any]:
    fills = order_result.get("fills") if isinstance(order_result, dict) else None
    fee_usdt = Decimal("0")
    if isinstance(fills, list):
        for fill in fills:
            commission = d(fill.get("commission"))
            asset = fill.get("commissionAsset")
            price = d(fill.get("price"))
            if asset == "USDT":
                fee_usdt += commission
            elif asset:
                fee_usdt += commission * price

    executed_qty = d(order_result.get("executedQty", "0"))
    quote_qty = d(order_result.get("cummulativeQuoteQty", "0"))
    average_price = quote_qty / executed_qty if executed_qty > 0 else Decimal("0")

    return {
        "orderId": order_result.get("orderId"),
        "clientOrderId": order_result.get("clientOrderId"),
        "executedQty": order_result.get("executedQty", "0"),
        "cummulativeQuoteQty": order_result.get("cummulativeQuoteQty", "0"),
        "averagePrice": str(average_price),
        "estimatedFeeUsdt": str(fee_usdt),
    }


def ai_spent_today_usdt(history: list[dict[str, Any]]) -> Decimal:
    today = datetime.now(timezone.utc).date()
    spent = Decimal("0")
    for item in history:
        if item.get("source") != "ai" or item.get("status") != "submitted" or item.get("side") != "BUY":
            continue
        try:
            created_at = datetime.fromisoformat(str(item.get("createdAt"))).date()
        except ValueError:
            continue
        if created_at == today:
            spent += d(item.get("cummulativeQuoteQty"))
    return spent


def filter_history(
    history: list[dict[str, Any]],
    side: str | None = None,
    status: str | None = None,
    source: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    side = side if isinstance(side, str) else None
    status = status if isinstance(status, str) else None
    source = source if isinstance(source, str) else None
    rows = history
    if side and side != "ALL":
        rows = [item for item in rows if str(item.get("side", "")).upper() == side.upper()]
    if status and status != "ALL":
        rows = [item for item in rows if str(item.get("status", "")).lower() == status.lower()]
    if source and source != "ALL":
        rows = [item for item in rows if str(item.get("source", "")).lower() == source.lower()]
    return rows[: max(1, min(limit, 1000))]
