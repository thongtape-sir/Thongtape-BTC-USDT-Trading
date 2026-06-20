from __future__ import annotations

from decimal import Decimal
from typing import Any


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
        high = Decimal(str(row[2]))
        low = Decimal(str(row[3]))
        close = Decimal(str(row[4]))
        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        ranges.append(true_range)
        previous_close = close

    return sum(ranges[-period:]) / Decimal(period)


def build_signal(ticker: dict[str, Any], klines: list[list[Any]]) -> dict[str, Any]:
    closes = [Decimal(str(row[4])) for row in klines if len(row) > 4]
    last_price = Decimal(str(ticker.get("lastPrice", "0")))
    ma_7 = average(closes, 7)
    ma_30 = average(closes, 30)
    ma_99 = average(closes, 99)
    rsi = simple_rsi(closes)
    atr = simple_atr(klines)

    recent_lows = [Decimal(str(row[3])) for row in klines[-20:]]
    recent_highs = [Decimal(str(row[2])) for row in klines[-20:]]
    support = min(recent_lows) if recent_lows else None
    resistance = max(recent_highs) if recent_highs else None

    trend_bull = bool(ma_7 and ma_30 and ma_99 and last_price > ma_7 > ma_30 > ma_99)
    trend_bear = bool(ma_7 and ma_30 and ma_99 and last_price < ma_7 < ma_30 < ma_99)
    above_long_trend = bool(ma_99 and last_price >= ma_99)
    rsi_value = Decimal(str(rsi)) if rsi is not None else None

    decision = "WAIT"
    action = "WAIT"
    confidence = 0.48
    summary = "ยังไม่ใช่จังหวะที่ได้เปรียบชัดเจน รอราคาเลือกทางก่อน"
    reasons: list[str] = ["สัญญาณระยะสั้นและเส้นค่าเฉลี่ยยังไม่สอดคล้องกันพอ"]
    risk_notes: list[str] = ["ใช้ขนาดออเดอร์เล็ก และกำหนดจุดตัดขาดทุนก่อนส่งคำสั่งจริง"]

    entry_low = last_price - pct(last_price, "0.15")
    entry_high = last_price + pct(last_price, "0.15")
    stop_loss = support - (atr or pct(last_price, "0.6")) if support else last_price - pct(last_price, "0.8")
    take_profit_1 = resistance if resistance and resistance > last_price else last_price + pct(last_price, "0.8")
    take_profit_2 = last_price + pct(last_price, "1.4")

    if trend_bull and rsi_value is not None and Decimal("42") <= rsi_value <= Decimal("68"):
        decision = "BUY"
        action = "BUY_ON_PULLBACK"
        confidence = 0.68
        summary = "bias ฝั่งซื้อดีกว่า แต่ควรรอใกล้โซนย่อ ไม่ควรไล่ราคาทันที"
        entry_low = min(last_price, ma_7 or last_price)
        entry_high = last_price + pct(last_price, "0.12")
        stop_loss = min(support or last_price, ma_30 or last_price) - (atr or pct(last_price, "0.6"))
        take_profit_1 = resistance if resistance and resistance > last_price else last_price + pct(last_price, "1.0")
        take_profit_2 = take_profit_1 + (take_profit_1 - stop_loss) * Decimal("0.6")
        reasons = [
            "ราคาอยู่เหนือ MA(7), MA(30), MA(99) แสดงว่าแนวโน้มหลักยังหนุนฝั่งซื้อ",
            "MA(7) อยู่เหนือ MA(30) และ MA(99) สะท้อน momentum ระยะสั้นยังดีกว่าระยะกลาง",
            "RSI ยังไม่เกิน 70 จึงยังไม่ใช่ภาวะ overbought รุนแรง",
        ]
    elif trend_bear and rsi_value is not None and rsi_value >= Decimal("32"):
        decision = "SELL"
        action = "SELL_OR_WAIT"
        confidence = 0.66
        summary = "bias ฝั่งขาย/ลดพอร์ตดีกว่า ถ้ายังถือเหรียญอยู่ควรรอเด้งใกล้แนวต้านเพื่อขายบางส่วน"
        entry_low = last_price - pct(last_price, "0.12")
        entry_high = max(last_price, ma_7 or last_price)
        stop_loss = max(resistance or last_price, ma_30 or last_price) + (atr or pct(last_price, "0.6"))
        take_profit_1 = support if support and support < last_price else last_price - pct(last_price, "0.9")
        take_profit_2 = take_profit_1 - (stop_loss - take_profit_1) * Decimal("0.45")
        reasons = [
            "ราคาอยู่ใต้ MA(7), MA(30), MA(99) แสดงว่าแรงขายยังคุมแนวโน้ม",
            "MA(7) อยู่ใต้ MA(30) และ MA(99) สะท้อน momentum ระยะสั้นยังอ่อน",
            "RSI ยังไม่ต่ำมากจนเป็น oversold ชัดเจน จึงยังไม่ควรรีบสวนซื้อ",
        ]
    elif rsi_value is not None and rsi_value >= Decimal("70"):
        decision = "WAIT"
        action = "TAKE_PROFIT_OR_WAIT"
        confidence = 0.58
        summary = "ราคาเริ่มร้อนแรง ควรรอพักฐานก่อนซื้อเพิ่ม หรือทยอยล็อกกำไรถ้ามีกำไรอยู่"
        stop_loss = last_price - pct(last_price, "0.9")
        take_profit_1 = resistance if resistance and resistance > last_price else last_price + pct(last_price, "0.7")
        take_profit_2 = last_price + pct(last_price, "1.2")
        reasons = [
            "RSI สูงกว่า 70 ซึ่งมักหมายถึงตลาดเริ่มร้อนแรง",
            "การไล่ซื้อทันทีมี risk/reward ไม่คุ้มเท่าการรอราคา pullback",
        ]
    elif rsi_value is not None and rsi_value <= Decimal("30"):
        decision = "WAIT"
        action = "WATCH_REBOUND"
        confidence = 0.56
        summary = "ราคาอ่อนมาก อาจมีเด้งสั้น แต่ควรรอแท่งกลับตัวยืนยันก่อนซื้อ"
        entry_low = last_price - pct(last_price, "0.2")
        entry_high = last_price + pct(last_price, "0.2")
        stop_loss = last_price - pct(last_price, "0.8")
        take_profit_1 = ma_7 or last_price + pct(last_price, "0.8")
        take_profit_2 = ma_30 or last_price + pct(last_price, "1.3")
        reasons = [
            "RSI ต่ำกว่า 30 แสดงว่าแรงขายกดราคามากแล้ว",
            "อย่างไรก็ตามการซื้อสวนต้องรอ confirmation เพราะแนวโน้มอาจยังลงต่อ",
        ]
    elif above_long_trend:
        decision = "WAIT"
        action = "WAIT_FOR_BREAKOUT"
        confidence = 0.52
        summary = "ภาพใหญ่ยังไม่เสีย แต่สัญญาณซื้อยังไม่ชัด รอทะลุแนวต้านหรือย่อใกล้ MA ก่อน"
        reasons = [
            "ราคายังอยู่เหนือ MA(99) จึงยังไม่ใช่ภาพลบเต็มตัว",
            "MA ระยะสั้นยังไม่เรียงตัวชัดพอสำหรับสัญญาณซื้อ",
        ]
    else:
        decision = "SELL"
        action = "DEFENSIVE_SELL"
        confidence = 0.54
        summary = "ภาพรวมเอนลบ ถ้าถือเหรียญอยู่ควรลดความเสี่ยงหรือรอให้ราคากลับเหนือ MA ก่อน"
        reasons = [
            "ราคายังต่ำกว่า MA(99) หรือ momentum ยังไม่ฟื้นชัด",
            "โอกาสซื้อที่ดีควรรอให้ราคา reclaim เส้นค่าเฉลี่ยสำคัญก่อน",
        ]

    if decision == "SELL" and take_profit_1 >= ((entry_low + entry_high) / Decimal("2")):
        take_profit_1 = support if support and support < last_price else last_price - pct(last_price, "0.8")
        take_profit_2 = take_profit_1 - pct(last_price, "0.7")

    if stop_loss >= entry_high and decision != "SELL":
        stop_loss = entry_low - pct(last_price, "0.7")
    if decision == "SELL" and stop_loss <= entry_high:
        stop_loss = entry_high + pct(last_price, "0.7")

    midpoint = (entry_low + entry_high) / Decimal("2")
    risk = abs(midpoint - stop_loss)
    reward = abs(take_profit_1 - midpoint)
    risk_reward = float((reward / risk).quantize(Decimal("0.01"))) if risk > 0 else None

    return {
        "action": action,
        "decision": decision,
        "confidence": confidence,
        "summary": summary,
        "reasons": reasons,
        "riskNotes": risk_notes,
        "tradePlan": {
            "side": decision,
            "currentPrice": to_float(last_price),
            "entryLow": to_float(entry_low),
            "entryHigh": to_float(entry_high),
            "stopLoss": to_float(stop_loss),
            "takeProfit1": to_float(take_profit_1),
            "takeProfit2": to_float(take_profit_2),
            "riskRewardToTp1": risk_reward,
            "support": to_float(support),
            "resistance": to_float(resistance),
        },
        "indicators": {
            "lastPrice": float(last_price),
            "ma7": float(ma_7) if ma_7 else None,
            "ma30": float(ma_30) if ma_30 else None,
            "ma99": float(ma_99) if ma_99 else None,
            "rsi14": round(rsi, 2) if rsi is not None else None,
            "atr14": to_float(atr),
        },
        "disclaimer": "สัญญาณนี้เป็นการประเมินเชิงเทคนิค ไม่ใช่คำแนะนำทางการเงิน และระบบจะไม่ส่งคำสั่งแทนคุณโดยอัตโนมัติ",
    }
