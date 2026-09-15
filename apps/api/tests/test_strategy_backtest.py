from datetime import datetime,timezone
from decimal import Decimal as D
from app.backtesting import Backtester
from app.trading import MarketTick,MeanReversionStrategy,SignalAction
def candles(n=40):
    data=[]
    for i in range(n):
        close=D("100") if i<30 else D("90")+D(i-30)
        data.append({"timestamp":datetime(2025,1,1,tzinfo=timezone.utc).isoformat(),"open":str(close),"high":str(close+D("2")),"low":str(close-D("2")),"close":str(close),"volume":"1000"})
    return data
def test_strategy_only_produces_signal():
    data=candles(); tick=MarketTick("BTC/USDT",datetime.now(timezone.utc),D("98.9"),D("99.1"),D("99"),D("1000"),D("0.02")); result=MeanReversionStrategy().evaluate("BTC/USDT",data,tick,D("100")); assert result.action in SignalAction; assert result.strategy_version=="1.0"; assert "ema20" in result.indicators
def test_backtest_metrics_and_no_lookahead():
    result=Backtester().run("BTC/USDT",candles(),D("10000")); required={"initial_capital","final_capital","return_pct","net_pnl","fees","trades","win_rate","average_win","average_loss","profit_factor","max_drawdown_pct","best_trade","worst_trade","buy_hold_pct"}; assert required<=result.metrics.keys(); assert len(result.equity_curve)==20
