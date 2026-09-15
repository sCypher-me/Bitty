import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.market_data import market_data
from app.mercado_bitcoin import MercadoBitcoinError
from app.models import Bot,BotConfig,BotStatus,Notification,Order,OrderStatus,Position,PortfolioSnapshot,RiskDecision as RiskDecisionModel,Side,Signal as SignalModel
from app.trading import MeanReversionStrategy,OrderManager,PaperExecutionAdapter,RiskConfig,RiskManager,RiskState,SignalAction,deterministic_order_id

_bot_locks:dict[str,asyncio.Lock]={}
def bot_cycle_lock(bot_id)->asyncio.Lock: return _bot_locks.setdefault(str(bot_id),asyncio.Lock())

async def reconcile_bot(db:AsyncSession,bot:Bot)->bool:
    unresolved=list((await db.scalars(select(Order).where(Order.bot_id==bot.id,Order.status.in_([OrderStatus.SUBMITTING,OrderStatus.SUBMITTED,OrderStatus.PARTIALLY_FILLED])))).all())
    if unresolved:
        bot.status=BotStatus.PAUSED; bot.reconciled=False
        return False
    bot.reconciled=True
    if bot.status==BotStatus.STARTING: bot.status=BotStatus.ACTIVE
    return True

async def execute_bot_cycle(db:AsyncSession,bot:Bot)->str:
    if bot.mode!="PAPER": return "NOT_PAPER"
    if bot.status not in {BotStatus.ACTIVE,BotStatus.RECONNECTING} or not bot.reconciled: return "NOT_ACTIVE"
    config=await db.scalar(select(BotConfig).where(BotConfig.bot_id==bot.id))
    positions=list((await db.scalars(select(Position).where(Position.bot_id==bot.id))).all()); invested=sum((p.quantity*p.average_cost for p in positions),D("0")); realized=sum((p.realized_pnl for p in positions),D("0")); cash=D(config.capital)+realized-invested; equity=cash+invested; peak=max(D(config.capital),equity); state=RiskState(cash=cash,exposure=invested,daily_pnl=realized,equity=equity,peak_equity=peak,positions=sum(1 for p in positions if p.quantity>0),bot_active=True)
    strategy=MeanReversionStrategy(); risk=RiskManager()
    try:
        ticker_rows=await market_data.get_tickers(config.symbols)
        tickers={row["symbol"].replace("-","/"):row for row in ticker_rows}
    except Exception:
        bot.status=BotStatus.RECONNECTING
        db.add(Notification(user_id=bot.user_id,level="WARNING",event="market_data_unavailable",message="Cotações do Mercado Bitcoin indisponíveis; ciclo ignorado sem enviar ordens."))
        return "MARKET_UNAVAILABLE"
    if bot.status==BotStatus.RECONNECTING: bot.status=BotStatus.ACTIVE
    for symbol in config.symbols:
        await db.refresh(bot)
        if bot.status not in {BotStatus.ACTIVE,BotStatus.RECONNECTING} or not bot.reconciled:
            return "STOPPED_DURING_CYCLE"
        position=next((p for p in positions if p.symbol==symbol),None)
        try:
            candles=await market_data.get_candles(symbol)
            tick=market_data.tick(tickers[symbol],candles)
        except (MercadoBitcoinError,KeyError,ValueError):
            continue
        requested=D(config.capital)*D(config.max_trade_pct); signal=strategy.evaluate(symbol,candles,tick,requested)
        signal_row=SignalModel(bot_id=bot.id,symbol=symbol,timestamp=signal.timestamp,action=signal.action.value,confidence=signal.confidence,suggested_amount=signal.suggested_amount,reason=signal.reason,strategy_name=signal.strategy_name,strategy_version=signal.strategy_version,indicators=signal.indicators); db.add(signal_row); await db.flush()
        if signal.action==SignalAction.HOLD: continue
        if signal.action==SignalAction.SELL:
            if not position or position.quantity<=0: continue
            requested=position.quantity*tick.bid
        recent_buy=await db.scalar(select(Order.id).where(Order.bot_id==bot.id,Order.symbol==symbol,Order.side==Side.BUY,Order.status==OrderStatus.FILLED,Order.created_at>=datetime.now(timezone.utc)-timedelta(minutes=15)).limit(1))
        state.cooldown_ok=not bool(recent_buy); state.asset_exposure=position.quantity*position.average_cost if position else D("0"); state.liquidity=tick.volume*tick.last
        rc=RiskConfig(capital=D(config.capital),reserve_pct=D(config.reserve_pct),max_trade_pct=D(config.max_trade_pct),max_asset_pct=D(config.max_asset_pct),max_exposure_pct=D(config.max_exposure_pct),daily_loss_pct=D(config.daily_loss_pct),max_drawdown_pct=D(config.max_drawdown_pct),minimum_notional=D("1")); decision=risk.evaluate(signal,tick,requested,rc,state)
        db.add(RiskDecisionModel(bot_id=bot.id,signal_id=signal_row.id,approved=decision.approved,reason_code=decision.reason_code,details={"requested":str(requested)}))
        if not decision.approved:
            continue
        await db.refresh(bot)
        if bot.status not in {BotStatus.ACTIVE,BotStatus.RECONNECTING} or not bot.reconciled:
            return "STOPPED_BEFORE_ORDER"
        client_id=deterministic_order_id(str(bot.id),signal); side=signal.action.value; price=tick.ask if side=="BUY" else tick.bid; order=Order(user_id=bot.user_id,bot_id=bot.id,client_order_id=client_id,symbol=symbol,side=Side(side),status=OrderStatus.SUBMITTING,quantity=D("0")); db.add(order); await db.flush()
        step_size=D("0.000001") if symbol.startswith("SOL") else D("0.00000001")
        result=await OrderManager(PaperExecutionAdapter()).execute(client_id,symbol,side,requested,price,step_size); order.status=OrderStatus.FILLED; order.quantity=result["quantity"]; order.filled_quantity=result["filled_quantity"]; order.average_price=result["average_price"]; order.fees=result["fee"]
        if not position:
            position=Position(user_id=bot.user_id,bot_id=bot.id,symbol=symbol,quantity=D("0"),average_cost=D("0"),realized_pnl=D("0"),fees=D("0")); db.add(position); positions.append(position)
        if side=="BUY":
            old_cost=position.quantity*position.average_cost; position.quantity+=order.filled_quantity; position.average_cost=(old_cost+order.filled_quantity*order.average_price+order.fees)/position.quantity; position.fees+=order.fees
        else:
            pnl=order.filled_quantity*order.average_price-order.filled_quantity*position.average_cost-order.fees; position.quantity-=order.filled_quantity; position.realized_pnl+=pnl; position.fees+=order.fees
            if position.quantity==0: position.average_cost=D("0")
        await db.flush(); invested=sum((p.quantity*(p.average_cost or D("0")) for p in positions),D("0")); realized=sum((p.realized_pnl for p in positions),D("0")); cash=D(config.capital)+realized-invested; equity=cash+sum((p.quantity*(tick.last if p.symbol==symbol else p.average_cost) for p in positions),D("0")); db.add(PortfolioSnapshot(bot_id=bot.id,cash=cash,invested=invested,equity=equity,drawdown=max(D("0"),(D(config.capital)-equity)/D(config.capital))))
    prices={symbol:D(row["last"]) for symbol,row in tickers.items()}
    cost_basis=sum((p.quantity*(p.average_cost or D("0")) for p in positions),D("0")); realized=sum((p.realized_pnl for p in positions),D("0")); cash=D(config.capital)+realized-cost_basis; market_value=sum((p.quantity*prices.get(p.symbol,p.average_cost) for p in positions),D("0")); equity=cash+market_value
    db.add(PortfolioSnapshot(bot_id=bot.id,cash=cash,invested=market_value,equity=equity,drawdown=max(D("0"),(D(config.capital)-equity)/D(config.capital))))
    return "OK"
