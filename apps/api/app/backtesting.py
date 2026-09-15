from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal as D
from app.trading import MarketTick,MeanReversionStrategy,PortfolioManager,SignalAction

@dataclass
class BacktestResult: metrics:dict; trades:list[dict]; equity_curve:list[dict]
class Backtester:
    def __init__(self,fee_rate:D=D("0.001"),slippage:D=D("0.0005")): self.fee_rate=fee_rate; self.slippage=slippage; self.strategy=MeanReversionStrategy()
    def run(self,symbol:str,candles:list[dict],initial_capital:D)->BacktestResult:
        portfolio=PortfolioManager(initial_capital); trades=[]; curve=[]; pnls=[]
        for i in range(20,len(candles)):
            c=candles[i]; price=D(str(c["close"])); ts=datetime.fromisoformat(c["timestamp"].replace("Z","+00:00")) if isinstance(c.get("timestamp"),str) else c.get("timestamp",datetime.now(timezone.utc)); tick=MarketTick(symbol,ts,price*(D("1")-D("0.0005")),price*(D("1")+D("0.0005")),price,D(str(c["volume"])),D("0.02")); amount=min(initial_capital*D("0.05"),portfolio.cash-initial_capital*D("0.30")); signal=self.strategy.evaluate(symbol,candles[:i+1],tick,max(D("0"),amount)); p=portfolio.positions.get(symbol)
            if signal.action==SignalAction.BUY and amount>=D("10") and (not p or p.quantity==0):
                fill=price*(D("1")+self.slippage); qty=amount/fill; fee=qty*fill*self.fee_rate; portfolio.buy(symbol,qty,fill,fee); trades.append({"side":"BUY","price":str(fill),"quantity":str(qty),"fee":str(fee),"timestamp":ts.isoformat(),"pnl":"0"})
            elif signal.action==SignalAction.SELL and p and p.quantity>0:
                fill=price*(D("1")-self.slippage); qty=p.quantity; fee=qty*fill*self.fee_rate; pnl=portfolio.sell(symbol,qty,fill,fee); pnls.append(pnl); trades.append({"side":"SELL","price":str(fill),"quantity":str(qty),"fee":str(fee),"timestamp":ts.isoformat(),"pnl":str(pnl)})
            equity=portfolio.equity({symbol:price}); curve.append({"timestamp":ts.isoformat(),"equity":str(equity)})
        final=portfolio.equity({symbol:D(str(candles[-1]["close"]))}); wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<0]; fees=sum((D(t["fee"]) for t in trades),D("0")); gross_profit=sum(wins,D("0")); gross_loss=-sum(losses,D("0")); best=max(pnls,default=D("0")); worst=min(pnls,default=D("0")); buy_hold=(D(str(candles[-1]["close"]))/D(str(candles[0]["close"]))-1)*D("100"); max_dd=D("0"); peak=initial_capital
        for point in curve: val=D(point["equity"]); peak=max(peak,val); max_dd=max(max_dd,(peak-val)/peak if peak else D("0"))
        metrics={"initial_capital":str(initial_capital),"final_capital":str(final),"return_pct":str((final/initial_capital-1)*D("100")),"net_pnl":str(final-initial_capital),"fees":str(fees),"trades":len(trades),"win_rate":str(D(len(wins))/D(len(pnls))*D("100") if pnls else D("0")),"average_win":str(gross_profit/D(len(wins)) if wins else D("0")),"average_loss":str(-gross_loss/D(len(losses)) if losses else D("0")),"profit_factor":str(gross_profit/gross_loss if gross_loss else D("0")),"max_drawdown_pct":str(max_dd*D("100")),"best_trade":str(best),"worst_trade":str(worst),"buy_hold_pct":str(buy_hold)}
        return BacktestResult(metrics,trades,curve)
