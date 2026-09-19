from decimal import Decimal as D

import httpx
import pytest

from app.mercado_bitcoin import MercadoBitcoinAdapter, MercadoBitcoinError


@pytest.mark.asyncio
async def test_authentication_and_read_only_account_validation():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/oauth2/token"):
            assert b"grant_type=client_credentials" in request.content
            assert b"client_secret=secret-value" in request.content
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer token"
        if request.url.path.endswith("/accounts"):
            return httpx.Response(200, json=[{"id": "account-1", "name": "Principal", "currency": "BRL", "type": "live"}])
        if request.url.path.endswith("/balances"):
            return httpx.Response(200, json=[{"symbol": "BRL", "available": "100.00", "on_hold": "0", "total": "100.00"}])
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await MercadoBitcoinAdapter("client-value", "secret-value", "https://example.test/api/v4", client).validate_account()
    assert result["account_id"] == "account-1"
    assert result["brl_available"] == D("100.00")
    assert calls == [("POST", "/api/v4/oauth2/token"), ("GET", "/api/v4/accounts"), ("GET", "/api/v4/accounts/account-1/balances")]


@pytest.mark.asyncio
async def test_accounts_retries_transient_provider_error(monkeypatch):
    account_attempts = 0

    async def no_wait(_delay):
        return None

    monkeypatch.setattr("app.mercado_bitcoin.asyncio.sleep", no_wait)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal account_attempts
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.path.endswith("/accounts"):
            account_attempts += 1
            if account_attempts < 3:
                return httpx.Response(500, json={"message": "An unexpected error has occurred"})
            return httpx.Response(200, json=[{"id": "account-1", "currency": "BRL"}])
        return httpx.Response(200, json=[{"symbol": "BRL", "available": "100.00"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await MercadoBitcoinAdapter(
            "client-value", "secret-value", "https://example.test/api/v4", client
        ).validate_account()

    assert account_attempts == 3
    assert result["account_id"] == "account-1"


@pytest.mark.asyncio
async def test_accounts_provider_error_explains_that_credentials_were_authenticated(monkeypatch):
    async def no_wait(_delay):
        return None

    monkeypatch.setattr("app.mercado_bitcoin.asyncio.sleep", no_wait)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(500, json={"message": "An unexpected error has occurred"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MercadoBitcoinAdapter(
            "client-value", "secret-value", "https://example.test/api/v4", client
        )
        with pytest.raises(MercadoBitcoinError, match="credenciais foram autenticadas"):
            await adapter.validate_account()


@pytest.mark.asyncio
async def test_symbol_rules_and_trading_fees_are_parsed_as_decimal():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.path.endswith("/symbols"):
            return httpx.Response(200, json={
                "symbol": ["BTC-BRL"],
                "exchange-listed": [True],
                "exchange-traded": [True],
                "min-price": ["100000.00000000"],
                "max-price": ["1000000.00000000"],
                "min-volume": ["0.00000150"],
                "max-volume": ["45.00000000"],
                "min-cost": ["0.90000000"],
                "max-cost": ["1000000.00000000"],
                "round-lot": ["0.00000001"],
            })
        return httpx.Response(200, json={"maker_fee": "0.003", "taker_fee": "0.007"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MercadoBitcoinAdapter("client", "secret", "https://example.test/api/v4", client)
        rules = await adapter.get_symbol_rules(["BTC/BRL"])
        fees = await adapter.get_trading_fees("account-1", "BTC/BRL")

    assert rules[0]["min-cost"] == "0.90000000"
    assert fees == {"maker_fee": D("0.003"), "taker_fee": D("0.007")}


@pytest.mark.asyncio
async def test_ticker_is_public_and_uses_brl_pair():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["symbols"] == "BTC-BRL"
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=[{"pair": "BTC-BRL", "buy": "499000", "sell": "500000", "last": "499500", "vol": "10"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await MercadoBitcoinAdapter("client-value", "secret-value", "https://example.test/api/v4", client).get_ticker("BTC/BRL")
    assert result["ask"] == D("500000")


@pytest.mark.asyncio
async def test_public_candles_are_parsed_without_credentials():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/candles")
        assert request.url.params["symbol"] == "BTC-BRL"
        assert request.url.params["resolution"] == "15m"
        assert "Authorization" not in request.headers
        values = list(range(40))
        return httpx.Response(200, json={"o": values, "h": values, "l": values, "c": values, "v": values, "t": values})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await MercadoBitcoinAdapter("", "", "https://example.test/api/v4", client).get_candles("BTC/BRL")
    assert len(result) == 40
    assert result[-1]["close"] == D("39")


@pytest.mark.asyncio
async def test_order_timeout_reconciles_using_external_id():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.method == "POST":
            raise httpx.ReadTimeout("unknown result", request=request)
        return httpx.Response(200, json={"items": [{"id": "order-1", "external_id": "client-order-1", "status": "working"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MercadoBitcoinAdapter("client-value", "secret-value", "https://example.test/api/v4", client)
        result = await adapter.create_limit_order("account-1", "client-order-1", "BTC/BRL", "BUY", D("0.00001"), D("500000"))
    assert result["id"] == "order-1"


@pytest.mark.asyncio
async def test_market_buy_uses_brl_cost_and_external_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(200, json={"orderId": "order-live-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await MercadoBitcoinAdapter("client", "secret", "https://example.test/api/v4", client).create_market_order(
            "account-1", "bitty-live-1", "BTC/BRL", "BUY", D("20.00")
        )
    assert result["orderId"] == "order-live-1"
    assert captured == {"async": False, "externalId": "bitty-live-1", "side": "buy", "type": "market", "cost": 20.0}
