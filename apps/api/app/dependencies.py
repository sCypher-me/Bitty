from datetime import datetime, timezone
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.models import DeviceSession, User
from app.security import decode_access_token


def is_expired(value)->bool:
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    return value<=datetime.now(timezone.utc)

async def current_user(access_token:str|None=Cookie(default=None),db:AsyncSession=Depends(get_db))->User:
    if not access_token: raise HTTPException(status.HTTP_401_UNAUTHORIZED,"Not authenticated")
    try: claims=decode_access_token(access_token)
    except Exception as exc: raise HTTPException(status.HTTP_401_UNAUTHORIZED,"Invalid session") from exc
    session=await db.scalar(select(DeviceSession).where(DeviceSession.id==claims.session_id,DeviceSession.user_id==claims.user_id))
    if not session or session.revoked_at or is_expired(session.expires_at): raise HTTPException(status.HTTP_401_UNAUTHORIZED,"Invalid session")
    user=await db.scalar(select(User).where(User.id==claims.user_id))
    if not user: raise HTTPException(status.HTTP_401_UNAUTHORIZED,"Invalid session")
    return user
