# CI/CD et déploiement de PIQBIT

## Vue d'ensemble

```
pull request / push sur main ─► CI (.github/workflows/ci.yml), cinq jobs en parallèle
                                 ├─ codescene   qualité du code modifié (Code Health)
                                 ├─ semgrep     sécurité du code
                                 ├─ gitleaks    secrets dans l'historique
                                 ├─ lighthouse  performance et accessibilité du frontend
                                 └─ docker      build des images backend et frontend

CI verte sur main   ─► CD (cd.yml) ─► images sha-xxxxxxx + main
Étiquette vX.Y.Z    ─► CD (cd.yml) ─► images vX.Y.Z, X.Y, latest + sha-xxxxxxx
Lancement manuel    ─► CD (cd.yml) ─► image sha-xxxxxxx de la référence choisie

Déploiement : manuel, sur le serveur, avec deploy.sh (voir plus bas).
```

Migrations, tests backend et tests frontend tournent sur votre machine, sans GitHub :
`bash scripts/ci-local.sh` (voir [Sans GitHub Actions](#sans-github-actions)).

Images : `ghcr.io/emnaouerghemmi/piqbit-backend` et `ghcr.io/emnaouerghemmi/piqbit-frontend`,
avec SBOM et attestation de provenance. Dépôt privé : les images sont privées.

## Préparer un serveur (une fois par environnement)

Prérequis : Linux, Docker Engine 24+ avec le plugin `docker compose` 2.20+, `curl`, `flock`
(paquet `util-linux`), accès SSH par clé.

```bash
# 1. Un utilisateur dédié, membre du groupe docker.
sudo adduser --disabled-password deploy && sudo usermod -aG docker deploy
sudo mkdir -p /opt/piqbit && sudo chown deploy: /opt/piqbit

# 2. Sa clé SSH de déploiement (la clé privée ira dans GitHub, voir plus bas).
ssh-keygen -t ed25519 -N '' -f piqbit-deploy -C github-actions
#    → ajouter piqbit-deploy.pub à /home/deploy/.ssh/authorized_keys

# 3. Les fichiers de configuration, à partir des modèles copiés par la CD
#    (ou copiés à la main depuis ce dossier lors de la toute première fois).
cd /opt/piqbit
cp .env.example .env              && nano .env          # POSTGRES_PASSWORD, HTTP_BIND, SMOKE_URL
cp backend.env.example backend.env && nano backend.env  # SECRET_KEY, FRONTEND_BASE_URL, SMTP…
chmod 600 .env backend.env
```

TLS : publier le frontend sur `127.0.0.1:8080` (`HTTP_BIND`) et placer devant un proxy TLS
de l'hôte (Caddy, Traefik ou nginx avec Let's Encrypt), ou laisser `80` derrière un
répartiteur de charge qui termine le TLS.

## Secrets et variables GitHub

*Settings › Environments* : créer `staging` et `production`. Dans un dépôt privé, il faut
GitHub Pro (inclus dans le GitHub Student Developer Pack) ; sans lui, créer les mêmes noms
en secrets et variables **de dépôt** (*Settings › Secrets and variables › Actions*).

L'approbation d'environnement (**Required reviewers**) est réservée aux dépôts publics :
la production ne se déploie donc jamais automatiquement, seulement par un lancement manuel
(voir plus bas), et uniquement avec une étiquette `vX.Y.Z`.

| Où | Nom | Contenu |
|---|---|---|
| secret d'environnement | `DEPLOY_HOST` | adresse du serveur |
| secret d'environnement | `DEPLOY_USER` | `deploy` |
| secret d'environnement | `DEPLOY_SSH_KEY` | contenu de `piqbit-deploy` (clé **privée**) |
| secret d'environnement | `DEPLOY_KNOWN_HOSTS` | sortie de `ssh-keyscan -H <serveur>` (vérifiée !) |
| variable d'environnement | `DEPLOY_PATH` | `/opt/piqbit` |
| variable d'environnement | `DEPLOY_PORT` | `22` (facultatif) |
| variable d'environnement | `PUBLIC_URL` | `https://recette.piqbit.tn` (facultatif : vérification externe) |

Aucun secret applicatif (clé JWT, SMTP, base) n'est stocké dans GitHub : ils restent
dans `.env` et `backend.env` sur le serveur. Le jeton du registre est celui du job,
valable le temps du job. Tant que ces secrets manquent, le déploiement est **sauté**
avec un avertissement : les images sont publiées, rien n'est déployé.

*Settings › Branches* : protéger `main` en exigeant la vérification **« CI — synthèse »**.

## Publier une version en production

```bash
git checkout main && git pull
git tag -a v1.0.0 -m "PIQBIT 1.0.0"
git push origin v1.0.0
```
L'étiquette déclenche la CD, qui publie les images `v1.0.0`, `1.0` et `latest`. Puis, sur
le serveur : `bash deploy.sh deploy v1.0.0` (voir [Sans GitHub Actions](#sans-github-actions)
pour la connexion au registre).

## Retour arrière

- **Automatique** : si les health checks ou la vérification de bout en bout échouent,
  `deploy.sh` remet en ligne la version précédente et le job échoue (code 1).
- **Manuel** : *Actions › Deploy › Run workflow*, action `rollback` (version précédente),
  ou action `deploy` avec une étiquette précise (`sha-1a2b3c4`, `v1.2.0`).
- **Sur le serveur** : `cd /opt/piqbit && bash deploy.sh rollback` ou `bash deploy.sh status`.

Le retour arrière remet les **images** précédentes ; il ne défait pas les migrations.
D'où la règle : **une migration doit rester compatible avec la version précédente du
code** (ajouter une colonne nullable avant de l'exploiter, retirer une colonne dans une
version ultérieure). La CI vérifie aussi que le `downgrade` de la dernière migration
fonctionne. Pour revenir sur les données : la sauvegarde prise avant chaque migration
est dans `sauvegardes/` :

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U piqbit -d piqbit --clean --if-exists < sauvegardes/<fichier>.dump
```

## Sans GitHub Actions

Quand Actions est indisponible (compte bloqué, quota de minutes épuisé), tout reste faisable
à la main.

**Vérifier** — depuis la racine du dépôt (Git Bash sous Windows, Docker démarré) :

```bash
bash scripts/ci-local.sh                    # tous les jobs, environ 30 min la première fois
bash scripts/ci-local.sh backend frontend   # seulement certains : workflows, backend, frontend, docker
```

Le script rejoue les contrôles de `ci.yml` sur une copie de vos fichiers (modifications non
committées comprises), dans des conteneurs dédiés : votre base et vos conteneurs de
développement ne sont pas touchés. Il termine par un bilan, code de sortie 1 si un job échoue.

**Publier les images** — avec un jeton personnel GitHub (*Settings › Developer settings ›
Personal access tokens*, droit `write:packages`) :

```bash
echo "<jeton>" | docker login ghcr.io -u <utilisateur> --password-stdin
docker build -t ghcr.io/emnaouerghemmi/piqbit-backend:v1.0.0 backend
docker build -t ghcr.io/emnaouerghemmi/piqbit-frontend:v1.0.0 frontend
docker push ghcr.io/emnaouerghemmi/piqbit-backend:v1.0.0
docker push ghcr.io/emnaouerghemmi/piqbit-frontend:v1.0.0
docker logout ghcr.io
```

**Déployer** — sur le serveur, connecté au registre (dépôt privé : images privées ; jeton
avec le seul droit `read:packages`) :

```bash
cd /opt/piqbit
echo "<jeton>" | docker login ghcr.io -u <utilisateur> --password-stdin
bash deploy.sh deploy v1.0.0     # ou : bash deploy.sh rollback
docker logout ghcr.io
```

Même sauvegarde, mêmes migrations, health checks et retour arrière automatique qu'en CD.

## Sondes

- `GET /health` (backend) : processus vivant — sonde Docker.
- `GET /health/ready` (backend), publié en **`GET /healthz`** par nginx : base joignable,
  schéma à la bonne révision, Redis joignable. 503 sinon. À brancher sur la supervision.
