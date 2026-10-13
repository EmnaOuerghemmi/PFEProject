"""pgvector native search

Ajoute la colonne vectorielle `embeddings.vec` et son index HNSW, qui
permettent la recherche sémantique par similarité cosinus directement en base.

Cette migration est CONDITIONNELLE : l'extension `vector` n'est pas disponible
partout (PostgreSQL Windows standard, SQLite des tests…). Quand elle manque, on
journalise et on passe — le service sémantique bascule alors sur son repli
Python (cosinus calculé en mémoire), fonctionnellement équivalent mais plus
lent. Faire échouer la migration ici empêcherait tout déploiement sur un
PostgreSQL sans pgvector, alors que l'application sait s'en passer.

Revision ID: 9b1c4d2e7f30
Revises: 88ae989a5ca0
"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

revision: str = "9b1c4d2e7f30"
down_revision: Union[str, Sequence[str], None] = "88ae989a5ca0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Doit rester aligné sur settings.EMBEDDING_DIM (modèle all-MiniLM-L6-v2 → 384).
# Figé en dur volontairement : une migration doit décrire un état immuable, pas
# dépendre d'une configuration qui peut changer après coup.
EMBEDDING_DIM = 384

log = logging.getLogger("alembic.pgvector")


def _vector_available(conn) -> bool:
    """L'extension pgvector est-elle installable sur ce serveur ?"""
    if conn.dialect.name != "postgresql":
        return False
    return bool(
        conn.execute(
            sa.text("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'")
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()

    if not _vector_available(conn):
        log.info(
            "Extension 'vector' indisponible sur ce serveur — colonne vectorielle "
            "ignorée, la recherche sémantique utilisera le repli Python."
        )
        return

    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    # DDL : un type de colonne ne peut pas être un paramètre lié. La dimension
    # est une constante entière du module, aucune donnée extérieure n'y entre.
    conn.execute(
        sa.text(f"ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS vec vector({int(EMBEDDING_DIM)})")  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
    )
    # HNSW + distance cosinus : correspond à `ORDER BY vec <=> :query`
    # utilisé par semantic_service.
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_embeddings_vec "
            "ON embeddings USING hnsw (vec vector_cosine_ops)"
        )
    )
    log.info("pgvector activé : colonne embeddings.vec + index HNSW créés.")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_embeddings_vec"))
    conn.execute(sa.text("ALTER TABLE embeddings DROP COLUMN IF EXISTS vec"))
    # L'extension n'est PAS supprimée : d'autres tables ou bases peuvent en
    # dépendre, et son coût de présence est nul.
