import uuid
from datetime import date

from sqlalchemy import Column, Date, DateTime, Float, Index, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


#: Vocabulaire du genre. « non renseigné » en fait partie et n'est pas un
#: oubli : la fiche est créée par un traitement automatique, sans personne
#: devant l'écran, et le genre ne se déduit PAS d'un prénom — c'est faux une
#: fois sur dix, et invisible quand ça l'est.
GENDERS = ("F", "M", "AUTRE", "NON_RENSEIGNE")

GENDER_LABELS = {
    "F": "Femme",
    "M": "Homme",
    "AUTRE": "Autre",
    "NON_RENSEIGNE": "Non renseigné",
}

#: Types de contrat, alignés sur ceux des offres (`schemas/recruitment.py`).
CONTRACT_TYPES = ("CDI", "CDD", "SIVP", "STAGE", "FREELANCE")

#: Champs attendus sur une fiche complète. Sert au repère « à compléter » de la
#: liste : sans lui, les fiches créées automatiquement resteraient incomplètes
#: sans que personne ne le remarque.
EXPECTED_FIELDS = ("birth_date", "gender", "position", "department",
                   "contract_type", "hire_date")


class Employee(Base):
    """
    Fiche employé interne (backoffice « Employés »). Distincte de `users`
    (comptes de connexion) : un employé n'a pas forcément de compte.
    Salaire mensuel brut en TND.
    """
    __tablename__ = "employees"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    phone = Column(String(30), nullable=True)
    position = Column(String(150), nullable=True)
    department = Column(String(100), nullable=True, index=True)
    salary = Column(Float, nullable=True)  # TND mensuel brut
    hire_date = Column(DateTime(timezone=True), nullable=True)
    # active | inactive | on-leave
    status = Column(String(20), nullable=False, default="active")

    # ── Données de pilotage RH ────────────────────────────────────────────────
    # Toutes nullables : la fiche est créée par un traitement de fond à la
    # signature du contrat, sans personne pour les saisir. Elles arrivent donc
    # vides et se complètent ensuite — d'où `missing_fields`.
    #
    # La DATE de naissance, pas l'âge : un âge stocké devient faux au bout d'un
    # an, et rien ne le signale.
    birth_date = Column(Date, nullable=True, index=True)
    gender = Column(String(20), nullable=True, index=True)
    contract_type = Column(String(20), nullable=True)
    education_level = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_employees_dept_status", "department", "status"),)

    @property
    def age(self) -> int | None:
        """
        Âge en années révolues, calculé — jamais stocké.

        `None` si la date de naissance manque : c'est une information absente,
        pas un âge de zéro. Les confondre placerait tous les employés non
        renseignés dans la tranche des nouveau-nés.
        """
        if not self.birth_date:
            return None
        aujourdhui = date.today()
        annees = aujourdhui.year - self.birth_date.year
        # L'anniversaire n'est pas encore passé cette année.
        if (aujourdhui.month, aujourdhui.day) < (self.birth_date.month,
                                                 self.birth_date.day):
            annees -= 1
        return annees if annees >= 0 else None

    @property
    def missing_fields(self) -> list[str]:
        """
        Ce qu'il reste à renseigner sur cette fiche.

        Calculé, pas stocké : une colonne se désynchroniserait de son contenu à
        la première modification qui oublierait de la mettre à jour.
        """
        manquants = []
        for champ in EXPECTED_FIELDS:
            valeur = getattr(self, champ, None)
            # « Non renseigné » est une réponse volontaire, pas un manque : le
            # RH qui l'a choisi ne doit pas être relancé indéfiniment.
            if valeur is None or (isinstance(valeur, str) and not valeur.strip()):
                manquants.append(champ)
        return manquants
