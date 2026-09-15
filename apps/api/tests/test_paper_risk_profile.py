from decimal import Decimal as D

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import set_paper_risk_profile
from app.db import Base
from app.models import Bot, BotConfig, BotStatus, User
from app.schemas import PaperRiskProfileIn


@pytest.mark.asyncio
async def test_paper_risk_profile_is_persisted_only_while_inactive():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = User(email="risk@example.com", password_hash="unused")
        db.add(user); await db.flush()
        bot = Bot(user_id=user.id, name="Bitty", mode="PAPER", status=BotStatus.PAUSED)
        db.add(bot); await db.flush()
        config = BotConfig(bot_id=bot.id, capital=D("1000"), symbols=["BTC/BRL"])
        db.add(config); await db.commit()

        result = await set_paper_risk_profile(bot.id, PaperRiskProfileIn(profile="AGGRESSIVE"), user, db)
        assert result["profile"] == "AGGRESSIVE"
        assert result["moves_money"] is False
        assert config.max_trade_pct == D("0.10")
        assert config.max_asset_pct == D("0.30")
        assert config.reserve_pct == D("0.10")
        assert config.advanced["paper_risk_profile"] == "AGGRESSIVE"

        bot.status = BotStatus.ACTIVE
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await set_paper_risk_profile(bot.id, PaperRiskProfileIn(profile="MODERATE"), user, db)
        assert error.value.status_code == 409
    await engine.dispose()
