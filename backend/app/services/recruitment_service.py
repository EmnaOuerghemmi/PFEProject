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
