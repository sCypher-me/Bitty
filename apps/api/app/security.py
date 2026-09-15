from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from uuid import UUID
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from app.config import settings

ph=PasswordHasher(time_cost=3,memory_cost=65536,parallelism=4)
def hash_password(password:str)->str: return ph.hash(password)
def verify_password(password:str, encoded:str)->bool:
    try: return ph.verify(encoded,password)
    except VerifyMismatchError: return False
@dataclass(frozen=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID


def create_access_token(user_id:UUID,session_id:UUID)->str:
    now=datetime.now(timezone.utc)
    return jwt.encode(
        {"sub":str(user_id),"sid":str(session_id),"type":"access","iat":now,"exp":now+timedelta(minutes=settings.access_token_minutes)},
        settings.app_secret,
        algorithm="HS256",
    )


def decode_access_token(token:str)->AccessClaims:
    payload=jwt.decode(token,settings.app_secret,algorithms=["HS256"])
    if payload.get("type")!="access" or not payload.get("sid"): raise jwt.InvalidTokenError("Invalid access token")
    return AccessClaims(user_id=UUID(payload["sub"]),session_id=UUID(payload["sid"]))


def new_refresh_token()->str: return secrets.token_urlsafe(48)
def hash_refresh_token(token:str)->str: return sha256(token.encode()).hexdigest()
def encrypt_secret(value:str)->str:
    if not settings.encryption_master_key: raise RuntimeError("ENCRYPTION_MASTER_KEY is required")
    return Fernet(settings.encryption_master_key.encode()).encrypt(value.encode()).decode()

def decrypt_secret(value:str)->str:
    if not settings.encryption_master_key: raise RuntimeError("ENCRYPTION_MASTER_KEY is required")
    return Fernet(settings.encryption_master_key.encode()).decrypt(value.encode()).decode()
