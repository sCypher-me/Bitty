from datetime import datetime, timezone

import pytest
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import create_device_session, logout, refresh_session
from app.db import Base
from app.dependencies import current_user
from app.models import DeviceSession, User
from app.security import create_access_token, hash_refresh_token


@pytest.mark.asyncio
async def test_refresh_rotates_secret_and_logout_revokes_only_current_device():
    engine=create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    async with sessions() as db:
        user=User(email="sessions@example.com",password_hash="unused")
        db.add(user); await db.flush()
        first,first_refresh=await create_device_session(db,user.id)
        second,second_refresh=await create_device_session(db,user.id)
        await db.commit()

        assert first.refresh_token_hash!=first_refresh
        assert first.refresh_token_hash==hash_refresh_token(first_refresh)
        assert second.refresh_token_hash==hash_refresh_token(second_refresh)

        refresh_response=Response(status_code=204)
        old_hash=first.refresh_token_hash
        await refresh_session(refresh_response,first_refresh,db)
        await db.refresh(first)
        assert first.refresh_token_hash!=old_hash
        refresh_cookies=[value.decode() for key,value in refresh_response.raw_headers if key==b"set-cookie"]
        assert any("refresh_token=" in value for value in refresh_cookies)

        first_access=create_access_token(user.id,first.id)
        assert await current_user(first_access,db)==user
        logout_response=Response(status_code=204)
        await logout(logout_response,first_access,None,db)
        await db.refresh(first); await db.refresh(second)

        assert first.revoked_at is not None
        assert first.revoked_at.replace(tzinfo=timezone.utc)<=datetime.now(timezone.utc)
        assert second.revoked_at is None
        assert await current_user(create_access_token(user.id,second.id),db)==user
        logout_cookies=[value.decode() for key,value in logout_response.raw_headers if key==b"set-cookie"]
        assert any("access_token=" in value for value in logout_cookies)

        stored=list((await db.scalars(select(DeviceSession))).all())
        assert len(stored)==2
    await engine.dispose()
