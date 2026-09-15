from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Protocol
import hashlib

D=Decimal
class SignalAction(str,Enum): BUY="BUY"; SELL="SELL"; HOLD="HOLD"
@dataclass(frozen=True)
class MarketTick:
    symbol:str; timestamp:datetime; bid:D; ask:D; last:D; volume:D; volatility:D
    @property
    def spread_pct(self): return (self.ask-self.bid)/self.last if self.last else D("1")
@dataclass(frozen=True)
class TradingSignal:
    symbol:str; timestamp:datetime; action:SignalAction; confidence:D; suggested_amount:D; reason:str; strategy_name:str="Adaptive Mean Reversion"; strategy_version:str="1.0"; indicators:dict=field(default_factory=dict)
@dataclass
class RiskConfig:
    capital:D; reserve_pct:D=D("0.30"); max_trade_pct:D=D("0.05"); max_asset_pct:D=D("0.15"); max_exposure_pct:D=D("0.60"); daily_loss_pct:D=D("0.03"); max_drawdown_pct:D=D("0.10"); max_spread_pct:D=D("0.005"); max_volatility:D=D("0.12"); max_slippage_pct:D=D("0.005"); max_positions:int=6; minimum_notional:D=D("10"); freshness_seconds:int=120
@dataclass
class RiskState:
    cash:D; exposure:D=D("0"); asset_exposure:D=D("0"); daily_pnl:D=D("0"); equity:D=D("0"); peak_equity:D=D("0"); positions:int=0; bot_active:bool=True; circuit_breaker:bool=False; cooldown_ok:bool=True; entries_for_asset:int=0; liquidity:D=D("100000")
@dataclass(frozen=True)
class RiskDecision:
    approved:bool; reason_code:str; approved_notional:D=D("0")

class RiskManager:
    def evaluate(self, signal:TradingSignal, tick:MarketTick, requested:D, config:RiskConfig, state:RiskState)->RiskDecision:
        now=datetime.now(timezone.utc)
        safety_checks=[
            (state.bot_active,"BOT_NOT_ACTIVE"),(not state.circuit_breaker,"CIRCUIT_BREAKER"),
            ((now-tick.timestamp).total_seconds()<=config.freshness_seconds,"STALE_DATA"),
            (tick.ask>0 and tick.bid>0,"INVALID_PRICE"),(tick.spread_pct<=config.max_spread_pct,"SPREAD_TOO_HIGH"),
            (tick.volatility<=config.max_volatility,"VOLATILITY_TOO_HIGH"),(state.liquidity>=requested*D("5"),"INSUFFICIENT_LIQUIDITY"),
        ]
        for ok,code in safety_checks:
            if not ok: return RiskDecision(False,code)
        if signal.action==SignalAction.SELL:
            return RiskDecision(True,"APPROVED_RISK_REDUCTION",requested)
        buy_checks=[
            (state.cooldown_ok,"COOLDOWN"),(state.entries_for_asset<3,"MAX_ENTRIES"),
            (state.daily_pnl>-(config.capital*config.daily_loss_pct),"DAILY_LOSS_LIMIT"),
            (not state.peak_equity or (state.peak_equity-state.equity)/state.peak_equity<config.max_drawdown_pct,"DRAWDOWN_LIMIT"),
            (state.positions<config.max_positions,"MAX_POSITIONS"),(requested>=config.minimum_notional,"MINIMUM_NOTIONAL"),
            (requested<=config.capital*config.max_trade_pct,"MAX_ORDER"),
            (state.asset_exposure+requested<=config.capital*config.max_asset_pct,"MAX_ASSET_EXPOSURE"),
            (state.exposure+requested<=config.capital*config.max_exposure_pct,"MAX_TOTAL_EXPOSURE"),
            (requested<=state.cash,"INSUFFICIENT_BALANCE"),
            (state.cash-requested>=config.capital*config.reserve_pct,"RESERVE_LIMIT")]
        for ok,code in buy_checks:
            if not ok: return RiskDecision(False,code)
        return RiskDecision(True,"APPROVED",requested)

def ema(values:list[D], period:int)->D:
    k=D("2")/D(period+1); result=values[0]
    for value in values[1:]: result=value*k+result*(D("1")-k)
    return result
def rsi(values:list[D],period:int=14)->D:
    diffs=[values[i]-values[i-1] for i in range(1,len(values))][-period:]
    gains=sum((x for x in diffs if x>0),D("0")); losses=-sum((x for x in diffs if x<0),D("0"))
    if losses==0: return D("100")
    return D("100")-(D("100")/(D("1")+gains/losses))
def atr(candles:list[dict],period:int=14)->D:
    trs=[]
    for i in range(max(1,len(candles)-period),len(candles)):
        h,l,pc=D(str(candles[i]["high"])),D(str(candles[i]["low"])),D(str(candles[i-1]["close"]))
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs,D("0"))/D(len(trs)) if trs else D("0")
class MeanReversionStrategy:
    def evaluate(self,symbol:str,candles:list[dict],tick:MarketTick,amount:D)->TradingSignal:
        if len(candles)<20: return TradingSignal(symbol,tick.timestamp,SignalAction.HOLD,D("0"),D("0"),"Dados insuficientes.")
        closes=[D(str(x["close"])) for x in candles]; volumes=[D(str(x["volume"])) for x in candles]
        e=ema(closes[-20:],20); r=rsi(closes); a=atr(candles); av=sum(volumes[-20:],D("0"))/D("20"); vol_ok=volumes[-1]>=av*D("0.7")
        indicators={"ema20":str(e),"rsi14":str(r),"atr14":str(a),"avg_volume":str(av),"spread_pct":str(tick.spread_pct)}
        if closes[-1]<e-a*D("0.5") and r<D("38") and vol_ok and tick.spread_pct<=D("0.005"):
            return TradingSignal(symbol,tick.timestamp,SignalAction.BUY,D("0.75"),amount,"Preço abaixo da EMA, RSI em sobrevenda, volume e spread aceitáveis.",indicators=indicators)
        if closes[-1]>e+a*D("0.5") or r>D("65"):
            return TradingSignal(symbol,tick.timestamp,SignalAction.SELL,D("0.70"),amount,"Preço revertido acima da média ou RSI elevado.",indicators=indicators)
        return TradingSignal(symbol,tick.timestamp,SignalAction.HOLD,D("0.5"),D("0"),"Sem confluência suficiente.",indicators=indicators)

@dataclass
class PositionState:
    quantity:D=D("0"); average_cost:D=D("0"); realized_pnl:D=D("0"); fees:D=D("0")
class PortfolioManager:
    def __init__(self,cash:D): self.cash=cash; self.initial_cash=cash; self.positions:dict[str,PositionState]={}; self.peak_equity=cash
    def buy(self,symbol:str,quantity:D,price:D,fee:D):
        cost=quantity*price; p=self.positions.setdefault(symbol,PositionState()); total=p.quantity*p.average_cost+cost+fee; p.quantity+=quantity; p.average_cost=total/p.quantity; p.fees+=fee; self.cash-=cost+fee
    def sell(self,symbol:str,quantity:D,price:D,fee:D):
        p=self.positions[symbol]
        if quantity>p.quantity: raise ValueError("insufficient position")
        proceeds=quantity*price; pnl=proceeds-quantity*p.average_cost-fee; p.quantity-=quantity; p.realized_pnl+=pnl; p.fees+=fee; self.cash+=proceeds-fee
        if p.quantity==0: p.average_cost=D("0")
        return pnl
    def equity(self,prices:dict[str,D])->D:
        value=self.cash+sum((p.quantity*prices.get(s,p.average_cost) for s,p in self.positions.items()),D("0")); self.peak_equity=max(self.peak_equity,value); return value
    def drawdown(self,prices:dict[str,D])->D:
        value=self.equity(prices); return (self.peak_equity-value)/self.peak_equity if self.peak_equity else D("0")

class ExecutionAdapter(Protocol):
    async def create_order(self,client_order_id:str,symbol:str,side:str,quantity:D,price:D)->dict: ...
class PaperExecutionAdapter:
    def __init__(self,fee_rate:D=D("0.001"),slippage:D=D("0.0005")): self.fee_rate=fee_rate; self.slippage=slippage; self.orders={}
    async def create_order(self,client_order_id:str,symbol:str,side:str,quantity:D,price:D)->dict:
        if client_order_id in self.orders: return self.orders[client_order_id]
        fill_price=price*(D("1")+self.slippage if side=="BUY" else D("1")-self.slippage); fill_price=fill_price.quantize(D("0.00000001")); fee=(quantity*fill_price*self.fee_rate).quantize(D("0.00000001")); order={"client_order_id":client_order_id,"symbol":symbol,"side":side,"status":"FILLED","quantity":quantity,"filled_quantity":quantity,"average_price":fill_price,"fee":fee}; self.orders[client_order_id]=order; return order
class OrderManager:
    def __init__(self,adapter:ExecutionAdapter): self.adapter=adapter; self.results={}
    async def execute(self,client_order_id:str,symbol:str,side:str,notional:D,price:D,step_size:D=D("0.000001"))->dict:
        if client_order_id in self.results: return self.results[client_order_id]
        if notional<=0 or price<=0: raise ValueError("invalid order")
        quantity=(notional/price).quantize(step_size,rounding=ROUND_DOWN)
        result=await self.adapter.create_order(client_order_id,symbol,side,quantity,price); self.results[client_order_id]=result; return result
def deterministic_order_id(bot_id:str,signal:TradingSignal)->str:
    raw=f"{bot_id}:{signal.symbol}:{signal.timestamp.isoformat()}:{signal.action.value}".encode(); return hashlib.sha256(raw).hexdigest()[:40]
