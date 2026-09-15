from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ---------- Auth schemas ----------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None


class GoogleLoginRequest(BaseModel):
    id_token: str


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TOTPSetupRequest(BaseModel):
    """
    `current_code` n'est requis que pour RÉINITIALISER une 2FA déjà active :
    sans lui, un jeton d'accès volé suffirait à remplacer le secret de la
    victime et à repartir avec un jeu de codes de secours neuf.
    """

    current_code: str | None = None


class TOTPSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    backup_codes: list[str]  # affichés une seule fois, en clair


class TOTPVerifyRequest(BaseModel):
    code: str


class BackupCodeLoginRequest(BaseModel):
    """
    Connexion par code de secours : c'est une variante de /login, pas une
    action authentifiée — on y recourt justement quand on ne peut PAS produire
    de second facteur, donc pas de jeton d'accès.
    """

    email: EmailStr
    password: str
    code: str = Field(..., min_length=4, max_length=64)


class EmailVerifyRequest(BaseModel):
    """
    Vérification d'adresse par code à usage unique.

    L'adresse accompagne le code : six chiffres ne sont pas discriminants à
    l'échelle de la base, et une recherche par code seul finirait par tomber
    sur le compte d'un inconnu.
    """

    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10, pattern=r"^\d+$")


class ResendVerificationRequest(BaseModel):
    email: EmailStr


# ---------- Audit log ----------

class AuditLogResponse(BaseModel):
    id: UUID
    user_id: UUID | None
    action: str
    resource: str | None
    resource_id: str | None
    details: dict | None
    ip_address: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAuditLogs(BaseModel):
    total: int
    page: int
    size: int
    items: list[AuditLogResponse]
