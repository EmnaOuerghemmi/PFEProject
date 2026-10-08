# ============================================================================
# PIQBIT — API FastAPI
# ----------------------------------------------------------------------------
# Build multi-étapes : les dépendances sont compilées dans une image « builder »
# jetable, seul l'environnement virtuel résultant est copié dans l'image finale.
# Cela évite d'embarquer gcc et les en-têtes de compilation en production.
# ============================================================================

# ─── Étape 1 : construction des dépendances ────────────────────────────────
FROM python:3.14-slim AS builder

# Outils nécessaires à la compilation de certaines roues (psycopg2, etc.).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Les roues torch pèsent plusieurs centaines de Mo : sur une connexion lente,
# le téléchargement dépasse les délais par défaut de pip et la couche échoue
# sur `IncompleteRead`. Ces réglages rendent le build tolérant aux coupures.
ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip

# torch installé SÉPARÉMENT, et depuis l'index CPU : la roue par défaut
# embarque les bibliothèques CUDA (~2,5 Go) inutiles ici, l'inférence
# sentence-transformers tournant sur CPU. L'isoler dans sa propre couche
# évite aussi de retélécharger tout le reste si ce gros transfert échoue.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.13.0

RUN pip install --no-cache-dir -r requirements.txt


# ─── Étape 2 : image d'exécution ───────────────────────────────────────────
FROM python:3.14-slim AS runtime

# libpq5 seule (client PostgreSQL à l'exécution), sans les en-têtes de dev.
# curl sert au HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non privilégié : un processus applicatif n'a aucune raison de
# tourner en root dans un conteneur.
RUN useradd --create-home --uid 1000 piqbit

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --chown=piqbit:piqbit . .

# Répertoires écrits à l'exécution : CV téléversés et photos de profil.
# Créés ICI, avec le bon propriétaire : /app appartient à root, et l'image
# construite par la CI (depuis Git) ne contient pas static/ — il n'est pas
# versionné. Sans cette ligne, le démarrage échouait sur une permission.
RUN mkdir -p /app/uploads /app/static/avatars \
    && chown -R piqbit:piqbit /app/uploads /app/static

USER piqbit

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Migrations au démarrage : pratiques en développement (docker-compose.yml),
# désactivées en production (RUN_MIGRATIONS_ON_START=false) où deploy/deploy.sh
# les applique explicitement, APRÈS une sauvegarde de la base. Les laisser au
# démarrage interdirait tout retour arrière : une image plus ancienne refuserait
# de démarrer sur un schéma qu'elle ne connaît pas.
#
# --proxy-headers : derrière nginx, l'adresse du client vient de
# X-Forwarded-For. FORWARDED_ALLOW_IPS=* n'est sûr que si le backend n'est
# joignable QUE par nginx — c'est le cas en production (réseau interne).
ENV RUN_MIGRATIONS_ON_START=true \
    FORWARDED_ALLOW_IPS=127.0.0.1
CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS_ON_START\" = \"true\" ]; then alembic upgrade head || exit 1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
