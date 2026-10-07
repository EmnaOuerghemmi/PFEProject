"""
Décision appliquée depuis l'aide à la décision, et vivier « en réserve ».

`appliquer_decision` fait passer une candidature au statut recommandé :

    HIRE   → ACCEPTED   (le candidat est notifié dans son espace)
    REJECT → REJECTED   (e-mail de refus, comme le rejet du back-office)
    HOLD   → ON_HOLD    (e-mail « candidature conservée », entrée au vivier)

`inviter_sur_offres_compatibles` est appelée en tâche de fond : pour chaque
candidat en réserve, elle cherche les offres ouvertes qui correspondent à son
profil — avec le moteur de recommandation déjà utilisé côté candidat (seuil,
contraintes bloquantes, pondération de l'offre) — et l'y invite par e-mail.

Garde-fous contre le harcèlement :

- une offre n'est jamais proposée deux fois au même candidat ;
- un seul e-mail par candidat et par délai `TALENT_POOL_COOLDOWN_HOURS`,
  qui regroupe les offres nouvelles (au plus `TALENT_POOL_MAX_OFFERS`) ;
- rien n'est envoyé sous le seuil de compatibilité : mieux vaut aucun e-mail
  qu'une offre que le candidat jugerait absurde.

Aucune donnée nominative dans les journaux : des comptes seulement.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import application_status
from app.models.application_status import ApplicationStatus
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.talent_pool import TalentPoolEntry, TalentPoolInvitation
from app.models.user import User

logger = logging.getLogger(__name__)

#: Recommandation de l'aide à la décision → statut de candidature.
STATUT_PAR_DECISION: dict[str, str] = {
    "HIRE": ApplicationStatus.ACCEPTED.value,
    "REJECT": ApplicationStatus.REJECTED.value,
    "HOLD": ApplicationStatus.ON_HOLD.value,
}


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DecisionAppliquee:
    application: Application
    candidate: Candidate
    user: User
    job: JobOffer
    decision: str
    statut: str


async def appliquer_decision(
    db: AsyncSession, application_id: UUID, decision: str, actor: User,
) -> DecisionAppliquee:
    """
    Fait passer la candidature au statut de la décision. N'envoie rien : les
    e-mails sont mis en file par l'appelant, une fois la transaction validée.
    """
    cible = STATUT_PAR_DECISION.get(decision)
    if cible is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Seules les décisions Recruter, Rejeter et En réserve s'appliquent.",
        )

    ligne = (await db.execute(
        select(Application, Candidate, User, JobOffer)
        .join(Candidate, Application.candidate_id == Candidate.id)
        .join(User, Candidate.user_id == User.id)
        .join(JobOffer, Application.job_offer_id == JobOffer.id)
        .where(Application.id == application_id)
    )).first()
    if not ligne:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidature introuvable.")
    application, candidate, user, job = ligne

    if application.status == cible:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La candidature est déjà « {application_status.label(cible)} ».",
        )
    if not application_status.can_transition(application.status, cible):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Passage impossible de « {application_status.label(application.status)} » "
                    f"à « {application_status.label(cible)} »."),
        )

    application.status = cible
    if cible == ApplicationStatus.ON_HOLD.value:
        entree = (await db.execute(
            select(TalentPoolEntry).where(TalentPoolEntry.application_id == application.id)
        )).scalar_one_or_none()
        if entree is None:
            db.add(TalentPoolEntry(candidate_id=candidate.id, application_id=application.id,
                                   reserved_by=actor.id))
        else:
            entree.reserved_at, entree.reserved_by = _maintenant(), actor.id
    await db.flush()
    return DecisionAppliquee(application, candidate, user, job, decision, cible)


# ── Vivier : invitations sur les offres compatibles ─────────────────────────

def lien_offre(job_id: UUID) -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/frontoffice/job/{job_id}"


async def _candidats_en_reserve(db: AsyncSession) -> list[tuple[Candidate, User]]:
    """Candidats dont au moins une candidature est encore en réserve, compte actif."""
    lignes = (await db.execute(
        select(Candidate, User)
        .join(User, Candidate.user_id == User.id)
        .where(
            User.is_active.is_(True),
            Candidate.id.in_(
                select(TalentPoolEntry.candidate_id)
                .join(Application, TalentPoolEntry.application_id == Application.id)
                .where(Application.status == ApplicationStatus.ON_HOLD.value)
            ),
        )
    )).all()
    return [(c, u) for c, u in lignes]


async def inviter_sur_offres_compatibles(db: AsyncSession) -> int:
    """Invite chaque candidat en réserve aux offres qui lui correspondent. Renvoie le nombre d'e-mails."""
    from app.services.email_service import send_talent_pool_offers
    from app.services.recommendation_service import recommendation_service

    candidats = await _candidats_en_reserve(db)
    if not candidats:
        return 0

    delai = _maintenant() - timedelta(hours=settings.TALENT_POOL_COOLDOWN_HOURS)
    envoyes = 0
    for candidate, user in candidats:
        try:
            dernier = (await db.execute(
                select(func.max(TalentPoolInvitation.sent_at))
                .where(TalentPoolInvitation.candidate_id == candidate.id)
            )).scalar()
            if dernier is not None and dernier.replace(tzinfo=dernier.tzinfo or timezone.utc) > delai:
                continue  # déjà sollicité récemment : on attend le prochain créneau

            deja = set((await db.execute(
                select(TalentPoolInvitation.job_offer_id)
                .where(TalentPoolInvitation.candidate_id == candidate.id)
            )).scalars().all())
            recos = await recommendation_service.recommend_for_candidate(
                db, candidate.id, limit=settings.TALENT_POOL_MAX_OFFERS + len(deja),
            )
            nouvelles = [r for r in recos if r["job_id"] not in deja][: settings.TALENT_POOL_MAX_OFFERS]
            if not nouvelles:
                continue

            for r in nouvelles:
                db.add(TalentPoolInvitation(candidate_id=candidate.id, job_offer_id=r["job_id"],
                                            compatibility=r["compatibility_score"]))
            await db.commit()

            await send_talent_pool_offers(
                to_email=user.email,
                candidate_name=candidate.full_name,
                offres=[{"title": r["title"], "url": lien_offre(r["job_id"]),
                         "reasons": r.get("reasons") or []} for r in nouvelles],
            )
            envoyes += 1
        except Exception as exc:  # pragma: no cover - au mieux, candidat par candidat
            await db.rollback()
            logger.warning("Vivier : invitation impossible pour un candidat (%s)", type(exc).__name__)

    if envoyes:
        logger.info("Vivier : %d candidat(s) en réserve invité(s) sur de nouvelles offres.", envoyes)
    return envoyes
