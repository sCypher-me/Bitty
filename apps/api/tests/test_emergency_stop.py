from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import emergency_stop_bot, start_bot
from app.db import Base
from app.models import AuditLog, Bot, BotConfig, BotStatus, Notification, User


@pytest.mark.asyncio
async def test_emergency_stop_is_persistent_audited_and_does_not_liquidate():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = User(email="emergency@example.com", password_hash="unused")
        db.add(user); await db.flush()
        bot = Bot(user_id=user.id, name="Bitty", mode="PAPER", status=BotStatus.ACTIVE, reconciled=True)
        db.add(bot); await db.flush()
        db.add(BotConfig(bot_id=bot.id, capital=D("100"), symbols=["BTC/BRL"], advanced={}))
        await db.commit()

        stopped = await emergency_stop_bot(bot.id, user, db)

        assert stopped.status == BotStatus.PAUSED
        assert stopped.reconciled is False
        config = await db.scalar(select(BotConfig).where(BotConfig.bot_id == bot.id))
        assert config is not None and config.advanced["emergency_stop"] is True
        audit = await db.scalar(select(AuditLog).where(AuditLog.event == "emergency_stop"))
        assert audit is not None and audit.details["positions_liquidated"] is False
        notice = await db.scalar(select(Notification).where(Notification.event == "emergency_stop"))
        assert notice is not None and notice.level == "CRITICAL"

        restarted = await start_bot(bot.id, user, db)
        assert restarted.status == BotStatus.ACTIVE
        config = await db.scalar(select(BotConfig).where(BotConfig.bot_id == bot.id))
        assert config is not None and config.advanced["emergency_stop"] is False
    await engine.dispose()
