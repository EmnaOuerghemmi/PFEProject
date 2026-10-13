import os
import logging
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import String, cast, select, func, and_, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.recruitment import JobOffer, Candidate, Application, SavedJob
from app.models.scoring import CandidateScore, CVAnalysis
from app.models.interview import InterviewInvitation, InterviewSlot
from app.schemas.recruitment import JobOfferCreate, JobOfferUpdate, ApplicationUpdate
from app.models import application_status
from app.models.contract import Contract, ContractStatus
from app.models.user import AuditLog

logger = logging.getLogger(__name__)


class RecruitmentService:

    async def create_job_offer(self, db: AsyncSession, data: JobOfferCreate, created_by: UUID) -> JobOffer:
        job = JobOffer(
            title=data.title,
            description=data.description,
            salary_min=data.salary_min,
            salary_max=data.salary_max,
            required_skills=data.required_skills,
            required_experience_years=data.required_experience_years,
            required_education_level=data.required_education_level,
            weight_skills=data.weight_skills,
            weight_experience=data.weight_experience,
            weight_education=data.weight_education,
            work_mode=data.work_mode,
            contract_types=data.contract_types,
            status=data.status,
            expires_at=data.expires_at,
            created_by=created_by
        )
        db.add(job)
        await db.flush()
        return job

    async def get_job_offers(
        self,
        db: AsyncSession,
        page: int = 1,
        size: int = 10,
        is_active: bool = True,
        search: str = None,
        sort_by: str = None,
        published_only: bool = False,
        status: str = None,
        work_mode: str = None,
        contract_type: str = None,
    ) -> tuple[int, list[JobOffer]]:
        """
        `published_only=True` applique la visibilité candidat : seules les
        offres PUBLISHED et non expirées remontent. Le backoffice l'omet pour
        voir aussi les brouillons et les offres fermées.
        """
        filters = [JobOffer.is_active == is_active]
        if search:
            filters.append(JobOffer.title.ilike(f"%{search}%") | JobOffer.description.ilike(f"%{search}%"))
        if published_only:
            filters.append(JobOffer.status == "PUBLISHED")
            # NULL = pas de date d'expiration → l'offre reste visible.
            filters.append(
                (JobOffer.expires_at.is_(None)) | (JobOffer.expires_at >= func.now())
            )
        elif status:
            filters.append(JobOffer.status == status)
        if work_mode:
            filters.append(JobOffer.work_mode == work_mode)
        if contract_type:
            # `contract_types` est un tableau : filtrer, c'est tester une
            # APPARTENANCE, pas une égalité. On compare le JSON sérialisé à
            # `%"CDD"%` — les guillemets rendent la correspondance exacte et
            # empêchent qu'une valeur soit le préfixe d'une autre.
            #
            # Un opérateur natif (JSONB `@>` côté PostgreSQL) serait indexable,
            # mais n'existe pas en SQLite, sur lequel tourne la suite de tests.
            # À l'échelle d'un catalogue d'offres, le balayage est sans effet
            # mesurable ; c'est la portabilité qui prime ici.
            filters.append(
                cast(JobOffer.contract_types, String).like(f'%"{contract_type}"%')
            )

        order = JobOffer.created_at.desc()
        if sort_by == 'oldest':
            order = JobOffer.created_at.asc()
        elif sort_by == 'title':
            order = JobOffer.title.asc()

        query = select(JobOffer).where(*filters).order_by(order)
        total = await db.scalar(select(func.count(JobOffer.id)).where(*filters))
        result = await db.execute(query.limit(size).offset((page - 1) * size))
        return total, result.scalars().all()

    async def get_job_offer(
        self, db: AsyncSession, job_id: UUID, published_only: bool = False
    ) -> JobOffer:
        """
        Charge une offre par identifiant.

        `published_only=True` applique la MÊME visibilité que le listing
        candidat : offre active, publiée et non expirée. Sans ce garde-fou, le
        filtrage soigneux de `get_job_offers` ne servait à rien — il suffisait
        de connaître l'identifiant pour lire un brouillon ou une offre fermée,
        conditions salariales comprises.

        Une offre masquée renvoie 404 et non 403 : un 403 confirmerait qu'elle
        existe.
        """
        filters = [JobOffer.id == job_id]
        if published_only:
            filters += [
                JobOffer.is_active.is_(True),
                JobOffer.status == "PUBLISHED",
                # NULL = pas de date d'expiration → l'offre reste visible.
                (JobOffer.expires_at.is_(None)) | (JobOffer.expires_at >= func.now()),
            ]

        result = await db.execute(select(JobOffer).where(*filters))
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job offer not found")
        return job

    async def get_similar_jobs(
        self, db: AsyncSession, job_id: UUID, limit: int = 4
    ) -> list[JobOffer]:
        """
        Offres « similaires » à `job_id`, pour la section de bas de page.

        Classement par pertinence décroissante :
          1. Nombre de compétences requises en commun (le critère le plus
             fort — un candidat qui matche 4 compétences sur une autre offre
             est un bien meilleur signal qu'une simple proximité d'expérience).
          2. Expérience requise proche (± 2 ans).
          3. Même mode de travail (présentiel / hybride / remote).

        Le score se calcule en Python plutôt qu'en SQL : le catalogue d'offres
        reste petit, `required_skills` est un JSON non indexable côté SQLite
        (utilisé en tests) et la comparaison d'ensembles est plus lisible ici
        qu'en expressions SQL.

        Le tri de base (le plus récent d'abord) sert de repli : une offre qui
        ne partage aucun signal reste éligible si le catalogue est trop petit
        pour remplir `limit` autrement — mieux vaut proposer autre chose à
        lire que de laisser la section vide.

        Silencieuse plutôt que 404 : appelée depuis la page d'une offre déjà
        chargée par ailleurs, y compris un brouillon prévisualisé par un RH —
        recommander d'autres offres n'a alors simplement rien à afficher.
        """
        result = await db.execute(select(JobOffer).where(JobOffer.id == job_id))
        current = result.scalar_one_or_none()
        if not current:
            return []

        filters = [
            JobOffer.id != job_id,
            JobOffer.is_active.is_(True),
            JobOffer.status == "PUBLISHED",
            (JobOffer.expires_at.is_(None)) | (JobOffer.expires_at >= func.now()),
        ]
        result = await db.execute(
            select(JobOffer).where(*filters).order_by(JobOffer.created_at.desc())
        )
        candidates = result.scalars().all()

        current_skills = {s.strip().lower() for s in (current.required_skills or []) if s}

        def score(job: JobOffer) -> int:
            job_skills = {s.strip().lower() for s in (job.required_skills or []) if s}
            points = len(current_skills & job_skills) * 3

            if (
                current.required_experience_years is not None
                and job.required_experience_years is not None
                and abs(job.required_experience_years - current.required_experience_years) <= 2
            ):
                points += 2

            if current.work_mode and job.work_mode and job.work_mode == current.work_mode:
                points += 1

            return points

        # `sorted` est stable : à score égal, l'ordre de `candidates` (déjà
        # trié par date décroissante) sert de départage.
        ranked = sorted(candidates, key=score, reverse=True)
        return ranked[:limit]

    async def update_job_offer(self, db: AsyncSession, job_id: UUID, data: JobOfferUpdate) -> JobOffer:
        job = await self.get_job_offer(db, job_id)
        if data.title is not None:
            job.title = data.title
        if data.description is not None:
            job.description = data.description
        if data.salary_min is not None:
            job.salary_min = data.salary_min
        if data.salary_max is not None:
            job.salary_max = data.salary_max
        if data.required_skills is not None:
            job.required_skills = data.required_skills
        if data.required_experience_years is not None:
            job.required_experience_years = data.required_experience_years
        if data.required_education_level is not None:
            job.required_education_level = data.required_education_level
        if data.weight_skills is not None:
            job.weight_skills = data.weight_skills
        if data.weight_experience is not None:
            job.weight_experience = data.weight_experience
        if data.weight_education is not None:
            job.weight_education = data.weight_education
        if data.is_active is not None:
            job.is_active = data.is_active
        if data.work_mode is not None:
            job.work_mode = data.work_mode
        if data.contract_types is not None:
            job.contract_types = data.contract_types
        if data.status is not None:
            job.status = data.status
        # `expires_at` doit pouvoir être EFFACÉE (retirer la date limite), pas
        # seulement modifiée : on distingue « champ absent » de « null explicite »
        # via les champs réellement envoyés par le client.
        if "expires_at" in data.model_fields_set:
            job.expires_at = data.expires_at
        await db.flush()
        return job

    async def delete_job_offer(self, db: AsyncSession, job_id: UUID) -> None:
        job = await self.get_job_offer(db, job_id)
        job.is_active = False
        await db.flush()

    async def get_or_create_candidate(self, db: AsyncSession, user_id: UUID, full_name: str, phone: str = None) -> Candidate:
        result = await db.execute(select(Candidate).where(Candidate.user_id == user_id))
        candidate = result.scalar_one_or_none()
        if not candidate:
            candidate = Candidate(user_id=user_id, full_name=full_name, phone=phone)
            db.add(candidate)
            await db.flush()
        return candidate

    async def apply_to_job(self, db: AsyncSession, candidate_id: UUID, job_offer_id: UUID, cv_file_path: str) -> Application:
        # Une offre non publiée (brouillon/fermée) ou expirée n'accepte plus de
        # candidature : sans ce contrôle, un lien direct suffirait à contourner
        # le filtrage du listing public.
        job = await self.get_job_offer(db, job_offer_id)  # 404 si inexistante
        if not job.is_active or job.status != "PUBLISHED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cette offre n'accepte plus de candidatures.",
            )
        if job.expires_at is not None and job.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La date limite de candidature pour cette offre est dépassée.",
            )

        result = await db.execute(select(Application).where(
            and_(Application.candidate_id == candidate_id, Application.job_offer_id == job_offer_id)
        ))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already applied")

        app = Application(candidate_id=candidate_id, job_offer_id=job_offer_id, cv_file_path=cv_file_path,
                          status=application_status.ApplicationStatus.PENDING.value)
        db.add(app)
        await db.flush()
        return app

    async def get_applications(self, db: AsyncSession, job_id: UUID = None, page: int = 1, size: int = 20) -> tuple[int, list[Application]]:
        query = (
            select(Application)
            .options(selectinload(Application.candidate), selectinload(Application.job_offer))
            .order_by(Application.created_at.desc())
        )
        if job_id:
            query = query.where(Application.job_offer_id == job_id)

        count_query = select(func.count(Application.id))
        if job_id:
            count_query = count_query.where(Application.job_offer_id == job_id)
        total = await db.scalar(count_query)

        result = await db.execute(query.limit(size).offset((page - 1) * size))
        apps = result.scalars().all()
        # Champs transitoires (non mappés) consommés par ApplicationResponse.candidate_name /
        # job_offer_title via from_attributes, pour afficher le nom du candidat et le titre du
        # poste au lieu de leurs UUID.
        for app in apps:
            app.candidate_name = app.candidate.full_name if app.candidate else None
            app.job_offer_title = app.job_offer.title if app.job_offer else None
        return total, apps

    async def get_own_application(
        self, db: AsyncSession, application_id: UUID, user_id: UUID
    ) -> Application:
        """
        Candidature appartenant à CET utilisateur, ou 404.

        La jointure sur `Candidate.user_id` fait le contrôle d'accès : une
        candidature d'autrui est introuvable plutôt qu'interdite. Répondre 403
        confirmerait son existence et permettrait d'énumérer les dossiers en
        testant des identifiants.
        """
        result = await db.execute(
            select(Application)
            .join(Candidate, Application.candidate_id == Candidate.id)
            .where(Application.id == application_id, Candidate.user_id == user_id)
        )
        application = result.scalar_one_or_none()
        if not application:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidature introuvable.",
            )
        return application

    async def get_my_applications(self, db: AsyncSession, user_id: UUID) -> list[dict]:
        """
        Return the current user's applications enriched with job offer details
        and optional score data. Returns dicts that map directly to MyApplicationResponse.
        """
        candidate_result = await db.execute(select(Candidate).where(Candidate.user_id == user_id))
        candidate = candidate_result.scalar_one_or_none()
        if not candidate:
            return []

        query = (
            select(Application, JobOffer, CandidateScore)
            .join(JobOffer, Application.job_offer_id == JobOffer.id)
            .outerjoin(CandidateScore, CandidateScore.application_id == Application.id)
            .where(Application.candidate_id == candidate.id)
            .order_by(Application.created_at.desc())
        )
        result = await db.execute(query)

        items: list[dict] = []
        for app, job, score in result.all():
            items.append({
                "id": app.id,
                "job_offer_id": app.job_offer_id,
                "candidate_id": app.candidate_id,
                "cv_file_path": app.cv_file_path,
                "status": app.status,
                "expected_salary": app.expected_salary,
                "created_at": app.created_at,
                "updated_at": app.updated_at,
                "job_title": job.title,
                "job_description": job.description,
                "job_salary_min": job.salary_min,
                "job_salary_max": job.salary_max,
                "job_required_skills": job.required_skills,
                "job_required_experience_years": job.required_experience_years,
                "job_required_education_level": job.required_education_level,
                "job_is_active": job.is_active,
                "job_work_mode": job.work_mode,
                "job_contract_types": job.contract_types,
                "total_score": score.total_score if score else None,
                "skills_score": score.skills_score if score else None,
                "experience_score": score.experience_score if score else None,
                "education_score": score.education_score if score else None,
            })
        return items

    async def update_application_status(self, db: AsyncSession, app_id: UUID, data: ApplicationUpdate) -> Application:
        result = await db.execute(select(Application).where(Application.id == app_id))
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
        if not application_status.can_transition(app.status, data.status):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Passage impossible de « {application_status.label(app.status)} » "
                    f"à « {application_status.label(data.status)} »."
                ),
            )
        app.status = data.status
        await db.flush()
        return app

    async def forcer_statut(
        self, db: AsyncSession, app_id: UUID, statut: str, *, motif: str, admin_id: UUID,
    ) -> Application:
        """
        Change le statut d'une candidature HORS des règles de parcours — action
        d'administrateur, pour corriger une erreur (un rejet par mégarde, un
        recrutement annulé…). Tout passe au journal d'audit, motif compris.

        Deux garde-fous demeurent. « Recrutée » découle de la signature d'un
        contrat : il ne se force pas. Et tant qu'un contrat est envoyé ou signé,
        le statut ne bouge pas — il faut d'abord retirer ce contrat, sans quoi le
        candidat pourrait signer, ou rester employé, d'une candidature rejetée.
        """
        app = (await db.execute(select(Application).where(Application.id == app_id))).scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
        if statut == application_status.ApplicationStatus.HIRED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="« Recrutée » découle de la signature d'un contrat : ce statut ne se force pas.",
            )
        contrat_en_cours = await db.scalar(
            select(Contract.id).where(
                Contract.application_id == app_id,
                Contract.status.in_([ContractStatus.SENT, ContractStatus.SIGNED, ContractStatus.ACTIVE]),
            ).limit(1)
        )
        if contrat_en_cours and statut != app.status:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cette candidature a un contrat envoyé ou signé : retirez-le d'abord (page Contrats).",
            )

        avant = app.status
        app.status = statut
        db.add(AuditLog(
            user_id=admin_id, action="APPLICATION_STATUS_FORCED", resource="application",
            resource_id=str(app.id), details={"avant": avant, "apres": statut, "motif": motif},
        ))
        await db.flush()
        return app

    async def withdraw_application(self, db: AsyncSession, app_id: UUID, user_id: UUID) -> Application:
        """
        Retire SA PROPRE candidature — action du candidat, pas du RH.

        La propriété est vérifiée par une jointure sur `Candidate.user_id`,
        comme `candidate_feedback_service.build` : un candidat ne doit pouvoir
        retirer que ses propres dossiers, jamais celui d'un autre en changeant
        l'identifiant dans l'URL. Une candidature introuvable OU qui n'est pas
        la sienne renvoie le même 404, pour ne rien laisser deviner.

        `can_transition` referme la porte une fois le dossier déjà dans un état
        terminal (recrutée, rejetée, ou déjà retirée) : rien à retirer là.
        """
        result = await db.execute(
            select(Application)
            .join(Candidate, Application.candidate_id == Candidate.id)
            .where(Application.id == app_id, Candidate.user_id == user_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
        if not application_status.can_transition(app.status, application_status.ApplicationStatus.WITHDRAWN.value):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cette candidature ne peut plus être retirée (« {application_status.label(app.status)} »).",
            )
        app.status = application_status.ApplicationStatus.WITHDRAWN.value
        await db.flush()
        return app

    async def delete_application(self, db: AsyncSession, app_id: UUID) -> None:
        """
        Delete an application and clean up everything attached to it:
        the CV file on disk, the score, the CV analysis and any interview
        invitation (+ slots). Used by the admin "Supprimer candidature" action
        (CAND-08).
        """
        result = await db.execute(select(Application).where(Application.id == app_id))
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

        cv_path = app.cv_file_path

        # Free interview slots first (FK → invitations), then invitations.
        inv_ids = (
            await db.execute(
                select(InterviewInvitation.id).where(InterviewInvitation.application_id == app_id)
            )
        ).scalars().all()
        if inv_ids:
            await db.execute(delete(InterviewSlot).where(InterviewSlot.invitation_id.in_(inv_ids)))
            await db.execute(delete(InterviewInvitation).where(InterviewInvitation.id.in_(inv_ids)))

        # Remove derived scoring data (FK → applications, no DB cascade).
        await db.execute(delete(CandidateScore).where(CandidateScore.application_id == app_id))
        await db.execute(delete(CVAnalysis).where(CVAnalysis.application_id == app_id))

        await db.execute(delete(Application).where(Application.id == app_id))
        await db.flush()

        # Best-effort filesystem cleanup — never fail the request because of it.
        if cv_path:
            try:
                if os.path.exists(cv_path):
                    os.remove(cv_path)
            except OSError as exc:
                logger.warning(f"Could not delete CV file {cv_path}: {exc}")

    # ── Saved jobs (frontoffice bookmarks) ──────────────────────────────────

    async def get_saved_jobs(self, db: AsyncSession, user_id: UUID) -> list[JobOffer]:
        result = await db.execute(
            select(JobOffer)
            .join(SavedJob, SavedJob.job_offer_id == JobOffer.id)
            .where(SavedJob.user_id == user_id)
            .order_by(SavedJob.created_at.desc())
        )
        return list(result.scalars().all())

    async def save_job(self, db: AsyncSession, user_id: UUID, job_id: UUID) -> JobOffer:
        job = await self.get_job_offer(db, job_id)  # 404 if missing
        existing = await db.execute(
            select(SavedJob).where(
                and_(SavedJob.user_id == user_id, SavedJob.job_offer_id == job_id)
            )
        )
        if existing.scalar_one_or_none() is None:
            db.add(SavedJob(user_id=user_id, job_offer_id=job_id))
            await db.flush()
        return job

    async def unsave_job(self, db: AsyncSession, user_id: UUID, job_id: UUID) -> None:
        await db.execute(
            delete(SavedJob).where(
                and_(SavedJob.user_id == user_id, SavedJob.job_offer_id == job_id)
            )
        )
        await db.flush()


recruitment_service = RecruitmentService()
