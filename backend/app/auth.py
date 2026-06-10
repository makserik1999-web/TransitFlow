"""JWT-аутентификация и роли (раздел 5, 11 спеки)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# tokenUrl — для Swagger "Authorize"; сам логин в routers/auth.py.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(*, user_id: int, role: UserRole, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "email": email,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Недействительный токен",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        if user_id is None:
            raise creds_exc
    except JWTError:
        raise creds_exc

    user = db.scalar(select(User).where(User.id == int(user_id)))
    if user is None:
        raise creds_exc
    return user


def require_role(*roles: UserRole):
    """Зависимость-фабрика: пускает только пользователей с одной из ролей."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этой роли",
            )
        return user

    return checker
