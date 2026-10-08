"""
Test technique : vivier de questions, session de passage, réponses.

Trois tables, trois portées distinctes :

* `TestQuestion` appartient à l'OFFRE. Un vivier d'une trentaine de questions,
  généré puis validé une fois, dans lequel on puise pour tous les candidats de
  cette offre. C'est ce qui rend les notes comparables entre eux : un test
  regénéré pour chaque candidat ne mesurerait plus la même chose d'un dossier à
  l'autre.
* `TestSession` appartient à la CANDIDATURE. Elle porte le jeton public, les
  bornes de temps et la note. Même patron que `InterviewInvitation` : un lien
  suffit, aucun compte n'est requis.
* `TestAnswer` est la trace d'une question servie. Les horodatages y sont posés
  PAR LE SERVEUR — un temps calculé côté navigateur se réécrit en trois lignes
  dans la console.

Le déroulé est linéaire et sans retour : le candidat ne reçoit la question
suivante qu'après avoir répondu ou explicitement passé. Le serveur n'envoie
jamais qu'une question à la fois, sinon l'intégralité du test serait lisible
dans l'onglet réseau et la contrainte ne protégerait rien.
"""
import enum
import uuid

from sqlalchemy import (
    Column, DateTime, Enum, Float, ForeignKey, Index, Integer,
    JSON, String, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class QuestionDifficulty(str, enum.Enum):
    FACILE = "FACILE"
    MOYENNE = "MOYENNE"
    DIFFICILE = "DIFFICILE"


class QuestionKind(str, enum.Enum):
    QCM_UNIQUE = "QCM_UNIQUE"        # une seule bonne réponse
    QCM_MULTIPLE = "QCM_MULTIPLE"    # plusieurs bonnes réponses, tout ou rien
    REPONSE_COURTE = "REPONSE_COURTE"  # correspondance exacte, insensible à la casse


class QuestionStatus(str, enum.Enum):
    GENEREE = "GENEREE"    # sortie du modèle, jamais relue — ne part pas chez un candidat
    VALIDEE = "VALIDEE"    # relue par un RH
    ACTIVE = "ACTIVE"      # utilisable dans un test
    RETIREE = "RETIREE"    # écartée du vivier, conservée pour l'historique


class SessionStatus(str, enum.Enum):
    ENVOYE = "ENVOYE"        # lien transmis, test jamais ouvert
    EN_COURS = "EN_COURS"    # première question servie
    TERMINE = "TERMINE"      # soumis par le candidat
    EXPIRE = "EXPIRE"        # limite de temps atteinte, corrigé en l'état
    ABANDONNE = "ABANDONNE"  # lien jamais ouvert avant sa date de validité


class AnswerOutcome(str, enum.Enum):
    """
    Quatre issues, là où un booléen suffirait au calcul.

    `PASSEE` et `NON_ATTEINTE` valent zéro point comme `FAUSSE` : au barème,
    rien ne les distingue. Mais pour le RH qui relit la copie, « il s'est
    trompé », « il a préféré passer » et « il n'a pas eu le temps » ne disent
    pas la même chose du candidat. Un `is_correct` booléen effacerait cette
    différence définitivement.
    """
    CORRECTE = "CORRECTE"
    FAUSSE = "FAUSSE"
    PASSEE = "PASSEE"
    NON_ATTEINTE = "NON_ATTEINTE"


# Budget de temps indicatif par difficulté, en secondes. Ne bloque rien : le
# candidat n'en est pas informé et peut le dépasser. Le dépassement est
# enregistré et affiché au RH, mais n'entre JAMAIS dans le calcul de la note —
# on ne décide pas sur un critère que le candidat n'a pas pu connaître.
EXPECTED_SECONDS = {
    QuestionDifficulty.FACILE: 60,
    QuestionDifficulty.MOYENNE: 90,
    QuestionDifficulty.DIFFICILE: 150,
}

# Composition d'un test : 12 questions, du plus simple au plus exigeant.
DIFFICULTY_TEMPLATE = {
    QuestionDifficulty.FACILE: 4,
    QuestionDifficulty.MOYENNE: 5,
    QuestionDifficulty.DIFFICILE: 3,
}
DEFAULT_QUESTION_COUNT = sum(DIFFICULTY_TEMPLATE.values())   # 12
DEFAULT_DURATION_MINUTES = 20


class TestQuestion(Base):
    """Une question du vivier d'une offre."""
    __tablename__ = "test_questions"
    # pytest collecte toute classe nommée Test* : on l'en dissuade.
    __test__ = False

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_offer_id = Column(
        UUID(as_uuid=True), ForeignKey("job_offers.id", ondelete="CASCADE"), nullable=False
    )

    statement = Column(Text, nullable=False)
    # Liste de propositions pour un QCM ; vide pour une réponse courte.
    options = Column(JSON, nullable=True, default=list)
    # Toujours une LISTE, même pour une réponse unique : le format ne change pas
    # selon le type de question, la correction n'a donc qu'un seul cas à traiter.
    correct_answer = Column(JSON, nullable=False)
    explanation = Column(Text, nullable=True)

    difficulty = Column(
        Enum(QuestionDifficulty, name="question_difficulty"),
        nullable=False, default=QuestionDifficulty.MOYENNE, server_default="MOYENNE", index=True,
    )
    kind = Column(
        Enum(QuestionKind, name="question_kind"),
        nullable=False, default=QuestionKind.QCM_UNIQUE, server_default="QCM_UNIQUE",
    )
    status = Column(
        Enum(QuestionStatus, name="question_status"),
        nullable=False, default=QuestionStatus.GENEREE, server_default="GENEREE", index=True,
    )

    expected_seconds = Column(Integer, nullable=False, default=90, server_default="90")
    # Compétence de l'offre couverte par la question. Sert à garantir qu'un
    # test tiré du vivier n'interroge pas douze fois la même technologie.
    skill_tag = Column(String(80), nullable=True, index=True)

    generated_by = Column(String(40), nullable=True)   # "llm:gemini", "manuel"…
    validated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    validated_at = Column(DateTime(timezone=True), nullable=True)

    # Statistiques de calibrage, mises à jour à chaque correction. Une question
    # réussie par 0 % ou par 100 % des candidats ne discrimine rien et doit
    # sortir du vivier ; une question massivement passée est mal formulée.
    times_served = Column(Integer, nullable=False, default=0, server_default="0")
    times_correct = Column(Integer, nullable=False, default=0, server_default="0")
    times_skipped = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_test_questions_offer_status", "job_offer_id", "status"),
        Index("ix_test_questions_offer_difficulty", "job_offer_id", "difficulty"),
    )

    @property
    def success_rate(self) -> float | None:
        """Taux de réussite, ou None tant que la question n'a pas servi."""
        if not self.times_served:
            return None
        return round(self.times_correct / self.times_served * 100, 1)


class TestSession(Base):
    """Le passage du test par un candidat, pour une candidature donnée."""
    __tablename__ = "test_sessions"
    # pytest collecte toute classe nommée Test* : on l'en dissuade.
    __test__ = False

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Jeton public URL-safe, même principe que l'invitation d'entretien : le
    # candidat n'a pas besoin d'un compte pour passer le test.
    token = Column(String(64), nullable=False, unique=True)

    status = Column(
        Enum(SessionStatus, name="test_session_status"),
        nullable=False, default=SessionStatus.ENVOYE, server_default="ENVOYE", index=True,
    )
    question_count = Column(Integer, nullable=False, default=DEFAULT_QUESTION_COUNT,
                            server_default=str(DEFAULT_QUESTION_COUNT))
    duration_minutes = Column(Integer, nullable=False, default=DEFAULT_DURATION_MINUTES,
                              server_default=str(DEFAULT_DURATION_MINUTES))

    sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Date au-delà de laquelle le lien ne s'ouvre plus (72 h par défaut).
    link_expires_at = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    score = Column(Float, nullable=True)               # 0–100
    correct_count = Column(Integer, nullable=True)

    # Réservés au back-office : jamais renvoyés au candidat.
    total_overrun_seconds = Column(Integer, nullable=False, default=0, server_default="0")
    overrun_question_count = Column(Integer, nullable=False, default=0, server_default="0")
    anomaly_flags = Column(JSON, nullable=True, default=list)

    # Quel RH a envoyé ce test. Sert à lui adresser l'alerte de fin plutôt
    # qu'à tous les administrateurs. `SET NULL` : un départ ne doit pas
    # emporter l'historique des tests.
    sent_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Garde-fou d'idempotence de l'alerte de fin. La boucle de balayage repasse
    # toutes les deux minutes : sans cette marque, une session déjà annoncée le
    # serait encore à chaque passage.
    notified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    answers = relationship(
        "TestAnswer", back_populates="session",
        cascade="all, delete-orphan", order_by="TestAnswer.position",
    )

    __table_args__ = (
        # Recherche par jeton (lien du candidat) — index unique, en plus de la
        # contrainte d'unicité de la colonne, tel que créé par la migration.
        Index("ix_test_sessions_token", "token", unique=True),
        # Balayage des alertes de fin : sessions rendues, pas encore annoncées.
        Index("ix_test_sessions_notification_due", "submitted_at", "notified_at"),
    )

    @property
    def deadline(self):
        """
        Fin du temps imparti, calculée par le serveur.

        `started_at + duration` fait foi : une soumission arrivée après cette
        borne est corrigée en l'état, quoi qu'affiche le navigateur.
        """
        if not self.started_at:
            return None
        from datetime import timedelta

        from app.utils.helpers import as_utc
        # SQLite rend des dates SANS fuseau, PostgreSQL avec. Sans cette
        # normalisation, comparer la limite à l'heure courante lève un
        # TypeError sur l'un des deux moteurs seulement — le genre de bug qui
        # passe les tests et casse en production, ou l'inverse.
        return as_utc(self.started_at) + timedelta(minutes=self.duration_minutes)


class TestAnswer(Base):
    """Une question servie à un candidat, et ce qu'il en a fait."""
    __tablename__ = "test_answers"
    # pytest collecte toute classe nommée Test* : on l'en dissuade.
    __test__ = False

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("test_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    question_id = Column(
        UUID(as_uuid=True), ForeignKey("test_questions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Rang de présentation (1..n). L'ordre est mélangé par candidat.
    position = Column(Integer, nullable=False)

    given_answer = Column(JSON, nullable=True)
    outcome = Column(
        Enum(AnswerOutcome, name="answer_outcome"),
        nullable=False, default=AnswerOutcome.NON_ATTEINTE, server_default="NON_ATTEINTE",
    )

    # Horodatés par le SERVEUR, jamais renseignés par le client.
    served_at = Column(DateTime(timezone=True), nullable=True)
    answered_at = Column(DateTime(timezone=True), nullable=True)
    overrun_seconds = Column(Integer, nullable=False, default=0, server_default="0")

    session = relationship("TestSession", back_populates="answers")
    question = relationship("TestQuestion")

    __table_args__ = (
        Index("ix_test_answers_session_position", "session_id", "position", unique=True),
    )

    @property
    def elapsed_seconds(self) -> int | None:
        """Temps réellement mis, ou None si la question n'a pas été traitée."""
        if not self.served_at or not self.answered_at:
            return None
        from app.utils.helpers import as_utc
        return max(0, int((as_utc(self.answered_at) - as_utc(self.served_at)).total_seconds()))
