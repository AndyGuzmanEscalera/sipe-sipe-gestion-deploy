from datetime import datetime, timedelta, timezone
import uuid
from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token, generate_refresh_token, hash_password, hash_refresh_token, set_refresh_cookie, clear_refresh_cookie, verify_password
from app.core.config import get_settings
from app.models import AuthSession, Permission, Role, RolePermission, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/admin/auth/login', auto_error=False)

def user_permissions(db: Session, user_id: uuid.UUID) -> list[str]:
    rows = db.execute(select(Permission.code).join(RolePermission, RolePermission.permission_id == Permission.id).join(Role, and_(Role.id == RolePermission.role_id, Role.is_active.is_(True))).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)).all()
    return sorted({row[0] for row in rows})

def user_roles(db: Session, user_id: uuid.UUID) -> list[str]:
    rows = db.execute(select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id, Role.is_active.is_(True))).all()
    return sorted({row[0] for row in rows})

def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    if not token:
        raise HTTPException(status_code=401, detail='Token requerido', headers={'WWW-Authenticate': 'Bearer'})
    try:
        subject = decode_access_token(token).get('sub')
        user_id = uuid.UUID(subject)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=401, detail='Token inválido', headers={'WWW-Authenticate': 'Bearer'})
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail='Usuario no disponible', headers={'WWW-Authenticate': 'Bearer'})
    return user

def require_permission(code: str):
    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if code not in user_permissions(db, user.id):
            raise HTTPException(status_code=403, detail='Permiso insuficiente')
        return user
    return dependency

def ensure_permission(db: Session, user: User, code: str) -> None:
    """Verifica un permiso fuera del ciclo de dependencias.

    Se usa cuando la exigencia depende del contenido de la petición
    (por ejemplo, asignar roles solo se exige si la petición los incluye).
    """
    if code not in user_permissions(db, user.id):
        raise HTTPException(status_code=403, detail='Permiso insuficiente')

def create_session(db: Session, user: User) -> str:
    raw, digest = generate_refresh_token()
    db.add(AuthSession(user_id=user.id, refresh_token_hash=digest, expires_at=datetime.now(timezone.utc) + timedelta(days=get_settings().refresh_token_ttl_days)))
    db.commit()
    return raw

def login_user(db: Session, username: str, password: str) -> tuple[User, str]:
    user = db.scalar(select(User).where(User.username == username.strip().lower(), User.is_active.is_(True)))
    if user is None or not verify_password(user.password_hash, password):
        raise HTTPException(status_code=401, detail='Credenciales inválidas')
    user.last_login_at = datetime.now(timezone.utc)
    raw = create_session(db, user)
    return user, raw

def refresh_user(db: Session, raw: str) -> tuple[User, str]:
    session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == hash_refresh_token(raw), AuthSession.revoked_at.is_(None)).with_for_update())
    if session is None:
        raise HTTPException(status_code=401, detail='Sesión inválida')
    now = datetime.now(timezone.utc)
    if session.expires_at < now:
        raise HTTPException(status_code=401, detail='Sesión expirada')
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail='Usuario no disponible')
    raw_new, digest = generate_refresh_token()
    session.refresh_token_hash = digest
    session.last_used_at = now
    db.commit()
    return user, raw_new

def auth_response(response: Response, db: Session, user: User, raw: str) -> dict:
    token, expires = create_access_token(user.id)
    set_refresh_cookie(response, raw)
    return {'access_token': token, 'expires_in': expires, 'user': user_response(db, user)}

def user_response(db: Session, user: User) -> dict:
    return {'id': str(user.id), 'username': user.username, 'email': user.email, 'is_active': user.is_active, 'roles': user_roles(db, user.id), 'permissions': user_permissions(db, user.id)}

def revoke_from_request(db: Session, request: Request) -> None:
    raw = request.cookies.get(get_settings().cookie_name)
    if raw:
        session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == hash_refresh_token(raw), AuthSession.revoked_at.is_(None)))
        if session:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
