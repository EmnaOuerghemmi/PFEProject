from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import validate_password_strength
from app.models.user import UserRole


# ---------- Base ----------

class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    full_name: str | None = None
    phone_number: str | None = None
    ministry: str | None = None
    department: str | None = None
    job_title: str | None = None
    employee_id: str | None = None
    language: str = Field(default="fr", pattern="^(fr|ar)$")
    timezone: str = "Africa/Tunis"


# ---------- Create ----------

class UserRegister(UserBase):
    """
    Corps de l'inscription PUBLIQUE (`POST /auth/register`).

    Volontairement dépourvu de `role` : tant que ce champ était exposé ici,
    n'importe quel visiteur pouvait s'attribuer ADMIN à l'inscription. Le rôle
    est fixé par le serveur à CANDIDAT ; seule la route d'administration
    `POST /users` (cf. `UserCreate`) permet d'en choisir un.
    """

    password: str = Field(..., min_length=8)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not validate_password_strength(v):
            raise ValueError(
                "Le mot de passe doit faire 8 caractères ou plus et contenir une majuscule, "
                "une minuscule, un chiffre et un caractère spécial."
            )
        return v


class UserCreate(UserRegister):
    """Création par un administrateur — le rôle est ici légitimement choisi."""

    role: str = Field(default=UserRole.CANDIDAT)

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in UserRole.ALL:
            raise ValueError(f"Le rôle doit être l'un de {UserRole.ALL}")
        return v


# ---------- Update ----------

class UserUpdate(BaseModel):
    full_name: str | None = None
    phone_number: str | None = None
    avatar_url: str | None = None
    ministry: str | None = None
    department: str | None = None
    job_title: str | None = None
    language: str | None = Field(default=None, pattern="^(fr|ar)$")
    timezone: str | None = None
    notification_preferences: dict[str, Any] | None = None


class UserAdminUpdate(UserUpdate):
    role: str | None = None
    is_active: bool | None = None
    is_verified: bool | None = None
    # `permissions` (colonne JSON) n'est plus ni accepté ni renvoyé : les
    # droits se décident par le RÔLE, dans `core/rbac_policy.csv`. Le champ
    # restait modifiable alors qu'aucun contrôle ne le lisait — un
    # administrateur pouvait y écrire en croyant accorder un accès.

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str | None) -> str | None:
        if v is not None and v not in UserRole.ALL:
            raise ValueError(f"Role must be one of {UserRole.ALL}")
        return v


# ---------- Response ----------

class UserResponse(UserBase):
    id: UUID
    is_active: bool
    is_superuser: bool
    is_verified: bool
    role: str
    totp_enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserPublicResponse(BaseModel):
    id: UUID
    username: str
    full_name: str | None
    avatar_url: str | None
    role: str
    ministry: str | None
    department: str | None

    model_config = {"from_attributes": True}


# ---------- Password ----------

class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not validate_password_strength(v):
            raise ValueError(
                "Password must be 8+ characters with uppercase, lowercase, digit, and special character."
            )
        return v


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordReset(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not validate_password_strength(v):
            raise ValueError(
                "Password must be 8+ characters with uppercase, lowercase, digit, and special character."
            )
        return v


# ---------- Pagination ----------

class PaginatedUsers(BaseModel):
    total: int
    page: int
    size: int
    items: list[UserResponse]
