import hashlib
import hmac
from decimal import Decimal as D

import httpx
import pytest

from app.binance import BinanceSpotAdapter, floor_to_step, signed_query


def test_signed_query_is_percent_encoded_before_hmac():
    query = signed_query({"note": "a b+c", "symbol": "BTCBRL", "timestamp": 1}, "secret")
    payload = "note=a%20b%2Bc&symbol=BTCBRL&timestamp=1"
    expected = hmac.new(b"secret", payload.encode(), hashlib.sha256).hexdigest()
    assert query == f"{payload}&signature={expected}"


def test_floor_to_exchange_step_never_rounds_up():
    assert floor_to_step(D("0.001239"), D("0.00001")) == D("0.00123")


@pytest.mark.asyncio
async def test_account_validation_sends_key_and_signed_query():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-MBX-APIKEY"] == "key-value"
        assert "signature=" in str(request.url)
        return httpx.Response(200, json={"canTrade": True, "accountType": "SPOT", "permissions": ["SPOT"]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await BinanceSpotAdapter("key-value", "secret-value", "https://example.test", client=client).validate_account()
    assert result == {"can_trade": True, "account_type": "SPOT", "permissions": ["SPOT"]}


@pytest.mark.asyncio
async def test_submit_timeout_reconciles_by_client_order_id():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadTimeout("unknown submit result", request=request)
        assert "origClientOrderId=order-1" in str(request.url)
        return httpx.Response(200, json={"clientOrderId": "order-1", "status": "NEW"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = BinanceSpotAdapter("key-value", "secret-value", "https://example.test", client=client)
        result = await adapter.create_order("order-1", "BTC/BRL", "BUY", D("0.001"), D("500000"))
    assert result["clientOrderId"] == "order-1"
    assert calls == ["POST", "GET"]
