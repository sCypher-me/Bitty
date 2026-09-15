import asyncio
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Strategy,StrategyVersion
async def main():
    async with SessionLocal() as db:
        strategy=await db.scalar(select(Strategy).where(Strategy.name=="Adaptive Mean Reversion"))
        if not strategy:
            strategy=Strategy(name="Adaptive Mean Reversion",description="EMA, RSI, ATR, volume and spread confluence"); db.add(strategy); await db.flush(); db.add(StrategyVersion(strategy_id=strategy.id,version="1.0",parameters={"ema":20,"rsi":14,"atr":14})); await db.commit()
if __name__=="__main__": asyncio.run(main())
