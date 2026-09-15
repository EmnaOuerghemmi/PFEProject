import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_active_user, rate_limit
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.agent import (
    BackupCodeLoginRequest,
    EmailVerifyRequest,
    GoogleLoginRequest,
    LoginRequest,
    RefreshTokenRequest,
    ResendVerificationRequest,
    TOTPSetupRequest,
    TOTPSetupResponse,
    TOTPVerifyRequest,
    TokenResponse,
)
from app.schemas.user import (
    PasswordChange,
    PasswordReset,
    PasswordResetRequest,
    UserRegister,
    UserResponse,
)
from app.services.email_service import send_email_verification, send_password_reset_email
from app.services.report_service import auth_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def _login_and_commit(db: AsyncSession, coro) -> TokenResponse:
    """
    Exécute une tentative de connexion en garantissant la persistance des
    échecs.

    `AuthService.login` incrémente `failed_login_attempts` et pose
    `locked_until` AVANT de lever son exception. Or `get_db` annule la
    transaction dès qu'une exception traverse la route : sans le commit
    explicite ci-dessous, tout ce travail était perdu et le verrouillage de
    compte ne se déclenchait jamais — pas plus que les lignes LOGIN_FAIL du
    journal d'audit.
    """
    try:
        tokens = await coro
    except HTTPException:
        await db.commit()
        raise
    await db.commit()
    return tokens


# ---------- Inscription ----------

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("register", *settings.RATE_LIMIT_REGISTER))],
)
async def register(
    body: UserRegister,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Inscription publique. Le rôle est imposé par le serveur (CANDIDAT) et
    n'est volontairement pas lisible depuis le corps de la requête : c'est un
    administrateur qui promeut ensuite le compte via `PATCH /users/{id}`.

    Un code à usage unique part par e-mail dans la foulée ; le client enchaîne
    sur `POST /auth/verify-email`, qui ouvre la session.
    """
    user, verification_code = await auth_service.register(
        db,
        email=body.email,
        username=body.username,
        password=body.password,
        full_name=body.full_name,
        role=UserRole.CANDIDAT,
    )
    await db.commit()
    await db.refresh(user)

    await send_email_verification(user.email, user.full_name or user.username, verification_code)
    return user


# ---------- Connexion ----------

@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("login", *settings.RATE_LIMIT_LOGIN))],
)
async def login(
    request: Request,
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _login_and_commit(
        db, auth_service.login(db, request, body.email, body.password, body.totp_code)
    )


@router.post(
    "/token",
    response_model=TokenResponse,
    include_in_schema=False,
    dependencies=[Depends(rate_limit("login", *settings.RATE_LIMIT_LOGIN))],
)
async def login_form(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Variante « formulaire » de /login, pour le bouton « Authorize » de Swagger.

    `OAuth2PasswordBearer` impose un point d'entrée acceptant
    `username`/`password` en `application/x-www-form-urlencoded` ; /login
    n'accepte que du JSON, si bien que l'authentification depuis /docs ne
    fonctionnait pas. Ici `username` porte l'adresse e-mail.
    """
    return await _login_and_commit(
        db, auth_service.login(db, request, form.username, form.password, None)
    )


@router.post(
    "/google",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("login", *settings.RATE_LIMIT_LOGIN))],
)
async def login_with_google(
    request: Request,
    body: GoogleLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tokens = await auth_service.google_login(db, request, body.id_token)
    await db.commit()
    return tokens


@router.post(
    "/2fa/backup",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("totp", *settings.RATE_LIMIT_TOTP))],
)
async def login_with_backup_code(
    request: Request,
    body: BackupCodeLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Connexion par code de secours, application d'authentification perdue.

    Cette route N'EXIGE PAS de jeton d'accès : dans sa version précédente elle
    était protégée par `get_current_active_user`, ce qui la rendait
    inatteignable — il fallait déjà être connecté pour utiliser le moyen prévu
    quand on ne peut pas se connecter.
    """
    return await _login_and_commit(
        db,
        auth_service.login_with_backup_code(db, request, body.email, body.password, body.code),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.logout(db, current_user)
    await db.commit()


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("refresh", *settings.RATE_LIMIT_REFRESH))],
)
async def refresh_token(
    body: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tokens = await auth_service.refresh(db, body.refresh_token)
    await db.commit()
    return tokens


# ---------- Vérification d'adresse ----------

@router.post(
    "/verify-email",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("token", *settings.RATE_LIMIT_TOKEN))],
)
async def verify_email(
    request: Request,
    body: EmailVerifyRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Valide le code reçu par e-mail et renvoie directement un couple de jetons :
    l'utilisateur enchaîne sur l'accueil sans repasser par l'écran de connexion.

    Le commit sur le chemin d'erreur est indispensable — sans lui, le compteur
    de tentatives serait annulé par le rollback et le code deviendrait
    forçable à l'infini.
    """
    return await _login_and_commit(
        db, auth_service.verify_email(db, request, body.email, body.code)
    )


@router.post(
    "/resend-verification",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("resend_otp", *settings.RATE_LIMIT_RESEND_OTP))],
)
async def resend_verification(
    body: ResendVerificationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    requested = await auth_service.resend_verification_code(db, body.email)
    await db.commit()

    if requested is not None:
        user, code = requested
        await send_email_verification(user.email, user.full_name or user.username, code)

    # Réponse identique quel que soit l'état du compte : la différencier
    # révélerait quelles adresses existent et lesquelles sont déjà vérifiées.
    return {"message": "Si un compte est en attente de vérification, un nouveau code vient d'être envoyé."}


# ---------- Mot de passe ----------

@router.post(
    "/forgot-password",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("forgot_password", *settings.RATE_LIMIT_FORGOT_PASSWORD))],
)
async def forgot_password(
    body: PasswordResetRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    requested = await auth_service.request_password_reset(db, body.email)
    await db.commit()

    if requested is not None:
        user, token = requested
        await send_password_reset_email(user.email, user.full_name or user.username, token)

    # Réponse identique que l'adresse existe ou non : la différencier
    # permettrait d'énumérer les comptes.
    return {"message": "Si cette adresse existe, un lien de réinitialisation vient d'être envoyé."}


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("token", *settings.RATE_LIMIT_TOKEN))],
)
async def reset_password(
    body: PasswordReset,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.reset_password(db, body.token, body.new_password)
    await db.commit()
    return {"message": "Mot de passe réinitialisé."}


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    body: PasswordChange,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.change_password(db, current_user, body.current_password, body.new_password)
    await db.commit()
    return {"message": "Mot de passe modifié."}


# ---------- 2FA ----------

@router.post(
    "/2fa/setup",
    response_model=TOTPSetupResponse,
    dependencies=[Depends(rate_limit("totp", *settings.RATE_LIMIT_TOTP))],
)
async def setup_2fa(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: TOTPSetupRequest = TOTPSetupRequest(),
):
    data = await auth_service.setup_totp(db, current_user, body.current_code)
    await db.commit()
    return TOTPSetupResponse(**data)


@router.post(
    "/2fa/enable",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("totp", *settings.RATE_LIMIT_TOTP))],
)
async def enable_2fa(
    body: TOTPVerifyRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.enable_totp(db, current_user, body.code)
    await db.commit()
    return {"message": "Double authentification activée."}


@router.post(
    "/2fa/disable",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("totp", *settings.RATE_LIMIT_TOTP))],
)
async def disable_2fa(
    body: TOTPVerifyRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.disable_totp(db, current_user, body.code)
    await db.commit()
    return {"message": "Double authentification désactivée."}
