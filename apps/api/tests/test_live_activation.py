import json
from decimal import Decimal as D

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import activate_live_bot
from app.config import settings
from app.db import Base
from app.models import AuditLog, Bot, BotConfig, BotStatus, ExchangeAccount, Order, User
from app.schemas import LiveActivationIn


class SafeActivationMercadoBitcoin:
    orders_created = 0

    def __init__(self, *_args, **_kwargs):
        pass

    async def validate_account(self):
        return {"account_id":"account-1","brl_available":D("100"),"currency":"BRL"}

    async def get_open_orders(self, _account_id):
        return []

    async def get_symbol_rules(self, _symbols):
        return [{"symbol":"BTC/BRL","exchange-traded":True}]

    async def get_trading_fees(self, _account_id, _symbol):
        return {"maker_fee":D("0.003"),"taker_fee":D("0.007")}

    async def create_market_order(self, *_args, **_kwargs):
        type(self).orders_created += 1
        raise AssertionError("activation must not submit an order")


@pytest.mark.asyncio
async def test_live_activation_requires_phrase_and_only_arms_worker(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "real_trading_enabled", True)
    monkeypatch.setattr("app.api.decrypt_secret", lambda _value: json.dumps({"client_id":"id","client_secret":"secret"}))
    monkeypatch.setattr("app.api.MercadoBitcoinAdapter", SafeActivationMercadoBitcoin)
    SafeActivationMercadoBitcoin.orders_created = 0
    async with sessions() as db:
        user = User(email="activation@example.com", password_hash="unused")
        db.add(user); await db.flush()
        bot = Bot(user_id=user.id, name="Bitty", mode="PAPER", status=BotStatus.STOPPED, reconciled=False)
        db.add(bot); await db.flush()
        config = BotConfig(bot_id=bot.id, capital=D("100"), symbols=["BTC/BRL"], advanced={"real_capital_brl":"100.00"})
        db.add(config)
        db.add(ExchangeAccount(user_id=user.id, exchange="MERCADO_BITCOIN", mode="LIVE", encrypted_credentials="encrypted"))
        await db.commit()

        with pytest.raises(HTTPException) as wrong_phrase:
            await activate_live_bot(bot.id, LiveActivationIn(confirmation="sim"), user, db)
        assert wrong_phrase.value.status_code == 422
        result = await activate_live_bot(bot.id, LiveActivationIn(confirmation=settings.real_trading_confirmation), user, db)
        assert result.mode == "LIVE"
        assert result.status == BotStatus.ACTIVE
        assert config.advanced["live_armed"] is True
        assert config.advanced["live_max_order_brl"] == "20.00"
        assert config.advanced["live_reserve_brl"] == "50.00"
        assert await db.scalar(select(func.count()).select_from(Order)) == 0
        assert await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.event == "live_trading_activated")) == 1
        assert SafeActivationMercadoBitcoin.orders_created == 0
    await engine.dispose()
