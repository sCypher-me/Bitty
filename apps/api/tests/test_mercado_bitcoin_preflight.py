import json
from decimal import Decimal as D

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import mercado_bitcoin_preflight, set_real_capital
from app.config import settings
from app.db import Base
from app.models import Bot, BotConfig, BotStatus, ExchangeAccount, User
from app.schemas import RealCapitalIn


class ReadOnlyMercadoBitcoin:
    created_orders = 0

    def __init__(self, *_args, **_kwargs):
        pass

    async def validate_account(self):
        return {"account_id": "account-safe-123456", "currency": "BRL", "brl_available": D("150")}

    async def get_tickers(self, symbols):
        return [{"symbol": symbol, "bid": D("399000"), "ask": D("400000"), "last": D("399500")} for symbol in symbols]

    async def get_symbol_rules(self, symbols):
        return [{"symbol": symbol, "exchange-traded": True, "min-cost": "0.90", "min-volume": "0.0000015", "round-lot": "0.00000001"} for symbol in symbols]

    async def get_open_orders(self, _account_id):
        return []

    async def get_trading_fees(self, _account_id, _symbol):
        return {"maker_fee": D("0.003"), "taker_fee": D("0.007")}

    async def create_limit_order(self, *_args, **_kwargs):
        type(self).created_orders += 1
        raise AssertionError("preflight must never create an order")


@pytest.mark.asyncio
@pytest.mark.parametrize("inactive_status", [BotStatus.STOPPED, BotStatus.PAUSED])
async def test_preflight_reads_account_rules_and_fees_without_creating_order(monkeypatch, inactive_status):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.api.decrypt_secret", lambda _value: json.dumps({"client_id": "id", "client_secret": "secret"}))
    monkeypatch.setattr("app.api.MercadoBitcoinAdapter", ReadOnlyMercadoBitcoin)
    monkeypatch.setattr(settings, "real_trading_enabled", False)
    ReadOnlyMercadoBitcoin.created_orders = 0

    async with sessions() as db:
        user = User(email="preflight@example.com", password_hash="unused")
        db.add(user); await db.flush()
        bot = Bot(user_id=user.id, name="Bitty", mode="PAPER", status=inactive_status, reconciled=True)
        db.add(bot); await db.flush()
        db.add(BotConfig(bot_id=bot.id, capital=D("100"), symbols=["BTC/BRL"]))
        db.add(ExchangeAccount(user_id=user.id, exchange="MERCADO_BITCOIN", mode="LIVE", encrypted_credentials="encrypted"))
        await db.commit()

        limit = await set_real_capital(bot.id, RealCapitalIn(amount_brl=D("10")), user, db)
        result = await mercado_bitcoin_preflight(bot.id, user, db)

    assert limit == {"amount_brl": "10.00", "moves_money": False, "real_trading_enabled": False}
    assert result["mode"] == "READ_ONLY_PREFLIGHT"
    assert result["executed_orders"] == 0
    assert result["account"]["available_brl"] == "150"
    assert result["configured_capital"] == "10.00"
    assert result["checks"]["balance_covers_capital"] is True
    assert result["checks"]["no_open_orders"] is True
    assert result["checks"]["paper_bot_stopped"] is True
    assert not any("bot Paper" in blocker for blocker in result["blockers"])
    assert result["ready_for_live"] is False
    assert ReadOnlyMercadoBitcoin.created_orders == 0
    await engine.dispose()
