from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .binance_client import BinanceClient, BinanceError, d, money
from .order_history import ai_spent_today_usdt, append_history, extract_execution, read_history, summarize_history
from .signal_engine import build_signal

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
SYMBOL = "BTCUSDT"
BASE_ASSET = "BTC"
QUOTE_ASSET = "USDT"
CONFIRM_TEXT = "PLACE REAL BTC ORDER"
ALLOWED_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_decimal(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


def make_client() -> BinanceClient:
    return BinanceClient(
        api_key=os.getenv("BINANCE_API_KEY"),
        secret_key=os.getenv("BINANCE_SECRET_KEY"),
        env=os.getenv("BINANCE_ENV", "live"),
        base_url=os.getenv("BINANCE_BASE_URL") or None,
        public_base_url=os.getenv("BINANCE_PUBLIC_BASE_URL") or None,
    )


class OrderRequest(BaseModel):
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET"] = Field(default="MARKET", alias="type")
    quantity: Decimal | None = None
    quoteOrderQty: Decimal | None = None
    dryRun: bool = True
    confirm: str = ""
    source: Literal["manual", "ai"] = "manual"


app = FastAPI(title="BTC Binance Monitor")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    client = make_client()
    return {
        "symbol": SYMBOL,
        "baseAsset": BASE_ASSET,
        "quoteAsset": QUOTE_ASSET,
        "binanceEnv": client.env,
        "binanceBaseUrl": client.base_url,
        "binancePublicBaseUrl": client.public_base_url,
        "hasCredentials": client.has_credentials,
        "liveTradingEnabled": env_bool("ENABLE_LIVE_TRADING"),
        "manualLiveTradingEnabled": env_bool("ENABLE_LIVE_TRADING"),
        "aiLiveOrdersEnabled": env_bool("ALLOW_AI_LIVE_ORDERS"),
        "maxOrderUsdt": float(env_decimal("MAX_ORDER_USDT", "25")),
        "maxBaseQty": float(env_decimal("MAX_BTC_QTY", "0.0002")),
        "maxBtcQty": float(env_decimal("MAX_BTC_QTY", "0.0002")),
        "aiOrderUsdt": float(env_decimal("AI_ORDER_USDT", "10")),
        "aiOrderBaseQty": float(env_decimal("AI_ORDER_BTC_QTY", "0.0001")),
        "aiOrderBtcQty": float(env_decimal("AI_ORDER_BTC_QTY", "0.0001")),
        "aiDailyBudgetUsdt": float(env_decimal("AI_DAILY_BUDGET_USDT", "25")),
    }


@app.get("/api/market")
async def market() -> dict[str, Any]:
    client = make_client()
    try:
        ticker = await client.public_get("/api/v3/ticker/24hr", {"symbol": SYMBOL})
        klines = await client.public_get(
            "/api/v3/klines",
            {"symbol": SYMBOL, "interval": "1h", "limit": 120},
        )
    except BinanceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    signal = build_signal(ticker, klines)
    return {
        "symbol": SYMBOL,
        "price": float(d(ticker.get("lastPrice"))),
        "priceChangePercent": float(d(ticker.get("priceChangePercent"))),
        "highPrice": float(d(ticker.get("highPrice"))),
        "lowPrice": float(d(ticker.get("lowPrice"))),
        "volume": float(d(ticker.get("volume"))),
        "quoteVolume": float(d(ticker.get("quoteVolume"))),
        "signal": signal,
        "updatedAt": ticker.get("closeTime"),
    }


@app.get("/api/candles")
async def candles(
    interval: str = Query(default="1h"),
    limit: int = Query(default=120, ge=20, le=500),
) -> dict[str, Any]:
    if interval not in ALLOWED_INTERVALS:
        raise HTTPException(status_code=400, detail="Unsupported candle interval.")

    client = make_client()
    try:
        klines = await client.public_get(
            "/api/v3/klines",
            {"symbol": SYMBOL, "interval": interval, "limit": limit},
        )
    except BinanceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "symbol": SYMBOL,
        "interval": interval,
        "candles": [
            {
                "openTime": row[0],
                "open": float(d(row[1])),
                "high": float(d(row[2])),
                "low": float(d(row[3])),
                "close": float(d(row[4])),
                "volume": float(d(row[5])),
                "ma7": moving_average(klines, index, 7),
                "ma30": moving_average(klines, index, 30),
                "ma99": moving_average(klines, index, 99),
                "closeTime": row[6],
            }
            for index, row in enumerate(klines)
        ],
    }


@app.get("/api/account")
async def account() -> dict[str, Any]:
    client = make_client()
    if not client.has_credentials:
        raise HTTPException(status_code=400, detail="ยังไม่ได้ตั้งค่า Binance API key ในไฟล์ .env")

    try:
        account_payload = await client.signed_request("GET", "/api/v3/account")
        ticker = await client.public_get("/api/v3/ticker/price", {"symbol": SYMBOL})
        trades = await client.signed_request("GET", "/api/v3/myTrades", {"symbol": SYMBOL, "limit": 1000})
    except BinanceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    base_price = d(ticker.get("price"))
    balances = account_payload.get("balances", [])
    non_zero = []
    base_total = Decimal("0")
    quote_total = Decimal("0")
    for item in balances:
        free = d(item.get("free"))
        locked = d(item.get("locked"))
        total = free + locked
        if total <= 0:
            continue
        asset = item.get("asset")
        if asset == BASE_ASSET:
            base_total = total
        if asset == QUOTE_ASSET:
            quote_total = total
        non_zero.append(
            {
                "asset": asset,
                "free": float(free),
                "locked": float(locked),
                "total": float(total),
            }
        )

    pnl = calculate_symbol_pnl(trades, base_price, base_total)
    base_value = base_total * base_price
    return {
        "basePrice": float(base_price),
        "ethPrice": float(base_price),
        "balances": non_zero,
        "base": {
            "asset": BASE_ASSET,
            "quantity": float(base_total),
            "valueUsdt": money(base_value),
        },
        "eth": {
            "quantity": float(base_total),
            "valueUsdt": money(base_value),
        },
        "usdt": {
            "quantity": float(quote_total),
        },
        "portfolio": {
            "trackedValueUsdt": money(base_value + quote_total),
            "note": f"มูลค่านี้นับเฉพาะ {BASE_ASSET} และ {QUOTE_ASSET} เพื่อเลี่ยงการเดาราคาของเหรียญอื่นผิดพลาด",
        },
        "pnl": pnl,
    }


@app.get("/api/ai/signal")
async def ai_signal() -> dict[str, Any]:
    market_payload = await market()
    return market_payload["signal"]


@app.post("/api/ai/execute")
async def execute_ai_order(dryRun: bool = True) -> dict[str, Any]:
    signal = await ai_signal()
    side = signal.get("decision", "WAIT")
    if side == "WAIT":
        append_history(
            {
                "source": "ai",
                "status": "blocked",
                "reason": "AI signal is WAIT. No order was created.",
                "symbol": SYMBOL,
                "side": "WAIT",
                "type": "MARKET",
                "dryRun": dryRun,
                "signal": signal,
            }
        )
        return {"status": "blocked", "reason": "AI signal is WAIT. No order was created.", "signal": signal}

    if side == "BUY":
        order = OrderRequest(
            side="BUY",
            type="MARKET",
            quoteOrderQty=env_decimal("AI_ORDER_USDT", "10"),
            dryRun=dryRun,
            confirm=CONFIRM_TEXT if not dryRun else "",
            source="ai",
        )
    else:
        order = OrderRequest(
            side="SELL",
            type="MARKET",
            quantity=env_decimal("AI_ORDER_BTC_QTY", "0.0001"),
            dryRun=dryRun,
            confirm=CONFIRM_TEXT if not dryRun else "",
            source="ai",
        )
    return await create_order(order)


@app.get("/api/orders/history")
async def order_history() -> dict[str, Any]:
    client = make_client()
    current_price: Decimal | None = None
    try:
        ticker = await client.public_get("/api/v3/ticker/price", {"symbol": SYMBOL})
        current_price = d(ticker.get("price"))
    except BinanceError:
        current_price = None
    return {"summary": summarize_history(current_price), "orders": read_history()}


@app.post("/api/orders")
async def create_order(order: OrderRequest) -> dict[str, Any]:
    client = make_client()
    manual_live_trading = env_bool("ENABLE_LIVE_TRADING")
    ai_live_orders = env_bool("ALLOW_AI_LIVE_ORDERS")

    if order.source == "ai" and not ai_live_orders:
        response = {
            "status": "blocked",
            "reason": "AI live orders are disabled. Set ALLOW_AI_LIVE_ORDERS=true only after testnet validation.",
        }
        append_history(history_entry(order, "blocked", build_order_params_safely(order), response["reason"]))
        return response

    params = build_order_params(order)
    live_allowed = ai_live_orders if order.source == "ai" else manual_live_trading
    should_dry_run = order.dryRun or not live_allowed
    await enforce_order_limits(client, order, should_dry_run)
    await enforce_ai_budget(order, params)
    if should_dry_run:
        reason = "Dry-run requested."
        if not order.dryRun and order.source == "manual" and not manual_live_trading:
            reason = "Manual live trading is disabled. Only AI live orders can be sent when ALLOW_AI_LIVE_ORDERS=true."
        elif not order.dryRun and order.source == "ai" and not ai_live_orders:
            reason = "AI live orders are disabled."
        response = {
            "status": "dry_run",
            "reason": reason,
            "wouldSend": params,
        }
        append_history(history_entry(order, "dry_run", params, response["reason"]))
        return response

    if order.confirm != CONFIRM_TEXT:
        append_history(history_entry(order, "blocked", params, "Missing real-order confirmation text."))
        raise HTTPException(
            status_code=400,
            detail=f"พิมพ์ '{CONFIRM_TEXT}' เพื่อยืนยันคำสั่งเงินจริง",
        )

    try:
        result = await client.signed_request("POST", "/api/v3/order", params)
    except BinanceError as exc:
        append_history(history_entry(order, "failed", params, str(exc)))
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    append_history(
        {
            **history_entry(order, "submitted", params, "Order submitted to Binance."),
            **extract_execution(result),
            "binanceStatus": result.get("status"),
        }
    )
    return {"status": "submitted", "result": result}


@app.post("/api/orders/validate")
async def validate_order(order: OrderRequest) -> dict[str, Any]:
    client = make_client()
    params = build_order_params(order)
    await enforce_order_limits(client, order, should_dry_run=False)
    await enforce_ai_budget(order, params)
    try:
        await client.signed_request("POST", "/api/v3/order/test", params)
    except BinanceError as exc:
        return {"status": "error", "reason": str(exc), "wouldSend": params}
    return {"status": "ok", "reason": "Binance accepted this test order. No real order was placed.", "wouldSend": params}


def build_order_params(order: OrderRequest) -> dict[str, Any]:
    if order.side == "BUY" and order.quoteOrderQty is None:
        raise HTTPException(status_code=400, detail="BUY MARKET ต้องใส่ quoteOrderQty เป็นจำนวน USDT")
    if order.side == "SELL" and order.quantity is None:
        raise HTTPException(status_code=400, detail=f"SELL MARKET ต้องใส่ quantity เป็นจำนวน {BASE_ASSET}")

    params: dict[str, Any] = {
        "symbol": SYMBOL,
        "side": order.side,
        "type": order.order_type,
    }
    if order.quoteOrderQty is not None:
        params["quoteOrderQty"] = str(order.quoteOrderQty)
    if order.quantity is not None:
        params["quantity"] = str(order.quantity)
    params["newOrderRespType"] = "FULL"
    return params


def build_order_params_safely(order: OrderRequest) -> dict[str, Any]:
    try:
        return build_order_params(order)
    except HTTPException:
        return {"symbol": SYMBOL, "side": order.side, "type": order.order_type}


def history_entry(order: OrderRequest, status: str, params: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "source": order.source,
        "status": status,
        "reason": reason,
        "symbol": SYMBOL,
        "side": order.side,
        "type": order.order_type,
        "dryRun": order.dryRun,
        "quantity": str(order.quantity) if order.quantity is not None else None,
        "quoteOrderQty": str(order.quoteOrderQty) if order.quoteOrderQty is not None else None,
        "params": {key: value for key, value in params.items() if key != "signature"},
    }


def moving_average(klines: list[list[Any]], index: int, period: int) -> float | None:
    start = index - period + 1
    if start < 0:
        return None
    closes = [d(row[4]) for row in klines[start : index + 1]]
    return float((sum(closes) / Decimal(period)).quantize(Decimal("0.01")))


async def enforce_order_limits(client: BinanceClient, order: OrderRequest, should_dry_run: bool) -> None:
    max_usdt = env_decimal("MAX_ORDER_USDT", "25")
    max_base_qty = env_decimal("MAX_BTC_QTY", "0.0002")

    if order.quoteOrderQty is not None and order.quoteOrderQty > max_usdt:
        raise HTTPException(status_code=400, detail=f"เกิน MAX_ORDER_USDT ({max_usdt})")

    if order.quantity is not None and order.quantity > max_base_qty:
        raise HTTPException(status_code=400, detail=f"เกิน MAX_BTC_QTY ({max_base_qty})")

    if order.quantity is not None:
        try:
            ticker = await client.public_get("/api/v3/ticker/price", {"symbol": SYMBOL})
        except BinanceError as exc:
            if should_dry_run:
                return
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        notional = order.quantity * d(ticker.get("price"))
        if notional > max_usdt:
            raise HTTPException(status_code=400, detail=f"มูลค่าออเดอร์เกิน MAX_ORDER_USDT ({max_usdt})")


async def enforce_ai_budget(order: OrderRequest, params: dict[str, Any]) -> None:
    if order.source != "ai":
        return

    ai_order_usdt = env_decimal("AI_ORDER_USDT", "10")
    ai_daily_budget = env_decimal("AI_DAILY_BUDGET_USDT", "25")
    if order.side == "BUY":
        quote_qty = d(params.get("quoteOrderQty"))
        if quote_qty > ai_order_usdt:
            raise HTTPException(status_code=400, detail=f"AI order exceeds AI_ORDER_USDT ({ai_order_usdt})")
        spent_today = ai_spent_today_usdt(read_history())
        if spent_today + quote_qty > ai_daily_budget:
            raise HTTPException(status_code=400, detail=f"AI daily budget exceeded ({ai_daily_budget} USDT)")


def calculate_symbol_pnl(trades: list[dict[str, Any]], current_price: Decimal, account_base: Decimal) -> dict[str, Any]:
    inventory = Decimal("0")
    cost_basis = Decimal("0")
    realized = Decimal("0")
    total_fees_usdt = Decimal("0")

    for trade in sorted(trades, key=lambda item: item.get("time", 0)):
        qty = d(trade.get("qty"))
        price = d(trade.get("price"))
        quote = qty * price
        commission = d(trade.get("commission"))
        commission_asset = trade.get("commissionAsset")
        is_buy = bool(trade.get("isBuyer"))

        if commission_asset == "USDT":
            total_fees_usdt += commission
        elif commission_asset == BASE_ASSET:
            qty -= commission

        if is_buy:
            fee_usdt = commission if commission_asset == "USDT" else Decimal("0")
            inventory += qty
            cost_basis += quote + fee_usdt
        else:
            fee_usdt = commission if commission_asset == "USDT" else Decimal("0")
            average_cost = cost_basis / inventory if inventory > 0 else Decimal("0")
            sold_qty = min(qty, inventory)
            proceeds = quote - fee_usdt
            realized += proceeds - (average_cost * sold_qty)
            inventory -= sold_qty
            cost_basis -= average_cost * sold_qty

    current_value = account_base * current_price
    unrealized = current_value - cost_basis if account_base > 0 else Decimal("0")
    return {
        "realizedUsdt": money(realized),
        "unrealizedUsdt": money(unrealized),
        "totalUsdt": money(realized + unrealized),
        "estimatedCostBasisUsdt": money(cost_basis),
        "trackedTradeInventoryBase": float(inventory),
        "accountInventoryBase": float(account_base),
        "trackedTradeInventoryEth": float(inventory),
        "accountInventoryEth": float(account_base),
        "trackedFeesUsdt": money(total_fees_usdt),
        "tradeCountUsed": len(trades),
        "warning": f"PnL เป็นค่าประมาณจากประวัติ {SYMBOL} ล่าสุด ไม่รวมการโอนเข้าออกหรือการซื้อขาย {BASE_ASSET} ผ่านคู่อื่น",
    }
