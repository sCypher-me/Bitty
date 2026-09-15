import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import select, text
from app.api import router
from app.config import settings
from app.db import SessionLocal
from app.engine import bot_cycle_lock, execute_bot_cycle, reconcile_bot
from app.models import Bot, BotStatus

logging.basicConfig(level=logging.INFO,format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
@asynccontextmanager
async def lifespan(app:FastAPI):
    logging.info("API started; bots must reconcile before resuming")
    stop=asyncio.Event()
    async def embedded_worker():
        while not stop.is_set():
            try:
                async with SessionLocal() as db:
                    bots=list((await db.scalars(select(Bot).where(Bot.mode=="PAPER",Bot.status.in_([BotStatus.STARTING,BotStatus.ACTIVE,BotStatus.RECONNECTING])))).all())
                    for bot in bots:
                        if not bot.reconciled: await reconcile_bot(db,bot)
                        elif bot.status in {BotStatus.ACTIVE,BotStatus.RECONNECTING}:
                            async with bot_cycle_lock(bot.id): await execute_bot_cycle(db,bot)
                    await db.commit()
            except Exception:
                logging.exception("embedded paper worker cycle failed")
            try: await asyncio.wait_for(stop.wait(),timeout=settings.embedded_worker_interval)
            except TimeoutError: pass
    task=asyncio.create_task(embedded_worker()) if settings.embedded_worker_enabled else None
    yield
    stop.set()
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
app=FastAPI(title="Bitty API",version="0.2.0",lifespan=lifespan)
allowed_origins={settings.frontend_url}
if "localhost" in settings.frontend_url: allowed_origins.add(settings.frontend_url.replace("localhost","127.0.0.1"))
app.add_middleware(CORSMiddleware,allow_origins=sorted(allowed_origins),allow_credentials=True,allow_methods=["GET","POST","PUT","DELETE"],allow_headers=["Content-Type","X-CSRF-Token","X-Request-ID"])
@app.middleware("http")
async def security_headers(request:Request,call_next):
    request_id=request.headers.get("X-Request-ID",str(uuid.uuid4())); started=time.monotonic(); response=await call_next(request); response.headers.update({"X-Request-ID":request_id,"X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY","Referrer-Policy":"same-origin","Permissions-Policy":"camera=(), microphone=(), geolocation=()"}); logging.info("request id=%s method=%s path=%s status=%s duration_ms=%.2f",request_id,request.method,request.url.path,response.status_code,(time.monotonic()-started)*1000); return response
@app.get("/health")
async def health(): return {"status":"ok","real_trading":settings.real_trading_enabled,"paper_worker":settings.embedded_worker_enabled}
@app.get("/ready")
async def ready():
    checks={"database":False,"worker":False}
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1")); checks["database"]=True
    except Exception: logging.exception("readiness database check failed")
    if settings.embedded_worker_enabled:
        checks["worker"]=True
    else:
        redis=Redis.from_url(settings.redis_url,decode_responses=True)
        try: checks["worker"]=(await redis.get("bitty:worker:heartbeat")) is not None
        except Exception: logging.exception("readiness worker check failed")
        finally: await redis.aclose()
    payload={"status":"ready" if all(checks.values()) else "not_ready","checks":checks,"worker_mode":"embedded" if settings.embedded_worker_enabled else "celery"}
    return JSONResponse(payload,status_code=200 if all(checks.values()) else 503)
app.include_router(router)
