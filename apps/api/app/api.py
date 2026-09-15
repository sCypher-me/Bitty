import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.backtesting import Backtester
from app.binance import BinanceError, BinanceSpotAdapter, floor_to_step
from app.mercado_bitcoin import MercadoBitcoinAdapter, MercadoBitcoinError
from app.config import settings
from app.db import SessionLocal, get_db
from app.dependencies import current_user, is_expired
from app.engine import bot_cycle_lock, reconcile_bot
from app.market_data import market_data
from app.models import AuditLog, Backtest, Bot, BotConfig, BotStatus, DeviceSession, ExchangeAccount, Notification, Order, OrderFill, PortfolioSnapshot, Position, RiskDecision, Signal, User
from app.schemas import BacktestIn, BinanceConnectIn, BinanceOrderTestIn, BotCreate, BotOut, LoginIn, MercadoBitcoinConnectIn, PaperResetIn, PaperRiskProfileIn, RealCapitalIn, RegisterIn, UserOut
from app.security import create_access_token, decode_access_token, decrypt_secret, encrypt_secret, hash_password, hash_refresh_token, new_refresh_token, verify_password

router=APIRouter(prefix="/api/v1")
auth=APIRouter(prefix="/auth",tags=["auth"]); bots=APIRouter(prefix="/bots",tags=["bots"]); backtests=APIRouter(prefix="/backtests",tags=["backtests"]); exchange_accounts=APIRouter(prefix="/exchange-accounts",tags=["exchange-accounts"])
PAPER_RISK_PROFILES={
    "CONSERVATIVE":{"max_trade_pct":Decimal("0.03"),"max_asset_pct":Decimal("0.10"),"max_exposure_pct":Decimal("0.50"),"reserve_pct":Decimal("0.30"),"daily_loss_pct":Decimal("0.02"),"max_drawdown_pct":Decimal("0.08")},
    "MODERATE":{"max_trade_pct":Decimal("0.05"),"max_asset_pct":Decimal("0.15"),"max_exposure_pct":Decimal("0.60"),"reserve_pct":Decimal("0.25"),"daily_loss_pct":Decimal("0.03"),"max_drawdown_pct":Decimal("0.10")},
    "AGGRESSIVE":{"max_trade_pct":Decimal("0.10"),"max_asset_pct":Decimal("0.30"),"max_exposure_pct":Decimal("0.80"),"reserve_pct":Decimal("0.10"),"daily_loss_pct":Decimal("0.06"),"max_drawdown_pct":Decimal("0.20")},
}

ACCESS_COOKIE_SECONDS=60*settings.access_token_minutes
REFRESH_COOKIE_SECONDS=86400*settings.refresh_token_days


def set_auth_cookies(response:Response,user_id:UUID,session_id:UUID,refresh_token:str)->None:
    common={"httponly":True,"secure":settings.cookie_secure,"samesite":"strict","path":"/"}
    response.set_cookie("access_token",create_access_token(user_id,session_id),max_age=ACCESS_COOKIE_SECONDS,**common)
    response.set_cookie("refresh_token",refresh_token,max_age=REFRESH_COOKIE_SECONDS,**common)


def clear_auth_cookies(response:Response)->None:
    response.delete_cookie("access_token",path="/",samesite="strict")
    response.delete_cookie("refresh_token",path="/",samesite="strict")


async def create_device_session(db:AsyncSession,user_id:UUID)->tuple[DeviceSession,str]:
    refresh_token=new_refresh_token()
    session=DeviceSession(
        user_id=user_id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        expires_at=datetime.now(timezone.utc)+timedelta(days=settings.refresh_token_days),
    )
    db.add(session)
    await db.flush()
    return session,refresh_token

@auth.post("/register",response_model=UserOut,status_code=201)
async def register(body:RegisterIn,response:Response,db:AsyncSession=Depends(get_db)):
    if await db.scalar(select(User).where(User.email==body.email.lower())): raise HTTPException(409,"Email already registered")
    user=User(email=body.email.lower(),password_hash=hash_password(body.password)); db.add(user); await db.flush()
    session,refresh_token=await create_device_session(db,user.id)
    db.add(AuditLog(user_id=user.id,event="user_registered")); await db.commit()
    set_auth_cookies(response,user.id,session.id,refresh_token); return user
@auth.post("/login",response_model=UserOut)
async def login(body:LoginIn,response:Response,db:AsyncSession=Depends(get_db)):
    user=await db.scalar(select(User).where(User.email==body.email.lower()))
    if not user or not verify_password(body.password,user.password_hash): raise HTTPException(status.HTTP_401_UNAUTHORIZED,"Invalid credentials")
    session,refresh_token=await create_device_session(db,user.id); await db.commit()
    set_auth_cookies(response,user.id,session.id,refresh_token); return user

@auth.post("/refresh",status_code=204)
async def refresh_session(response:Response,refresh_token:str|None=Cookie(default=None),db:AsyncSession=Depends(get_db)):
    if not refresh_token: raise HTTPException(status.HTTP_401_UNAUTHORIZED,"Refresh session required")
    session=await db.scalar(select(DeviceSession).where(DeviceSession.refresh_token_hash==hash_refresh_token(refresh_token)).with_for_update())
    if not session or session.revoked_at or is_expired(session.expires_at):
        failure=JSONResponse({"detail":"Invalid refresh session"},status_code=status.HTTP_401_UNAUTHORIZED)
        clear_auth_cookies(failure); return failure
    rotated=new_refresh_token()
    session.refresh_token_hash=hash_refresh_token(rotated)
    session.last_seen_at=datetime.now(timezone.utc)
    await db.commit()
    set_auth_cookies(response,session.user_id,session.id,rotated)

@auth.post("/logout",status_code=204)
async def logout(response:Response,access_token:str|None=Cookie(default=None),refresh_token:str|None=Cookie(default=None),db:AsyncSession=Depends(get_db)):
    session=None
    if access_token:
        try:
            claims=decode_access_token(access_token)
            session=await db.scalar(select(DeviceSession).where(DeviceSession.id==claims.session_id,DeviceSession.user_id==claims.user_id))
        except Exception: pass
    if session is None and refresh_token:
        session=await db.scalar(select(DeviceSession).where(DeviceSession.refresh_token_hash==hash_refresh_token(refresh_token)))
    if session and not session.revoked_at:
        session.revoked_at=datetime.now(timezone.utc); await db.commit()
    clear_auth_cookies(response)

@auth.get("/me",response_model=UserOut)
async def me(user:User=Depends(current_user)): return user

@auth.get("/sessions")
async def sessions(user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    rows=(await db.scalars(select(DeviceSession).where(DeviceSession.user_id==user.id).order_by(DeviceSession.created_at.desc()))).all()
    return [{"id":str(row.id),"created_at":row.created_at,"last_seen_at":row.last_seen_at,"expires_at":row.expires_at,"active":not row.revoked_at and not is_expired(row.expires_at)} for row in rows]

@bots.post("",response_model=BotOut,status_code=201)
async def create_bot(body:BotCreate,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=Bot(user_id=user.id,name=body.name,mode="PAPER"); db.add(bot); await db.flush(); profiles={"CONSERVATIVE":(Decimal("0.03"),Decimal("0.10")),"MODERATE":(Decimal("0.05"),Decimal("0.15"))}; trade,asset=profiles.get(body.risk_profile,(Decimal("0.05"),Decimal("0.15"))); db.add(BotConfig(bot_id=bot.id,capital=body.capital,symbols=body.symbols,max_trade_pct=trade,max_asset_pct=asset)); db.add(AuditLog(user_id=user.id,event="bot_created",entity_id=str(bot.id))); await db.commit(); await db.refresh(bot); return bot
@bots.get("",response_model=list[BotOut])
async def list_bots(user:User=Depends(current_user),db:AsyncSession=Depends(get_db)): return list((await db.scalars(select(Bot).where(Bot.user_id==user.id).order_by(Bot.created_at.desc()))).all())
async def owned_bot(bot_id:UUID,user:User,db:AsyncSession)->Bot:
    bot=await db.scalar(select(Bot).where(Bot.id==bot_id,Bot.user_id==user.id))
    if not bot: raise HTTPException(404,"Bot not found")
    return bot
@bots.post("/{bot_id}/start",response_model=BotOut)
async def start_bot(bot_id:UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    if bot.mode!="PAPER": raise HTTPException(409,"Execução automática real ainda não foi ativada para este bot")
    config=await db.scalar(select(BotConfig).where(BotConfig.bot_id==bot.id))
    if config:
        advanced=dict(config.advanced or {}); advanced["emergency_stop"]=False; config.advanced=advanced
    bot.status=BotStatus.STARTING; bot.reconciled=False; await reconcile_bot(db,bot); db.add(Notification(user_id=user.id,level="INFO",event="bot_started",message="Bot reconciliado e iniciado em Paper Trading.")); db.add(AuditLog(user_id=user.id,event="bot_started",entity_id=str(bot.id))); await db.commit(); await db.refresh(bot); return bot
@bots.post("/{bot_id}/pause",response_model=BotOut)
async def pause_bot(bot_id:UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    async with bot_cycle_lock(bot.id):
        await db.refresh(bot); bot.status=BotStatus.PAUSED; bot.reconciled=False
        db.add(AuditLog(user_id=user.id,event="bot_paused",entity_id=str(bot.id))); await db.commit(); await db.refresh(bot)
    return bot
@bots.post("/{bot_id}/stop",response_model=BotOut)
async def stop_bot(bot_id:UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    async with bot_cycle_lock(bot.id):
        await db.refresh(bot); bot.status=BotStatus.STOPPING; bot.reconciled=False; await db.commit()
        bot.status=BotStatus.STOPPED; db.add(AuditLog(user_id=user.id,event="bot_stopped",entity_id=str(bot.id))); await db.commit(); await db.refresh(bot)
    return bot
@bots.post("/{bot_id}/emergency-stop",response_model=BotOut)
async def emergency_stop_bot(bot_id:UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    async with bot_cycle_lock(bot.id):
        await db.refresh(bot)
        previous=bot.status.value
        bot.status=BotStatus.PAUSED; bot.reconciled=False
        config=await db.scalar(select(BotConfig).where(BotConfig.bot_id==bot.id))
        if config:
            advanced=dict(config.advanced or {})
            advanced.update({"emergency_stop":True,"emergency_stopped_at":datetime.now(timezone.utc).isoformat()})
            config.advanced=advanced
        db.add(Notification(user_id=user.id,level="CRITICAL",event="emergency_stop",message="Parada de emergência acionada. Nenhuma nova ordem será criada; posições existentes não foram vendidas."))
        db.add(AuditLog(user_id=user.id,event="emergency_stop",entity_id=str(bot.id),details={"previous_status":previous,"positions_liquidated":False}))
        await db.commit(); await db.refresh(bot)
    return bot
@bots.post("/{bot_id}/reset-paper")
async def reset_paper(bot_id:UUID,body:PaperResetIn|None=None,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    if bot.mode!="PAPER": raise HTTPException(409,"Somente um bot Paper pode ser zerado")
    async with bot_cycle_lock(bot.id):
        await db.refresh(bot)
        config=await db.scalar(select(BotConfig).where(BotConfig.bot_id==bot.id))
        if not config: raise HTTPException(409,"Configuração do bot não encontrada")
        capital=(body.initial_capital_brl if body else Decimal(config.capital)).quantize(Decimal("0.01"))
        config.capital=capital
        bot.status=BotStatus.STOPPED; bot.reconciled=False
        order_ids=select(Order.id).where(Order.bot_id==bot.id,Order.user_id==user.id)
        signal_ids=select(Signal.id).where(Signal.bot_id==bot.id)
        await db.execute(delete(OrderFill).where(OrderFill.order_id.in_(order_ids)))
        await db.execute(delete(RiskDecision).where((RiskDecision.bot_id==bot.id)|(RiskDecision.signal_id.in_(signal_ids))))
        await db.execute(delete(Order).where(Order.bot_id==bot.id,Order.user_id==user.id))
        await db.execute(delete(Signal).where(Signal.bot_id==bot.id))
        await db.execute(delete(Position).where(Position.bot_id==bot.id,Position.user_id==user.id))
        await db.execute(delete(PortfolioSnapshot).where(PortfolioSnapshot.bot_id==bot.id))
        db.add(Notification(user_id=user.id,level="INFO",event="paper_reset",message=f"Mercado de teste zerado com capital virtual de R$ {capital}."))
        db.add(AuditLog(user_id=user.id,event="paper_reset",entity_id=str(bot.id),details={"capital":str(capital)}))
        await db.commit()
    return {"reset":True,"status":"STOPPED","capital":str(capital)}
@bots.put("/{bot_id}/paper-risk-profile")
async def set_paper_risk_profile(bot_id:UUID,body:PaperRiskProfileIn,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    if bot.mode!="PAPER": raise HTTPException(409,"Perfis de simulação só podem ser usados no Paper Trading")
    if bot.status not in {BotStatus.STOPPED,BotStatus.PAUSED}: raise HTTPException(409,"Pause o Paper Bot antes de trocar o perfil de risco")
    config=await db.scalar(select(BotConfig).where(BotConfig.bot_id==bot.id))
    if not config: raise HTTPException(409,"Configuração do bot não encontrada")
    values=PAPER_RISK_PROFILES[body.profile]
    for field,value in values.items(): setattr(config,field,value)
    advanced=dict(config.advanced or {}); advanced["paper_risk_profile"]=body.profile; config.advanced=advanced
    db.add(AuditLog(user_id=user.id,event="paper_risk_profile_changed",entity_id=str(bot.id),details={"profile":body.profile,"moves_money":False,**{key:str(value) for key,value in values.items()}}))
    await db.commit()
    return {"profile":body.profile,"moves_money":False,**{key:str(value) for key,value in values.items()}}
@bots.get("/{bot_id}/dashboard")
async def dashboard(bot_id:UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    config=await db.scalar(select(BotConfig).where(BotConfig.bot_id==bot.id))
    positions=list((await db.scalars(select(Position).where(Position.bot_id==bot.id,Position.user_id==user.id))).all())
    orders=list((await db.scalars(select(Order).where(Order.bot_id==bot.id,Order.user_id==user.id).order_by(Order.created_at.desc()).limit(25))).all())
    snapshots=list((await db.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.bot_id==bot.id).order_by(PortfolioSnapshot.created_at.desc()).limit(48))).all())
    market_status="LIVE"
    try:
        market_rows=await market_data.get_tickers(config.symbols)
    except Exception:
        market_status="UNAVAILABLE"
        market_rows=[]
    prices={row["symbol"].replace("-","/"):Decimal(row["last"]) for row in market_rows}
    cost_basis=sum((p.quantity*p.average_cost for p in positions),Decimal("0"))
    realized=sum((p.realized_pnl for p in positions),Decimal("0"))
    available=Decimal(config.capital)+realized-cost_basis
    invested=sum((p.quantity*prices.get(p.symbol,p.average_cost) for p in positions),Decimal("0"))
    equity=available+invested
    total_pnl=equity-Decimal(config.capital)
    curve=[{"time":item.created_at.isoformat(),"equity":str(item.equity)} for item in reversed(snapshots)]
    curve.append({"time":datetime.now(timezone.utc).isoformat(),"equity":str(equity)})
    return {
        "bot":{"id":str(bot.id),"name":bot.name,"status":bot.status,"mode":bot.mode},
        "summary":{"initial_capital":str(config.capital),"equity":str(equity),"today_pnl":str(total_pnl),"total_pnl":str(total_pnl),"available":str(available),"invested":str(invested)},
        "risk_profile":{"name":str((config.advanced or {}).get("paper_risk_profile") or ("CONSERVATIVE" if Decimal(config.max_trade_pct)==Decimal("0.03") else "MODERATE")),"max_trade_pct":str(config.max_trade_pct),"max_asset_pct":str(config.max_asset_pct),"max_exposure_pct":str(config.max_exposure_pct),"reserve_pct":str(config.reserve_pct),"daily_loss_pct":str(config.daily_loss_pct),"max_drawdown_pct":str(config.max_drawdown_pct)},
        "market_status":market_status,
        "market":[{"symbol":row["symbol"].replace("-","/"),"bid":str(row["bid"]),"ask":str(row["ask"]),"last":str(row["last"]),"volume":str(row["volume"])} for row in market_rows],
        "equity_curve":curve,
        "positions":[{"symbol":p.symbol,"quantity":str(p.quantity),"average_cost":str(p.average_cost),"realized_pnl":str(p.realized_pnl)} for p in positions],
        "orders":[{"symbol":o.symbol,"side":o.side,"status":o.status,"quantity":str(o.quantity),"price":str(o.average_price or 0),"fees":str(o.fees),"created_at":o.created_at.isoformat()} for o in orders],
        "disclaimer":"Resultados simulados não garantem resultados futuros. Dados públicos: Mercado Bitcoin.",
    }

@backtests.post("")
async def run_backtest(body:BacktestIn,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    if len(body.candles)<21: raise HTTPException(422,"At least 21 candles required")
    result=Backtester().run(body.symbol,body.candles,body.initial_capital); record=Backtest(user_id=user.id,symbol=body.symbol,metrics=result.metrics); db.add(record); await db.commit(); return {"id":str(record.id),"metrics":result.metrics,"trades":result.trades,"equity_curve":result.equity_curve}

def binance_adapter(body:BinanceConnectIn)->BinanceSpotAdapter:
    base_url=settings.binance_testnet_base_url if body.environment=="TESTNET" else settings.binance_base_url
    return BinanceSpotAdapter(body.api_key.get_secret_value(),body.api_secret.get_secret_value(),base_url,settings.binance_recv_window_ms)

@exchange_accounts.post("/binance",status_code=201)
async def connect_binance(body:BinanceConnectIn,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    if not settings.encryption_master_key: raise HTTPException(503,"Configure ENCRYPTION_MASTER_KEY antes de salvar credenciais")
    try: validation=await binance_adapter(body).validate_account()
    except BinanceError as exc: raise HTTPException(422,str(exc)) from exc
    except Exception as exc: raise HTTPException(502,"Não foi possível validar a conexão com a Binance") from exc
    credentials=json.dumps({"api_key":body.api_key.get_secret_value(),"api_secret":body.api_secret.get_secret_value()})
    account=await db.scalar(select(ExchangeAccount).where(ExchangeAccount.user_id==user.id,ExchangeAccount.exchange=="BINANCE",ExchangeAccount.mode==body.environment))
    if account: account.encrypted_credentials=encrypt_secret(credentials)
    else: account=ExchangeAccount(user_id=user.id,exchange="BINANCE",mode=body.environment,encrypted_credentials=encrypt_secret(credentials)); db.add(account); await db.flush()
    db.add(AuditLog(user_id=user.id,event="exchange_connected",entity_id=str(account.id),details={"exchange":"BINANCE","environment":body.environment,"can_trade":validation["can_trade"]}))
    await db.commit()
    return {"id":str(account.id),"exchange":"BINANCE","environment":body.environment,"connected":True,"can_trade":True,"withdrawals_required":False}

@exchange_accounts.get("")
async def list_exchange_accounts(user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    accounts=list((await db.scalars(select(ExchangeAccount).where(ExchangeAccount.user_id==user.id).order_by(ExchangeAccount.created_at.desc()))).all())
    return [{"id":str(item.id),"exchange":item.exchange,"environment":item.mode,"connected":bool(item.encrypted_credentials),"credentials":"********" if item.encrypted_credentials else None} for item in accounts]

@exchange_accounts.post("/binance/test-order")
async def test_binance_order(body:BinanceOrderTestIn,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    account=await db.scalar(select(ExchangeAccount).where(ExchangeAccount.id==body.exchange_account_id,ExchangeAccount.user_id==user.id,ExchangeAccount.exchange=="BINANCE"))
    if not account or not account.encrypted_credentials: raise HTTPException(404,"Conta Binance não encontrada")
    if account.mode!="TESTNET": raise HTTPException(409,"O teste de ordem deve ser feito primeiro na Testnet")
    try:
        credentials=json.loads(decrypt_secret(account.encrypted_credentials))
        adapter=BinanceSpotAdapter(credentials["api_key"],credentials["api_secret"],settings.binance_testnet_base_url,settings.binance_recv_window_ms)
        rules=await adapter.rules(body.symbol); ticker=await adapter.get_ticker(body.symbol); quantity=floor_to_step(Decimal(body.notional_brl)/ticker["ask"],rules["step_size"])
        if quantity<rules["min_quantity"] or quantity*ticker["ask"]<rules["min_notional"]: raise HTTPException(422,f"R$ {body.notional_brl} está abaixo do mínimo aceito para {body.symbol}")
        client_id=f"aegis-test-{str(user.id).replace('-','')[:12]}"; await adapter.test_order(client_id,body.symbol,"BUY",quantity,ticker["ask"])
    except HTTPException: raise
    except BinanceError as exc: raise HTTPException(422,str(exc)) from exc
    except Exception as exc: raise HTTPException(502,"Falha ao validar a ordem na Binance Testnet") from exc
    db.add(AuditLog(user_id=user.id,event="exchange_test_order_validated",entity_id=str(account.id),details={"symbol":body.symbol,"notional_brl":str(body.notional_brl),"quantity":str(quantity)})); await db.commit()
    return {"validated":True,"executed":False,"environment":"TESTNET","symbol":body.symbol,"quantity":str(quantity),"limit_price":str(ticker["ask"]),"message":"Parâmetros aceitos; nenhuma ordem foi executada."}

@exchange_accounts.post("/mercado-bitcoin",status_code=201)
async def connect_mercado_bitcoin(body:MercadoBitcoinConnectIn,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    if not settings.encryption_master_key: raise HTTPException(503,"Configure ENCRYPTION_MASTER_KEY antes de salvar credenciais")
    adapter=MercadoBitcoinAdapter(body.client_id.get_secret_value(),body.client_secret.get_secret_value(),settings.mercado_bitcoin_base_url)
    try:
        validation=await adapter.validate_account()
        await adapter.get_tickers(["BTC/BRL","ETH/BRL","SOL/BRL"])
    except MercadoBitcoinError as exc: raise HTTPException(422,str(exc)) from exc
    except Exception as exc: raise HTTPException(502,"Não foi possível validar a conexão com o Mercado Bitcoin") from exc
    credentials=json.dumps({"client_id":body.client_id.get_secret_value(),"client_secret":body.client_secret.get_secret_value(),"account_id":validation["account_id"]})
    account=await db.scalar(select(ExchangeAccount).where(ExchangeAccount.user_id==user.id,ExchangeAccount.exchange=="MERCADO_BITCOIN",ExchangeAccount.mode=="LIVE"))
    if account: account.encrypted_credentials=encrypt_secret(credentials)
    else: account=ExchangeAccount(user_id=user.id,exchange="MERCADO_BITCOIN",mode="LIVE",encrypted_credentials=encrypt_secret(credentials)); db.add(account); await db.flush()
    db.add(AuditLog(user_id=user.id,event="exchange_connected",entity_id=str(account.id),details={"exchange":"MERCADO_BITCOIN","environment":"LIVE","account_type":validation["account_type"],"currency":validation["currency"]}))
    await db.commit()
    return {"id":str(account.id),"exchange":"MERCADO_BITCOIN","environment":"LIVE","connected":True,"account_name":validation["account_name"],"currency":validation["currency"],"brl_available":str(validation["brl_available"]),"validated_read_only":True}

@exchange_accounts.post("/mercado-bitcoin/preflight/{bot_id}")
async def mercado_bitcoin_preflight(bot_id:UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    config=await db.scalar(select(BotConfig).where(BotConfig.bot_id==bot.id))
    account=await db.scalar(select(ExchangeAccount).where(ExchangeAccount.user_id==user.id,ExchangeAccount.exchange=="MERCADO_BITCOIN",ExchangeAccount.mode=="LIVE"))
    if not config: raise HTTPException(409,"Configuração do bot não encontrada")
    if not account or not account.encrypted_credentials: raise HTTPException(404,"Conta Mercado Bitcoin não conectada")
    try:
        credentials=json.loads(decrypt_secret(account.encrypted_credentials))
        adapter=MercadoBitcoinAdapter(credentials["client_id"],credentials["client_secret"],settings.mercado_bitcoin_base_url)
        validation=await adapter.validate_account()
        account_id=validation["account_id"]
        tickers=await adapter.get_tickers(config.symbols)
        rules=await adapter.get_symbol_rules(config.symbols)
        open_orders=await adapter.get_open_orders(account_id)
        fees=[]
        for symbol in config.symbols:
            fees.append(await adapter.get_trading_fees(account_id,symbol))
    except MercadoBitcoinError as exc: raise HTTPException(422,str(exc)) from exc
    except Exception as exc: raise HTTPException(502,"Não foi possível concluir o diagnóstico seguro do Mercado Bitcoin") from exc
    brl_available=Decimal(validation["brl_available"])
    rules_by_symbol={row["symbol"].replace("-","/"):row for row in rules}
    fees_by_symbol={symbol:fee for symbol,fee in zip(config.symbols,fees,strict=True)}
    ticker_by_symbol={row["symbol"].replace("-","/"):row for row in tickers}
    market_rows=[]
    for symbol in config.symbols:
        rule=rules_by_symbol[symbol]; fee=fees_by_symbol[symbol]; ticker=ticker_by_symbol[symbol]
        bid=Decimal(ticker["bid"]); ask=Decimal(ticker["ask"]); midpoint=(bid+ask)/Decimal("2")
        spread_pct=((ask-bid)/midpoint*Decimal("100")) if midpoint else Decimal("0")
        market_rows.append({
            "symbol":symbol,
            "last":str(ticker["last"]),
            "spread_pct":str(spread_pct.quantize(Decimal("0.0001"))),
            "min_cost":str(rule["min-cost"]),
            "min_volume":str(rule["min-volume"]),
            "round_lot":str(rule["round-lot"]),
            "maker_fee":str(fee["maker_fee"]),
            "taker_fee":str(fee["taker_fee"]),
            "traded":bool(rule.get("exchange-traded")),
        })
    live_capital=Decimal(str((config.advanced or {}).get("real_capital_brl",config.capital)))
    checks={
        "credentials_valid":True,
        "account_readable":True,
        "markets_available":all(row["traded"] for row in market_rows),
        "rules_loaded":len(market_rows)==len(config.symbols),
        "fees_loaded":len(fees)==len(config.symbols),
        "balance_covers_capital":brl_available>=live_capital,
        "no_open_orders":len(open_orders)==0,
        "paper_bot_stopped":bot.status in {BotStatus.STOPPED,BotStatus.PAUSED},
        "server_live_enabled":settings.real_trading_enabled,
        "live_executor_enabled":False,
    }
    blockers=[]
    if not checks["balance_covers_capital"]: blockers.append("O saldo BRL disponível é menor que o capital configurado no bot.")
    if not checks["no_open_orders"]: blockers.append("Existem ordens abertas no Mercado Bitcoin; elas precisam ser reconciliadas antes de qualquer ativação.")
    if not checks["paper_bot_stopped"]: blockers.append("Pause ou pare o bot Paper antes de preparar o modo real.")
    blockers.append("O executor real permanece desabilitado no servidor e nenhuma ordem foi enviada.")
    db.add(AuditLog(user_id=user.id,event="mercado_bitcoin_preflight",entity_id=str(account.id),details={"bot_id":str(bot.id),"symbols":config.symbols,"open_orders":len(open_orders),"passed":all(checks[key] for key in ("credentials_valid","account_readable","markets_available","rules_loaded","fees_loaded","balance_covers_capital","no_open_orders","paper_bot_stopped"))}))
    await db.commit()
    return {
        "mode":"READ_ONLY_PREFLIGHT",
        "executed_orders":0,
        "account":{"suffix":str(account_id)[-6:],"currency":validation.get("currency") or "BRL","available_brl":str(brl_available)},
        "configured_capital":str(live_capital),
        "open_orders":len(open_orders),
        "checks":checks,
        "markets":market_rows,
        "blockers":blockers,
        "ready_for_live":False,
    }

@bots.put("/{bot_id}/real-capital")
async def set_real_capital(bot_id:UUID,body:RealCapitalIn,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    config=await db.scalar(select(BotConfig).where(BotConfig.bot_id==bot.id))
    if not config: raise HTTPException(409,"Configuração do bot não encontrada")
    amount=body.amount_brl.quantize(Decimal("0.01"))
    advanced=dict(config.advanced or {})
    previous=str(advanced.get("real_capital_brl",config.capital))
    advanced["real_capital_brl"]=str(amount)
    config.advanced=advanced
    db.add(AuditLog(user_id=user.id,event="real_capital_limit_changed",entity_id=str(bot.id),details={"previous_brl":previous,"new_brl":str(amount),"moves_money":False}))
    await db.commit()
    return {"amount_brl":str(amount),"moves_money":False,"real_trading_enabled":False}

@bots.get("/{bot_id}/real-readiness")
async def real_readiness(bot_id:UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    bot=await owned_bot(bot_id,user,db)
    accounts=list((await db.scalars(select(ExchangeAccount).where(ExchangeAccount.user_id==user.id,ExchangeAccount.exchange=="BINANCE"))).all())
    mercado_bitcoin=await db.scalar(select(ExchangeAccount).where(ExchangeAccount.user_id==user.id,ExchangeAccount.exchange=="MERCADO_BITCOIN",ExchangeAccount.mode=="LIVE"))
    checks={"bot_stopped":bot.status in {BotStatus.STOPPED,BotStatus.PAUSED},"encryption_configured":bool(settings.encryption_master_key),"testnet_connected":any(a.mode=="TESTNET" and a.encrypted_credentials for a in accounts),"live_connected":any(a.mode=="LIVE" and a.encrypted_credentials for a in accounts),"mercado_bitcoin_connected":bool(mercado_bitcoin and mercado_bitcoin.encrypted_credentials),"server_live_enabled":settings.real_trading_enabled,"live_executor_enabled":False}
    return {"ready_for_testnet":all(checks[key] for key in ("bot_stopped","encryption_configured","testnet_connected")),"ready_for_live":all(checks[key] for key in ("bot_stopped","encryption_configured","mercado_bitcoin_connected","server_live_enabled","live_executor_enabled")),"checks":checks,"next_step":"Conecte o Mercado Bitcoin para validar conta, saldo e mercados BRL sem criar ordens."}

@router.get("/market/ticker/{symbol:path}")
async def ticker(symbol:str,user:User=Depends(current_user)):
    try:
        row=(await market_data.get_tickers([symbol.upper()]))[0]
    except MercadoBitcoinError as exc:
        raise HTTPException(503,"Cotação do Mercado Bitcoin temporariamente indisponível") from exc
    return {"symbol":row["symbol"].replace("-","/"),"timestamp":datetime.now(timezone.utc),"bid":str(row["bid"]),"ask":str(row["ask"]),"last":str(row["last"]),"volume":str(row["volume"]),"source":"Mercado Bitcoin"}
@router.get("/notifications")
async def notifications(user:User=Depends(current_user),db:AsyncSession=Depends(get_db)): return [{"id":str(n.id),"event":n.event,"message":n.message,"level":n.level,"read":n.read,"created_at":n.created_at} for n in (await db.scalars(select(Notification).where(Notification.user_id==user.id).order_by(Notification.created_at.desc()).limit(50))).all()]
@router.get("/strategies")
async def strategies(user:User=Depends(current_user)): return [{"name":"Adaptive Mean Reversion","version":"1.0","indicators":["EMA","RSI","ATR","volume","spread"]}]
@router.get("/exchanges")
async def exchanges(user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    connected=list((await db.scalars(select(ExchangeAccount).where(ExchangeAccount.user_id==user.id))).all())
    return [{"name":"Mock/Paper","mode":"PAPER","connected":True,"withdrawals":False},{"name":"Mercado Bitcoin","mode":"LIVE","connected":any(a.exchange=="MERCADO_BITCOIN" and a.mode=="LIVE" for a in connected),"withdrawals":False},{"name":"Binance Spot Testnet","mode":"TESTNET","connected":any(a.exchange=="BINANCE" and a.mode=="TESTNET" for a in connected),"withdrawals":False},{"name":"Binance Spot","mode":"LIVE","connected":any(a.exchange=="BINANCE" and a.mode=="LIVE" for a in connected),"withdrawals":False}]
@router.websocket("/ws/{bot_id}")
async def websocket(websocket:WebSocket,bot_id:UUID):
    token=websocket.cookies.get("access_token")
    if not token:
        await websocket.close(code=4401); return
    try: claims=decode_access_token(token)
    except Exception:
        await websocket.close(code=4401); return
    async with SessionLocal() as db:
        session=await db.scalar(select(DeviceSession).where(DeviceSession.id==claims.session_id,DeviceSession.user_id==claims.user_id))
        bot=await db.scalar(select(Bot).where(Bot.id==bot_id,Bot.user_id==claims.user_id)) if session and not session.revoked_at and not is_expired(session.expires_at) else None
    if not bot:
        await websocket.close(code=4404); return
    await websocket.accept()
    try:
        while True:
            async with SessionLocal() as db:
                session=await db.scalar(select(DeviceSession).where(DeviceSession.id==claims.session_id,DeviceSession.user_id==claims.user_id))
                current=await db.scalar(select(Bot).where(Bot.id==bot_id,Bot.user_id==claims.user_id)) if session and not session.revoked_at and not is_expired(session.expires_at) else None
            if not current:
                await websocket.close(code=4404); return
            await websocket.send_json({"type":"bot_state","bot_id":str(bot_id),"status":current.status.value,"mode":current.mode,"reconciled":current.reconciled,"timestamp":datetime.now(timezone.utc).isoformat()})
            await asyncio.sleep(3)
    except WebSocketDisconnect: pass

router.include_router(auth); router.include_router(bots); router.include_router(backtests); router.include_router(exchange_accounts)
