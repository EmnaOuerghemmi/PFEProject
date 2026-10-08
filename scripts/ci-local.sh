#!/usr/bin/env bash
# ============================================================================
# CI locale : rejoue sur votre machine les contrôles de
# .github/workflows/ci.yml, dans Docker, sans GitHub Actions.
# ----------------------------------------------------------------------------
#   bash scripts/ci-local.sh                     tous les jobs
#   bash scripts/ci-local.sh backend frontend    seulement ceux-là
#
#   workflows  actionlint + shellcheck
#   backend    ruff, pip-audit, migrations sur PostgreSQL/pgvector
#              (application, dérive, retour arrière), tests et couverture
#   frontend   npm audit, typage, build de production, tests (Chromium)
#   docker     images, Trivy, VRAI déploiement avec deploy/deploy.sh, retour
#              arrière automatique sur une version cassée, puis manuel
#
# Ce qui est vérifié : l'état ACTUEL des fichiers suivis par Git et des
# nouveaux fichiers non ignorés, modifications non committées comprises,
# c'est-à-dire ce que vous vous apprêtez à pousser. Tout se passe sur une
# copie temporaire et dans des conteneurs dédiés (préfixe piqbit-ci-local) :
# votre dossier, votre base et vos conteneurs de développement ne sont pas
# touchés.
#
# Prérequis : Docker (Docker Desktop sous Windows) et Bash (Git Bash sous
# Windows). Première exécution : environ 30 min ; les caches Docker
# raccourcissent les suivantes. Le déploiement de test écoute sur
# 127.0.0.1:8090 (variable CI_LOCAL_PORT pour en changer).
# ============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash : ne pas réécrire les chemins passés à Docker

RACINE=$(git rev-parse --show-toplevel) || exit 2
CI_YML="$RACINE/.github/workflows/ci.yml"
PREFIXE=piqbit-ci-local
PORT=${CI_LOCAL_PORT:-8090}
TOUS=(workflows backend frontend docker)

usage() {
  echo "Usage : bash scripts/ci-local.sh [${TOUS[*]}]" >&2
  exit 2
}

# Versions des outils : lues dans ci.yml, seule source de vérité.
valeur_ci() { sed -nE "s/^  $1: '?([^'[:space:]]+)'?[[:space:]]*$/\1/p" "$CI_YML"; }
NODE_VERSION=$(valeur_ci NODE_VERSION)
TRIVY_IMAGE=$(valeur_ci TRIVY_IMAGE)
ACTIONLINT_IMAGE=$(valeur_ci ACTIONLINT_IMAGE)
SHELLCHECK_IMAGE=$(valeur_ci SHELLCHECK_IMAGE)
for v in NODE_VERSION TRIVY_IMAGE ACTIONLINT_IMAGE SHELLCHECK_IMAGE; do
  [[ -n "${!v}" ]] || { echo "$v introuvable dans $CI_YML." >&2; exit 2; }
done

if (( $# == 0 )); then JOBS=("${TOUS[@]}"); else JOBS=("$@"); fi
for j in "${JOBS[@]}"; do
  [[ " ${TOUS[*]} " == *" $j "* ]] || usage
done
veut() { [[ " ${JOBS[*]} " == *" $1 "* ]]; }

docker info >/dev/null 2>&1 || { echo "Docker ne répond pas : démarrez Docker Desktop." >&2; exit 2; }
docker compose version >/dev/null 2>&1 || { echo "Le plugin « docker compose » est introuvable." >&2; exit 2; }

# --- Copie de travail --------------------------------------------------------
COPIE=$(mktemp -d -t piqbit-ci.XXXXXX) || exit 2
# Chemin de la copie tel que Docker le comprend (C:/… sous Git Bash).
if command -v cygpath >/dev/null; then HOTE=$(cygpath -m "$COPIE"); else HOTE=$COPIE; fi
export COMPOSE_PROJECT_NAME=$PREFIXE

nettoyer() {
  if [[ -f "$COPIE/deploy/.env" ]]; then
    (cd "$COPIE/deploy" && IMAGE_TAG=ci docker compose -f docker-compose.prod.yml down -v --remove-orphans >/dev/null 2>&1)
  fi
  docker rm -f "$PREFIXE-pg" "$PREFIXE-redis" >/dev/null 2>&1
  docker network rm "$PREFIXE" >/dev/null 2>&1
  docker image rm local/piqbit-backend:ci-cassee local/piqbit-frontend:ci-cassee \
    local/piqbit-backend:ci-bis local/piqbit-frontend:ci-bis >/dev/null 2>&1
  rm -rf -- "$COPIE"
}
trap nettoyer EXIT
trap 'exit 130' INT TERM

(cd "$RACINE" && git ls-files -z --cached --others --exclude-standard \
  | tar --null -T - --ignore-failed-read -cf - 2>/dev/null) | tar -xf - -C "$COPIE" || exit 2

# --- Outils ------------------------------------------------------------------
BILAN=()
ECHECS=0
section() { printf '\n######## %s\n' "$*"; }
noter() {
  BILAN+=("$(printf '%-10s %s' "$1" "$2")")
  [[ "$2" == OK* ]] || ECHECS=$((ECHECS + 1))
}
lancer() {  # lancer <nom> <fonction> : exécute un job et note son résultat
  local debut=$SECONDS
  if "$2"; then noter "$1" "OK ($(( (SECONDS - debut) / 60 )) min)"; else noter "$1" "ÉCHEC"; fi
}
attendre_sain() {
  local essais=60
  while (( essais-- > 0 )); do
    [[ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" == healthy ]] && return 0
    sleep 2
  done
  echo "$1 n'est pas devenu sain." >&2
  return 1
}
aleatoire_hex() { od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'; }

# --- Jobs --------------------------------------------------------------------
# La copie n'a pas de dossier .git : les fichiers sont donc nommés explicitement.
job_workflows() (
  section "workflows : actionlint + shellcheck"
  cd "$COPIE" || return 1
  docker run --rm -v "$HOTE:/repo:ro" -w /repo "$ACTIONLINT_IMAGE" .github/workflows/*.yml || return 1
  docker run --rm -v "$HOTE:/mnt:ro" -w /mnt "$SHELLCHECK_IMAGE" --severity=warning deploy/*.sh scripts/*.sh
)

job_images() {
  section "images Docker"
  docker build -q -t local/piqbit-backend:ci "$HOTE/backend" >/dev/null &&
    docker build -q -t local/piqbit-frontend:ci "$HOTE/frontend" >/dev/null
}

# Les tests tournent dans l'image backend (dépendances déjà installées) ; le
# code y est COPIÉ, tout ce qui est produit disparaît avec le conteneur.
job_backend() {
  section "backend : ruff, pip-audit, migrations, tests"
  docker network create "$PREFIXE" >/dev/null || return 1
  docker run -d --name "$PREFIXE-pg" --network "$PREFIXE" \
    -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=piqbit_test \
    --health-cmd "pg_isready -U postgres" --health-interval 2s pgvector/pgvector:pg16 >/dev/null || return 1
  docker run -d --name "$PREFIXE-redis" --network "$PREFIXE" redis:7-alpine >/dev/null || return 1
  attendre_sain "$PREFIXE-pg" || return 1

  docker run --rm -i --network "$PREFIXE" --user root \
    -v "$HOTE/backend:/src:ro" -v "$PREFIXE-pip:/root/.cache/pip" \
    -e DATABASE_URL="postgresql+asyncpg://postgres:postgres@$PREFIXE-pg:5432/piqbit_test" \
    -e SECRET_KEY=ci-secret-sans-usage-en-production \
    -e REDIS_URL="redis://$PREFIXE-redis:6379" \
    -e EMBEDDINGS_BACKEND=hash -e TEST_DB_PATH=/tmp/test.db -e PYTHONDONTWRITEBYTECODE=1 \
    local/piqbit-backend:ci bash -s <<'EOF'
set -euo pipefail
cp -r /src /work && cd /work
echo "== outils (versions de requirements-dev.txt)"
grep -E '^(ruff|pip-audit|pytest-cov)==' requirements-dev.txt > /tmp/outils.txt
pip install -q --disable-pip-version-check --root-user-action=ignore -r /tmp/outils.txt
echo "== ruff"
ruff check . --no-cache
echo "== pip-audit"
mapfile -t exceptions < <(grep -vE '^\s*(#|$)' .pip-audit-ignore)
args=(); for id in "${exceptions[@]}"; do args+=(--ignore-vuln "$id"); done
pip-audit -r requirements.txt --no-deps --disable-pip --progress-spinner off "${args[@]}"
echo "== migrations : application complète"
alembic upgrade head
echo "== migrations : aucun modèle modifié sans migration"
alembic check
echo "== migrations : retour arrière d'une révision puis réapplication"
alembic downgrade -1
alembic upgrade head
echo "== tests et couverture"
pytest -q --no-header -p no:cacheprovider --cov=app --cov-report=term:skip-covered
EOF
  local code=$?
  docker rm -f "$PREFIXE-pg" "$PREFIXE-redis" >/dev/null 2>&1
  docker network rm "$PREFIXE" >/dev/null 2>&1
  return $code
}

# Node de la CI + Chromium pour Karma ; image construite une fois, puis en cache.
job_frontend() {
  section "frontend : npm audit, typage, build, tests"
  printf 'FROM node:%s-bookworm-slim\nRUN apt-get update && apt-get install -y --no-install-recommends chromium && rm -rf /var/lib/apt/lists/*\nENV CHROME_BIN=/usr/bin/chromium\n' \
    "$NODE_VERSION" | docker build -q -t "$PREFIXE-node:$NODE_VERSION" - >/dev/null || return 1

  docker run --rm -i -v "$HOTE/frontend:/src:ro" -v "$PREFIXE-npm:/root/.npm" \
    "$PREFIXE-node:$NODE_VERSION" bash -s <<'EOF'
set -euo pipefail
cp -r /src /work && cd /work
echo "== npm ci"
npm ci --no-fund --no-audit
echo "== npm audit : bloquant sur les vulnérabilités CRITIQUES livrées en production"
npm audit --omit=dev --audit-level=critical
echo "== typage"
npm run typecheck
echo "== build de production"
npm run build -- --configuration production
echo "== tests et couverture"
npm run test:ci
EOF
}

# Sous-shell : le « cd » ne quitte pas la fonction.
job_docker() (
  section "docker : Trivy, déploiement réel, retour arrière"
  local image code
  for image in local/piqbit-backend:ci local/piqbit-frontend:ci; do
    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$PREFIXE-trivy:/root/.cache" "$TRIVY_IMAGE" \
      image --scanners vuln --severity CRITICAL --ignore-unfixed --exit-code 1 --no-progress --quiet "$image" || return 1
  done

  cd "$COPIE/deploy" || return 1
  cp .env.example .env
  sed -i "s|^IMAGE_REGISTRY=.*|IMAGE_REGISTRY=local|" .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(aleatoire_hex 24)|" .env
  sed -i "s|^HTTP_BIND=.*|HTTP_BIND=127.0.0.1:$PORT|" .env
  sed -i "s|^SMOKE_URL=.*|SMOKE_URL=http://127.0.0.1:$PORT|" .env
  cp backend.env.example backend.env
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(aleatoire_hex 64)|" backend.env
  sed -i "s|^FRONTEND_BASE_URL=.*|FRONTEND_BASE_URL=http://127.0.0.1:$PORT|" backend.env
  echo "EMBEDDINGS_BACKEND=hash" >> backend.env

  echo "== déploiement réel (sauvegarde, migrations, health checks, vérification)"
  WAIT_TIMEOUT=600 bash deploy.sh deploy ci --no-pull || return 1

  echo "== version cassée : le retour arrière automatique doit rétablir « ci »"
  printf 'FROM local/piqbit-backend:ci\nCMD ["false"]\n' | docker build -q -t local/piqbit-backend:ci-cassee - >/dev/null
  docker tag local/piqbit-frontend:ci local/piqbit-frontend:ci-cassee
  WAIT_TIMEOUT=180 bash deploy.sh deploy ci-cassee --no-pull --skip-migrations
  code=$?
  if [[ $code -ne 1 ]]; then echo "Code $code, attendu 1 (échec puis retour arrière réussi)." >&2; return 1; fi
  bash smoke-test.sh "http://127.0.0.1:$PORT" || return 1
  [[ "$(cat .etat/actuelle)" == ci ]] || return 1

  echo "== retour arrière manuel (commande rollback)"
  docker tag local/piqbit-backend:ci local/piqbit-backend:ci-bis
  docker tag local/piqbit-frontend:ci local/piqbit-frontend:ci-bis
  WAIT_TIMEOUT=600 bash deploy.sh deploy ci-bis --no-pull || return 1
  bash deploy.sh rollback || return 1
  [[ "$(cat .etat/actuelle)" == ci ]] || return 1
  bash deploy.sh status
)

# --- Exécution ---------------------------------------------------------------
echo "CI locale de $(git -C "$RACINE" rev-parse --abbrev-ref HEAD) · jobs : ${JOBS[*]}"
veut workflows && lancer workflows job_workflows

images_pretes=1
if veut backend || veut docker; then
  lancer images job_images
  [[ "${BILAN[-1]}" == *OK* ]] || images_pretes=0
fi
if veut backend; then
  if (( images_pretes )); then lancer backend job_backend; else noter backend "ÉCHEC (images non construites)"; fi
fi
veut frontend && lancer frontend job_frontend
if veut docker; then
  if (( images_pretes )); then lancer docker job_docker; else noter docker "ÉCHEC (images non construites)"; fi
fi

section "BILAN"
printf '  %s\n' "${BILAN[@]}"
if (( ECHECS > 0 )); then
  echo "  → $ECHECS job(s) en échec : détails plus haut."
  exit 1
fi
echo "  → tout est vert."
