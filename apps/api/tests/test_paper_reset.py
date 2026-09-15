from decimal import Decimal as D

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import reset_paper
from app.db import Base
from app.models import Bot, BotConfig, BotStatus, Order, PortfolioSnapshot, Position, Side, User
from app.schemas import PaperResetIn


@pytest.mark.asyncio
async def test_reset_paper_clears_metrics_and_applies_new_initial_capital():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = User(email="reset@example.com", password_hash="unused")
        db.add(user); await db.flush()
        bot = Bot(user_id=user.id, name="Bitty Test", mode="PAPER", status=BotStatus.ACTIVE, reconciled=True)
        db.add(bot); await db.flush()
        db.add(BotConfig(bot_id=bot.id, capital=D("100"), symbols=["BTC/BRL"]))
        db.add(Order(user_id=user.id, bot_id=bot.id, client_order_id="reset-order", symbol="BTC/BRL", side=Side.BUY, quantity=D("0.00001")))
        db.add(Position(user_id=user.id, bot_id=bot.id, symbol="BTC/BRL", quantity=D("0.00001"), average_cost=D("400000")))
        db.add(PortfolioSnapshot(bot_id=bot.id, cash=D("96"), invested=D("4"), equity=D("101"), drawdown=D("0")))
        await db.commit()

        result = await reset_paper(bot.id, PaperResetIn(initial_capital_brl=D("250")), user, db)

        assert result == {"reset": True, "status": "STOPPED", "capital": "250.00"}
        assert await db.scalar(select(func.count()).select_from(Order).where(Order.bot_id == bot.id)) == 0
        assert await db.scalar(select(func.count()).select_from(Position).where(Position.bot_id == bot.id)) == 0
        assert await db.scalar(select(func.count()).select_from(PortfolioSnapshot).where(PortfolioSnapshot.bot_id == bot.id)) == 0
        config = await db.scalar(select(BotConfig).where(BotConfig.bot_id == bot.id))
        assert config is not None and config.capital == D("250")
        await db.refresh(bot)
        assert bot.status == BotStatus.STOPPED and bot.reconciled is False
    await engine.dispose()
