# Motor de trading

A estratégia adaptativa combina EMA20, RSI14, ATR14, volume e spread e produz somente `BUY`, `SELL` ou `HOLD`. Toda intenção passa pelo Risk Manager: status, circuit breaker, freshness, spread, volatilidade, liquidez, cooldown, entradas, perdas, drawdown, posições, notional, limites por ordem/ativo/exposição, reserva e saldo.

`client_order_id` determinístico e unicidade no banco evitam duplicação. Paper Execution inclui taxa e slippage. Portfólio usa `Decimal`, custo médio com taxa, PNL realizado e drawdown. Incerteza ou divergência pausa o bot. Backtest processa candles em ordem e entrega à estratégia somente o prefixo disponível, evitando lookahead.
