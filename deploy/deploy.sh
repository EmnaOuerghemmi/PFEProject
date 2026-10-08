#!/usr/bin/env bash
# ============================================================================
# Déploiement PIQBIT sur un serveur Docker — appelé par la CD (GitHub Actions)
# ou à la main, depuis le dossier qui contient ce script.
#
#   ./deploy.sh deploy <tag> [--skip-migrations] [--no-pull]
#   ./deploy.sh rollback                    revient à la version précédente
#   ./deploy.sh status                      version en ligne et état des services
#
# Déroulé d'un déploiement :
#   1. verrou (un seul déploiement à la fois) ;
#   2. récupération des images <registre>/piqbit-{backend,frontend}:<tag> ;
#   3. sauvegarde de la base (pg_dump), avant toute migration ;
#   4. migrations Alembic, dans un conteneur jetable ;
#   5. mise en ligne, en attendant que chaque service soit « healthy » ;
#   6. vérification de bout en bout (smoke-test.sh) ;
#   7. en cas d'échec à 5 ou 6 : retour AUTOMATIQUE à la version précédente.
#
# Le retour arrière ne défait pas les migrations : il relance les images
# précédentes sur le schéma courant. C'est sûr tant que les migrations restent
# rétrocompatibles (ajouter avant de retirer — voir deploy/README.md). Pour
# revenir aussi sur les données, la sauvegarde prise à l'étape 3 est dans
# sauvegardes/.
#
# Codes de sortie : 0 succès · 1 échec, version précédente rétablie (ou aucune
# à rétablir) · 2 échec ET retour arrière impossible : intervention requise.
# ============================================================================
set -Eeuo pipefail
umask 077                       # sauvegardes et état : lisibles par le seul propriétaire
export MSYS_NO_PATHCONV=1       # sans effet sous Linux ; évite la conversion de chemins sous Git Bash

cd "$(dirname "$0")"

FICHIER_COMPOSE="docker-compose.prod.yml"
ETAT=".etat"
SAUVEGARDES="sauvegardes"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-600}"

log()  { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERREUR : $*"; exit 1; }

compose() { docker compose -f "$FICHIER_COMPOSE" "$@"; }

# ── Préalables ──────────────────────────────────────────────────────────────

preparer() {
  command -v docker >/dev/null || fail "docker introuvable."
  docker compose version >/dev/null 2>&1 || fail "le plugin « docker compose » est requis."
  [[ -f .env ]] || fail "deploy/.env manquant (modèle : .env.example)."
  [[ -f backend.env ]] || fail "deploy/backend.env manquant (modèle : backend.env.example)."
  mkdir -p "$ETAT" "$SAUVEGARDES"

  # Variables de la pile (POSTGRES_*, SMOKE_URL, BACKUPS_TO_KEEP…).
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  POSTGRES_USER="${POSTGRES_USER:-piqbit}"
  POSTGRES_DB="${POSTGRES_DB:-piqbit}"
  SMOKE_URL="${SMOKE_URL:-http://127.0.0.1:80}"
  BACKUPS_TO_KEEP="${BACKUPS_TO_KEEP:-10}"

  # Un seul déploiement à la fois : deux mises en ligne croisées laisseraient
  # la pile dans un état que personne n'a choisi.
  if command -v flock >/dev/null; then
    exec 9>"$ETAT/verrou"
    flock -n 9 || fail "un autre déploiement est en cours."
  else
    log "Avertissement : flock indisponible, pas de verrou (acceptable hors serveur)."
  fi
}

valider_tag() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || fail "étiquette d'image invalide : « $1 »."
}

version_actuelle()   { cat "$ETAT/actuelle" 2>/dev/null || true; }
version_precedente() { cat "$ETAT/precedente" 2>/dev/null || true; }

# ── Étapes ──────────────────────────────────────────────────────────────────

sauvegarder_base() {
  local tag="$1" fichier
  fichier="$SAUVEGARDES/${POSTGRES_DB}-$(date -u +%Y%m%dT%H%M%SZ)-avant-${tag}.dump"
  log "Sauvegarde de la base → $fichier"
  compose exec -T postgres pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" >"$fichier" \
    || fail "sauvegarde impossible : déploiement interrompu, rien n'a changé."
  [[ -s "$fichier" ]] || fail "sauvegarde vide : déploiement interrompu, rien n'a changé."
  # Rotation : on garde les BACKUPS_TO_KEEP plus récentes (tri par date de modification).
  find "$SAUVEGARDES" -maxdepth 1 -name '*.dump' -type f -printf '%T@ %p\n' \
    | sort -rn | tail -n +"$((BACKUPS_TO_KEEP + 1))" | cut -d' ' -f2- \
    | while read -r ancien; do rm -f -- "$ancien"; done
}

migrer() {
  log "Migrations Alembic (alembic upgrade head)"
  compose run --rm --no-deps backend alembic upgrade head \
    || fail "migrations en échec : l'ancienne version reste en ligne. Sauvegarde dans $SAUVEGARDES/."
}

mettre_en_ligne() {
  log "Mise en ligne de la version $IMAGE_TAG (attente des health checks, ${WAIT_TIMEOUT}s max)"
  compose up -d --remove-orphans --wait --wait-timeout "$WAIT_TIMEOUT" \
    && ./smoke-test.sh "$SMOKE_URL"
}

journaux_echec() {
  log "Derniers journaux :"
  compose ps || true
  compose logs --no-color --tail 60 backend frontend || true
}

# ── Commandes ───────────────────────────────────────────────────────────────

deployer() {
  local tag="$1" sauter_migrations="$2" sans_pull="$3"
  valider_tag "$tag"
  local avant
  avant="$(version_actuelle)"
  log "Déploiement de $tag (version en ligne : ${avant:-aucune})"

  export IMAGE_TAG="$tag"
  if [[ "$sans_pull" != "oui" ]]; then
    log "Récupération des images"
    compose pull --quiet
  fi

  compose up -d --wait --wait-timeout 120 postgres redis
  sauvegarder_base "$tag"
  [[ "$sauter_migrations" == "oui" ]] || migrer

  if mettre_en_ligne; then
    if [[ -n "$avant" && "$avant" != "$tag" ]]; then printf '%s\n' "$avant" >"$ETAT/precedente"; fi
    printf '%s\n' "$tag" >"$ETAT/actuelle"
    docker image prune -f >/dev/null 2>&1 || true
    log "Succès : $tag est en ligne."
    return 0
  fi

  journaux_echec
  if [[ -z "$avant" || "$avant" == "$tag" ]]; then
    log "Échec, et aucune version précédente à rétablir."
    exit 2
  fi
  log "Échec : retour automatique à $avant"
  export IMAGE_TAG="$avant"
  if mettre_en_ligne; then
    log "Version précédente $avant rétablie. Le déploiement de $tag a échoué."
    exit 1
  fi
  journaux_echec
  log "Retour arrière en échec : intervention manuelle requise."
  exit 2
}

revenir() {
  local cible actuelle
  cible="$(version_precedente)"
  actuelle="$(version_actuelle)"
  [[ -n "$cible" ]] || fail "aucune version précédente connue."
  log "Retour arrière : $actuelle → $cible"
  export IMAGE_TAG="$cible"
  compose pull --quiet || log "Avertissement : images non récupérées, utilisation du cache local."
  if mettre_en_ligne; then
    printf '%s\n' "$cible" >"$ETAT/actuelle"
    [[ -n "$actuelle" ]] && printf '%s\n' "$actuelle" >"$ETAT/precedente"
    log "Succès : $cible est en ligne."
    return 0
  fi
  journaux_echec
  exit 2
}

etat() {
  echo "Version en ligne    : $(version_actuelle || true)"
  echo "Version précédente  : $(version_precedente || true)"
  IMAGE_TAG="$(version_actuelle)"
  export IMAGE_TAG="${IMAGE_TAG:-inconnue}"
  compose ps
}

# ── Point d'entrée ──────────────────────────────────────────────────────────

commande="${1:-}"
shift || true
case "$commande" in
  deploy)
    tag="${1:-}"; [[ -n "$tag" ]] || fail "usage : $0 deploy <tag> [--skip-migrations] [--no-pull]"
    shift
    sauter="non"; sans_pull="non"
    for option in "$@"; do
      case "$option" in
        --skip-migrations) sauter="oui" ;;
        --no-pull) sans_pull="oui" ;;
        *) fail "option inconnue : $option" ;;
      esac
    done
    preparer
    deployer "$tag" "$sauter" "$sans_pull"
    ;;
  rollback) preparer; revenir ;;
  status)   preparer; etat ;;
  *) echo "usage : $0 {deploy <tag> [--skip-migrations] [--no-pull] | rollback | status}"; exit 64 ;;
esac
