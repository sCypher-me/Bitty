from decimal import Decimal
from app.trading import PaperExecutionAdapter
class MockExchangeAdapter(PaperExecutionAdapter):
    def __init__(self,scenario="success",**kwargs): super().__init__(**kwargs); self.scenario=scenario
    async def get_balance(self): return {"BRL":Decimal("10000")}
    async def get_ticker(self,symbol): return {"symbol":symbol,"bid":Decimal("999.5"),"ask":Decimal("1000.5"),"last":Decimal("1000")}
    async def get_candles(self,*_): return []
    async def get_order_book(self,*_): return {"bids":[],"asks":[]}
    async def get_open_orders(self): return []
    async def get_order(self,client_order_id): return self.orders.get(client_order_id)
    async def cancel_order(self,client_order_id): self.orders[client_order_id]["status"]="CANCELED"; return self.orders[client_order_id]
    async def get_fees(self): return {"maker":Decimal("0.001"),"taker":Decimal("0.001")}
    async def get_exchange_info(self): return {"spot_only":True,"withdrawals":False}
    async def create_order(self,*args,**kwargs):
        if self.scenario=="timeout": raise TimeoutError("simulated timeout")
        if self.scenario in {"rate_limit","rejection","disconnect","invalid_price"}: raise RuntimeError(self.scenario)
        result=await super().create_order(*args,**kwargs)
        if self.scenario=="partial_fill": result={**result,"status":"PARTIALLY_FILLED","filled_quantity":result["quantity"]/2}
        return result
