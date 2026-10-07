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
    COMPANY_NAME: str = "PIQBIT"
    COMPANY_MANAGER: str = "Mohamed Derbali"       # le gérant
    COMPANY_MANAGER_NATIONALITY: str = ""          # ex. « tunisienne » (optionnel)
    COMPANY_MANAGER_ID_DOC: str = ""               # ex. « la CIN n° … » (optionnel)
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

    # ─── Ollama : modèle LOCAL, réservé aux données personnelles ───────────
    # Tout prompt qui contient des données personnelles (texte d'un CV, notes
    # d'entretien, négociation avec un candidat nommé) part vers ce modèle, et
    # vers lui SEUL — voir `app/integrations/llm_router.py`. Sans Ollama, ces
    # fonctionnalités retombent sur leur logique déterministe, jamais sur un
    # service cloud.
    #
    # Modèle par défaut : `qwen2.5:3b` (1,9 Go), choisi pour une machine SANS
    # GPU exploitable. C'est le plus léger des modèles multilingues fiables en
    # JSON, et il ne fait pas de réflexion interne. Un modèle « pensant »
    # (famille qwen3.5…) dépense l'essentiel de son budget à réfléchir — le
    # même piège que Gemini ci-dessus — et multiplie la latence sur processeur.
    # S'il est retenu, passer OLLAMA_DISABLE_THINKING à true.
    #
    # Installation : https://ollama.com, puis `ollama pull qwen2.5:3b`.
    OLLAMA_ENABLED: bool = True
    # 127.0.0.1 et non `localhost` : Ollama écoute en IPv4, et sous Windows
    # `localhost` est d'abord tenté en IPv6 (::1) — une tentative perdue qui
    # coûte ~2 s à chaque sonde quand Ollama est absent.
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    # Inférence sur processeur : une réponse longue (évaluation d'entretien en
    # JSON) peut dépasser la minute. Le délai doit le permettre.
    OLLAMA_TIMEOUT_SECONDS: float = 180.0
    # Garde le modèle en mémoire entre deux appels : le recharger coûte
    # plusieurs dizaines de secondes sur cette machine.
    OLLAMA_KEEP_ALIVE: str = "30m"
    # Fixée explicitement plutôt que laissée au défaut d'Ollama, qui varie
    # selon les versions : un CV tronqué à 4 000 caractères plus les consignes
    # doit tenir dans la fenêtre, sinon le début du prompt est perdu en silence.
    OLLAMA_NUM_CTX: int = 4096
    # N'est transmis à Ollama que s'il vaut true : le comportement du
    # paramètre `think` sur un modèle sans réflexion n'est pas documenté.
    OLLAMA_DISABLE_THINKING: bool = False

    # ─── Détecteur de CV au dépôt (TF-IDF + régression logistique) ─────────
    # Modèle entraîné par `cv_detector/train.py`, chargé depuis ce dossier.
    # Sans modèle sur disque, le détecteur s'efface : le dépôt est accepté et un
    # avertissement est journalisé une fois — même principe que tous les modèles
    # de la plateforme.
    CV_DETECTOR_ENABLED: bool = True
    CV_DETECTOR_MODEL_DIR: str = "cv_detector/models"
    # Probabilité « CV » au-dessus de laquelle le dépôt est accepté sans réserve.
    CV_DETECTOR_ACCEPT_THRESHOLD: float = 0.80
    # En dessous, le dépôt est refusé. Entre les deux seuils, il est ACCEPTÉ :
    # refuser un vrai CV fait perdre un candidat, accepter un non-CV ne coûte
    # au RH qu'un coup d'œil. L'erreur la plus chère est donc celle qu'on évite.
    CV_DETECTOR_REJECT_THRESHOLD: float = 0.50
    # Sous ce nombre de caractères extraits, le document est jugé illisible
    # (scan, image, PDF protégé) : il ne peut ni être vérifié ni être analysé.
    CV_DETECTOR_MIN_TEXT_CHARS: int = 150
    # Vérification préalable du formulaire d'inscription : route publique qui
    # extrait et classe un document de 5 Mo au plus, d'où une limite par IP.
    # Dix essais en dix minutes laissent le temps de trouver le bon fichier.
    RATE_LIMIT_CV_CHECK: tuple[int, int] = (10, 600)

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:3000/api/v1/auth/google/callback"

    # ─── Google Meet (API Meet v2, OAuth utilisateur) ──────────────────────
    # Distinct de GOOGLE_CALENDAR_* : l'agenda passe par un compte de service,
    # Meet exige des identifiants UTILISATEUR. Un compte de service ne peut pas
    # créer d'espace Meet sans délégation domaine — d'où ce second chemin, qui
    # fonctionne avec un compte Google ordinaire.
    # Cette URI doit être déclarée à l'identique dans la console Google Cloud.
    GOOGLE_MEET_REDIRECT_URI: str = "http://localhost:8000/api/v1/interview/google-meet/callback"
    # Où renvoyer le navigateur après l'autorisation. 4200 est le port réel du
    # serveur de développement Angular ici — `.claude/launch.json` annonce 4300
    # mais n'est pas ce qui est lancé. À corriger dans le `.env` si vous servez
    # le client ailleurs (8080 dans la composition Docker).
    GOOGLE_MEET_POST_AUTH_REDIRECT: str = "http://localhost:4200/admin/interviews"

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

    # ── Recommandation d'offres (matching inverse candidat → offres) ──────────
    # Score de compatibilité minimal, sur 0..1, pour qu'une offre soit
    # recommandée. En dessous, elle n'est pas affichée du tout : mieux vaut
    # une section absente qu'une suggestion que le candidat jugera absurde.
    # 0.70 est un point de départ prudent, à ajuster en observant les
    # recommandations réelles — d'où sa présence ici plutôt qu'en dur.
    RECOMMENDATION_THRESHOLD: float = 0.70
    # Nombre d'offres remontées par la recherche vectorielle AVANT reclassement
    # métier. Large assez pour que le reclassement ait de la matière, petit
    # assez pour rester une seule requête indexée.
    RECOMMENDATION_POOL_SIZE: int = 20
    # Part de la similarité sémantique dans le score final ; le reste revient
    # aux critères métier (compétences / expérience / formation), pondérés par
    # l'offre elle-même. La sémantique situe le métier, elle ne décide pas.
    RECOMMENDATION_SEMANTIC_WEIGHT: float = 0.15
    # Reranking par cross-encoder : désactivé par défaut. `sentence-transformers`
    # fournit déjà `CrossEncoder` (aucune dépendance à ajouter), mais le modèle
    # ci-dessous pèse ~2,3 Go au premier chargement — à n'activer que sur un
    # environnement qui l'a déjà téléchargé.
    RERANKER_ENABLED: bool = False
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-v2-m3"

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
    # À la confirmation d'un créneau, un espace Google Meet est créé et figé
    # sur l'invitation (cf. GOOGLE_MEET_* plus haut). Un courriel « rejoindre
    # maintenant » part ensuite N minutes avant l'heure, au candidat, au
    # recruteur assigné et au RH.
    #
    # AUCUN REPLI. Google Meet est le seul fournisseur : sans compte Google
    # lié, il n'y a pas de lien, et le rappel n'est pas envoyé. Une absence
    # visible se corrige ; un lien de secours inattendu laisse le candidat
    # seul dans une salle que personne n'attend.
    #
    # 30 minutes : de quoi laisser au candidat le temps de s'installer et de
    # tester son micro. Passé sous 10, le rappel arrive alors que l'entretien
    # est déjà commencé pour qui n'était pas devant son écran.
    INTERVIEW_MEET_REMINDER_MINUTES: int = 30

    # ─── Vivier « en réserve » ─────────────────────────────────────────────
    # Un candidat placé en réserve est invité par e-mail quand une offre
    # ouverte correspond à son profil (même seuil que les recommandations
    # côté candidat). Balayage périodique plutôt qu'à la publication : l'offre
    # est indexée en tâche de fond, et la chercher aussitôt publiée la ratait.
    TALENT_POOL_SWEEP_MINUTES: int = 60
    # Au plus un e-mail par candidat sur ce délai — il regroupe les offres.
    TALENT_POOL_COOLDOWN_HOURS: int = 24
    TALENT_POOL_MAX_OFFERS: int = 3

    # ─── Observabilité : Langfuse (optionnel) ──────────────────────────────
    # Traçage du pipeline de recherche : embedding de la question, récupération
    # des passages, score de confiance, service depuis le cache. Sans clés,
    # `available` vaut False et chaque appel de traçage devient un no-op — le
    # produit fonctionne exactement comme avant.
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: SecretStr | None = None
    # Instance auto-hébergée par défaut. Pointer vers le service managé
    # (https://cloud.langfuse.com) revient à SORTIR les traces du périmètre :
    # à n'envisager qu'avec LANGFUSE_TRACE_CONTENT à false.
    #
    # DEUX NOMS, et c'est subi, pas choisi : le SDK Python lit `LANGFUSE_HOST`,
    # tandis que le CLI officiel et le skill Langfuse emploient
    # `LANGFUSE_BASE_URL`. Les deux sont acceptés ici pour qu'un `.env` écrit
    # d'après la documentation d'un outil ne casse pas l'autre.
    # `LANGFUSE_BASE_URL` l'emporte quand les deux sont renseignés.
    LANGFUSE_HOST: str = "http://localhost:3000"
    LANGFUSE_BASE_URL: str = ""

    @property
    def langfuse_url(self) -> str:
        """URL effective de l'instance Langfuse."""
        return (self.LANGFUSE_BASE_URL or self.LANGFUSE_HOST).rstrip("/")
    # Interrupteur explicite : des clés présentes ne suffisent pas à activer le
    # traçage. Permet de couper l'envoi sans retirer la configuration.
    LANGFUSE_ENABLED: bool = False

    # ─── Traçage du CONTENU : défaut FERMÉ, et ce défaut est un choix ──────
    # Le pipeline interrogé porte des CV. Une trace non masquée contiendrait
    # nom, téléphone, employeurs et parcours — c'est-à-dire exactement ce que
    # la règle du projet interdit de faire sortir (« ne jamais exposer les
    # données personnelles des CV dans les logs »). Un outil d'observabilité
    # est un journal comme un autre.
    #
    # À false (défaut), les traces ne portent que des MÉTADONNÉES : longueurs,
    # scores, nombre de passages, durées, empreinte tronquée de la question.
    # L'empreinte permet de reconnaître deux questions identiques d'une trace à
    # l'autre — donc de diagnostiquer le cache — sans révéler la question.
    #
    # Ne passer à true que sur une instance AUTO-HÉBERGÉE, avec un accord écrit
    # et une durée de rétention définie.
    LANGFUSE_TRACE_CONTENT: bool = False
    # Longueur maximale d'un champ tracé lorsque le contenu est autorisé.
    LANGFUSE_CONTENT_MAX_CHARS: int = 500

    # Étiquette d'environnement portée par chaque trace. Sans elle, les traces
    # d'un poste de développement et celles d'un déploiement se mélangent dans
    # les tableaux de bord, et toute statistique devient ininterprétable.
    LANGFUSE_ENVIRONMENT: str = "development"
    # Échantillonnage : 1.0 trace tout. À abaisser si le volume devient coûteux
    # — mais garder 1.0 tant que le trafic est faible, un échantillon ne permet
    # pas de retrouver la trace d'un incident précis.
    LANGFUSE_SAMPLE_RATE: float = 1.0

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
