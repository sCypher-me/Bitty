from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.live_engine import apply_exchange_order, live_limits
from app.models import Bot, BotConfig, BotStatus, Order, OrderStatus, Position, Side, User


def test_live_limits_are_conservative_for_one_hundred_reais():
    config = BotConfig(bot_id=__import__("uuid").uuid4(), capital=D("100"), symbols=["BTC/BRL"], advanced={"real_capital_brl":"100"})
    limits = live_limits(config)
    assert limits["capital"] == D("100")
    assert limits["max_order"] == D("20")
    assert limits["reserve"] == D("50")
    assert limits["daily_loss"] == D("2")
    assert limits["stop_loss"] == D("0.02")


@pytest.mark.asyncio
async def test_filled_real_buy_accounts_for_fee_in_acquired_asset():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = User(email="live@example.com", password_hash="unused")
        db.add(user); await db.flush()
        bot = Bot(user_id=user.id, name="Bitty", mode="LIVE", status=BotStatus.ACTIVE, reconciled=True)
        db.add(bot); await db.flush()
        order = Order(user_id=user.id, bot_id=bot.id, client_order_id="live-1", symbol="BTC/BRL", side=Side.BUY, status=OrderStatus.SUBMITTED, quantity=D("0"))
        db.add(order); await db.flush()
        await apply_exchange_order(db, bot, order, {"id":"mb-1","status":"filled","filledQty":"0.00005","avgPrice":"400000","fee":"0.00000035"})
        await db.commit()
        position = await db.scalar(select(Position).where(Position.bot_id == bot.id))
        assert order.status == OrderStatus.FILLED
        assert order.fees == D("0.14")
        assert position.quantity == D("0.00004965")
        assert position.average_cost > D("400000")
    await engine.dispose()
