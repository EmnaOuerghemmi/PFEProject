"""User CRUD service — list, get, update, delete, audit logs."""
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recruitment import Candidate
from app.models.user import AuditLog, User
from app.schemas.user import UserAdminUpdate, UserUpdate


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


#: Familles d'actions du journal d'audit, pour le filtrer à l'écran.
AUDIT_CATEGORIES: dict[str, tuple[str, ...]] = {
    "connexions": (
        "LOGIN_SUCCESS", "LOGIN_SUCCESS_GOOGLE", "LOGIN_SUCCESS_BACKUP_CODE",
        "LOGIN_SUCCESS_AFTER_VERIFY", "LOGIN_FAIL", "LOGIN_FAIL_2FA", "LOGOUT",
    ),
    "securite": (
        "PASSWORD_CHANGE", "PASSWORD_RESET", "PASSWORD_RESET_REQUEST",
        "TOTP_SETUP_INIT", "TOTP_ENABLED", "TOTP_DISABLED", "TOTP_RESET",
        "BACKUP_CODE_USED", "BACKUP_CODE_FAIL",
        "EMAIL_VERIFIED", "EMAIL_VERIFY_FAIL", "EMAIL_VERIFY_RESEND",
    ),
    "comptes": (
        "REGISTER", "GOOGLE_REGISTER", "GOOGLE_LINKED",
        "USER_UPDATE_SELF", "USER_ADMIN_UPDATE", "USER_DELETE",
    ),
}


class UserService:

    async def get_by_id(self, db: AsyncSession, user_id: UUID) -> User:
        result = await db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        return user

    async def list_users(
        self,
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
        role: str | None = None,
        ministry: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> tuple[int, list[User]]:
        query = select(User).where(User.deleted_at.is_(None))

        if role:
            query = query.where(User.role == role)
        if ministry:
            query = query.where(User.ministry == ministry)
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        if search:
            term = f"%{search}%"
            query = query.where(
                User.email.ilike(term) | User.username.ilike(term) | User.full_name.ilike(term)
            )

        count_result = await db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar_one()

        query = query.offset((page - 1) * size).limit(size).order_by(User.created_at.desc())
        result = await db.execute(query)
        return total, list(result.scalars().all())

    async def update_me(self, db: AsyncSession, user: User, data: UserUpdate) -> User:
        changes = data.model_dump(exclude_none=True)
        for field, value in changes.items():
            setattr(user, field, value)
        user.updated_at = _utcnow()
        if "full_name" in changes:
            await self._sync_candidate_name(db, user)
        await self._log(db, user.id, "USER_UPDATE_SELF", "user", str(user.id))
        return user

    async def admin_update(
        self, db: AsyncSession, user_id: UUID, data: UserAdminUpdate, acting_user: User
    ) -> User:
        user = await self.get_by_id(db, user_id)
        changes = data.model_dump(exclude_none=True)
        for field, value in changes.items():
            setattr(user, field, value)
        user.updated_by = acting_user.id
        user.updated_at = _utcnow()
        if "full_name" in changes:
            await self._sync_candidate_name(db, user)

        # Désactiver un compte, ou changer son rôle et ses permissions, doit
        # clore les sessions en cours : sinon le jeton d'accès déjà délivré
        # reste utilisable jusqu'à son expiration, avec les anciens droits.
        if {"is_active", "role", "permissions"} & changes.keys():
            self._revoke_sessions(user)

        await self._log(db, acting_user.id, "USER_ADMIN_UPDATE", "user", str(user_id))
        return user

    @staticmethod
    async def _sync_candidate_name(db: AsyncSession, user: User) -> None:
        """
        Répercute le nom du compte sur le dossier candidat.

        Le nom vit à deux endroits : `users.full_name` (le compte, que le
        candidat modifie depuis son profil) et `candidates.full_name` (copié à
        l'inscription, lu par les candidatures, le classement, les contrats).
        Sans cette synchronisation, un candidat renommé restait affiché sous
        son ancien nom dans tout le back-office.
        """
        nom = (user.full_name or "").strip()
        if not nom:
            return
        candidat = (await db.execute(
            select(Candidate).where(Candidate.user_id == user.id)
        )).scalar_one_or_none()
        if candidat and candidat.full_name != nom:
            candidat.full_name = nom

    async def soft_delete(self, db: AsyncSession, user_id: UUID, acting_user: User) -> None:
        user = await self.get_by_id(db, user_id)
        if user.is_superuser:
            raise HTTPException(status_code=403, detail="Cannot delete a superuser.")
        user.deleted_at = _utcnow()
        user.is_active = False
        self._revoke_sessions(user)
        self._release_unique_identifiers(user)
        await self._log(db, acting_user.id, "USER_DELETE", "user", str(user_id))

    @staticmethod
    def _release_unique_identifiers(user: User) -> None:
        """
        Rend au pot commun les identifiants uniques d'un compte supprimé.

        `email`, `username`, `google_id` et `employee_id` portent une contrainte
        d'unicité qui couvre TOUTES les lignes, alors que chaque lecture de
        l'application filtre `deleted_at IS NULL`. Sans cette libération, un
        compte supprimé devient un trou noir : plus personne ne le voit ni ne
        peut s'y connecter, et pourtant son adresse reste à jamais interdite à
        l'inscription — sans le moindre indice pour l'administrateur, puisque
        la liste des utilisateurs ne l'affiche plus.

        On ne réanime pas la ligne pour autant : elle subsiste, anonymisée,
        pour que les entrées d'audit qui la référencent gardent une cible. Une
        réinscription crée un compte neuf, avec un nouvel identifiant — et
        n'hérite donc ni des candidatures ni de l'historique du précédent.
        """
        marker = uuid.uuid4().hex[:12]
        user.email = f"supprime+{marker}@invalide.local"
        user.username = f"supprime_{marker}"
        user.google_id = None
        user.employee_id = None

    @staticmethod
    def _revoke_sessions(user: User) -> None:
        """Coupe le renouvellement ET les jetons d'accès déjà signés."""
        user.refresh_token = None
        user.refresh_token_expires_at = None
        # La seconde d'avance couvre les jetons émis dans la même seconde,
        # l'`iat` d'un JWT n'ayant qu'une résolution d'une seconde.
        user.tokens_valid_from = _utcnow() + timedelta(seconds=1)

    async def get_audit_logs(
        self,
        db: AsyncSession,
        user_id: UUID | None = None,
        page: int = 1,
        size: int = 50,
        *,
        category: str | None = None,
        search: str | None = None,
        failures_only: bool = False,
        include_refresh: bool = False,
    ) -> tuple[int, list[dict]]:
        """
        Journal paginé, du plus récent au plus ancien.

        Chaque ligne porte le nom, l'e-mail et le rôle de son auteur (jointure), pour
        qu'un écran n'ait jamais à afficher un identifiant brut. Les filtres :
        `category` (connexions, sécurité, comptes), `search` (nom, e-mail,
        action ou adresse IP), `failures_only` (tentatives échouées) et
        `include_refresh` (renouvellements de session, masqués par défaut :
        un toutes les quelques minutes, ils noieraient le reste du journal).
        """
        query = select(AuditLog, User.full_name, User.email, User.role).outerjoin(User, AuditLog.user_id == User.id)
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        if not include_refresh:
            query = query.where(AuditLog.action != "TOKEN_REFRESH")
        actions = AUDIT_CATEGORIES.get(category or "")
        if actions:
            query = query.where(AuditLog.action.in_(actions))
        if failures_only:
            query = query.where(AuditLog.action.like("%FAIL%"))
        if search and search.strip():
            motif = f"%{search.strip()}%"
            query = query.where(or_(
                User.full_name.ilike(motif), User.email.ilike(motif),
                AuditLog.action.ilike(motif), AuditLog.ip_address.ilike(motif),
            ))

        count_result = await db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar_one()

        query = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * size).limit(size)
        lignes = (await db.execute(query)).all()
        return total, [
            {
                "id": log.id, "user_id": log.user_id, "action": log.action,
                "resource": log.resource, "resource_id": log.resource_id,
                "details": log.details, "ip_address": log.ip_address,
                "created_at": log.created_at, "user_name": nom, "user_email": email, "user_role": role,
            }
            for log, nom, email, role in lignes
        ]

    async def _log(
        self,
        db: AsyncSession,
        user_id: UUID | None,
        action: str,
        resource: str | None = None,
        resource_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        db.add(AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
        ))


user_service = UserService()
