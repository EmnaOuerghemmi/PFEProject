"""
Réglages partagés de la plateforme, en clé / valeur JSON.

Un réglage qui vaut pour TOUS les utilisateurs — la composition du tableau de
bord fixée par l'administrateur, par exemple — n'a pas sa place sur la ligne
d'un utilisateur : avec plusieurs administrateurs, laquelle ferait foi ? Une
table clé / valeur évite aussi une migration par nouveau réglage.
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(JSON, nullable=False, default=dict)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
