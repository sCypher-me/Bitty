import json
import logging
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_DOWN

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.market_data import market_data
from app.mercado_bitcoin import MercadoBitcoinAdapter, MercadoBitcoinAmbiguousOrderError
from app.models import Bot, BotConfig, BotStatus, ExchangeAccount, Notification, Order, OrderStatus, Position, RiskDecision, Side, Signal as SignalModel
from app.security import decrypt_secret
from app.trading import MeanReversionStrategy, SignalAction, deterministic_order_id

logger = logging.getLogger(__name__)
OPEN_ORDER_STATUSES = (OrderStatus.SUBMITTING, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)


def live_limits(config: BotConfig) -> dict[str, D | str | bool]:
    advanced = config.advanced or {}
    return {
        "armed": bool(advanced.get("live_armed")),
        "symbol": str(advanced.get("live_symbol", "BTC/BRL")),
        "capital": D(str(advanced.get("real_capital_brl", "100"))),
        "max_order": D(str(advanced.get("live_max_order_brl", "20"))),
        "reserve": D(str(advanced.get("live_reserve_brl", "50"))),
        "daily_loss": D(str(advanced.get("live_daily_loss_brl", "2"))),
        "max_spread": D(str(advanced.get("live_max_spread_pct", "0.002"))),
        "edge_buffer": D(str(advanced.get("live_edge_buffer_pct", "0.005"))),
        "stop_loss": D(str(advanced.get("live_stop_loss_pct", "0.02"))),
    }


def normalized_order_status(value: str) -> OrderStatus:
    return {
        "created": OrderStatus.SUBMITTED,
        "working": OrderStatus.SUBMITTED,
        "filled": OrderStatus.FILLED,
        "cancelled": OrderStatus.CANCELED,
    }.get(value.lower(), OrderStatus.SUBMITTED)


async def apply_exchange_order(db: AsyncSession, bot: Bot, order: Order, payload: dict) -> None:
    status = normalized_order_status(str(payload.get("status", "created")))
    filled = D(str(payload.get("filledQty", payload.get("filled_quantity", "0"))))
    average_price = D(str(payload.get("avgPrice", payload.get("average_price", "0"))))
    raw_fee = D(str(payload.get("fee", "0")))
    previous_filled = D(order.filled_quantity or 0)
    delta = max(D("0"), filled - previous_filled)
    order.exchange_order_id = str(payload.get("id") or payload.get("orderId") or order.exchange_order_id or "") or None
    order.status = status
    order.filled_quantity = filled
    order.average_price = average_price or order.average_price
    fee_brl = raw_fee * average_price if order.side == Side.BUY else raw_fee
    previous_fee = D(order.fees or 0)
    fee_delta_brl = max(D("0"), fee_brl - previous_fee)
    order.fees = fee_brl
    if delta <= 0 or average_price <= 0:
        return
    position = await db.scalar(select(Position).where(Position.bot_id == bot.id, Position.symbol == order.symbol))
    if not position:
        position = Position(user_id=bot.user_id, bot_id=bot.id, symbol=order.symbol, quantity=D("0"), average_cost=D("0"), realized_pnl=D("0"), fees=D("0"))
        db.add(position)
    if order.side == Side.BUY:
        # MB debits the buy fee from the acquired asset; convert it to BRL for cost reporting.
        base_fee_delta = fee_delta_brl / average_price
        net_delta = max(D("0"), delta - base_fee_delta)
        old_cost = position.quantity * position.average_cost
        position.quantity += net_delta
        if position.quantity > 0:
            position.average_cost = (old_cost + delta * average_price) / position.quantity
    else:
        sold = min(delta, position.quantity)
        position.realized_pnl += sold * average_price - fee_delta_brl - sold * position.average_cost
        position.quantity -= sold
        if position.quantity <= 0:
            position.quantity = D("0")
            position.average_cost = D("0")
    position.fees += fee_delta_brl


async def reconcile_live_orders(db: AsyncSession, bot: Bot, adapter: MercadoBitcoinAdapter, account_id: str) -> bool:
    orders = list((await db.scalars(select(Order).where(Order.bot_id == bot.id, Order.status.in_(OPEN_ORDER_STATUSES)))).all())
    for order in orders:
        payload = None
        if order.exchange_order_id:
            payload = await adapter.get_order(account_id, order.symbol, order.exchange_order_id)
        else:
            payload = await adapter.get_order_by_external_id(account_id, order.symbol, order.client_order_id)
        if payload is None:
            bot.status = BotStatus.PAUSED
            bot.reconciled = False
            db.add(Notification(user_id=bot.user_id, level="CRITICAL", event="live_order_missing", message="Uma ordem real não foi localizada no MB. O bot foi pausado para conferência manual."))
            return False
        await apply_exchange_order(db, bot, order, payload)
    await db.flush()
    still_open = await db.scalar(select(Order.id).where(Order.bot_id == bot.id, Order.status.in_(OPEN_ORDER_STATUSES)).limit(1))
    bot.reconciled = not bool(still_open)
    return bot.reconciled


async def execute_live_cycle(db: AsyncSession, bot: Bot) -> str:
    if not settings.real_trading_enabled or bot.mode != "LIVE" or bot.status not in {BotStatus.ACTIVE, BotStatus.RECONNECTING}:
        return "LIVE_DISABLED"
    config = await db.scalar(select(BotConfig).where(BotConfig.bot_id == bot.id))
    account = await db.scalar(select(ExchangeAccount).where(ExchangeAccount.user_id == bot.user_id, ExchangeAccount.exchange == "MERCADO_BITCOIN", ExchangeAccount.mode == "LIVE"))
    if not config or not account or not account.encrypted_credentials:
        bot.status = BotStatus.PAUSED
        return "ACCOUNT_UNAVAILABLE"
    limits = live_limits(config)
    if not limits["armed"]:
        bot.status = BotStatus.PAUSED
        return "NOT_ARMED"
    credentials = json.loads(decrypt_secret(account.encrypted_credentials))
    adapter = MercadoBitcoinAdapter(credentials["client_id"], credentials["client_secret"], settings.mercado_bitcoin_base_url)
    validation = await adapter.validate_account()
    account_id = validation["account_id"]
    if not await reconcile_live_orders(db, bot, adapter, account_id):
        return "RECONCILING"
    symbol = str(limits["symbol"])
    ticker = (await market_data.get_tickers([symbol]))[0]
    candles = await market_data.get_candles(symbol)
    rules = (await adapter.get_symbol_rules([symbol]))[0]
    fees = await adapter.get_trading_fees(account_id, symbol)
    balances = await adapter.get_balance(account_id)
    bid, ask = D(ticker["bid"]), D(ticker["ask"])
    midpoint = (bid + ask) / D("2")
    spread = (ask - bid) / midpoint if midpoint else D("1")
    if spread > D(limits["max_spread"]):
        return "SPREAD_BLOCKED"
    position = await db.scalar(select(Position).where(Position.bot_id == bot.id, Position.symbol == symbol))
    realized = D(position.realized_pnl if position else 0)
    if realized <= -D(limits["daily_loss"]):
        bot.status = BotStatus.RISK
        db.add(Notification(user_id=bot.user_id, level="CRITICAL", event="live_daily_loss", message="Limite de perda real atingido. Novas ordens foram bloqueadas."))
        return "DAILY_LOSS_BLOCKED"
    strategy = MeanReversionStrategy()
    signal = strategy.evaluate(symbol, candles, market_data.tick(ticker, candles), D(limits["max_order"]))
    stop_loss = bool(position and position.quantity > 0 and bid <= position.average_cost * (D("1") - D(limits["stop_loss"])))
    if stop_loss:
        signal = signal.__class__(symbol, datetime.now(timezone.utc), SignalAction.SELL, D("1"), position.quantity * bid, "Stop-loss real de 2% acionado.", indicators=signal.indicators)
    signal_row = SignalModel(bot_id=bot.id, symbol=symbol, timestamp=signal.timestamp, action=signal.action.value, confidence=signal.confidence, suggested_amount=signal.suggested_amount, reason=signal.reason, strategy_name=signal.strategy_name, strategy_version=signal.strategy_version, indicators=signal.indicators)
    db.add(signal_row)
    await db.flush()
    if signal.action == SignalAction.HOLD:
        return "HOLD"
    taker_fee = D(fees["taker_fee"])
    if signal.action == SignalAction.BUY:
        if position and position.quantity > 0:
            return "POSITION_EXISTS"
        ema = D(str(signal.indicators.get("ema20", ask)))
        expected_edge = (ema - ask) / ask if ask else D("0")
        required_edge = taker_fee * D("2") + spread + D(limits["edge_buffer"])
        if expected_edge <= required_edge:
            db.add(RiskDecision(bot_id=bot.id, signal_id=signal_row.id, approved=False, reason_code="EDGE_BELOW_FEES", details={"expected_edge":str(expected_edge),"required_edge":str(required_edge),"taker_fee_each_side":str(taker_fee),"spread":str(spread)}))
            return "EDGE_BELOW_FEES"
        brl_available = D(balances.get("BRL", 0))
        amount = min(D(limits["max_order"]), brl_available - D(limits["reserve"]))
        if amount < max(D(str(rules["min-cost"])), D("10")):
            return "INSUFFICIENT_AVAILABLE_BRL"
        side, requested = Side.BUY, amount
    else:
        if not position or position.quantity <= 0:
            return "NO_POSITION"
        net_proceeds = position.quantity * bid * (D("1") - taker_fee)
        cost_basis = position.quantity * position.average_cost
        if not stop_loss and net_proceeds <= cost_basis * (D("1") + D(limits["edge_buffer"])):
            db.add(RiskDecision(bot_id=bot.id, signal_id=signal_row.id, approved=False, reason_code="NET_PROFIT_BELOW_BUFFER", details={"net_proceeds":str(net_proceeds),"cost_basis":str(cost_basis)}))
            return "NET_PROFIT_BELOW_BUFFER"
        step = D(str(rules["round-lot"]))
        requested = position.quantity.quantize(step, rounding=ROUND_DOWN)
        side = Side.SELL
    db.add(RiskDecision(bot_id=bot.id, signal_id=signal_row.id, approved=True, reason_code="LIVE_APPROVED", details={"requested":str(requested),"fee_rate":str(taker_fee),"stop_loss":stop_loss}))
    client_id = deterministic_order_id(str(bot.id), signal)
    order = Order(user_id=bot.user_id, bot_id=bot.id, client_order_id=client_id, symbol=symbol, side=side, status=OrderStatus.SUBMITTING, quantity=D("0"))
    db.add(order)
    await db.commit()  # Persist intent before the irreversible external request.
    try:
        payload = await adapter.create_market_order(account_id, client_id, symbol, side.value, requested)
        order.exchange_order_id = str(payload.get("orderId") or payload.get("id") or "") or None
        order.status = OrderStatus.SUBMITTED
        if payload.get("status"):
            await apply_exchange_order(db, bot, order, payload)
        await db.commit()
        return "ORDER_SUBMITTED"
    except MercadoBitcoinAmbiguousOrderError:
        bot.status = BotStatus.PAUSED
        bot.reconciled = False
        db.add(Notification(user_id=bot.user_id, level="CRITICAL", event="live_order_ambiguous", message="O resultado de uma ordem real ficou incerto. O bot foi pausado; confira a conta do MB."))
        await db.commit()
        logger.exception("Ambiguous live order for bot %s", bot.id)
        return "AMBIGUOUS_ORDER"
    except Exception:
        order.status = OrderStatus.FAILED
        bot.status = BotStatus.PAUSED
        db.add(Notification(user_id=bot.user_id, level="CRITICAL", event="live_order_failed", message="A ordem real falhou e o bot foi pausado sem repetir automaticamente."))
        await db.commit()
        logger.exception("Live order failed for bot %s", bot.id)
        return "ORDER_FAILED"
