from decimal import Decimal as D
import pytest
from app.exchange import MockExchangeAdapter
from app.trading import OrderManager,PaperExecutionAdapter,PortfolioManager

@pytest.mark.asyncio
async def test_idempotency_does_not_duplicate():
    adapter=PaperExecutionAdapter(); manager=OrderManager(adapter); first=await manager.execute("same-id","BTC/USDT","BUY",D("100"),D("1000")); second=await manager.execute("same-id","BTC/USDT","BUY",D("100"),D("1000")); assert first is second; assert len(adapter.orders)==1
@pytest.mark.asyncio
async def test_partial_fill():
    result=await OrderManager(MockExchangeAdapter("partial_fill")).execute("x","BTC/USDT","BUY",D("100"),D("1000")); assert result["status"]=="PARTIALLY_FILLED"; assert result["filled_quantity"]==result["quantity"]/2
def test_weighted_average_cost_includes_fees():
    p=PortfolioManager(D("1000")); p.buy("BTC",D("1"),D("100"),D("1")); p.buy("BTC",D("1"),D("120"),D("1")); assert p.positions["BTC"].average_cost==D("111"); assert p.cash==D("778")
def test_realized_pnl_includes_exit_fee():
    p=PortfolioManager(D("1000")); p.buy("BTC",D("1"),D("100"),D("1")); pnl=p.sell("BTC",D("1"),D("120"),D("1")); assert pnl==D("18"); assert p.cash==D("1018")
def test_cannot_sell_more_than_position():
    p=PortfolioManager(D("1000")); p.buy("BTC",D("1"),D("100"),D("0"));
    with pytest.raises(ValueError): p.sell("BTC",D("2"),D("100"),D("0"))
