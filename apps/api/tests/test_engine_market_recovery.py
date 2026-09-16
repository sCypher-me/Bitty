from decimal import Decimal as D

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.engine import execute_bot_cycle
from app.models import Bot, BotConfig, BotStatus, Notification, PortfolioSnapshot, Signal, User


async def make_active_bot(db):
    user = User(email="engine@example.com", password_hash="unused")
    db.add(user)
    await db.flush()
    bot = Bot(user_id=user.id, name="Bitty", mode="PAPER", status=BotStatus.ACTIVE, reconciled=True)
    db.add(bot)
    await db.flush()
    db.add(BotConfig(bot_id=bot.id, capital=D("100"), symbols=["BTC/BRL"]))
    await db.commit()
    return bot


@pytest.mark.asyncio
async def test_market_failure_warns_once_and_enters_reconnecting(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        bot = await make_active_bot(db)

        async def fail_tickers(_symbols):
            raise RuntimeError("network down")

        monkeypatch.setattr("app.engine.market_data.get_tickers", fail_tickers)
        assert await execute_bot_cycle(db, bot) == "MARKET_UNAVAILABLE"
        await db.commit()
        assert bot.status == BotStatus.RECONNECTING
        assert await execute_bot_cycle(db, bot) == "MARKET_UNAVAILABLE"
        await db.commit()
        warnings = await db.scalar(select(func.count()).select_from(Notification).where(Notification.event == "market_data_unavailable"))
        assert warnings == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_market_recovery_reactivates_and_records_cycle(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        bot = await make_active_bot(db)
        bot.status = BotStatus.RECONNECTING
        await db.commit()

        async def tickers(_symbols):
            return [{"symbol": "BTC-BRL", "bid": D("399900"), "ask": D("400100"), "last": D("400000"), "volume": D("100")}]

        async def candles(_symbol):
            return [{"open": D("400000"), "high": D("401000"), "low": D("399000"), "close": D("400000"), "volume": D("10")} for _ in range(40)]

        monkeypatch.setattr("app.engine.market_data.get_tickers", tickers)
        monkeypatch.setattr("app.engine.market_data.get_candles", candles)
        assert await execute_bot_cycle(db, bot) == "OK"
        await db.commit()
        assert bot.status == BotStatus.ACTIVE
        assert await db.scalar(select(func.count()).select_from(Signal).where(Signal.bot_id == bot.id)) == 1
        assert await db.scalar(select(func.count()).select_from(PortfolioSnapshot).where(PortfolioSnapshot.bot_id == bot.id)) == 1
        assert await db.scalar(select(func.count()).select_from(Notification).where(Notification.event == "market_data_recovered")) == 1
    await engine.dispose()
