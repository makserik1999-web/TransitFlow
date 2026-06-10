"""Pydantic-схемы. На Этапе 0 — только то, что нужно для логина."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models import UserRole


class LoginRequest(BaseModel):
    # email — это логин-хендл; демо-аккаунты вида shipper@demo (раздел 4)
    # намеренно не являются валидными RFC-email, поэтому str, а не EmailStr.
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: UserRole
    company: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
