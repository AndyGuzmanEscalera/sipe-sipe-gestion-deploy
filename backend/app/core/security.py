import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Response
from app.core.config import get_settings

_hasher = PasswordHasher()

def hash_password(plain: str) -> str:
    return _hasher.hash(plain)

def verify_password(stored_hash: str, plain: str) -> bool:
    try:
        return _hasher.verify(stored_hash, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False

def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {'sub': str(user_id), 'typ': 'access', 'iat': int(now.timestamp()), 'exp': int(exp.timestamp()), 'iss': settings.jwt_issuer, 'aud': settings.jwt_audience}
    return jwt.encode(payload, settings.jwt_access_secret, algorithm='HS256'), settings.access_token_ttl_minutes * 60

def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_access_secret, algorithms=['HS256'], issuer=settings.jwt_issuer, audience=settings.jwt_audience)
    except jwt.exceptions.InvalidTokenError as exc:
        raise ValueError('invalid token') from exc
    if payload.get('typ') != 'access':
        raise ValueError('invalid token')
    return payload

def generate_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()

def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

def set_refresh_cookie(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(settings.cookie_name, raw, max_age=settings.refresh_token_ttl_days * 86400, path=settings.cookie_path, httponly=True, secure=settings.cookie_secure, samesite=settings.cookie_samesite)

def clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.cookie_name, path=settings.cookie_path, httponly=True, secure=settings.cookie_secure, samesite=settings.cookie_samesite)
