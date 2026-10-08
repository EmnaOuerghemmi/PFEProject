#!/usr/bin/env bash
# ============================================================================
# Vérification « de bout en bout » d'une pile PIQBIT en marche.
#
#   deploy/smoke-test.sh [URL]          (défaut : http://127.0.0.1:8080)
#
# Utilisé par la CI (job Docker) et par deploy.sh après chaque mise en ligne.
# Ne teste que ce qu'un visiteur verrait : il passe par nginx, comme lui.
# Code de sortie 0 si tout passe, 1 sinon (avec le détail de chaque contrôle).
# ============================================================================
set -Eeuo pipefail

URL="${1:-http://127.0.0.1:8080}"
URL="${URL%/}"
echecs=0

ok()     { printf '  [ok]    %s\n' "$1"; }
echec()  { printf '  [ÉCHEC] %s\n' "$1"; echecs=$((echecs + 1)); }

# statut HTTP d'une URL (000 si injoignable)
statut() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$1" || true; }

echo "Vérification de ${URL}"

# 1. Page d'accueil servie par nginx (application Angular).
corps="$(curl -s --max-time 15 "${URL}/" || true)"
if [[ "$corps" == *"<app-root"* ]]; then ok "page d'accueil (index.html)"; else echec "page d'accueil : index.html attendu"; fi

# 2. En-têtes de sécurité posés par nginx.
entetes="$(curl -s -D - -o /dev/null --max-time 15 "${URL}/" || true)"
for h in "X-Content-Type-Options: nosniff" "X-Frame-Options" "Content-Security-Policy" "Referrer-Policy"; do
  if grep -qi "^${h}" <<<"$entetes"; then ok "en-tête ${h%%:*}"; else echec "en-tête ${h%%:*} absent"; fi
done

# 3. Routage côté client : une URL profonde renvoie l'application, pas un 404.
code="$(statut "${URL}/frontoffice/home")"
if [[ "$code" == "200" ]]; then ok "repli SPA (/frontoffice/home)"; else echec "repli SPA : HTTP ${code}"; fi

# 4. Backend prêt (base, schéma, Redis) à travers nginx.
sante="$(curl -s --max-time 15 "${URL}/healthz" || true)"
code="$(statut "${URL}/healthz")"
if [[ "$code" == "200" && "$sante" == *'"status":"ok"'* ]]; then
  ok "backend prêt (/healthz)"
else
  echec "backend non prêt (/healthz → HTTP ${code}) : ${sante:0:300}"
fi

# 5. API publique : le mandataire /api/ atteint FastAPI et la base répond.
code="$(statut "${URL}/api/v1/recruitment/jobs?page=1&size=1")"
if [[ "$code" == "200" ]]; then ok "API publique (/api/v1/recruitment/jobs)"; else echec "API publique : HTTP ${code}"; fi

# 6. Une route protégée refuse un visiteur anonyme (l'authentification est active).
code="$(statut "${URL}/api/v1/users/me")"
if [[ "$code" == "401" || "$code" == "403" ]]; then ok "route protégée refusée sans jeton (${code})"; else echec "route protégée : HTTP ${code}, 401 attendu"; fi

if (( echecs > 0 )); then
  echo "Vérification échouée : ${echecs} contrôle(s) en erreur."
  exit 1
fi
echo "Vérification réussie."
