# ============================================================================
# PIQBIT — frontend Angular servi par nginx
# ----------------------------------------------------------------------------
# Build multi-étapes : Node ne sert qu'à compiler. L'image finale ne contient
# que les fichiers statiques et nginx (~50 Mo au lieu de ~1,5 Go).
# ============================================================================

# ─── Étape 1 : compilation Angular ─────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /build

# package.json + lockfile copiés seuls d'abord : tant que les dépendances ne
# changent pas, Docker réutilise le cache de cette couche et saute le
# `npm ci` (l'étape la plus lente) lors des rebuilds de code.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build -- --configuration production

# ─── Étape 2 : service statique ────────────────────────────────────────────
# Branche STABLE de nginx (maintenue). La 1.27 ne l'était plus : son OpenSSL
# portait une faille critique corrigée depuis (CVE-2026-31789), relevée par
# Trivy en CI. `apk upgrade` reprend à chaque build les derniers correctifs
# de sécurité de la distribution, sans attendre une nouvelle image de base.
FROM nginx:1.30-alpine AS runtime

RUN apk upgrade --no-cache \
    && rm -rf /usr/share/nginx/html/* \
    && rm /etc/nginx/conf.d/default.conf

# Angular 17+ (application builder) émet dans dist/<projet>/browser.
COPY --from=builder /build/dist/frontend/browser /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf

EXPOSE 80

# On interroge 127.0.0.1 et non `localhost` : wget résout ce dernier en IPv6
# ([::1]) alors que nginx n'écoute qu'en IPv4 (`listen 80`), ce qui faisait
# systématiquement échouer la sonde alors que le service répondait bien.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
