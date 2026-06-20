# BTC Binance Monitor

เว็บแอปสำหรับดูราคา BTCUSDT, อ่านพอร์ต Spot จาก Binance, คำนวณ PnL แบบประมาณการจากประวัติเทรด BTCUSDT และเตรียมคำสั่งซื้อขายแบบมีรางกันความเสี่ยง

ตอนนี้หน้า dashboard มีกราฟแท่งเทียน BTCUSDT พร้อม timeframe `1m`, `5m`, `15m`, `1h`, `4h`, และ `1d` พร้อมเส้นราคา Close, MA(7), MA(30), MA(99), volume, และ zoom ด้วยปุ่มหรือ mouse wheel

AI Signal จะแสดง bias ว่าควร `BUY`, `SELL`, หรือ `WAIT` พร้อมโซนเข้า, stop loss, take profit, แนวรับ/แนวต้าน และเหตุผลเชิงเทคนิค

## สิ่งที่ต้องทำก่อน

1. Revoke API key ที่เคยส่งในแชต แล้วสร้าง Binance API key ใหม่
2. แนะนำให้เปิดแค่ `Enable Reading` ก่อน
3. ถ้าจะใช้คำสั่งเงินจริง ให้จำกัด IP ใน Binance API Management และกำหนดวงเงินเล็กมาก

## ติดตั้งและรัน

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

เปิดเว็บที่:

```text
http://127.0.0.1:8000
```

ราคาตลาดใช้ endpoint public ของ Binance (`https://data-api.binance.vision`) โดยค่าเริ่มต้น ส่วนพอร์ตและคำสั่งซื้อขายใช้ signed endpoint ของบัญชีจริง ถ้าเครื่องต่อ Binance live endpoint ไม่ได้ ให้ลองตั้ง `BINANCE_BASE_URL` ใน `.env` เช่น `https://api1.binance.com` หรือเริ่มจาก `BINANCE_ENV=testnet` เพื่อทดสอบก่อน

อย่าใส่ API key ใน `.env.example` ให้ใส่ใน `.env` เท่านั้น

## การเปิดส่งออเดอร์เงินจริง

ค่าเริ่มต้นคือไม่ส่งเงินจริง แม้กดปุ่มในหน้าเว็บ ระบบจะทำ dry-run เท่านั้น

ถ้าต้องการเปิด manual order จริง ต้องตั้งค่าใน `.env`:

```text
ENABLE_LIVE_TRADING=true
```

ถ้าต้องการให้ manual กดได้เฉพาะ dry-run แต่ให้ AI ส่ง order จริงได้ ให้ตั้งแบบนี้:

```text
ENABLE_LIVE_TRADING=false
ALLOW_AI_LIVE_ORDERS=true
```

และทุกคำสั่งจริงต้องพิมพ์ข้อความยืนยัน:

```text
PLACE REAL BTC ORDER
```

ถ้าส่งคำสั่งจริงผ่านระบบ AI ต้องเปิด:

```text
ALLOW_AI_LIVE_ORDERS=true
```

ต้องแน่ใจว่า Binance API key เปิดสิทธิ์ Spot Trading ไว้ และควรจำกัด IP รวมถึงตั้ง `MAX_ORDER_USDT` และ `MAX_BTC_QTY` ให้ต่ำก่อนทดสอบจริง

งบและขนาด order ของ AI ตั้งใน `.env`:

```text
AI_ORDER_USDT=10
AI_ORDER_BTC_QTY=0.0001
AI_DAILY_BUDGET_USDT=25
```

ระบบจะบันทึก order history ที่ส่งผ่านแอปไว้ใน `data/order_history.json` และแสดงในหน้า dashboard พร้อมสรุปจำนวน order, dry-run, net BTC และ PnL โดยประมาณจาก order history ของแอป

ส่วน AI auto order ถูกปิดด้วยค่า:

```text
ALLOW_AI_LIVE_ORDERS=false
```

แนะนำให้เปิดเฉพาะหลังจากทดสอบบน Binance Spot Testnet และเข้าใจความเสี่ยงทั้งหมดแล้ว

## หมายเหตุ PnL

PnL เป็นค่าประมาณจากประวัติ `BTCUSDT` trades ที่ Binance API ส่งกลับล่าสุด อาจไม่ตรงทั้งหมดถ้ามีการฝาก/ถอน/โอน BTC, ซื้อขายผ่านคู่เงินอื่น, fee เป็นเหรียญอื่น หรือมีประวัติเกินจำนวนที่ API ส่งกลับในครั้งเดียว
