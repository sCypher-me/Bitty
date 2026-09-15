from datetime import datetime, timezone
from celery import Celery
import asyncio
import logging
from celery.schedules import crontab
from redis import Redis
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.engine import execute_bot_cycle,reconcile_bot
from app.models import Bot,BotStatus
celery=Celery("cryptobot",broker=settings.redis_url,backend=settings.redis_url)
celery.conf.beat_schedule={"worker-heartbeat":{"task":"app.worker.heartbeat","schedule":30.0},"reconcile":{"task":"app.worker.reconcile","schedule":crontab(minute="*/5")},"execute":{"task":"app.worker.execute_active","schedule":30.0}}
celery.conf.task_acks_late=True; celery.conf.worker_prefetch_multiplier=1
@celery.task(name="app.worker.heartbeat")
def heartbeat():
    timestamp=datetime.now(timezone.utc).isoformat()
    redis=Redis.from_url(settings.redis_url)
    redis.set("bitty:worker:heartbeat",timestamp,ex=90)
    return {"timestamp":timestamp}
@celery.task(name="app.worker.reconcile")
def reconcile():
    async def run():
        async with SessionLocal() as db:
            bots=list((await db.scalars(select(Bot).where(Bot.mode=="PAPER",Bot.status.in_([BotStatus.STARTING,BotStatus.ACTIVE])))).all())
            for bot in bots: await reconcile_bot(db,bot)
            await db.commit(); return len(bots)
    return {"reconciled":asyncio.run(run()),"timestamp":datetime.now(timezone.utc).isoformat()}
@celery.task(name="app.worker.execute_active")
def execute_active():
    async def run():
        async with SessionLocal() as db:
            bots=list((await db.scalars(select(Bot).where(Bot.mode=="PAPER",Bot.status.in_([BotStatus.ACTIVE,BotStatus.RECONNECTING]),Bot.reconciled.is_(True)))).all()); done=0
            redis=Redis.from_url(settings.redis_url)
            for bot in bots:
                lock=redis.lock(f"bot:{bot.id}:execution",timeout=25,blocking_timeout=0)
                if not lock.acquire(blocking=False): continue
                try: await execute_bot_cycle(db,bot); await db.commit(); done+=1
                except Exception:
                    await db.rollback(); bot=await db.get(Bot,bot.id); bot.status=BotStatus.ERROR; await db.commit()
                finally:
                    try: lock.release()
                    except Exception: logging.exception("failed to release execution lock for bot %s",bot.id)
            return done
    return {"processed":asyncio.run(run()),"timestamp":datetime.now(timezone.utc).isoformat()}
