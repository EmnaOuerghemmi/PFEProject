from pydantic_settings import BaseSettings, NoDecode
from pydantic import ConfigDict, SecretStr, field_validator
from pathlib import Path
from typing import Annotated


class Settings(BaseSettings):
    # App
    APP_NAME: str = "PIQBIT API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    # Niveau du logger racine, appliqué au démarrage (cf. app/main.py).
    # DEBUG pour tracer finement, WARNING pour une sortie silencieuse.
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379"


    # JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"

    # Bcrypt
    BCRYPT_ROUNDS: int = 12

    # Brute-force (/login : compteur par IP + verrouillage du compte en base)
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15

    # Limitation des autres routes d'authentification non protégées par le
    # mécanisme ci-dessus. Format : (nombre d'appels, fenêtre en secondes).
    #   register        — freine la création massive de comptes
    #   forgot-password — freine l'énumération d'e-mails et le mail-bombing
    #   token           — freine le brute-force des jetons de vérification
    #                     et de réinitialisation (reset-password, verify-email)
    #   login           — plafond par IP en complément du compteur anti-bruteforce
    #                     (celui-ci se réinitialise à chaque succès, pas celui-là)
    #   refresh         — freine le rejeu massif de jetons de renouvellement
    #   totp            — freine le brute-force des codes TOTP (6 chiffres) et
    #                     des codes de secours (8 caractères)
    RATE_LIMIT_REGISTER: tuple[int, int] = (10, 3600)
    RATE_LIMIT_FORGOT_PASSWORD: tuple[int, int] = (3, 600)
    RATE_LIMIT_TOKEN: tuple[int, int] = (10, 600)
    RATE_LIMIT_LOGIN: tuple[int, int] = (30, 600)
    RATE_LIMIT_REFRESH: tuple[int, int] = (60, 600)
    RATE_LIMIT_TOTP: tuple[int, int] = (10, 600)

    # Exige un e-mail vérifié pour se connecter. Laissé à False par défaut :
    # activer sur une base existante déconnecterait tous les comptes créés
    # avant la mise en service de l'envoi d'e-mails.
    REQUIRE_EMAIL_VERIFICATION: bool = False

    # Compte superadmin créé au démarrage. AUCUNE valeur par défaut pour le mot
    # de passe : sans SUPERADMIN_PASSWORD dans l'environnement, la création est
    # simplement ignorée. Un identifiant en dur dans le code se retrouverait
    # dans l'historique Git, donc public.
    SUPERADMIN_EMAIL: str = ""
    SUPERADMIN_USERNAME: str = "superadmin"
    SUPERADMIN_PASSWORD: str = ""

    # Racine du frontend, utilisée pour bâtir les liens envoyés par e-mail
    # (vérification d'adresse, réinitialisation de mot de passe).
    FRONTEND_BASE_URL: str = "http://localhost:4200"

    # 2FA
    TOTP_ISSUER: str = "PIQBIT"
    TOTP_EXPIRE_SECONDS: int = 300  # 5 min
    TOTP_BACKUP_CODES_COUNT: int = 10

    # Vérification d'adresse par code à usage unique (OTP) envoyé par e-mail.
    # Un code court se force en 10^6 essais : la fenêtre de validité est donc
    # brève et le nombre de tentatives plafonné PAR COMPTE (le plafond par IP
    # ne suffirait pas, l'attaquant pouvant changer d'adresse source).
    EMAIL_OTP_LENGTH: int = 6
    EMAIL_OTP_EXPIRE_MINUTES: int = 15
    EMAIL_OTP_MAX_ATTEMPTS: int = 5
    RATE_LIMIT_RESEND_OTP: tuple[int, int] = (5, 900)

    # Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAILS_FROM_EMAIL: str = "noreply@piqbit.tn"
    EMAILS_FROM_NAME: str = "PIQBIT"

    # Société (en-tête des contrats de travail)
    COMPANY_NAME: str = "PIQBIT Lab"
    COMPANY_MANAGER: str = "Mohamed Derbali"       # le gérant
    COMPANY_TAX_ID: str = ""                        # matricule fiscal (optionnel)
    COMPANY_ADDRESS: str = "Tunis, Tunisie"
    COMPANY_CITY: str = "Tunis"

    # Anthropic / Claude (optional — features degrade gracefully if unset)
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # Google Gemini (optional — free-tier alternative to Claude; same graceful degradation)
    #
    # Le nom du modèle N'EST PAS un détail. Deux pièges déjà rencontrés ici :
    #
    # 1. Google retire ses anciennes versions sans préavis utile —
    #    `gemini-2.0-flash` a été mis hors service et renvoie un 404, que le
    #    client attrape, si bien qu'un appel échoué rendait simplement « rien
    #    d'exploitable » sans jamais dire pourquoi.
    # 2. Les variantes « pensantes » (`gemini-3.6-flash` compris) consomment
    #    la majeure partie de `max_output_tokens` en RÉFLEXION INTERNE
    #    invisible avant d'écrire la réponse visible — mesuré : 1212 jetons
    #    consommés pour 185 de texte réel. La réponse arrivait alors coupée en
    #    plein milieu du JSON, quelle que soit la marge demandée. Le SDK
    #    installé (`google-generativeai` 0.8.5) ne permet pas de désactiver
    #    cette réflexion (`thinking_config` lève une erreur). Les variantes
    #    « -lite » n'en font pas : mesuré, la même requête n'y consomme aucun
    #    jeton de réflexion.
    #
    # Avant de changer ce nom, vérifier le comportement réel avec
    # `usage_metadata` (`total_token_count` très supérieur à
    # `candidates_token_count` = réflexion cachée) plutôt que de supposer
    # qu'une version plus récente se comporte comme la précédente.
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:3000/api/v1/auth/google/callback"

    # Embeddings / matching sémantique
    # Backend : "auto" (sentence-transformers si dispo, sinon hash), "model", "hash".
    EMBEDDINGS_BACKEND: str = "auto"
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIM: int = 384
    # Jeton Hugging Face, facultatif : le modèle d'embeddings est public, mais un
    # jeton relève les quotas de téléchargement et débloque les dépôts privés.
    # `SecretStr` garantit qu'il n'apparaît ni dans un `repr()`, ni dans un log,
    # ni dans une trace d'exception. `embedding_service` l'exporte vers
    # l'environnement au chargement du modèle — `huggingface_hub` ne lit QUE
    # `os.environ`, jamais le `.env` (que seul pydantic-settings interprète).
    HF_TOKEN: SecretStr | None = None

    # Google Calendar (optional — interview sync degrades gracefully if unset)
    # Path to the service-account JSON key downloaded from Google Cloud Console.
    GOOGLE_CALENDAR_CREDENTIALS_FILE: str = ""
    # Calendar to write into: "primary" (with impersonation) or the calendar id
    # (e.g. xxxx@group.calendar.google.com) shared with the service account.
    GOOGLE_CALENDAR_ID: str = ""
    # Optional Workspace user to impersonate (domain-wide delegation).
    GOOGLE_CALENDAR_IMPERSONATE: str = ""
    GOOGLE_CALENDAR_TIMEZONE: str = "Africa/Tunis"

    # ─── Lien visio des entretiens ───────────────────────────────────────
    # À la confirmation d'un créneau, un lien de visioconférence est généré et
    # figé sur l'invitation. Google Meet est demandé à l'événement Google
    # Calendar quand la délégation domaine le permet ; sinon on retombe sur une
    # salle Jitsi Meet, dérivée du token de l'invitation (URL-safe, unique,
    # non devinable). Un email « rejoindre maintenant » part ensuite N minutes
    # avant l'heure de l'entretien, au candidat, au RH et au superadmin.
    INTERVIEW_MEET_REMINDER_MINUTES: int = 8
    INTERVIEW_MEET_JITSI_BASE: str = "https://meet.jit.si"
    INTERVIEW_MEET_FALLBACK_ENABLED: bool = True

    # ─── Test technique ────────────────────────────────────────────────────
    # Score de CV minimal pour qu'un test technique soit proposé. Le seuil est
    # ici, et non dans le gabarit du navigateur : c'est une règle métier, et un
    # chiffre qui vit côté client finit toujours par diverger de celui du
    # serveur. L'API renvoie l'éligibilité déjà calculée.
    TEST_ELIGIBILITY_MIN_SCORE: float = 50.0

    # ─── CORS ──────────────────────────────────────────────────────────────
    # Origines autorisées à appeler l'API depuis un navigateur. Renseigner en
    # production le(s) domaine(s) du frontend, séparés par des virgules :
    #   ALLOWED_ORIGINS=https://app.piqbit.tn,https://admin.piqbit.tn
    # `NoDecode` désactive le décodage JSON automatique que pydantic-settings
    # applique aux types complexes AVANT les validateurs : sans lui, une valeur
    # « a,b » lève une JSONDecodeError et le validateur ci-dessous n'est jamais
    # atteint.
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:4200",
        "http://localhost:3000",
    ]

    # Autorise TOUT port de localhost/127.0.0.1 (previews Angular, second
    # `ng serve`…). Pratique en développement, à passer à False en production
    # où seule la liste ALLOWED_ORIGINS doit faire foi.
    ALLOW_LOCALHOST_ORIGINS: bool = True

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value):
        """
        Accepte trois écritures, les variables d'environnement (Docker,
        systemd, CI) ne sachant transporter que des chaînes :
          - liste séparée par des virgules : a,b        <- forme recommandée
          - tableau JSON                   : ["a","b"]  <- rétrocompatibilité
          - chaîne vide                    : aucune origine autorisée

        Le parsing JSON est fait ici explicitement : `NoDecode` sur le champ
        désactive celui de pydantic-settings, sinon la forme à virgules
        échouerait avant d'atteindre ce validateur.
        """
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            import json
            return json.loads(stripped)
        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"dev", "development"}:
                return True
        return value

    model_config = ConfigDict(
        env_file=str(Path(__file__).parent.parent.parent / ".env"),
        case_sensitive=True
    )


settings = Settings()
