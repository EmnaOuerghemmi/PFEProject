"""
Point d'entrée unique des modèles ORM.

Importer ce module suffit à peupler `Base.metadata` avec l'intégralité des
tables. C'est indispensable à Alembic : sans ces imports, `Base.metadata` est
vide, l'autogenerate croit que le projet ne déclare aucune table et génère une
migration qui SUPPRIME tout le schéma existant.

Ordre alphabétique volontaire — SQLAlchemy résout les relations paresseusement
à partir des noms de classes, l'ordre d'import n'a donc pas d'importance
fonctionnelle.
"""

from app.models import agent_log  # noqa: F401
from app.models import assessment  # noqa: F401
from app.models import budget  # noqa: F401
from app.models import career  # noqa: F401
from app.models import contract  # noqa: F401
from app.models import embedding  # noqa: F401
from app.models import employee  # noqa: F401
from app.models import interview  # noqa: F401
from app.models import knowledge  # noqa: F401
from app.models import negotiation  # noqa: F401
from app.models import notification  # noqa: F401
from app.models import recruitment  # noqa: F401
from app.models import report  # noqa: F401
from app.models import scoring  # noqa: F401
from app.models import user  # noqa: F401
