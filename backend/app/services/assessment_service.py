"""
Test technique : vivier, tirage, correction, notation.

Ce module ne connaît ni HTTP ni LLM. Il porte les règles métier :

* comment on choisit les 12 questions d'un test parmi la trentaine du vivier ;
* comment on corrige une réponse selon son type ;
* comment on note une session et ce qu'on en retient pour le calibrage.

Le service des questions une par une et le chronométrage HTTP appartiennent à
l'endpoint (lot 2) : ici, les horodatages sont reçus, jamais fabriqués.
"""
from __future__ import annotations

import logging
import random
import secrets
import unicodedata
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Iterable, Optional, Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import application_status
from app.models.application_status import ApplicationStatus
from app.models.assessment import (
    DEFAULT_DURATION_MINUTES, DEFAULT_QUESTION_COUNT, DIFFICULTY_TEMPLATE,
    EXPECTED_SECONDS, AnswerOutcome, QuestionDifficulty, QuestionKind,
    QuestionStatus, SessionStatus, TestAnswer, TestQuestion, TestSession,
)
from app.models.recruitment import Application, Candidate, JobOffer
from app.utils.helpers import as_utc, utcnow

logger = logging.getLogger(__name__)

# Validité du lien envoyé au candidat.
LINK_VALIDITY_HOURS = 72

# En dessous de ce temps, une bonne réponse à une question difficile est
# signalée : elle suggère une recherche externe. C'est un DRAPEAU remonté au RH,
# jamais une pénalité — quelqu'un peut simplement connaître la réponse.
SUSPICIOUS_SECONDS = 10


def _normaliser(texte: str) -> str:
    """Minuscules, sans accents ni espaces superflus — pour les réponses courtes."""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", str(texte or "").strip().lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sans_accent.split())


class AssessmentService:

    # ── Vivier ────────────────────────────────────────────────────────────────

    async def list_questions(
        self, db: AsyncSession, job_offer_id: UUID,
        statuses: Optional[Sequence[QuestionStatus]] = None,
    ) -> list[TestQuestion]:
        requete = select(TestQuestion).where(TestQuestion.job_offer_id == job_offer_id)
        if statuses:
            requete = requete.where(TestQuestion.status.in_(list(statuses)))
        requete = requete.order_by(TestQuestion.difficulty, TestQuestion.created_at)
        return list((await db.execute(requete)).scalars().all())

    async def get_question(self, db: AsyncSession, question_id: UUID) -> TestQuestion:
        question = (await db.execute(
            select(TestQuestion).where(TestQuestion.id == question_id)
        )).scalar_one_or_none()
        if not question:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question introuvable.")
        return question

    async def create_question(
        self, db: AsyncSession, job_offer_id: UUID, data: dict,
        *, generated_by: str = "manuel",
    ) -> TestQuestion:
        """
        Ajoute une question au vivier.

        Une question saisie à la main naît VALIDEE : c'est un humain qui l'écrit.
        Une question produite par un modèle naît GENEREE et devra être relue —
        c'est la seule barrière entre une fausse bonne réponse et un candidat
        pénalisé sans que personne ne le sache.
        """
        await self._assert_offer_exists(db, job_offer_id)
        difficulte = QuestionDifficulty(data.get("difficulty", QuestionDifficulty.MOYENNE))
        question = TestQuestion(
            job_offer_id=job_offer_id,
            statement=data["statement"],
            options=data.get("options") or [],
            correct_answer=self._normaliser_cle(data["correct_answer"]),
            explanation=data.get("explanation"),
            difficulty=difficulte,
            kind=QuestionKind(data.get("kind", QuestionKind.QCM_UNIQUE)),
            status=QuestionStatus.VALIDEE if generated_by == "manuel" else QuestionStatus.GENEREE,
            expected_seconds=data.get("expected_seconds") or EXPECTED_SECONDS[difficulte],
            skill_tag=(data.get("skill_tag") or None),
            generated_by=generated_by,
        )
        self._valider_coherence(question)
        db.add(question)
        await db.flush()
        return question

    async def update_question(
        self, db: AsyncSession, question_id: UUID, data: dict
    ) -> TestQuestion:
        question = await self.get_question(db, question_id)
        for champ in ("statement", "options", "explanation", "skill_tag", "expected_seconds"):
            if champ in data and data[champ] is not None:
                setattr(question, champ, data[champ])
        if data.get("correct_answer") is not None:
            question.correct_answer = self._normaliser_cle(data["correct_answer"])
        if data.get("difficulty"):
            question.difficulty = QuestionDifficulty(data["difficulty"])
            # Le budget suit la difficulté tant qu'il n'a pas été fixé à la main.
            if not data.get("expected_seconds"):
                question.expected_seconds = EXPECTED_SECONDS[question.difficulty]
        if data.get("kind"):
            question.kind = QuestionKind(data["kind"])
        self._valider_coherence(question)
        await db.flush()
        return question

    async def set_question_status(
        self, db: AsyncSession, question_id: UUID,
        nouveau: QuestionStatus, *, validated_by: Optional[UUID] = None,
    ) -> TestQuestion:
        question = await self.get_question(db, question_id)
        question.status = nouveau
        if nouveau in (QuestionStatus.VALIDEE, QuestionStatus.ACTIVE):
            question.validated_by = validated_by
            question.validated_at = utcnow()
        await db.flush()
        return question

    async def activate_bank(self, db: AsyncSession, job_offer_id: UUID,
                            validated_by: UUID) -> int:
        """Bascule toutes les questions relues en ACTIVE. Renvoie le compte."""
        questions = await self.list_questions(
            db, job_offer_id, [QuestionStatus.VALIDEE]
        )
        maintenant = utcnow()
        for question in questions:
            question.status = QuestionStatus.ACTIVE
            question.validated_by = validated_by
            question.validated_at = maintenant
        await db.flush()
        return len(questions)

    # ── Tirage des questions d'un test ────────────────────────────────────────

    async def recommend_questions(
        self, db: AsyncSession, job_offer_id: UUID,
        count: int = DEFAULT_QUESTION_COUNT,
    ) -> list[TestQuestion]:
        """
        Présélectionne les questions d'un test parmi le vivier ACTIVE.

        Deux contraintes, dans cet ordre :

        1. **Couverture des compétences** — chaque `required_skill` de l'offre
           doit apparaître au moins une fois avant qu'une compétence soit
           représentée deux fois. Sans cette règle, un tirage parfaitement
           plausible donne douze questions sur une seule technologie et le test
           ne mesure plus le poste.
        2. **Gabarit de difficulté** — 4 faciles, 5 moyennes, 3 difficiles pour
           douze questions, ajusté au prorata si le RH demande un autre nombre.

        Quand le vivier ne permet pas de tenir le gabarit, on complète avec ce
        qui reste plutôt que de rendre une liste incomplète : c'est au RH de
        voir le déséquilibre à l'écran et de décider.
        """
        disponibles = await self.list_questions(db, job_offer_id, [QuestionStatus.ACTIVE])
        if not disponibles:
            return []

        offre = await self._assert_offer_exists(db, job_offer_id)
        competences = [str(s).strip().lower() for s in (offre.required_skills or []) if str(s).strip()]

        quotas = self._quotas(count)
        par_difficulte: dict[QuestionDifficulty, list[TestQuestion]] = defaultdict(list)
        for question in disponibles:
            par_difficulte[question.difficulty].append(question)
        for lot in par_difficulte.values():
            # Les questions les moins servies d'abord : le vivier tourne au lieu
            # de resservir éternellement les mêmes douze.
            random.shuffle(lot)
            lot.sort(key=lambda q: q.times_served)

        retenues: list[TestQuestion] = []
        couvertes: set[str] = set()

        def prendre(lot: list[TestQuestion], privilegier_nouvelles: bool) -> Optional[TestQuestion]:
            for question in lot:
                tag = (question.skill_tag or "").strip().lower()
                if privilegier_nouvelles and tag and tag in couvertes:
                    continue
                lot.remove(question)
                if tag:
                    couvertes.add(tag)
                return question
            return None

        # Premier passage : on cherche à couvrir des compétences neuves.
        for difficulte, quota in quotas.items():
            lot = par_difficulte[difficulte]
            for _ in range(quota):
                question = prendre(lot, privilegier_nouvelles=bool(competences)) or prendre(lot, False)
                if question:
                    retenues.append(question)

        # Complément si le gabarit n'a pas pu être tenu.
        if len(retenues) < count:
            reste = [q for lot in par_difficulte.values() for q in lot]
            reste.sort(key=lambda q: q.times_served)
            retenues.extend(reste[: count - len(retenues)])

        retenues.sort(key=lambda q: list(QuestionDifficulty).index(q.difficulty))
        return retenues[:count]

    def coverage_report(
        self, questions: Iterable[TestQuestion], required_skills: Iterable[str]
    ) -> dict:
        """
        Ce que l'écran de sélection doit afficher en permanence.

        Sans ces deux compteurs sous les yeux, un RH décoche librement et envoie
        un test déséquilibré sans s'en apercevoir.
        """
        questions = list(questions)
        attendues = {str(s).strip().lower() for s in required_skills if str(s).strip()}
        couvertes = {
            (q.skill_tag or "").strip().lower() for q in questions if q.skill_tag
        } & attendues
        par_difficulte = Counter(q.difficulty.value for q in questions)
        return {
            "total": len(questions),
            "par_difficulte": {d.value: par_difficulte.get(d.value, 0) for d in QuestionDifficulty},
            "gabarit": {d.value: n for d, n in self._quotas(len(questions) or DEFAULT_QUESTION_COUNT).items()},
            "competences_couvertes": sorted(couvertes),
            "competences_manquantes": sorted(attendues - couvertes),
        }

    # ── Session ───────────────────────────────────────────────────────────────

    async def create_session(
        self, db: AsyncSession, application_id: UUID, question_ids: Sequence[UUID],
        *, duration_minutes: int = DEFAULT_DURATION_MINUTES,
    ) -> TestSession:
        """
        Ouvre une session et fige l'ordre des questions.

        L'ordre est mélangé par candidat, et les lignes de réponse sont créées
        d'emblée : le serveur sait ainsi exactement quelle question vient
        ensuite, sans avoir à retirer au vol — et une question ne peut pas être
        servie deux fois.
        """
        if not question_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Sélectionnez au moins une question.")

        application = (await db.execute(
            select(Application).where(Application.id == application_id)
        )).scalar_one_or_none()
        if not application:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidature introuvable.")

        existante = (await db.execute(
            select(TestSession).where(
                TestSession.application_id == application_id,
                TestSession.status.in_([SessionStatus.ENVOYE, SessionStatus.EN_COURS]),
            )
        )).scalar_one_or_none()
        if existante:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Un test est déjà en cours pour cette candidature.",
            )

        questions = list((await db.execute(
            select(TestQuestion).where(TestQuestion.id.in_(list(question_ids)))
        )).scalars().all())
        if len(questions) != len(set(question_ids)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Certaines questions sélectionnées n'existent plus.")
        inactives = [q for q in questions if q.status != QuestionStatus.ACTIVE]
        if inactives:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{len(inactives)} question(s) ne sont pas actives : relisez le vivier avant l'envoi.",
            )

        session = TestSession(
            application_id=application_id,
            token=secrets.token_urlsafe(32),
            status=SessionStatus.ENVOYE,
            question_count=len(questions),
            duration_minutes=duration_minutes,
            link_expires_at=utcnow() + timedelta(hours=LINK_VALIDITY_HOURS),
        )
        db.add(session)
        await db.flush()

        random.shuffle(questions)
        for rang, question in enumerate(questions, start=1):
            db.add(TestAnswer(
                session_id=session.id, question_id=question.id,
                position=rang, outcome=AnswerOutcome.NON_ATTEINTE,
            ))
        await db.flush()
        logger.info("Session de test %s ouverte pour la candidature %s (%d questions)",
                    session.id, application_id, len(questions))
        return session

    async def auto_send_test_for_confirmed_interview(
        self, db: AsyncSession, application_id: UUID,
    ) -> Optional[TestSession]:
        """
        Envoie automatiquement un test au candidat qui vient de confirmer un
        entretien — pour qu'il l'ait fait avant d'y arriver.

        Silencieux par construction, comme l'indexation sémantique : l'appelant
        est un flux de confirmation, pas un flux de test, et une raison de ne
        pas envoyer (pas de vivier, déjà testé, sous le seuil) n'est jamais une
        erreur à remonter au candidat — juste rien à faire ici. Le RH garde la
        main : un test déjà en cours, terminé ou expiré n'est jamais recouvert.
        """
        from app.core.config import settings
        from app.models.scoring import CandidateScore

        deja = (await db.execute(
            select(TestSession.id).where(TestSession.application_id == application_id)
        )).scalar_one_or_none()
        if deja is not None:
            return None

        application = (await db.execute(
            select(Application).where(Application.id == application_id)
        )).scalar_one_or_none()
        if not application:
            return None

        score = (await db.execute(
            select(CandidateScore.total_score)
            .where(CandidateScore.application_id == application_id)
        )).scalar_one_or_none()
        if score is None or score < settings.TEST_ELIGIBILITY_MIN_SCORE:
            return None

        questions = await self.recommend_questions(db, application.job_offer_id)
        if not questions:
            return None

        try:
            session = await self.create_session(db, application_id, [q.id for q in questions])
        except HTTPException:
            return None

        application.status = ApplicationStatus.TEST_SENT.value
        await db.flush()
        return session

    async def get_session_by_token(self, db: AsyncSession, token: str) -> TestSession:
        session = (await db.execute(
            select(TestSession)
            .options(selectinload(TestSession.answers).selectinload(TestAnswer.question))
            .where(TestSession.token == token)
        )).scalar_one_or_none()
        if not session:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Test introuvable ou lien expiré.")
        return session

    # ── Déroulé du test ───────────────────────────────────────────────────────

    async def open_session(self, db: AsyncSession, token: str) -> TestSession:
        """
        Ouvre le lien. Démarre le chronomètre au premier accès.

        C'est ici que `started_at` est posé, et nulle part ailleurs : la limite
        de temps court à partir du moment où le candidat ouvre réellement le
        test, pas de l'envoi de l'e-mail.
        """
        session = await self.get_session_by_token(db, token)

        if session.status in (SessionStatus.TERMINE, SessionStatus.EXPIRE):
            return session
        if session.status == SessionStatus.ENVOYE:
            if utcnow() > as_utc(session.link_expires_at):
                session.status = SessionStatus.ABANDONNE
                await db.flush()
                raise HTTPException(status.HTTP_410_GONE,
                                    "Ce lien a expiré. Contactez le recruteur.")
            session.status = SessionStatus.EN_COURS
            session.started_at = utcnow()
            await self._refleter_sur_la_candidature(
                db, session, ApplicationStatus.EN_TEST
            )
            await db.flush()

        # Le temps a pu s'écouler entre deux visites : on referme si besoin.
        await self.expire_if_due(db, session)
        return session

    async def expire_if_due(self, db: AsyncSession, session: TestSession) -> bool:
        """
        Clôt une session dont le temps global est écoulé.

        C'est `started_at + duration`, côté serveur, qui fait foi — quoi
        qu'affiche le navigateur, et quelle que soit la requête entrante.
        """
        if session.status != SessionStatus.EN_COURS or not session.deadline:
            return False
        if utcnow() <= session.deadline:
            return False
        session.status = SessionStatus.EXPIRE
        session.submitted_at = session.deadline
        await self.score_session(db, session)
        return True

    def seconds_remaining(self, session: TestSession) -> int:
        """Temps global restant, seule information de temps donnée au candidat."""
        if not session.deadline:
            return session.duration_minutes * 60
        return max(0, int((session.deadline - utcnow()).total_seconds()))

    async def serve_next(self, db: AsyncSession, session: TestSession) -> Optional[TestAnswer]:
        """
        Sert LA question suivante, et une seule.

        Envoyer les douze d'un coup rendrait tout le test lisible dans l'onglet
        réseau : la progression imposée ne protégerait plus rien et les temps
        par question ne voudraient plus rien dire.

        `served_at` est posé au premier envoi seulement. Un candidat qui
        rafraîchit sa page ne remet pas son chronomètre à zéro.
        """
        if session.status != SessionStatus.EN_COURS:
            return None
        for reponse in sorted(session.answers, key=lambda r: r.position):
            if reponse.answered_at is None:
                if reponse.served_at is None:
                    reponse.served_at = utcnow()
                    await db.flush()
                return reponse
        return None

    async def submit_answer(
        self, db: AsyncSession, session: TestSession, position: int, given_answer,
    ) -> Optional[TestAnswer]:
        """
        Enregistre une réponse et rend la question suivante.

        Trois refus, qui sont la raison d'être de ce service :

        * hors séquence — on ne répond qu'à la question en cours, jamais à la
          suivante ni à une précédente ;
        * déjà répondue — pas de correction après coup, la progression est
          définitive ;
        * temps écoulé — la session est close et corrigée en l'état.
        """
        if await self.expire_if_due(db, session):
            raise HTTPException(status.HTTP_410_GONE, "Le temps imparti est écoulé.")
        if session.status != SessionStatus.EN_COURS:
            raise HTTPException(status.HTTP_409_CONFLICT, "Ce test n'est plus en cours.")

        courante = await self.serve_next(db, session)
        if courante is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Toutes les questions ont été traitées.")
        if courante.position != position:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Répondez à la question {courante.position} avant de passer à la suite.",
            )

        self.record_answer(courante, given_answer, answered_at=utcnow())
        await db.flush()

        suivante = await self.serve_next(db, session)
        if suivante is None:
            await self.score_session(db, session)
        return suivante

    # ── Correction ────────────────────────────────────────────────────────────

    def grade(self, question: TestQuestion, given_answer) -> AnswerOutcome:
        """
        Corrige une réponse. `None` ou vide vaut PASSEE.

        Les QCM à réponses multiples sont en tout ou rien : une réponse
        partielle n'est pas une demi-compréhension, et attribuer des points
        partiels rendrait le barème arbitraire.
        """
        if given_answer is None or given_answer == [] or given_answer == "":
            return AnswerOutcome.PASSEE

        attendu = self._normaliser_cle(question.correct_answer)
        donne = self._normaliser_cle(given_answer)

        if question.kind == QuestionKind.REPONSE_COURTE:
            acceptees = {_normaliser(v) for v in attendu}
            juste = bool(donne) and _normaliser(donne[0]) in acceptees
        elif question.kind == QuestionKind.QCM_MULTIPLE:
            juste = {str(v) for v in donne} == {str(v) for v in attendu}
        else:
            juste = len(donne) == 1 and str(donne[0]) == str(attendu[0]) if attendu else False

        return AnswerOutcome.CORRECTE if juste else AnswerOutcome.FAUSSE

    def record_answer(self, answer: TestAnswer, given_answer, *, answered_at) -> AnswerOutcome:
        """
        Enregistre une réponse et calcule son dépassement.

        `answered_at` vient de l'appelant, qui l'obtient de l'horloge SERVEUR.
        Le dépassement se mesure contre le budget de la question, jamais contre
        une valeur fournie par le client.
        """
        answer.given_answer = given_answer
        answer.answered_at = answered_at
        answer.outcome = self.grade(answer.question, given_answer)

        ecoule = answer.elapsed_seconds
        budget = answer.question.expected_seconds or 90
        answer.overrun_seconds = max(0, ecoule - budget) if ecoule is not None else 0
        return answer.outcome

    async def score_session(self, db: AsyncSession, session: TestSession) -> TestSession:
        """
        Clôt une session : note, dépassements, anomalies, statistiques du vivier.

        Les questions jamais servies restent NON_ATTEINTE et comptent zéro, comme
        une réponse fausse — mais restent distinguables à la relecture.
        """
        reponses = session.answers
        justes = sum(1 for r in reponses if r.outcome == AnswerOutcome.CORRECTE)
        total = len(reponses) or 1

        session.correct_count = justes
        session.score = round(justes / total * 100, 1)
        session.total_overrun_seconds = sum(r.overrun_seconds or 0 for r in reponses)
        session.overrun_question_count = sum(1 for r in reponses if (r.overrun_seconds or 0) > 0)
        session.anomaly_flags = self._anomalies(reponses)
        if session.status != SessionStatus.EXPIRE:
            session.status = SessionStatus.TERMINE
        session.submitted_at = session.submitted_at or utcnow()

        # Calibrage du vivier : ces compteurs disent plus tard quelles questions
        # ne discriminent rien et doivent en sortir.
        for reponse in reponses:
            question = reponse.question
            if reponse.outcome == AnswerOutcome.NON_ATTEINTE:
                continue
            question.times_served += 1
            if reponse.outcome == AnswerOutcome.CORRECTE:
                question.times_correct += 1
            elif reponse.outcome == AnswerOutcome.PASSEE:
                question.times_skipped += 1

        await self._refleter_sur_la_candidature(db, session, ApplicationStatus.TEST_DONE)

        await db.flush()
        logger.info("Session de test %s notée : %.1f/100 (%d/%d)",
                    session.id, session.score, justes, total)
        return session

    @staticmethod
    async def _refleter_sur_la_candidature(
        db: AsyncSession, session: TestSession, cible: ApplicationStatus
    ) -> None:
        """
        Reporte l'état du test sur la candidature.

        Appelé depuis `open_session` et `score_session`, et de nulle part
        ailleurs : ce sont les deux seuls goulots par lesquels une session
        change d'état. Le recopier à la main depuis un écran ferait diverger
        les deux vérités — une session expirée par le balayage laisserait une
        candidature bloquée sur « Test en cours ».

        Best-effort : une candidature déjà plus avancée dans le parcours ne
        recule pas, et l'échec du report ne doit jamais empêcher le test de se
        dérouler. La session, elle, reste la source faisant foi.
        """
        application = (await db.execute(
            select(Application).where(Application.id == session.application_id)
        )).scalar_one_or_none()
        if not application:
            return
        if application_status.can_transition(application.status, cible.value):
            application.status = cible.value

    # ── Interne ───────────────────────────────────────────────────────────────

    @staticmethod
    def _quotas(count: int) -> dict[QuestionDifficulty, int]:
        """Gabarit de difficulté, mis à l'échelle du nombre demandé."""
        if count == DEFAULT_QUESTION_COUNT:
            return dict(DIFFICULTY_TEMPLATE)
        quotas, attribues = {}, 0
        difficultes = list(DIFFICULTY_TEMPLATE)
        for difficulte in difficultes[:-1]:
            part = round(count * DIFFICULTY_TEMPLATE[difficulte] / DEFAULT_QUESTION_COUNT)
            quotas[difficulte] = part
            attribues += part
        quotas[difficultes[-1]] = max(0, count - attribues)
        return quotas

    @staticmethod
    def _normaliser_cle(valeur) -> list:
        """Toute réponse est une LISTE — la correction n'a ainsi qu'un cas."""
        if valeur is None:
            return []
        return list(valeur) if isinstance(valeur, (list, tuple, set)) else [valeur]

    @staticmethod
    def _valider_coherence(question: TestQuestion) -> None:
        """
        Refuse une question inutilisable avant qu'elle n'atteigne un candidat.

        Ces contrôles paraissent tatillons ; ils attrapent exactement ce qu'un
        modèle produit de travers — une bonne réponse absente des options, un
        QCM à une seule proposition, une réponse multiple qui n'en contient
        qu'une.
        """
        attendu = [str(v) for v in (question.correct_answer or [])]
        if not attendu:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Une question doit avoir au moins une bonne réponse.")

        if question.kind == QuestionKind.REPONSE_COURTE:
            return

        options = [str(o) for o in (question.options or [])]
        if len(options) < 2:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Un QCM demande au moins deux propositions.")
        hors_options = [v for v in attendu if v not in options]
        if hors_options:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"La bonne réponse ne figure pas dans les propositions : {hors_options}.",
            )
        if question.kind == QuestionKind.QCM_UNIQUE and len(attendu) != 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Un QCM à réponse unique doit avoir exactement une bonne réponse.")
        if question.kind == QuestionKind.QCM_MULTIPLE and len(attendu) < 2:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Un QCM à réponses multiples doit en avoir au moins deux.")

    @staticmethod
    def _anomalies(reponses: Sequence[TestAnswer]) -> list[dict]:
        """
        Signale les réponses justes anormalement rapides sur les questions
        difficiles. Remonté au RH comme un doute, jamais soustrait de la note.
        """
        drapeaux = []
        for reponse in reponses:
            ecoule = reponse.elapsed_seconds
            if (reponse.outcome == AnswerOutcome.CORRECTE
                    and ecoule is not None and ecoule < SUSPICIOUS_SECONDS
                    and reponse.question.difficulty == QuestionDifficulty.DIFFICILE):
                drapeaux.append({
                    "type": "reponse_rapide",
                    "position": reponse.position,
                    "seconds": ecoule,
                    "message": f"Bonne réponse à une question difficile en {ecoule} s.",
                })
        return drapeaux

    @staticmethod
    async def _assert_offer_exists(db: AsyncSession, job_offer_id: UUID) -> JobOffer:
        offre = (await db.execute(
            select(JobOffer).where(JobOffer.id == job_offer_id)
        )).scalar_one_or_none()
        if not offre:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Offre introuvable.")
        return offre


assessment_service = AssessmentService()


async def sweep_expired_sessions(db: AsyncSession) -> int:
    """
    Balayage de fond : clôt les tests dont le temps est écoulé et abandonne les
    liens jamais ouverts.

    Sans ce balayage, une session laissée ouverte par un candidat qui ferme son
    navigateur resterait EN_COURS indéfiniment et n'apparaîtrait jamais comme
    terminée côté RH. La correction se fait en l'état, questions non atteintes
    comprises.
    """
    maintenant = utcnow()
    traitees = 0

    en_cours = (await db.execute(
        select(TestSession)
        .options(selectinload(TestSession.answers).selectinload(TestAnswer.question))
        .where(TestSession.status == SessionStatus.EN_COURS)
    )).scalars().all()
    for session in en_cours:
        try:
            if await assessment_service.expire_if_due(db, session):
                traitees += 1
        except Exception as exc:  # pragma: no cover - défensif, une session ne doit pas bloquer les autres
            logger.warning("Clôture de la session de test %s impossible : %s", session.id, exc)

    jamais_ouverts = (await db.execute(
        select(TestSession).where(
            TestSession.status == SessionStatus.ENVOYE,
            TestSession.link_expires_at < maintenant,
        )
    )).scalars().all()
    for session in jamais_ouverts:
        session.status = SessionStatus.ABANDONNE
        traitees += 1

    if traitees:
        await db.commit()
        logger.info("Balayage des tests : %d session(s) closes.", traitees)
    return traitees


async def send_due_test_notifications(db: AsyncSession) -> int:
    """
    Prévient le RH des tests rendus, par notification et par courriel.

    Pourquoi un balayage plutôt qu'un envoi depuis `score_session` :

    * **Une session se ferme par quatre chemins** — le candidat termine, il
      répond à la dernière question, son temps s'écoule, ou le balayage la
      referme parce qu'il a fermé son navigateur. Envoyer depuis chacun serait
      quatre occasions d'en oublier un ; or c'est justement le dernier cas, le
      candidat qui disparaît, dont le RH doit être averti.
    * **Deux de ces chemins sont des requêtes HTTP du candidat.** Y greffer un
      envoi SMTP le ferait attendre le serveur de messagerie pour voir son
      écran de fin.

    `notified_at` est posé AVANT l'envoi, délibérément. Si le SMTP échoue et
    qu'on ne l'a pas posé, ce balayage réessaie toutes les deux minutes,
    indéfiniment. Une alerte perdue et journalisée vaut mieux qu'une boucle
    d'envoi — le résultat, lui, reste consultable dans le back-office.
    """
    from app.core.config import settings
    from app.models.user import User, UserRole
    from app.services.email_service import send_technical_test_completed
    from app.services.notification_service import notification_service

    a_annoncer = (await db.execute(
        select(TestSession).where(
            TestSession.submitted_at.is_not(None),
            TestSession.notified_at.is_(None),
        )
    )).scalars().all()
    if not a_annoncer:
        return 0

    envoyees = 0
    for session in a_annoncer:
        # Posé d'abord : voir la note de docstring.
        session.notified_at = utcnow()
        try:
            contexte = (await db.execute(
                select(Candidate.full_name, JobOffer.title, Application.id)
                .select_from(Application)
                .join(Candidate, Application.candidate_id == Candidate.id)
                .join(JobOffer, Application.job_offer_id == JobOffer.id)
                .where(Application.id == session.application_id)
            )).first()
            if not contexte:
                continue
            nom_candidat, poste, app_id = contexte

            issue = session.status.value
            lien = f"/admin/assessment?application={app_id}"
            titre = "Test technique rendu"
            corps = (f"{nom_candidat} a rendu son test pour le poste de {poste}"
                     + (f" — {session.score:.0f}/100." if session.score is not None else "."))

            # Le RH qui a envoyé le test, plus les administrateurs — mais
            # DÉDUPLIQUÉS. Le RH qui envoie est très souvent administrateur
            # lui-même : le notifier par les deux voies lui vaudrait deux
            # notifications et deux courriels à chaque test rendu.
            admins = (await db.execute(
                select(User.id).where(
                    User.role == UserRole.ADMIN,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )).scalars().all()

            destinataires_ids = set(admins)
            if session.sent_by:
                destinataires_ids.add(session.sent_by)

            for destinataire in destinataires_ids:
                await notification_service.notify_user(
                    db, recipient_id=destinataire, type="TEST_COMPLETED",
                    title=titre, message=corps, link=lien,
                )

            # Courriels, aux mêmes personnes, dédupliqués.
            adresses = (await db.execute(
                select(User.email, User.full_name).where(User.id.in_(destinataires_ids))
            )).all() if destinataires_ids else []
            if settings.SUPERADMIN_EMAIL and not any(
                e == settings.SUPERADMIN_EMAIL for e, _ in adresses
            ):
                adresses = list(adresses) + [(settings.SUPERADMIN_EMAIL, "Administrateur")]

            for email, nom in adresses:
                if not email:
                    continue
                try:
                    await send_technical_test_completed(
                        to_email=email, recipient_name=nom or "",
                        candidate_name=nom_candidat, job_title=poste,
                        application_id=app_id, score=session.score,
                        correct_count=session.correct_count,
                        question_count=session.question_count,
                        outcome=issue,
                    )
                except Exception as exc:      # pragma: no cover - défensif
                    logger.warning(
                        "Alerte de fin de test non envoyée pour la session %s : %s",
                        session.id, exc,
                    )
            envoyees += 1
        except Exception:                     # pragma: no cover - défensif
            # Une session ne doit jamais empêcher les autres d'être annoncées :
            # ce balayage tourne en fond, et une exception qui remonterait
            # priverait TOUTES les sessions suivantes de leur alerte.
            #
            # Mais en ERROR avec la trace, pas en WARNING sans : ce filet a
            # déjà masqué un import manquant, qui s'est traduit par des alertes
            # silencieusement perdues. Un `except` large doit crier.
            logger.error("Alerte de fin de test impossible pour la session %s",
                         session.id, exc_info=True)

    await db.commit()
    if envoyees:
        logger.info("Alertes de fin de test : %d session(s) annoncée(s).", envoyees)
    return envoyees
