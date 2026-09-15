from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

class RegisterIn(BaseModel): email: EmailStr; password: str = Field(min_length=12, max_length=128)
class LoginIn(BaseModel): email: EmailStr; password: str
class UserOut(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id: UUID; email: str
class BotCreate(BaseModel):
    name: str = Field(min_length=2,max_length=80); capital: Decimal = Field(gt=0); symbols: list[str] = Field(min_length=1,max_length=10); risk_profile: str = "CONSERVATIVE"
    @field_validator("symbols")
    @classmethod
    def symbols_valid(cls,v):
        allowed={"BTC/BRL","ETH/BRL","SOL/BRL"}
        result=list(dict.fromkeys(x.upper() for x in v))
        if not set(result)<=allowed: raise ValueError("unsupported symbol")
        return result
class BotOut(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id: UUID; name: str; mode: str; status: str; reconciled: bool; created_at: datetime
class BacktestIn(BaseModel):
    symbol: str="BTC/USDT"; initial_capital: Decimal=Field(default=Decimal("10000"),gt=0); candles: list[dict]

class BinanceConnectIn(BaseModel):
    api_key: SecretStr = Field(min_length=8)
    api_secret: SecretStr = Field(min_length=8)
    environment: Literal["TESTNET", "LIVE"] = "TESTNET"

class TradingModeIn(BaseModel):
    exchange_account_id: UUID
    environment: Literal["TESTNET", "LIVE"] = "TESTNET"
    confirmation: str = ""

class BinanceOrderTestIn(BaseModel):
    exchange_account_id: UUID
    symbol: Literal["BTC/BRL", "ETH/BRL", "SOL/BRL"] = "BTC/BRL"
    notional_brl: Decimal = Field(default=Decimal("10"), gt=0, le=100)

class MercadoBitcoinConnectIn(BaseModel):
    client_id: SecretStr = Field(min_length=8)
    client_secret: SecretStr = Field(min_length=8)

class RealCapitalIn(BaseModel):
    amount_brl: Decimal = Field(ge=Decimal("10.00"), le=Decimal("1000.00"), decimal_places=2)

class PaperResetIn(BaseModel):
    initial_capital_brl: Decimal = Field(ge=Decimal("10.00"), le=Decimal("1000000.00"), decimal_places=2)

class PaperRiskProfileIn(BaseModel):
    profile: Literal["CONSERVATIVE", "MODERATE", "AGGRESSIVE"]
