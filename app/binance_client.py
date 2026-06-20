from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx


class BinanceError(RuntimeError):
    pass


class BinanceClient:
    def __init__(
        self,
        api_key: str | None,
        secret_key: str | None,
        env: str = "live",
        provider: str = "binance_th",
        base_url: str | None = None,
        public_base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.secret_key = secret_key or ""
        self.env = env
        self.provider = (provider or "binance_th").strip().lower()
        self.is_binance_th = self.provider in {"binance_th", "binance.th", "th"}
        is_testnet = env == "testnet"

        if self.is_binance_th:
            default_url = "https://api.binance.th"
            default_public_url = "https://api.binance.th"
        else:
            default_url = "https://testnet.binance.vision" if is_testnet else "https://api.binance.com"
            default_public_url = "https://testnet.binance.vision" if is_testnet else "https://data-api.binance.vision"

        self.base_url = (base_url or default_url).rstrip("/")
        self.public_base_url = (public_base_url or default_public_url).rstrip("/")
        self.endpoints = self._endpoint_map()

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.secret_key)

    async def public_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            async with httpx.AsyncClient(base_url=self.public_base_url, timeout=15) as client:
                response = await client.get(path, params=params or {})
        except httpx.RequestError as exc:
            raise BinanceError(f"Cannot connect to Binance market data at {self.public_base_url}: {exc}") from exc
        return self._read_response(response)

    async def signed_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if not self.has_credentials:
            raise BinanceError("Missing Binance API credentials.")

        signed_params = dict(params or {})
        signed_params.setdefault("recvWindow", 10000)
        signed_params["timestamp"] = await self._timestamp_ms()
        query = urlencode(signed_params, doseq=True)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params["signature"] = signature

        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=20, headers=headers) as client:
                response = await client.request(method.upper(), path, params=signed_params)
        except httpx.RequestError as exc:
            raise BinanceError(f"Cannot connect to Binance at {self.base_url}: {exc}") from exc
        return self._read_response(response)

    async def _timestamp_ms(self) -> int:
        local_time = int(time.time() * 1000)
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
                response = await client.get(self.endpoints["time"])
            payload = self._read_response(response)
            return int(payload["serverTime"])
        except (BinanceError, httpx.RequestError, KeyError, TypeError, ValueError):
            return local_time

    def _read_response(self, response: httpx.Response) -> Any:
        try:
            payload = response.json()
        except ValueError as exc:
            raise BinanceError(f"Binance returned non-JSON response: {response.text[:200]}") from exc

        if response.status_code >= 400:
            message = payload.get("msg") if isinstance(payload, dict) else str(payload)
            code = payload.get("code") if isinstance(payload, dict) else response.status_code
            raise BinanceError(f"Binance error {code}: {message}")

        if self.is_binance_th and isinstance(payload, dict) and "code" in payload and "data" in payload:
            if int(payload.get("code", 0)) != 0:
                raise BinanceError(f"Binance TH error {payload.get('code')}: {payload.get('msg')}")
            return payload.get("data")

        return payload

    def _endpoint_map(self) -> dict[str, str | None]:
        if self.is_binance_th:
            return {
                "time": "/api/v1/time",
                "ticker_24hr": "/api/v1/ticker/24hr",
                "ticker_price": "/api/v1/ticker/price",
                "klines": "/api/v1/klines",
                "account": "/api/v1/accountV2",
                "my_trades": "/api/v1/userTrades",
                "order": "/api/v1/order",
                "test_order": None,
            }
        return {
            "time": "/api/v3/time",
            "ticker_24hr": "/api/v3/ticker/24hr",
            "ticker_price": "/api/v3/ticker/price",
            "klines": "/api/v3/klines",
            "account": "/api/v3/account",
            "my_trades": "/api/v3/myTrades",
            "order": "/api/v3/order",
            "test_order": "/api/v3/order/test",
        }


def d(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def money(value: Decimal, places: int = 2) -> float:
    quant = Decimal("1") if places == 0 else Decimal("1").scaleb(-places)
    return float(value.quantize(quant))
