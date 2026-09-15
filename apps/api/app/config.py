from functools import lru_cache
from typing import Literal
from cryptography.fernet import Fernet
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: Literal["development","test","production"] = "development"
    database_url: str = "sqlite+aiosqlite:///./cryptobot.db"
    redis_url: str = "redis://localhost:6379/0"
    app_secret: str = "dev-only-secret-change-me-32-characters"
    encryption_master_key: str = ""
    frontend_url: str = "http://localhost:3000"
    real_trading_enabled: bool = False
    binance_base_url: str = "https://api.binance.com"
    binance_testnet_base_url: str = "https://testnet.binance.vision"
    binance_recv_window_ms: int = 5000
    mercado_bitcoin_base_url: str = "https://api.mercadobitcoin.net/api/v4"
    real_trading_confirmation: str = "ATIVAR TRADING REAL"
    cookie_secure: bool = False
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    embedded_worker_enabled: bool = True
    embedded_worker_interval: int = 15
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    @field_validator("database_url",mode="before")
    @classmethod
    def use_async_postgres_driver(cls,value):
        if isinstance(value,str) and value.startswith("postgresql://"):
            return value.replace("postgresql://","postgresql+asyncpg://",1)
        return value

    @model_validator(mode="after")
    def production_must_fail_closed(self):
        if self.app_env!="production": return self
        problems=[]
        normalized_secret=self.app_secret.lower()
        if len(self.app_secret)<32 or "dev-only" in normalized_secret or "replace" in normalized_secret: problems.append("APP_SECRET must be a strong production secret")
        if not self.encryption_master_key: problems.append("ENCRYPTION_MASTER_KEY is required")
        else:
            try: Fernet(self.encryption_master_key.encode())
            except Exception: problems.append("ENCRYPTION_MASTER_KEY must be a valid Fernet key")
        if self.database_url.startswith("sqlite"): problems.append("DATABASE_URL must use a centralized database")
        if not self.cookie_secure: problems.append("COOKIE_SECURE must be true")
        if self.embedded_worker_enabled: problems.append("EMBEDDED_WORKER_ENABLED must be false")
        if problems: raise ValueError("Unsafe production configuration: "+"; ".join(problems))
        return self

@lru_cache
def get_settings(): return Settings()
settings = get_settings()
