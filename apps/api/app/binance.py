import hashlib
import hmac
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any
from urllib.parse import quote, urlencode

import httpx


class BinanceError(RuntimeError):
    pass


class BinanceAmbiguousOrderError(BinanceError):
    """The submit result is unknown; the caller must stop and reconcile."""


def to_binance_symbol(symbol: str) -> str:
    return symbol.replace("/", "").upper()


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def signed_query(params: dict[str, Any], secret: str) -> str:
    normalized = sorted((key, decimal_text(value) if isinstance(value, Decimal) else str(value)) for key, value in params.items())
    payload = urlencode(normalized, quote_via=quote, safe="-_.~")
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}&signature={signature}"


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


class BinanceSpotAdapter:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str,
        recv_window_ms: int = 5000,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key or not api_secret:
            raise ValueError("Binance API key and secret are required")
        if recv_window_ms <= 0 or recv_window_ms > 60000:
            raise ValueError("recvWindow must be between 1 and 60000 ms")
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.recv_window_ms = recv_window_ms
        self._client = client

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        signed: bool = False,
    ) -> Any:
        values = dict(params or {})
        headers: dict[str, str] = {}
        if signed:
            values.update(timestamp=int(time.time() * 1000), recvWindow=self.recv_window_ms)
            encoded = signed_query(values, self.api_secret)
            headers["X-MBX-APIKEY"] = self.api_key
        else:
            encoded = urlencode(values, quote_via=quote, safe="-_.~")
        client = self._client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        owns_client = self._client is None
        try:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                content=encoded if method in {"POST", "PUT", "DELETE"} else None,
                params=None if method in {"POST", "PUT", "DELETE"} else encoded,
                headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
            )
            if response.is_error:
                try:
                    detail = response.json()
                    message = detail.get("msg", "Binance request failed")
                    code = detail.get("code", response.status_code)
                except ValueError:
                    message, code = "Binance request failed", response.status_code
                raise BinanceError(f"Binance error {code}: {message}")
            return response.json()
        finally:
            if owns_client:
                await client.aclose()

    async def validate_account(self) -> dict[str, Any]:
        account = await self._request("GET", "/api/v3/account", signed=True)
        if not account.get("canTrade", False):
            raise BinanceError("The API key does not have Spot trading permission")
        return {
            "can_trade": True,
            "account_type": account.get("accountType"),
            "permissions": account.get("permissions", []),
        }

    async def get_balance(self) -> dict[str, Decimal]:
        account = await self._request("GET", "/api/v3/account", signed=True)
        return {item["asset"]: Decimal(item["free"]) for item in account.get("balances", [])}

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        ticker = await self._request("GET", "/api/v3/ticker/bookTicker", {"symbol": to_binance_symbol(symbol)})
        return {
            "symbol": symbol.upper(),
            "bid": Decimal(ticker["bidPrice"]),
            "ask": Decimal(ticker["askPrice"]),
        }

    async def get_candles(self, symbol: str, interval: str = "1m", limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._request("GET", "/api/v3/klines", {"symbol": to_binance_symbol(symbol), "interval": interval, "limit": limit})
        return [
            {"opened_at": row[0], "open": Decimal(row[1]), "high": Decimal(row[2]), "low": Decimal(row[3]), "close": Decimal(row[4]), "volume": Decimal(row[5])}
            for row in rows
        ]

    async def get_order_book(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        return await self._request("GET", "/api/v3/depth", {"symbol": to_binance_symbol(symbol), "limit": limit})

    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": to_binance_symbol(symbol)} if symbol else {}
        return await self._request("GET", "/api/v3/openOrders", params, signed=True)

    async def get_order(self, symbol: str, client_order_id: str) -> dict[str, Any] | None:
        try:
            return await self._request("GET", "/api/v3/order", {"symbol": to_binance_symbol(symbol), "origClientOrderId": client_order_id}, signed=True)
        except BinanceError as exc:
            if "-2013" in str(exc):
                return None
            raise

    async def cancel_order(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        return await self._request("DELETE", "/api/v3/order", {"symbol": to_binance_symbol(symbol), "origClientOrderId": client_order_id}, signed=True)

    async def get_exchange_info(self, symbol: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v3/exchangeInfo", {"symbol": to_binance_symbol(symbol)})

    async def rules(self, symbol: str) -> dict[str, Decimal]:
        info = await self.get_exchange_info(symbol)
        if not info.get("symbols") or info["symbols"][0].get("status") != "TRADING":
            raise BinanceError(f"{symbol} is not available for Spot trading")
        filters = {item["filterType"]: item for item in info["symbols"][0]["filters"]}
        lot = filters["LOT_SIZE"]
        notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {}))
        return {
            "step_size": Decimal(lot["stepSize"]),
            "min_quantity": Decimal(lot["minQty"]),
            "max_quantity": Decimal(lot["maxQty"]),
            "min_notional": Decimal(notional.get("minNotional", "0")),
        }

    async def test_order(self, client_order_id: str, symbol: str, side: str, quantity: Decimal, price: Decimal) -> None:
        await self._request("POST", "/api/v3/order/test", self._limit_params(client_order_id, symbol, side, quantity, price), signed=True)

    async def create_order(self, client_order_id: str, symbol: str, side: str, quantity: Decimal, price: Decimal) -> dict[str, Any]:
        params = self._limit_params(client_order_id, symbol, side, quantity, price)
        try:
            return await self._request("POST", "/api/v3/order", params, signed=True)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            try:
                existing = await self.get_order(symbol, client_order_id)
            except Exception as reconciliation_error:
                raise BinanceAmbiguousOrderError("Order submission is ambiguous; trading must pause for reconciliation") from reconciliation_error
            if existing is None:
                raise BinanceAmbiguousOrderError("Order was not found after a transport failure; trading must pause") from exc
            return existing

    @staticmethod
    def _limit_params(client_order_id: str, symbol: str, side: str, quantity: Decimal, price: Decimal) -> dict[str, Any]:
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        return {
            "symbol": to_binance_symbol(symbol),
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": decimal_text(quantity),
            "price": decimal_text(price),
            "newClientOrderId": client_order_id,
            "newOrderRespType": "FULL",
        }
