from __future__ import annotations

from decimal import Decimal
from typing import Any


MIN_RISK_REWARD = Decimal("1.15")


def average(values: list[Decimal], period: int) -> Decimal | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / Decimal(period)


def pct(value: Decimal, percent: str) -> Decimal:
    return value * Decimal(percent) / Decimal("100")


def to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01")))


def decimal_at(row: list[Any], index: int, default: str = "0") -> Decimal:
    try:
        return Decimal(str(row[index]))
    except (IndexError, TypeError, ValueError):
        return Decimal(default)


def simple_rsi(closes: list[Decimal], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for previous, current in zip(closes[-period - 1 : -1], closes[-period:]):
        change = current - previous
        if change >= 0:
            gains.append(change)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(abs(change))

    average_gain = sum(gains) / Decimal(period)
    average_loss = sum(losses) / Decimal(period)
    if average_loss == 0:
        return 100.0
    rs = average_gain / average_loss
    return float(100 - (100 / (1 + rs)))


def simple_atr(klines: list[list[Any]], period: int = 14) -> Decimal | None:
    if len(klines) <= period:
        return None

    ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    for row in klines[-period - 1 :]:
        high = decimal_at(row, 2)
        low = decimal_at(row, 3)
        close = decimal_at(row, 4)
        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        ranges.append(true_range)
        previous_close = close

    return sum(ranges[-period:]) / Decimal(period)


def volume_ratio(klines: list[list[Any]], period: int = 20) -> Decimal | None:
    if len(klines) <= period:
        return None
    volumes = [decimal_at(row, 5) for row in klines[-period - 1 : -1]]
    average_volume = sum(volumes) / Decimal(len(volumes)) if volumes else Decimal("0")
    if average_volume <= 0:
        return None
    return decimal_at(klines[-1], 5) / average_volume


def support_resistance(klines: list[list[Any]], lookback: int = 20) -> tuple[Decimal | None, Decimal | None]:
    rows = klines[-lookback:]
    if not rows:
        return None, None
    lows = [decimal_at(row, 3) for row in rows]
    highs = [decimal_at(row, 2) for row in rows]
    return min(lows), max(highs)


def prior_support_resistance(klines: list[list[Any]], lookback: int = 20) -> tuple[Decimal | None, Decimal | None]:
    rows = klines[-lookback - 1 : -1]
    if not rows:
        return support_resistance(klines, lookback)
    lows = [decimal_at(row, 3) for row in rows]
    highs = [decimal_at(row, 2) for row in rows]
    return min(lows), max(highs)


def ma_slope(closes: list[Decimal], period: int, shift: int = 5) -> Decimal | None:
    if len(closes) < period + shift:
        return None
    current = average(closes, period)
    previous = average(closes[:-shift], period)
    if current is None or previous is None:
        return None
    return current - previous


def risk_reward(entry: Decimal, stop_loss: Decimal, take_profit: Decimal) -> Decimal | None:
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if risk <= 0:
        return None
    return (reward / risk).quantize(Decimal("0.01"))


def classify_regime(
    last_price: Decimal,
    ma_7: Decimal | None,
    ma_30: Decimal | None,
    ma_99: Decimal | None,
    slope_30: Decimal | None,
) -> str:
    if ma_7 and ma_30 and ma_99 and slope_30 is not None:
        if last_price > ma_7 > ma_30 > ma_99 and slope_30 > 0:
            return "bull_trend"
        if last_price < ma_7 < ma_30 < ma_99 and slope_30 < 0:
            return "bear_trend"
    if ma_99 and last_price >= ma_99:
        return "bull_bias"
    if ma_99 and last_price < ma_99:
        return "bear_bias"
    return "range"


def build_signal(ticker: dict[str, Any], klines: list[list[Any]]) -> dict[str, Any]:
    closes = [decimal_at(row, 4) for row in klines if len(row) > 4]
    last_price = Decimal(str(ticker.get("lastPrice", "0")))
    if not closes or last_price <= 0:
        return empty_signal("Market data is not enough to build a signal.")

    ma_7 = average(closes, 7)
    ma_30 = average(closes, 30)
    ma_99 = average(closes, 99)
    slope_30 = ma_slope(closes, 30)
    rsi = simple_rsi(closes)
    rsi_value = Decimal(str(rsi)) if rsi is not None else None
    atr = simple_atr(klines) or pct(last_price, "0.75")
    vol_ratio = volume_ratio(klines)
    support, resistance = support_resistance(klines)
    prior_support, prior_resistance = prior_support_resistance(klines)
    previous_close = closes[-2] if len(closes) > 1 else last_price
    last_close = closes[-1]
    regime = classify_regime(last_price, ma_7, ma_30, ma_99, slope_30)

    decision = "WAIT"
    action = "WAIT_FOR_CONFIRMATION"
    confidence = Decimal("0.50")
    tags = ["structured_rules", "risk_first"]
    reasons = [
        "No high-probability setup yet. The bot waits until trend, price action, and risk/reward agree.",
    ]
    risk_notes = [
        "This signal uses predefined rules, ATR-based stops, and a minimum risk/reward filter.",
        "Keep order size small and review trade history before raising live-trading limits.",
    ]

    entry_low = last_price - pct(last_price, "0.12")
    entry_high = last_price + pct(last_price, "0.12")
    stop_loss = last_price - (atr * Decimal("1.25"))
    take_profit_1 = last_price + (atr * Decimal("1.5"))
    take_profit_2 = last_price + (atr * Decimal("2.3"))

    strong_volume = bool(vol_ratio and vol_ratio >= Decimal("1.15"))
    bullish_breakout = bool(
        prior_resistance
        and last_close > prior_resistance
        and previous_close <= prior_resistance
        and strong_volume
        and (rsi_value is None or rsi_value <= Decimal("72"))
    )
    bearish_breakdown = bool(
        prior_support
        and last_close < prior_support
        and previous_close >= prior_support
        and strong_volume
        and (rsi_value is None or rsi_value >= Decimal("28"))
    )
    near_bull_pullback = bool(
        regime in {"bull_trend", "bull_bias"}
        and ma_30
        and abs(last_price - ma_30) / last_price <= Decimal("0.012")
        and (rsi_value is None or Decimal("38") <= rsi_value <= Decimal("64"))
    )
    near_bear_pullback = bool(
        regime in {"bear_trend", "bear_bias"}
        and ma_30
        and abs(last_price - ma_30) / last_price <= Decimal("0.012")
        and (rsi_value is None or Decimal("36") <= rsi_value <= Decimal("62"))
    )

    if bullish_breakout:
        decision = "BUY"
        action = "BUY_BREAKOUT_CONFIRMATION"
        confidence = Decimal("0.70")
        tags += ["breakout", "volume_confirmation"]
        entry_low = prior_resistance or last_price
        entry_high = last_price + pct(last_price, "0.10")
        stop_loss = max((prior_resistance or last_price) - (atr * Decimal("1.15")), last_price - pct(last_price, "1.8"))
        take_profit_1 = last_price + (abs(last_price - stop_loss) * Decimal("1.5"))
        take_profit_2 = last_price + (abs(last_price - stop_loss) * Decimal("2.2"))
        reasons = [
            "Price closed above prior resistance with higher-than-average volume.",
            "Breakout is accepted only when RSI is not extremely overbought.",
            "Entry, stop, and targets are defined before any live order is allowed.",
        ]
    elif bearish_breakdown:
        decision = "SELL"
        action = "SELL_BREAKDOWN_CONFIRMATION"
        confidence = Decimal("0.69")
        tags += ["breakdown", "volume_confirmation"]
        entry_low = last_price - pct(last_price, "0.10")
        entry_high = prior_support or last_price
        stop_loss = min((prior_support or last_price) + (atr * Decimal("1.15")), last_price + pct(last_price, "1.8"))
        take_profit_1 = last_price - (abs(stop_loss - last_price) * Decimal("1.5"))
        take_profit_2 = last_price - (abs(stop_loss - last_price) * Decimal("2.2"))
        reasons = [
            "Price closed below prior support with higher-than-average volume.",
            "Breakdown is accepted only when RSI is not already deeply oversold.",
            "The bot treats this as a risk-reduction setup, not a prediction.",
        ]
    elif near_bull_pullback:
        decision = "BUY"
        action = "BUY_TREND_PULLBACK"
        confidence = Decimal("0.67") if regime == "bull_trend" else Decimal("0.63")
        tags += ["trend_following", "pullback"]
        entry_low = min(last_price, ma_30 or last_price)
        entry_high = last_price + pct(last_price, "0.10")
        stop_anchor = min(support or last_price, ma_30 or last_price)
        stop_loss = stop_anchor - (atr * Decimal("1.05"))
        take_profit_1 = max(resistance or last_price, last_price + (abs(last_price - stop_loss) * Decimal("1.35")))
        take_profit_2 = last_price + (abs(last_price - stop_loss) * Decimal("2.0"))
        reasons = [
            "The market is above the long moving average and has pulled back near MA30.",
            "RSI is in a tradable middle zone, so the setup is not chasing an overheated move.",
            "This follows the trend-following style recommended for simpler rule-based systems.",
        ]
    elif near_bear_pullback:
        decision = "SELL"
        action = "SELL_TREND_PULLBACK"
        confidence = Decimal("0.66") if regime == "bear_trend" else Decimal("0.62")
        tags += ["trend_following", "pullback"]
        entry_low = last_price - pct(last_price, "0.10")
        entry_high = max(last_price, ma_30 or last_price)
        stop_anchor = max(resistance or last_price, ma_30 or last_price)
        stop_loss = stop_anchor + (atr * Decimal("1.05"))
        take_profit_1 = min(support or last_price, last_price - (abs(stop_loss - last_price) * Decimal("1.35")))
        take_profit_2 = last_price - (abs(stop_loss - last_price) * Decimal("2.0"))
        reasons = [
            "The market is below the long moving average and has pulled back near MA30.",
            "RSI is not deeply oversold, so defensive selling is not late by rule.",
            "This reduces risk when the trend and price action remain negative.",
        ]
    elif rsi_value is not None and rsi_value >= Decimal("72"):
        action = "WAIT_OVERBOUGHT"
        confidence = Decimal("0.56")
        tags += ["overbought_filter"]
        stop_loss = last_price - (atr * Decimal("1.2"))
        take_profit_1 = resistance if resistance and resistance > last_price else last_price + (atr * Decimal("1.0"))
        take_profit_2 = last_price + (atr * Decimal("1.6"))
        reasons = [
            "RSI is above 72, so buying now would chase strength.",
            "A better setup needs either a pullback or a confirmed breakout with volume.",
        ]
    elif rsi_value is not None and rsi_value <= Decimal("28"):
        action = "WAIT_OVERSOLD_REBOUND"
        confidence = Decimal("0.55")
        tags += ["oversold_filter"]
        stop_loss = last_price - (atr * Decimal("1.1"))
        take_profit_1 = ma_7 or last_price + (atr * Decimal("1.0"))
        take_profit_2 = ma_30 or last_price + (atr * Decimal("1.6"))
        reasons = [
            "RSI is below 28, so the bot waits for a rebound confirmation instead of catching a falling market.",
            "A long setup needs price to reclaim a short moving average or break resistance.",
        ]
    elif regime in {"bull_trend", "bull_bias"}:
        action = "WAIT_FOR_PULLBACK_OR_BREAKOUT"
        confidence = Decimal("0.53")
        tags += ["bull_bias"]
        reasons = [
            "The broader bias is positive, but entry rules are not aligned yet.",
            "The bot waits for a pullback near MA30 or a resistance breakout with volume.",
        ]
    elif regime in {"bear_trend", "bear_bias"}:
        action = "WAIT_OR_REDUCE_RISK"
        confidence = Decimal("0.53")
        tags += ["bear_bias"]
        reasons = [
            "The broader bias is negative, but a new sell setup is not clean enough yet.",
            "The bot waits for a support breakdown or a weak pullback into MA30.",
        ]

    entry_mid = (entry_low + entry_high) / Decimal("2")
    rr = risk_reward(entry_mid, stop_loss, take_profit_1)
    if decision in {"BUY", "SELL"} and (rr is None or rr < MIN_RISK_REWARD):
        reasons.append(
            f"Signal downgraded to WAIT because risk/reward {rr or 'N/A'} is below {MIN_RISK_REWARD}:1."
        )
        decision = "WAIT"
        action = "WAIT_RISK_REWARD_TOO_LOW"
        confidence = min(confidence, Decimal("0.58"))
        tags += ["risk_reward_block"]

    return {
        "action": action,
        "decision": decision,
        "confidence": float(confidence),
        "summary": signal_summary(decision, action, regime, rr),
        "reasons": reasons,
        "riskNotes": risk_notes,
        "strategyTags": tags,
        "tradePlan": {
            "side": decision,
            "currentPrice": to_float(last_price),
            "entryLow": to_float(entry_low),
            "entryHigh": to_float(entry_high),
            "stopLoss": to_float(stop_loss),
            "takeProfit1": to_float(take_profit_1),
            "takeProfit2": to_float(take_profit_2),
            "riskRewardToTp1": float(rr) if rr is not None else None,
            "support": to_float(support),
            "resistance": to_float(resistance),
            "priorSupport": to_float(prior_support),
            "priorResistance": to_float(prior_resistance),
        },
        "indicators": {
            "lastPrice": float(last_price),
            "ma7": float(ma_7) if ma_7 else None,
            "ma30": float(ma_30) if ma_30 else None,
            "ma99": float(ma_99) if ma_99 else None,
            "ma30Slope": to_float(slope_30),
            "rsi14": round(rsi, 2) if rsi is not None else None,
            "atr14": to_float(atr),
            "volumeRatio20": float(vol_ratio.quantize(Decimal("0.01"))) if vol_ratio else None,
            "marketRegime": regime,
        },
        "disclaimer": (
            "Technical signal only, not financial advice. The bot should be tested with dry-run/backtesting "
            "before increasing live trading limits."
        ),
    }


def signal_summary(decision: str, action: str, regime: str, rr: Decimal | None) -> str:
    rr_text = f" Risk/reward to TP1 is about {rr}:1." if rr is not None else ""
    if decision == "BUY":
        return f"BUY setup: {action.replace('_', ' ').lower()} in {regime.replace('_', ' ')}.{rr_text}"
    if decision == "SELL":
        return f"SELL setup: {action.replace('_', ' ').lower()} in {regime.replace('_', ' ')}.{rr_text}"
    return f"WAIT: {action.replace('_', ' ').lower()} in {regime.replace('_', ' ')}.{rr_text}"


def empty_signal(reason: str) -> dict[str, Any]:
    return {
        "action": "WAIT",
        "decision": "WAIT",
        "confidence": 0.0,
        "summary": reason,
        "reasons": [reason],
        "riskNotes": ["No order should be placed without enough market data."],
        "strategyTags": ["data_guard"],
        "tradePlan": {
            "side": "WAIT",
            "currentPrice": None,
            "entryLow": None,
            "entryHigh": None,
            "stopLoss": None,
            "takeProfit1": None,
            "takeProfit2": None,
            "riskRewardToTp1": None,
            "support": None,
            "resistance": None,
        },
        "indicators": {
            "lastPrice": None,
            "ma7": None,
            "ma30": None,
            "ma99": None,
            "rsi14": None,
            "atr14": None,
            "volumeRatio20": None,
            "marketRegime": "unknown",
        },
        "disclaimer": "Technical signal only, not financial advice.",
    }
