# CI/CD et déploiement de PIQBIT

## Vue d'ensemble

```
push / pull request ─► CI (.github/workflows/ci.yml)
                        ├─ workflows        actionlint + shellcheck
                        ├─ backend-qualite  ruff (bugs, failles) + pip-audit
                        ├─ backend-tests    migrations (application, dérive, retour arrière) + pytest + couverture
                        ├─ frontend         npm audit + typage + build de production + tests + couverture
                        ├─ docker           images + Trivy + VRAI déploiement de test avec deploy.sh,
                        │                   y compris retour arrière automatique et manuel
                        └─ ci-ok            synthèse (à exiger avant fusion)

CI vert sur main    ─► Release (release.yml) ─► images sha-xxxxxxx + main  ─► déploiement RECETTE
CI vert sur vX.Y.Z  ─► Release (release.yml) ─► images vX.Y.Z, X.Y, latest ─► déploiement PRODUCTION
                                                                              (après approbation)
Lancement manuel    ─► Deploy (deploy.yml) : déployer une étiquette, ou rollback

CodeQL (codeql.yml) : analyse de sécurité du code, à chaque push sur main, à chaque PR, et chaque lundi.
Dependabot (.github/dependabot.yml) : mises à jour hebdomadaires (pip, npm, actions, images Docker).
```

Images : `ghcr.io/emnaouerghemmi/piqbit-backend` et `ghcr.io/emnaouerghemmi/piqbit-frontend`,
avec SBOM et attestation de provenance.

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

*Settings › Environments* : créer `staging` et `production`. Pour `production`, activer
**Required reviewers** : chaque mise en production attendra une approbation.

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
CI complet sur l'étiquette → publication `v1.0.0` → approbation → déploiement.

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

## Sondes

- `GET /health` (backend) : processus vivant — sonde Docker.
- `GET /health/ready` (backend), publié en **`GET /healthz`** par nginx : base joignable,
  schéma à la bonne révision, Redis joignable. 503 sinon. À brancher sur la supervision.
