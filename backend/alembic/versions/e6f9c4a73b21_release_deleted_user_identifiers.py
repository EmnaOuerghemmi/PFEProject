"""Libère les identifiants uniques des comptes déjà supprimés

`users.email`, `users.username`, `users.google_id` et `users.employee_id`
portent une contrainte d'unicité qui couvre TOUTES les lignes, alors que chaque
lecture de l'application filtre `deleted_at IS NULL`. Un compte supprimé
devenait donc un trou noir : invisible dans la liste d'administration,
impossible à réactiver, et pourtant son adresse restait interdite à
l'inscription — l'utilisateur ne recevant qu'un « adresse déjà enregistrée »
sans rien voir nulle part.

`UserService.soft_delete` libère désormais ces identifiants au moment de la
suppression. Cette migration applique le même traitement aux lignes déjà
supprimées avant le correctif.

Les lignes sont conservées (et non effacées) pour que les entrées de
`audit_logs` qui les référencent gardent une cible.

Revision ID: e6f9c4a73b21
Revises: d5e8b3f62a17
Create Date: 2026-09-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f9c4a73b21"
down_revision: Union[str, Sequence[str], None] = "d5e8b3f62a17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    bloques = conn.execute(sa.text(
        "SELECT id, email FROM users "
        "WHERE deleted_at IS NOT NULL AND email NOT LIKE 'supprime+%'"
    )).fetchall()

    for user_id, email in bloques:
        # Marqueur dérivé de l'identifiant du compte : stable, unique, et
        # reproductible si la migration devait être rejouée.
        marker = str(user_id).replace("-", "")[:12]
        conn.execute(
            sa.text(
                "UPDATE users SET email = :email, username = :username, "
                "google_id = NULL, employee_id = NULL WHERE id = :id"
            ),
            {
                "email": f"supprime+{marker}@invalide.local",
                "username": f"supprime_{marker}",
                "id": user_id,
            },
        )
        print(f"  identifiants libérés pour le compte supprimé {email}")


def downgrade() -> None:
    # Les adresses d'origine n'ont volontairement pas été conservées : les
    # restaurer supposerait de garder en base les données personnelles d'un
    # compte que son titulaire a demandé à supprimer.
    pass
