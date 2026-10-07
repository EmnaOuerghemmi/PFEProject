"""Auth service — register, login, logout, token refresh, 2FA, password reset."""
import asyncio
import logging
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import (
    get_login_attempts,
    increment_login_attempts,
    reset_login_attempts,
)
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    dummy_verify_password,
    generate_backup_codes,
    generate_otp_code,
    generate_secure_token,
    generate_totp_secret,
    get_totp_uri,
    hash_backup_code,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_backup_code,
    verify_password,
    verify_token_hash,
    verify_totp,
)
from app.models.user import AuditLog, User, UserRole
from app.schemas.agent import TokenResponse
from app.utils.helpers import as_utc, get_client_ip, utcnow as _utcnow

logger = logging.getLogger(__name__)

# Message unique renvoyé sur tout échec d'identification. Distinguer « adresse
# inconnue » de « mot de passe faux » permettrait d'énumérer les comptes.
_INVALID_CREDENTIALS = "Identifiants invalides."


class AuthService:

    # ---- Registration ----

    async def register(
        self,
        db: AsyncSession,
        email: str,
        username: str,
        password: str,
        full_name: str | None = None,
        role: str = UserRole.CANDIDAT,
        created_by: UUID | None = None,
    ) -> tuple[User, str]:
        """
        Crée un compte et renvoie `(utilisateur, jeton de vérification en clair)`.

        Le jeton n'est lisible qu'ici : la base n'en garde que l'empreinte.
        L'appelant l'expédie par e-mail.

        `role` n'est PAS pilotable par l'inscription publique — seule la route
        d'administration `POST /users` le transmet. Cf. `endpoints/auth.py`.
        """
        await self._assert_email_unique(db, email)
        await self._assert_username_unique(db, username)

        if not validate_password_strength(password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mot de passe trop faible.")

        if role not in UserRole.ALL:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rôle inconnu.")

        user = User(
            email=email,
            username=username,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=role,
            is_active=True,
            is_verified=False,
            created_by=created_by,
        )
        code = self._issue_verification_code(user)
        db.add(user)
        await db.flush()
        await self._log(db, user.id, "REGISTER", "user", str(user.id))
        return user, code

    # ---- Login ----

    async def login(
        self,
        db: AsyncSession,
        request: Request,
        email: str,
        password: str,
        totp_code: str | None = None,
    ) -> TokenResponse:
        """
        Vérifie les identifiants et délivre un couple de jetons.

        CONTRAT D'APPEL — important : en cas d'échec, cette méthode écrit en
        base (compteur `failed_login_attempts`, `locked_until`, journal
        d'audit) AVANT de lever son exception. L'appelant doit donc committer
        la session sur le chemin d'erreur, sinon `get_db` annule tout et le
        verrouillage de compte ne s'applique jamais. Cf. `endpoints/auth.py`.
        """
        ip = get_client_ip(request)
        attempts = await get_login_attempts(ip)

        if attempts >= settings.MAX_LOGIN_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Trop de tentatives. Réessayez dans {settings.LOCKOUT_MINUTES} minutes.",
            )

        user = await self._get_user_by_email(db, email)

        if not user or not user.hashed_password:
            # Compte inconnu, ou compte OAuth sans mot de passe : on calcule
            # quand même une empreinte bcrypt pour que la durée de réponse soit
            # indiscernable de celle d'un mot de passe faux.
            dummy_verify_password(password)
            await increment_login_attempts(ip)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)

        if not verify_password(password, user.hashed_password):
            await self._register_failed_attempt(db, user, ip, "LOGIN_FAIL")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)

        self._assert_account_usable(user)

        # 2FA. Un code faux compte comme un échec d'identification : sans cela,
        # un mot de passe volé donne un nombre illimité d'essais sur 6 chiffres.
        if user.totp_enabled:
            if not totp_code:
                # 428 plutôt que 401 : le mot de passe est bon, il manque
                # seulement le second facteur. Ce code distinct évite au client
                # d'avoir à reconnaître l'étape en analysant le texte du
                # message — couplage qui cassait à la moindre reformulation.
                raise HTTPException(
                    status.HTTP_428_PRECONDITION_REQUIRED,
                    "Code de double authentification requis.",
                )
            if not verify_totp(user.totp_secret, totp_code):
                await self._register_failed_attempt(db, user, ip, "LOGIN_FAIL_2FA")
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code de double authentification invalide.")

        return await self._complete_login(db, user, ip, "LOGIN_SUCCESS")

    async def login_with_backup_code(
        self,
        db: AsyncSession,
        request: Request,
        email: str,
        password: str,
        code: str,
    ) -> TokenResponse:
        """
        Connexion avec un code de secours, quand l'application TOTP est perdue.

        Cette route remplace l'ancienne `/2fa/backup`, qui exigeait un jeton
        d'accès valide : elle était donc inatteignable, puisqu'on a précisément
        besoin d'un code de secours lorsqu'on ne peut PAS finir de se connecter.
        Même contrat de commit que `login` en cas d'échec.
        """
        ip = get_client_ip(request)

        user = await self._get_user_by_email(db, email)
        if not user or not user.hashed_password:
            dummy_verify_password(password)
            await increment_login_attempts(ip)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)

        if not verify_password(password, user.hashed_password):
            await self._register_failed_attempt(db, user, ip, "LOGIN_FAIL")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)

        self._assert_account_usable(user)

        if not user.totp_enabled:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "La double authentification n'est pas active.")

        if not self._consume_backup_code(user, code):
            await self._register_failed_attempt(db, user, ip, "BACKUP_CODE_FAIL")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code de secours invalide.")

        await self._log(db, user.id, "BACKUP_CODE_USED", "user", str(user.id), {"ip": ip})
        return await self._complete_login(db, user, ip, "LOGIN_SUCCESS_BACKUP_CODE")

    # ---- Google OAuth Login ----

    async def google_login(
        self,
        db: AsyncSession,
        request: Request,
        id_token: str,
    ) -> TokenResponse:
        """Connexion (ou inscription) via Google OAuth."""
        user_info = await self._verify_google_token(id_token)

        google_id = user_info.get("sub")
        email = user_info.get("email")
        full_name = user_info.get("name")

        if not google_id or not email:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Données Google incomplètes.")

        # Google peut émettre un jeton pour une adresse non vérifiée (comptes
        # Workspace, fédération tierce). L'accepter permettrait de revendiquer
        # l'adresse de quelqu'un d'autre, donc de prendre le contrôle du compte
        # local correspondant lors de la liaison ci-dessous.
        if not user_info.get("email_verified"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Adresse Google non vérifiée.")

        # Recherche par google_id, puis repli sur l'adresse e-mail.
        result = await db.execute(
            select(User).where(User.google_id == google_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()

        if not user:
            result = await db.execute(
                select(User).where(User.email == email, User.deleted_at.is_(None))
            )
            user = result.scalar_one_or_none()

        ip = get_client_ip(request)

        if not user:
            user = User(
                email=email,
                username=await self._unique_username_from_email(db, email),
                full_name=full_name,
                google_id=google_id,
                oauth_provider="google",
                hashed_password=None,  # les comptes OAuth n'ont pas de mot de passe
                is_active=True,
                is_verified=True,  # l'adresse est vérifiée côté Google (contrôlé plus haut)
                role=UserRole.CANDIDAT,
            )
            db.add(user)
            await db.flush()
            await self._log(db, user.id, "GOOGLE_REGISTER", "user", str(user.id))
        else:
            # Un compte désactivé ou verrouillé ne doit pas pouvoir contourner
            # le contrôle par la porte OAuth — c'était le cas jusqu'ici.
            self._assert_account_usable(user)
            if not user.google_id:
                user.google_id = google_id
                user.oauth_provider = "google"
                await self._log(db, user.id, "GOOGLE_LINKED", "user", str(user.id))

        return await self._complete_login(db, user, ip, "LOGIN_SUCCESS_GOOGLE")

    async def _verify_google_token(self, id_token: str) -> dict:
        """Valide un jeton d'identité Google et renvoie ses revendications."""
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token as google_id_token

        if not settings.GOOGLE_CLIENT_ID:
            # `verify_oauth2_token` ignore le contrôle d'audience si celle-ci est
            # vide : tout jeton Google, émis pour n'importe quelle application,
            # serait alors accepté. On refuse plutôt que de valider à l'aveugle.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Connexion Google non configurée sur ce serveur.",
            )

        def _verify() -> dict:
            return google_id_token.verify_oauth2_token(
                id_token, GoogleRequest(), audience=settings.GOOGLE_CLIENT_ID
            )

        try:
            # `verify_oauth2_token` fait un appel HTTP bloquant (récupération des
            # clés publiques Google) : l'exécuter directement dans la coroutine
            # bloquait la boucle d'événements à chaque connexion.
            idinfo = await asyncio.to_thread(_verify)

            if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
                raise ValueError("émetteur inattendu")
            if idinfo.get("aud") != settings.GOOGLE_CLIENT_ID:
                raise ValueError("audience inattendue")
            return idinfo
        except HTTPException:
            raise
        except Exception as exc:
            # Le détail reste côté serveur : le renvoyer au client exposait la
            # configuration interne (client_id attendu, message de la librairie).
            logger.warning("Échec de validation d'un jeton Google : %s", type(exc).__name__)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton Google invalide.")

    # ---- Logout ----

    async def logout(self, db: AsyncSession, user: User) -> None:
        user.refresh_token = None
        user.refresh_token_expires_at = None
        # Coupe aussi les jetons d'accès déjà émis : sans cela, celui que le
        # client vient d'utiliser restait accepté jusqu'à 30 minutes après la
        # déconnexion.
        self._revoke_issued_tokens(user)
        await self._log(db, user.id, "LOGOUT", "user", str(user.id))

    # ---- Refresh ----

    async def refresh(self, db: AsyncSession, refresh_token: str) -> TokenResponse:
        try:
            payload = decode_token(refresh_token)
        except Exception:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton de renouvellement invalide.")

        if payload.get("type") != "refresh":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Type de jeton invalide.")

        try:
            user_id = UUID(str(payload.get("sub")))
        except (ValueError, TypeError):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton de renouvellement invalide.")

        user = await self._get_user_by_id(db, user_id)
        if not user or not user.refresh_token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée.")

        if not verify_token_hash(refresh_token, user.refresh_token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton de renouvellement non reconnu.")

        expires_at = as_utc(user.refresh_token_expires_at)
        if expires_at and _utcnow() > expires_at:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton de renouvellement expiré.")

        # Un jeton émis avant la dernière coupure de session (déconnexion,
        # changement de mot de passe) ne doit plus rien renouveler.
        if user.is_token_revoked(payload.get("iat")):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session révoquée.")

        # Désactivation ou verrouillage : le contrôle n'existait que sur /login,
        # si bien qu'un compte désactivé se renouvelait indéfiniment des jetons.
        self._assert_account_usable(user)

        # Rotation
        tokens = self._issue_tokens(user)
        user.refresh_token = hash_token(tokens.refresh_token)
        user.refresh_token_expires_at = _utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        await self._log(db, user.id, "TOKEN_REFRESH", "user", str(user.id))
        return tokens

    # ---- Email verification ----

    def _issue_verification_code(self, user: User) -> str:
        """
        Pose un nouveau code de vérification sur le compte et le renvoie en clair.

        La base n'en conserve que l'empreinte HMAC : le code lui-même ne
        circule que dans l'e-mail. Le compteur de tentatives repart de zéro,
        sinon un compte ayant épuisé son quota resterait bloqué à jamais.
        """
        code = generate_otp_code(settings.EMAIL_OTP_LENGTH)
        user.email_verification_token = hash_token(code)
        user.email_verification_expires_at = _utcnow() + timedelta(
            minutes=settings.EMAIL_OTP_EXPIRE_MINUTES
        )
        user.email_verification_attempts = 0
        return code

    async def verify_email(
        self, db: AsyncSession, request: Request, email: str, code: str
    ) -> TokenResponse:
        """
        Valide le code reçu par e-mail et ouvre la session dans la foulée.

        La recherche se fait par ADRESSE, jamais par code seul : six chiffres
        ne sont pas discriminants à l'échelle de la base, et un code tiré au
        hasard finirait par tomber sur le compte d'un inconnu.

        MÊME CONTRAT DE COMMIT QUE `login` : le compteur de tentatives est
        écrit avant que l'exception ne soit levée, l'appelant doit donc
        committer sur le chemin d'erreur.
        """
        user = await self._get_user_by_email(db, email)
        if not user:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code de vérification invalide.")

        if user.is_verified:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cette adresse est déjà vérifiée.")

        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Compte désactivé.")

        if not user.email_verification_token:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Aucun code en attente. Demandez l'envoi d'un nouveau code.",
            )

        if (user.email_verification_attempts or 0) >= settings.EMAIL_OTP_MAX_ATTEMPTS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Trop de tentatives. Demandez l'envoi d'un nouveau code.",
            )

        expires_at = as_utc(user.email_verification_expires_at)
        if expires_at and _utcnow() > expires_at:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Code expiré. Demandez l'envoi d'un nouveau code.",
            )

        # Comparaison à temps constant, sur les empreintes (cf. `verify_token_hash`).
        if not verify_token_hash(code, user.email_verification_token):
            user.email_verification_attempts = (user.email_verification_attempts or 0) + 1
            restantes = settings.EMAIL_OTP_MAX_ATTEMPTS - user.email_verification_attempts
            await self._log(db, user.id, "EMAIL_VERIFY_FAIL", "user", str(user.id))
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Code invalide. Il vous reste {max(restantes, 0)} tentative(s).",
            )

        user.is_verified = True
        user.email_verification_token = None
        user.email_verification_expires_at = None
        user.email_verification_attempts = 0
        await self._log(db, user.id, "EMAIL_VERIFIED", "user", str(user.id))

        # Le compte vient d'être créé par cette même personne, qui prouve à
        # l'instant qu'elle contrôle l'adresse : on enchaîne sur la session
        # plutôt que de la renvoyer ressaisir son mot de passe.
        return await self._complete_login(db, user, get_client_ip(request), "LOGIN_SUCCESS_AFTER_VERIFY")

    async def resend_verification_code(self, db: AsyncSession, email: str) -> tuple[User, str] | None:
        """
        Régénère un code et le renvoie pour expédition.

        `None` si l'adresse est inconnue ou déjà vérifiée — sans le dire au
        client, cette route ne devant pas permettre de savoir quelles adresses
        existent.
        """
        user = await self._get_user_by_email(db, email)
        if not user or user.is_verified or not user.is_active:
            return None
        code = self._issue_verification_code(user)
        await self._log(db, user.id, "EMAIL_VERIFY_RESEND", "user", str(user.id))
        return user, code

    # ---- Password reset ----

    async def request_password_reset(self, db: AsyncSession, email: str) -> tuple[User, str] | None:
        """
        Prépare une réinitialisation et renvoie `(utilisateur, jeton en clair)`.

        L'appelant est chargé d'expédier le jeton par e-mail : il n'est renvoyé
        qu'ici et n'existe nulle part ailleurs en clair. `None` si l'adresse est
        inconnue — sans le dire au client, pour ne pas énumérer les comptes.
        """
        user = await self._get_user_by_email(db, email)
        if not user:
            return None
        token = generate_secure_token()
        user.password_reset_token = hash_token(token)
        user.password_reset_expires_at = _utcnow() + timedelta(hours=1)
        await self._log(db, user.id, "PASSWORD_RESET_REQUEST", "user", str(user.id))
        return user, token

    async def reset_password(self, db: AsyncSession, token: str, new_password: str) -> None:
        if not validate_password_strength(new_password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mot de passe trop faible.")

        result = await db.execute(
            select(User).where(User.password_reset_token == hash_token(token))
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Jeton invalide.")

        expires_at = as_utc(user.password_reset_expires_at)
        if expires_at and _utcnow() > expires_at:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Jeton expiré.")

        user.hashed_password = hash_password(new_password)
        user.password_reset_token = None
        user.password_reset_expires_at = None
        user.refresh_token = None
        user.refresh_token_expires_at = None
        # Reprendre la main sur son compte doit aussi lever un éventuel
        # verrouillage anti-bruteforce, sinon l'utilisateur reste bloqué.
        user.failed_login_attempts = 0
        user.locked_until = None
        self._revoke_issued_tokens(user)
        await self._log(db, user.id, "PASSWORD_RESET", "user", str(user.id))

    async def change_password(self, db: AsyncSession, user: User, current: str, new: str) -> None:
        if not user.hashed_password:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Ce compte n'a pas de mot de passe (connexion Google).",
            )
        if not verify_password(current, user.hashed_password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mot de passe actuel incorrect.")
        if not validate_password_strength(new):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mot de passe trop faible.")
        user.hashed_password = hash_password(new)
        user.refresh_token = None
        user.refresh_token_expires_at = None
        self._revoke_issued_tokens(user)
        await self._log(db, user.id, "PASSWORD_CHANGE", "user", str(user.id))

    # ---- 2FA ----

    async def setup_totp(self, db: AsyncSession, user: User, current_code: str | None = None) -> dict:
        """
        Génère un nouveau secret TOTP et un nouveau jeu de codes de secours.

        Quand la 2FA est DÉJÀ active, un code valide est exigé : sans ce
        contrôle, un jeton d'accès volé suffisait à réinitialiser le secret —
        cassant l'application d'authentification de la victime — et à repartir
        avec dix codes de secours tout neufs.
        """
        was_enabled = user.totp_enabled
        if was_enabled:
            if not current_code or not verify_totp(user.totp_secret, current_code):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Double authentification déjà active : fournissez un code valide pour la réinitialiser.",
                )

        secret = generate_totp_secret()
        uri = get_totp_uri(secret, user.email)
        plain_codes = generate_backup_codes(settings.TOTP_BACKUP_CODES_COUNT)

        user.totp_secret = secret
        user.totp_backup_codes = [hash_backup_code(c) for c in plain_codes]

        if was_enabled:
            # Le nouveau secret écrase l'ancien immédiatement : laisser
            # `totp_enabled` à True enfermerait dehors quiconque abandonne
            # avant d'avoir scanné le nouveau QR code — son application
            # produirait des codes désormais invalides, et les codes de secours
            # viennent eux aussi d'être remplacés. On suspend donc la
            # protection jusqu'à confirmation par `enable_totp`.
            user.totp_enabled = False
            await self._log(db, user.id, "TOTP_RESET", "user", str(user.id))

        await self._log(db, user.id, "TOTP_SETUP_INIT", "user", str(user.id))

        return {"secret": secret, "provisioning_uri": uri, "backup_codes": plain_codes}

    async def enable_totp(self, db: AsyncSession, user: User, code: str) -> None:
        if not user.totp_secret:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Initialisez d'abord la double authentification.")
        if not verify_totp(user.totp_secret, code):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code invalide.")
        user.totp_enabled = True
        # Pas de révocation des jetons ici, contrairement au changement de mot
        # de passe : aucune donnée d'authentification existante n'est
        # compromise, et déconnecter l'utilisateur dans la seconde qui suit son
        # activation serait déroutant. La désactivation, elle, exige déjà un
        # code valide — un jeton volé seul ne permet pas d'y toucher.
        await self._log(db, user.id, "TOTP_ENABLED", "user", str(user.id))

    async def disable_totp(self, db: AsyncSession, user: User, code: str) -> None:
        if not user.totp_enabled:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "La double authentification n'est pas active.")
        if not verify_totp(user.totp_secret, code):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code invalide.")
        user.totp_enabled = False
        user.totp_secret = None
        user.totp_backup_codes = []
        await self._log(db, user.id, "TOTP_DISABLED", "user", str(user.id))

    # ---- Helpers ----

    def _consume_backup_code(self, user: User, plain_code: str) -> bool:
        """
        Retire le code de secours correspondant et signale s'il a été trouvé.

        La liste de remplacement est un OBJET NEUF, et c'est essentiel : muter
        en place la liste portée par la colonne JSON (`stored.pop(i)` suivi
        d'une ré-assignation du même objet) ne déclenche aucune détection de
        changement côté SQLAlchemy. Rien n'était écrit, et le même code de
        secours restait utilisable indéfiniment.
        """
        stored: list[str] = list(user.totp_backup_codes or [])
        for i, hashed in enumerate(stored):
            if verify_backup_code(plain_code, hashed):
                user.totp_backup_codes = stored[:i] + stored[i + 1:]
                return True
        return False

    def _assert_account_usable(self, user: User) -> None:
        """Contrôles d'état communs à toutes les voies d'entrée (mot de passe, Google, refresh)."""
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Compte désactivé.")
        if user.is_locked:
            raise HTTPException(status.HTTP_423_LOCKED, "Compte temporairement verrouillé.")
        if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_verified:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Adresse e-mail non vérifiée.")

    def _revoke_issued_tokens(self, user: User) -> None:
        """
        Invalide tous les jetons d'accès déjà signés pour cet utilisateur.

        La seconde d'avance est volontaire : l'`iat` d'un JWT est en secondes
        entières, donc un jeton émis dans la même seconde que la révocation
        survivrait à une comparaison stricte.
        """
        user.tokens_valid_from = _utcnow() + timedelta(seconds=1)

    async def _register_failed_attempt(
        self, db: AsyncSession, user: User, ip: str, action: str
    ) -> None:
        """Incrémente les compteurs anti-bruteforce et verrouille au seuil."""
        await increment_login_attempts(ip)
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.locked_until = _utcnow() + timedelta(minutes=settings.LOCKOUT_MINUTES)
        await self._log(db, user.id, action, "user", str(user.id), {"ip": ip})

    async def _complete_login(
        self, db: AsyncSession, user: User, ip: str, action: str
    ) -> TokenResponse:
        """Remise à zéro des compteurs, émission et enregistrement du couple de jetons."""
        await reset_login_attempts(ip)
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = _utcnow()
        user.last_login_ip = ip

        tokens = self._issue_tokens(user)
        user.refresh_token = hash_token(tokens.refresh_token)
        user.refresh_token_expires_at = _utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        await self._log(db, user.id, action, "user", str(user.id), {"ip": ip})
        return tokens

    async def _unique_username_from_email(self, db: AsyncSession, email: str) -> str:
        """
        Dérive un identifiant libre du préfixe de l'adresse.

        `username` porte une contrainte d'unicité : deux comptes Google
        « prenom@a.com » et « prenom@b.com » provoquaient une IntegrityError
        (erreur 500) au second passage.
        """
        base = (email.split("@")[0] or "user")[:90]
        candidate = base
        suffix = 1
        while True:
            exists = await db.execute(select(User.id).where(User.username == candidate))
            if exists.scalar_one_or_none() is None:
                return candidate
            suffix += 1
            candidate = f"{base}{suffix}"

    def _issue_tokens(self, user: User) -> TokenResponse:
        access = create_access_token(
            str(user.id), user.role, user.permissions or {}
        )
        refresh = create_refresh_token(str(user.id))
        return TokenResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def _get_user_by_email(self, db: AsyncSession, email: str) -> User | None:
        result = await db.execute(
            select(User).where(User.email == email, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def _get_user_by_id(self, db: AsyncSession, user_id: UUID) -> User | None:
        result = await db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def _assert_email_unique(self, db: AsyncSession, email: str) -> None:
        result = await db.execute(select(User.id).where(User.email == email))
        if result.scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "Adresse e-mail déjà enregistrée.")

    async def _assert_username_unique(self, db: AsyncSession, username: str) -> None:
        result = await db.execute(select(User.id).where(User.username == username))
        if result.scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "Nom d'utilisateur déjà pris.")

    async def _log(
        self,
        db: AsyncSession,
        user_id: UUID | None,
        action: str,
        resource: str | None = None,
        resource_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        log = AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
        )
        db.add(log)


auth_service = AuthService()
