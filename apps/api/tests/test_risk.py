from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pytest
from app.trading import MarketTick,RiskConfig,RiskManager,RiskState,SignalAction,TradingSignal

def objects(**state):
    tick=MarketTick("BTC/USDT",datetime.now(timezone.utc),D("99.9"),D("100.1"),D("100"),D("100000"),D("0.02")); signal=TradingSignal("BTC/USDT",tick.timestamp,SignalAction.BUY,D("0.8"),D("100"),"test"); config=RiskConfig(capital=D("10000")); base=dict(cash=D("10000"),equity=D("10000"),peak_equity=D("10000")); base.update(state); return signal,tick,config,RiskState(**base)
def decision(**state): s,t,c,st=objects(**state); return RiskManager().evaluate(s,t,D("100"),c,st)
def test_approves_safe_order(): assert decision().approved
def test_does_not_spend_reserve(): assert decision(cash=D("3050")).reason_code=="RESERVE_LIMIT"
def test_capital_and_order_limit():
    s,t,c,st=objects(); assert RiskManager().evaluate(s,t,D("501"),c,st).reason_code=="MAX_ORDER"
def test_asset_limit(): assert decision(asset_exposure=D("1450")).reason_code=="MAX_ASSET_EXPOSURE"
def test_paused_bot(): assert decision(bot_active=False).reason_code=="BOT_NOT_ACTIVE"
def test_stale_data():
    s,t,c,st=objects(); t=MarketTick(t.symbol,datetime.now(timezone.utc)-timedelta(minutes=5),t.bid,t.ask,t.last,t.volume,t.volatility); assert RiskManager().evaluate(s,t,D("100"),c,st).reason_code=="STALE_DATA"
def test_daily_loss(): assert decision(daily_pnl=D("-301")).reason_code=="DAILY_LOSS_LIMIT"
def test_drawdown(): assert decision(equity=D("8900")).reason_code=="DRAWDOWN_LIMIT"
def test_no_balance():
    s,t,c,st=objects(cash=D("50")); c.reserve_pct=D("0"); assert RiskManager().evaluate(s,t,D("100"),c,st).reason_code=="INSUFFICIENT_BALANCE"
def test_minimum_notional():
    s,t,c,st=objects(); assert RiskManager().evaluate(s,t,D("9"),c,st).reason_code=="MINIMUM_NOTIONAL"
def test_spread():
    s,t,c,st=objects(); t=MarketTick(t.symbol,t.timestamp,D("98"),D("102"),D("100"),t.volume,t.volatility); assert RiskManager().evaluate(s,t,D("100"),c,st).reason_code=="SPREAD_TOO_HIGH"
def test_total_exposure(): assert decision(exposure=D("5950")).reason_code=="MAX_TOTAL_EXPOSURE"
def test_circuit_breaker(): assert decision(circuit_breaker=True).reason_code=="CIRCUIT_BREAKER"
def test_sell_is_allowed_to_reduce_exposure():
    s,t,c,st=objects(cash=D("0"),exposure=D("6000"),asset_exposure=D("1500")); s=TradingSignal(s.symbol,s.timestamp,SignalAction.SELL,s.confidence,s.suggested_amount,s.reason); result=RiskManager().evaluate(s,t,D("500"),c,st); assert result.approved; assert result.reason_code=="APPROVED_RISK_REDUCTION"
