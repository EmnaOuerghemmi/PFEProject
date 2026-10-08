import os
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import permissions_de, require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.agent import PaginatedAuditLogs
from app.schemas.user import (
    PaginatedUsers,
    UserAdminUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)

from app.services.agent_service import user_service
from app.services.report_service import auth_service
from app.schemas.user_profile import UserProfile
from app.services.user_profile_service import user_profile_service

router = APIRouter()


# ---------- /me ----------

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: Annotated[User, Depends(get_current_active_user)]):
    return current_user


@router.get("/me/permissions")
async def get_my_permissions(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Ce que le rôle de l'appelant autorise, ressource par ressource.

    Sert à l'INTERFACE : masquer une entrée de menu que l'utilisateur ne peut
    pas ouvrir vaut mieux que le laisser cliquer et tomber sur un écran vide
    rempli d'un 403. Ce n'est pas un contrôle — chaque requête reste vérifiée
    côté serveur, et un client qui mentirait sur ses permissions n'obtiendrait
    rien de plus.

    `{"*": ["*"]}` signifie « tout » : le périmètre de l'administrateur ne
    s'énumère pas.
    """
    if current_user.is_superuser:
        return {"role": current_user.role, "permissions": {"*": ["*"]}}
    return {
        "role": current_user.role,
        "permissions": permissions_de(current_user.role),
    }


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: UserUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await user_service.update_me(db, current_user, body)
    await db.commit()
    await db.refresh(user)
    return user


_AVATAR_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "static", "avatars")
_ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
# Une photo de smartphone pèse couramment 3 à 8 Mo : 2 Mo refusait la plupart
# des vraies photos. 10 Mo reste très en deçà du plafond de 25 Mo de nginx.
_MAX_SIZE = 10 * 1024 * 1024
_AVATAR_EXTENSIONS = ("jpg", "png", "webp")


def _image_extension(data: bytes) -> str | None:
    """Extension déduite des premiers octets, jamais du nom ni du type déclarés.

    Les fichiers sont servis tels quels depuis /static : une extension reprise
    du nom (« photo.html ») ferait servir du HTML sous notre propre domaine.
    """
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _version_photo() -> int:
    return int(time.time())


@router.post("/me/avatar", response_model=UserResponse)
async def upload_my_avatar(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Format non accepté (JPEG, PNG ou WebP).")
    # Lecture bornée : un fichier énorme est refusé sans être chargé en entier.
    data = await file.read(_MAX_SIZE + 1)
    if len(data) > _MAX_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Image trop lourde ({_MAX_SIZE // (1024 * 1024)} Mo maximum).")
    ext = _image_extension(data)
    if ext is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Format non accepté (JPEG, PNG ou WebP).")

    filename = f"{current_user.id}.{ext}"
    os.makedirs(_AVATAR_DIR, exist_ok=True)
    dest = os.path.join(_AVATAR_DIR, filename)
    with open(dest, "wb") as f:
        f.write(data)
    # Une ancienne photo d'un autre format ne doit pas rester sur le disque.
    for autre in _AVATAR_EXTENSIONS:
        if autre != ext:
            try:
                os.remove(os.path.join(_AVATAR_DIR, f"{current_user.id}.{autre}"))
            except FileNotFoundError:
                pass

    base = str(request.base_url).rstrip("/")
    # Le fichier garde le même nom d'un envoi à l'autre : sans ce paramètre, le
    # navigateur continuerait d'afficher l'ancienne photo, mise en cache.
    avatar_url = f"{base}/static/avatars/{filename}?v={_version_photo()}"
    user = await user_service.update_me(db, current_user, UserUpdate(avatar_url=avatar_url))
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Self-service account deletion (profile "Danger zone").
    Soft-deletes the account and revokes the active session. The superadmin
    account is protected and cannot be self-deleted.
    """
    # La révocation des jetons (renouvellement ET accès déjà émis) est portée
    # par `soft_delete`, pour valoir aussi bien ici que sur la suppression
    # effectuée par un administrateur.
    await user_service.soft_delete(db, current_user.id, current_user)
    await db.commit()


# ---------- Admin: list & create ----------

@router.get(
    "",
    response_model=PaginatedUsers,
    dependencies=[Depends(require("users", "read"))],
)
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    role: str | None = None,
    ministry: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
):
    total, users = await user_service.list_users(db, page, size, role, ministry, is_active, search)
    return PaginatedUsers(total=total, page=page, size=size, items=users)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("users", "write"))],
)
async def create_user(
    body: UserCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user, _verification_token = await auth_service.register(
        db,
        email=body.email,
        username=body.username,
        password=body.password,
        full_name=body.full_name,
        role=body.role,
        created_by=current_user.id,
    )
    await db.commit()
    await db.refresh(user)
    return user


# ---------- Audit logs ----------
#
# ATTENTION à l'ordre : ces routes DOIVENT précéder `/{user_id}`. FastAPI
# résout les chemins dans l'ordre de déclaration, si bien que `/audit-logs`
# était capté par `/{user_id}` et échouait en 422 (« audit-logs » n'est pas un
# UUID) — la page d'audit de l'administration était donc inutilisable.

@router.get(
    "/audit-logs",
    response_model=PaginatedAuditLogs,
    dependencies=[Depends(require("users", "read"))],
)
async def get_audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: UUID | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    total, logs = await user_service.get_audit_logs(db, user_id, page, size)
    return PaginatedAuditLogs(total=total, page=page, size=size, items=logs)


@router.get("/me/audit-logs", response_model=PaginatedAuditLogs)
async def get_my_audit_logs(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    total, logs = await user_service.get_audit_logs(db, current_user.id, page, size)
    return PaginatedAuditLogs(total=total, page=page, size=size, items=logs)


# ---------- Admin: single user ops ----------

@router.get(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require("users", "read"))],
)
async def get_user(user_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    return await user_service.get_by_id(db, user_id)


@router.get(
    "/{user_id}/profile",
    response_model=UserProfile,
    dependencies=[Depends(require("users", "read"))],
)
async def get_user_profile(
    user_id: UUID, db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Fiche complète d'un utilisateur.

    Deux formes selon la personne : un candidat amène son dossier, ses
    candidatures, ses scores et l'état de ses tests ; toute autre personne
    s'arrête à son compte. Rendre des sections vides pour un RH laisserait
    croire à une donnée manquante.

    Aucun secret d'authentification ne sort d'ici — ni mot de passe haché, ni
    secret TOTP, ni jeton. Le schéma les exclut par construction : ce sont des
    moyens d'usurpation, pas des informations de profil.
    """
    fiche = await user_profile_service.build(db, user_id)
    if fiche is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur introuvable.")
    return fiche


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require("users", "write"))],
)
async def admin_update_user(
    user_id: UUID,
    body: UserAdminUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await user_service.admin_update(db, user_id, body, current_user)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("users", "delete"))],
)
async def delete_user(
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await user_service.soft_delete(db, user_id, current_user)
    await db.commit()
