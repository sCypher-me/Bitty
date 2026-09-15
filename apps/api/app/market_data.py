import asyncio
import time
from datetime import datetime, timezone
from decimal import Decimal as D

from app.config import settings
from app.mercado_bitcoin import MercadoBitcoinAdapter
from app.trading import MarketTick


class MercadoBitcoinMarketData:
    """Public BRL market data with short caches and exchange-rate-limit protection."""

    def __init__(self):
        self.adapter = MercadoBitcoinAdapter("", "", settings.mercado_bitcoin_base_url)
        self._ticker_cache: dict[tuple[str, ...], tuple[float, list[dict]]] = {}
        self._candle_cache: dict[str, tuple[float, list[dict]]] = {}
        self._candle_lock = asyncio.Lock()
        self._last_candle_request = 0.0

    async def get_tickers(self, symbols: list[str]) -> list[dict]:
        key = tuple(sorted(symbol.upper() for symbol in symbols))
        cached = self._ticker_cache.get(key)
        if cached and time.monotonic() - cached[0] < 10:
            return cached[1]
        rows = await self.adapter.get_tickers(list(key))
        self._ticker_cache[key] = (time.monotonic(), rows)
        return rows

    async def get_candles(self, symbol: str) -> list[dict]:
        symbol = symbol.upper()
        cached = self._candle_cache.get(symbol)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        async with self._candle_lock:
            cached = self._candle_cache.get(symbol)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1]
            wait_for = 1.05 - (time.monotonic() - self._last_candle_request)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            candles = await self.adapter.get_candles(symbol)
            self._last_candle_request = time.monotonic()
            self._candle_cache[symbol] = (self._last_candle_request, candles)
            return candles

    @staticmethod
    def tick(row: dict, candles: list[dict]) -> MarketTick:
        closes = [D(str(item["close"])) for item in candles[-20:]]
        changes = [abs(closes[index] / closes[index - 1] - D("1")) for index in range(1, len(closes)) if closes[index - 1] > 0]
        volatility = sum(changes, D("0")) / D(len(changes)) if changes else D("0")
        return MarketTick(
            symbol=row["symbol"].replace("-", "/"),
            timestamp=datetime.now(timezone.utc),
            bid=D(row["bid"]),
            ask=D(row["ask"]),
            last=D(row["last"]),
            volume=D(row["volume"]),
            volatility=volatility,
        )


market_data = MercadoBitcoinMarketData()
