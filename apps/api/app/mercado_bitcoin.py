import asyncio
import random
import time
from decimal import Decimal
from typing import Any

import httpx


class MercadoBitcoinError(RuntimeError):
    pass


class MercadoBitcoinAmbiguousOrderError(MercadoBitcoinError):
    """The order result is unknown and must be reconciled before proceeding."""


class MercadoBitcoinAdapter:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    async def _with_client(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        owns_client = self._client is None
        try:
            return await client.request(method, url, **kwargs)
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _raise_for_api_error(response: httpx.Response) -> None:
        if not response.is_error:
            return
        try:
            body = response.json()
            message = body.get("message") or body.get("code") or "Mercado Bitcoin request failed"
        except ValueError:
            message = "Mercado Bitcoin request failed"
        raise MercadoBitcoinError(f"Mercado Bitcoin error {response.status_code}: {message}")

    async def authenticate(self) -> str:
        if not self.client_id or not self.client_secret:
            raise MercadoBitcoinError("Credenciais do Mercado Bitcoin são necessárias para esta operação")
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token
        response = await self._with_client(
            "POST",
            f"{self.base_url}/oauth2/token",
            data={"grant_type": "client_credentials", "scope": "global", "client_id": self.client_id, "client_secret": self.client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code == 401:
            raise MercadoBitcoinError(
                "Client ID ou Client Secret inválido. Gere uma nova chave no Mercado Bitcoin e copie o segredo completo."
            )
        self._raise_for_api_error(response)
        payload = response.json()
        self._access_token = payload["access_token"]
        self._token_expires_at = time.monotonic() + max(0, int(payload.get("expires_in", 3600)) - 30)
        return self._access_token

    async def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None, authenticated: bool = True) -> Any:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {await self.authenticate()}"
        response: httpx.Response | None = None
        retryable = method.upper() == "GET"
        for attempt in range(3):
            response = await self._with_client(
                method, f"{self.base_url}{path}", params=params, json=json, headers=headers
            )
            if (
                retryable
                and response.status_code in {429, 500, 502, 503, 504}
                and attempt < 2
            ):
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(float(retry_after), 2.0) if retry_after else 0.2 * (2**attempt)
                except ValueError:
                    delay = 0.2 * (2**attempt)
                await asyncio.sleep(delay + random.uniform(0, 0.1))
                continue
            break
        assert response is not None
        if path == "/accounts" and response.status_code == 403:
            raise MercadoBitcoinError(
                "A chave foi autenticada, mas não tem permissão para consultar a conta. Revise as permissões da API no Mercado Bitcoin."
            )
        if path == "/accounts" and response.status_code >= 500:
            raise MercadoBitcoinError(
                "As credenciais foram autenticadas, mas o Mercado Bitcoin não conseguiu listar a conta. Aguarde alguns minutos e tente novamente; se persistir, confirme a ativação da chave com o suporte do MB."
            )
        self._raise_for_api_error(response)
        return response.json()

    async def validate_account(self) -> dict[str, Any]:
        accounts = await self._request("GET", "/accounts")
        account = next((item for item in accounts if item.get("currency") == "BRL"), accounts[0] if accounts else None)
        if not account:
            raise MercadoBitcoinError("Nenhuma conta de negociação foi encontrada")
        balances = await self.get_balance(account["id"])
        return {"account_id": account["id"], "account_name": account.get("name", "Mercado Bitcoin"), "account_type": account.get("type"), "currency": account.get("currency"), "brl_available": balances.get("BRL", Decimal("0"))}

    async def get_balance(self, account_id: str) -> dict[str, Decimal]:
        balances = await self._request("GET", f"/accounts/{account_id}/balances")
        return {item["symbol"]: Decimal(item["available"]) for item in balances}

    async def get_tickers(self, symbols: list[str]) -> list[dict[str, Any]]:
        pairs = [symbol.replace("/", "-").upper() for symbol in symbols]
        rows = await self._request("GET", "/tickers", params={"symbols": ",".join(pairs)}, authenticated=False)
        by_pair = {row["pair"]: row for row in rows}
        missing = [pair for pair in pairs if pair not in by_pair]
        if missing:
            raise MercadoBitcoinError(f"Mercado indisponível: {', '.join(missing)}")
        return [{"symbol": pair, "bid": Decimal(by_pair[pair]["buy"]), "ask": Decimal(by_pair[pair]["sell"]), "last": Decimal(by_pair[pair]["last"]), "volume": Decimal(by_pair[pair]["vol"])} for pair in pairs]

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        return (await self.get_tickers([symbol]))[0]

    async def get_symbol_rules(self, symbols: list[str]) -> list[dict[str, Any]]:
        pairs = [symbol.replace("/", "-").upper() for symbol in symbols]
        payload = await self._request(
            "GET", "/symbols", params={"symbols": ",".join(pairs)}, authenticated=False
        )
        returned = payload.get("symbol", []) if isinstance(payload, dict) else []
        by_pair: dict[str, dict[str, Any]] = {}
        fields = ("exchange-listed", "exchange-traded", "min-price", "max-price", "min-volume", "max-volume", "min-cost", "max-cost", "round-lot")
        for index, pair in enumerate(returned):
            row: dict[str, Any] = {"symbol": pair}
            for field in fields:
                values = payload.get(field, [])
                if index < len(values):
                    row[field] = values[index]
            by_pair[pair] = row
        missing = [pair for pair in pairs if pair not in by_pair]
        if missing:
            raise MercadoBitcoinError(f"Regras indisponíveis: {', '.join(missing)}")
        return [by_pair[pair] for pair in pairs]

    async def get_trading_fees(self, account_id: str, symbol: str) -> dict[str, Decimal]:
        pair = symbol.replace("/", "-").upper()
        payload = await self._request("GET", f"/accounts/{account_id}/{pair}/fees")
        return {
            "maker_fee": Decimal(str(payload["maker_fee"])),
            "taker_fee": Decimal(str(payload["taker_fee"])),
        }

    async def get_candles(self, symbol: str, resolution: str = "15m", countback: int = 40) -> list[dict[str, Any]]:
        pair = symbol.replace("/", "-").upper()
        payload = await self._request(
            "GET",
            "/candles",
            params={"symbol": pair, "resolution": resolution, "to": int(time.time()), "countback": countback},
            authenticated=False,
        )
        required = ("o", "h", "l", "c", "v", "t")
        if not all(isinstance(payload.get(key), list) for key in required):
            raise MercadoBitcoinError(f"Candles inválidos para {pair}")
        size = min(len(payload[key]) for key in required)
        if size < 20:
            raise MercadoBitcoinError(f"Histórico insuficiente para {pair}")
        return [
            {
                "open": Decimal(str(payload["o"][index])),
                "high": Decimal(str(payload["h"][index])),
                "low": Decimal(str(payload["l"][index])),
                "close": Decimal(str(payload["c"][index])),
                "volume": Decimal(str(payload["v"][index])),
                "timestamp": int(payload["t"][index]),
            }
            for index in range(size)
        ]

    async def get_order_book(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        pair = symbol.replace("/", "-").upper()
        return await self._request("GET", f"/{pair}/orderbook", params={"limit": limit}, authenticated=False)

    async def get_open_orders(self, account_id: str, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"status": "created,working", "size": "100"}
        if symbol:
            params["symbol"] = symbol.replace("/", "-").upper()
        result = await self._request("GET", f"/accounts/{account_id}/orders", params=params)
        return result.get("items", result if isinstance(result, list) else [])

    async def get_order_by_external_id(self, account_id: str, symbol: str, external_id: str) -> dict[str, Any] | None:
        pair = symbol.replace("/", "-").upper()
        result = await self._request("GET", f"/accounts/{account_id}/orders", params={"symbol": pair, "size": "100"})
        orders = result.get("items", result if isinstance(result, list) else [])
        return next((item for item in orders if item.get("externalId") == external_id or item.get("external_id") == external_id), None)

    async def create_limit_order(self, account_id: str, external_id: str, symbol: str, side: str, quantity: Decimal, price: Decimal) -> dict[str, Any]:
        pair = symbol.replace("/", "-").upper()
        payload = {"async": False, "externalId": external_id, "limitPrice": float(price), "qty": format(quantity, "f"), "side": side.lower(), "type": "limit"}
        try:
            return await self._request("POST", f"/accounts/{account_id}/{pair}/orders", json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            try:
                existing = await self.get_order_by_external_id(account_id, symbol, external_id)
            except Exception as reconciliation_error:
                raise MercadoBitcoinAmbiguousOrderError("Resultado da ordem é incerto; pause e reconcilie antes de continuar") from reconciliation_error
            if existing is None:
                raise MercadoBitcoinAmbiguousOrderError("Ordem não localizada após falha de transporte; operação pausada") from exc
            return existing

    async def cancel_order(self, account_id: str, symbol: str, order_id: str) -> dict[str, Any]:
        pair = symbol.replace("/", "-").upper()
        return await self._request("DELETE", f"/accounts/{account_id}/{pair}/orders/{order_id}", params={"async": "false"})
