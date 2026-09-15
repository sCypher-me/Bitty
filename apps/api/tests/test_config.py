import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings


def test_production_rejects_local_and_weak_configuration():
    with pytest.raises(ValidationError,match="Unsafe production configuration"):
        Settings(
            app_env="production",
            database_url="sqlite+aiosqlite:///./local.db",
            app_secret="dev-only",
            encryption_master_key="",
            cookie_secure=False,
            embedded_worker_enabled=True,
            _env_file=None,
        )


def test_production_accepts_centralized_fail_closed_configuration():
    config=Settings(
        app_env="production",
        database_url="postgresql+asyncpg://bitty:secret@db.example/bitty",
        app_secret="a-strong-random-production-secret-with-entropy",
        encryption_master_key=Fernet.generate_key().decode(),
        cookie_secure=True,
        embedded_worker_enabled=False,
        _env_file=None,
    )
    assert config.app_env=="production"
    assert config.database_url.startswith("postgresql+asyncpg://")
