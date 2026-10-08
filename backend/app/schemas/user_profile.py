"""
Fiche d'un utilisateur, vue par l'administration.

Deux formes selon qui l'on regarde :

* **Un candidat** — son compte, son CV de référence, ses candidatures avec leur
  score, l'état de ses tests techniques et son score composite.
* **Toute autre personne** — son compte seul. Un RH n'a pas de candidatures ;
  afficher des sections vides laisserait croire à une donnée manquante.

Ce qui n'y figure JAMAIS, quel que soit le rôle du demandeur : mot de passe
haché, secret TOTP, codes de secours, jetons de rafraîchissement ou de
vérification. Ce sont des secrets d'authentification, pas des informations de
profil — les exposer transformerait une fiche en moyen d'usurpation.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileAccount(BaseModel):
    """Le compte — champs sûrs uniquement."""
    id: UUID
    email: str
    username: str
    full_name: str | None = None
    phone_number: str | None = None
    avatar_url: str | None = None
    role: str
    is_active: bool
    is_verified: bool
    is_superuser: bool
    totp_enabled: bool
    department: str | None = None
    job_title: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProfileCandidate(BaseModel):
    """Le dossier candidat, quand la personne en a un."""
    id: UUID
    full_name: str
    phone: str | None = None
    cv_filename: str | None = None
    #: Chemin de stockage du CV de référence — réservé à ADMIN/RH,
    #: comme cette fiche entière. Sert uniquement à construire le lien
    #: d'aperçu ; c'est le même choix déjà fait pour `cv_file_path` sur
    #: chaque candidature (`ApplicationResponse`), qu'on ne réinvente pas ici.
    cv_path: str | None = None
    cv_uploaded_at: datetime | None = None
    created_at: datetime


class ProfileTestSession(BaseModel):
    """L'essentiel d'un test technique — jamais le détail des réponses."""
    status: str
    score: float | None = None
    correct_count: int | None = None
    question_count: int
    submitted_at: datetime | None = None


class ProfileApplication(BaseModel):
    id: UUID
    job_offer_id: UUID
    job_title: str
    status: str
    status_label: str
    applied_at: datetime
    expected_salary: float | None = None

    #: Score de correspondance du CV. `None` tant que l'analyse n'a pas tourné.
    cv_score: float | None = None
    composite_score: float | None = None
    #: Nombre de volets disponibles (1 à 3). Deux composites de complétude
    #: différente ne se comparent pas — l'afficher sans lui serait trompeur.
    composite_completeness: int | None = None
    interview_score: float | None = None
    #: Ce que le RH a écrit pendant/après l'entretien — libre, jamais partagé
    #: au candidat. C'était présent en base mais absent de cette fiche.
    interview_notes: str | None = None
    #: Résumé de la proposition du modèle, à titre de repère. La note retenue
    #: reste `interview_score`, celle du RH — jamais celle-ci.
    interview_ai_summary: str | None = None

    test: ProfileTestSession | None = None


class ProfileStats(BaseModel):
    """Compteurs d'en-tête, pour situer le dossier d'un coup d'œil."""
    applications: int = 0
    tests_taken: int = 0
    interviews: int = 0
    best_score: float | None = None


class UserProfile(BaseModel):
    account: ProfileAccount
    #: Faux pour un RH ou un administrateur : la fiche s'arrête au compte.
    is_candidate: bool = False
    candidate: ProfileCandidate | None = None
    applications: list[ProfileApplication] = Field(default_factory=list)
    stats: ProfileStats = Field(default_factory=ProfileStats)
    #: Détail libre pour les comptes internes (rôle, permissions).
