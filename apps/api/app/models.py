import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

def uid(): return uuid.uuid4()
def utcnow(): return datetime.now(timezone.utc)
class BotStatus(str, enum.Enum): STOPPED="STOPPED"; STARTING="STARTING"; ACTIVE="ACTIVE"; PAUSED="PAUSED"; RISK="RISK"; STOPPING="STOPPING"; ERROR="ERROR"; RECONNECTING="RECONNECTING"
class OrderStatus(str, enum.Enum): CREATED="CREATED"; VALIDATING="VALIDATING"; APPROVED="APPROVED"; SUBMITTING="SUBMITTING"; SUBMITTED="SUBMITTED"; PARTIALLY_FILLED="PARTIALLY_FILLED"; FILLED="FILLED"; CANCELED="CANCELED"; REJECTED="REJECTED"; FAILED="FAILED"
class Side(str, enum.Enum): BUY="BUY"; SELL="SELL"
class Action(str, enum.Enum): BUY="BUY"; SELL="SELL"; HOLD="HOLD"

class User(Base):
    __tablename__="users"
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid)
    email: Mapped[str]=mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str]=mapped_column(String(255))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)

class DeviceSession(Base):
    __tablename__="device_sessions"
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid)
    user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str]=mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)

class ExchangeAccount(Base):
    __tablename__="exchange_accounts"
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    exchange: Mapped[str]=mapped_column(String(32), default="mock"); mode: Mapped[str]=mapped_column(String(16), default="PAPER")
    encrypted_credentials: Mapped[str|None]=mapped_column(Text, nullable=True); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)

class Bot(Base):
    __tablename__="bots"; __table_args__=(Index("ix_bots_user_status", "user_id", "status"),)
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str]=mapped_column(String(80)); mode: Mapped[str]=mapped_column(String(16), default="PAPER")
    status: Mapped[BotStatus]=mapped_column(Enum(BotStatus), default=BotStatus.STOPPED); reconciled: Mapped[bool]=mapped_column(Boolean, default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    config: Mapped["BotConfig"]=relationship(back_populates="bot", cascade="all, delete-orphan", uselist=False)

class BotConfig(Base):
    __tablename__="bot_configs"
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); bot_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), unique=True)
    capital: Mapped[Decimal]=mapped_column(Numeric(28,8)); reserve_pct: Mapped[Decimal]=mapped_column(Numeric(8,4), default=Decimal("0.30")); max_trade_pct: Mapped[Decimal]=mapped_column(Numeric(8,4), default=Decimal("0.05")); max_asset_pct: Mapped[Decimal]=mapped_column(Numeric(8,4), default=Decimal("0.15")); max_exposure_pct: Mapped[Decimal]=mapped_column(Numeric(8,4), default=Decimal("0.60")); daily_loss_pct: Mapped[Decimal]=mapped_column(Numeric(8,4), default=Decimal("0.03")); max_drawdown_pct: Mapped[Decimal]=mapped_column(Numeric(8,4), default=Decimal("0.10")); symbols: Mapped[list]=mapped_column(JSON); advanced: Mapped[dict]=mapped_column(JSON, default=dict)
    bot: Mapped[Bot]=relationship(back_populates="config")

class Strategy(Base):
    __tablename__="strategies"; id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); name: Mapped[str]=mapped_column(String(80), unique=True); description: Mapped[str]=mapped_column(Text)
class StrategyVersion(Base):
    __tablename__="strategy_versions"; __table_args__=(UniqueConstraint("strategy_id","version"),)
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); strategy_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("strategies.id")); version: Mapped[str]=mapped_column(String(20)); parameters: Mapped[dict]=mapped_column(JSON)
class Candle(Base):
    __tablename__="candles"; __table_args__=(UniqueConstraint("symbol","timeframe","opened_at"),)
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); symbol: Mapped[str]=mapped_column(String(24), index=True); timeframe: Mapped[str]=mapped_column(String(4)); opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True)); open: Mapped[Decimal]=mapped_column(Numeric(28,8)); high: Mapped[Decimal]=mapped_column(Numeric(28,8)); low: Mapped[Decimal]=mapped_column(Numeric(28,8)); close: Mapped[Decimal]=mapped_column(Numeric(28,8)); volume: Mapped[Decimal]=mapped_column(Numeric(28,8))
class Signal(Base):
    __tablename__="signals"; id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); bot_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("bots.id"), index=True); symbol: Mapped[str]=mapped_column(String(24)); timestamp: Mapped[datetime]=mapped_column(DateTime(timezone=True)); action: Mapped[Action]=mapped_column(Enum(Action)); confidence: Mapped[Decimal]=mapped_column(Numeric(8,4)); suggested_amount: Mapped[Decimal]=mapped_column(Numeric(28,8)); reason: Mapped[str]=mapped_column(Text); strategy_name: Mapped[str]=mapped_column(String(80)); strategy_version: Mapped[str]=mapped_column(String(20)); indicators: Mapped[dict]=mapped_column(JSON)
class RiskDecision(Base):
    __tablename__="risk_decisions"; id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); bot_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("bots.id"), index=True); signal_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey("signals.id"), nullable=True); approved: Mapped[bool]=mapped_column(Boolean); reason_code: Mapped[str]=mapped_column(String(64)); details: Mapped[dict]=mapped_column(JSON, default=dict); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
class Order(Base):
    __tablename__="orders"; __table_args__=(UniqueConstraint("client_order_id"),)
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("users.id"), index=True); bot_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("bots.id"), index=True); client_order_id: Mapped[str]=mapped_column(String(64)); exchange_order_id: Mapped[str|None]=mapped_column(String(80), nullable=True); symbol: Mapped[str]=mapped_column(String(24)); side: Mapped[Side]=mapped_column(Enum(Side)); status: Mapped[OrderStatus]=mapped_column(Enum(OrderStatus), default=OrderStatus.CREATED); quantity: Mapped[Decimal]=mapped_column(Numeric(28,8)); filled_quantity: Mapped[Decimal]=mapped_column(Numeric(28,8), default=0); average_price: Mapped[Decimal|None]=mapped_column(Numeric(28,8), nullable=True); fees: Mapped[Decimal]=mapped_column(Numeric(28,8), default=0); rejection_reason: Mapped[str|None]=mapped_column(String(64), nullable=True); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
class OrderFill(Base):
    __tablename__="order_fills"; __table_args__=(UniqueConstraint("order_id","external_fill_id"),)
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); order_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("orders.id", ondelete="CASCADE")); external_fill_id: Mapped[str]=mapped_column(String(80)); quantity: Mapped[Decimal]=mapped_column(Numeric(28,8)); price: Mapped[Decimal]=mapped_column(Numeric(28,8)); fee: Mapped[Decimal]=mapped_column(Numeric(28,8)); filled_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
class Position(Base):
    __tablename__="positions"; __table_args__=(UniqueConstraint("bot_id","symbol"),)
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("users.id"), index=True); bot_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("bots.id"), index=True); symbol: Mapped[str]=mapped_column(String(24)); quantity: Mapped[Decimal]=mapped_column(Numeric(28,8), default=0); average_cost: Mapped[Decimal]=mapped_column(Numeric(28,8), default=0); realized_pnl: Mapped[Decimal]=mapped_column(Numeric(28,8), default=0); fees: Mapped[Decimal]=mapped_column(Numeric(28,8), default=0); stop_price: Mapped[Decimal|None]=mapped_column(Numeric(28,8), nullable=True); take_profit_price: Mapped[Decimal|None]=mapped_column(Numeric(28,8), nullable=True)
class PortfolioSnapshot(Base):
    __tablename__="portfolio_snapshots"; id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); bot_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("bots.id"), index=True); cash: Mapped[Decimal]=mapped_column(Numeric(28,8)); invested: Mapped[Decimal]=mapped_column(Numeric(28,8)); equity: Mapped[Decimal]=mapped_column(Numeric(28,8)); drawdown: Mapped[Decimal]=mapped_column(Numeric(10,6)); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
class Backtest(Base):
    __tablename__="backtests"; id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("users.id"), index=True); symbol: Mapped[str]=mapped_column(String(24)); status: Mapped[str]=mapped_column(String(20), default="COMPLETED"); metrics: Mapped[dict]=mapped_column(JSON); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
class BacktestTrade(Base):
    __tablename__="backtest_trades"; id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); backtest_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("backtests.id", ondelete="CASCADE")); side: Mapped[Side]=mapped_column(Enum(Side)); quantity: Mapped[Decimal]=mapped_column(Numeric(28,8)); price: Mapped[Decimal]=mapped_column(Numeric(28,8)); fee: Mapped[Decimal]=mapped_column(Numeric(28,8)); pnl: Mapped[Decimal]=mapped_column(Numeric(28,8), default=0); timestamp: Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Notification(Base):
    __tablename__="notifications"; id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("users.id"), index=True); level: Mapped[str]=mapped_column(String(16)); event: Mapped[str]=mapped_column(String(64)); message: Mapped[str]=mapped_column(Text); read: Mapped[bool]=mapped_column(Boolean, default=False); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
class AuditLog(Base):
    __tablename__="audit_logs"; id: Mapped[uuid.UUID]=mapped_column(primary_key=True, default=uid); user_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey("users.id"), index=True, nullable=True); event: Mapped[str]=mapped_column(String(64)); entity_id: Mapped[str|None]=mapped_column(String(64), nullable=True); details: Mapped[dict]=mapped_column(JSON, default=dict); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
