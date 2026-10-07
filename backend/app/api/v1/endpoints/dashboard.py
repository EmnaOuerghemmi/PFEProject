from typing import Annotated
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.recruitment import JobOffer, Application, Candidate
from app.schemas.recruitment import ApplicationResponse, JobOfferResponse
from app.models.application_status import ApplicationStatus
from app.schemas.analytics import ChartSeries, SeriesCatalog
from app.schemas.dashboard_config import DashboardConfig, DashboardConfigView
from app.schemas.report import RecruitmentSummary
from app.services.analytics_service import analytics_service
from app.services.chart_series_service import chart_series_service
from app.services.dashboard_config_service import dashboard_config_service

# Le tableau de bord expose des agrégats de TOUTE la base (volumes de
# candidatures, score moyen, postes ouverts). Il était protégé par la
# seule authentification : un candidat connecté les lisait.
router = APIRouter(dependencies=[Depends(require("dashboard", "read"))])


class DashboardStats:
    """Schema for dashboard statistics"""
    total_jobs: int
    total_applications: int
    total_hires: int
    active_users: int | None = None
    new_users: int | None = None


@router.get("/stats")
async def get_dashboard_stats(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get dashboard statistics. If user is superadmin, include user stats."""
    
    # Count total job offers (active)
    total_jobs_result = await db.execute(
        select(func.count(JobOffer.id)).where(JobOffer.is_active == True)
    )
    total_jobs = total_jobs_result.scalar() or 0
    
    # Count total applications
    total_applications_result = await db.execute(
        select(func.count(Application.id))
    )
    total_applications = total_applications_result.scalar() or 0
    
    # Count hired candidates (Applications with status = "HIRED" or "ACCEPTED")
    total_hires_result = await db.execute(
        select(func.count(Application.id)).where(
            Application.status.in_([ApplicationStatus.HIRED.value,
                                    ApplicationStatus.ACCEPTED.value])
        )
    )
    total_hires = total_hires_result.scalar() or 0
    
    response = {
        "total_jobs": total_jobs,
        "total_applications": total_applications,
        "total_hires": total_hires,
        "active_users": None,
        "new_users": None
    }
    
    # If user is superadmin, add user stats
    if current_user.is_superuser:
        # Count active users
        active_users_result = await db.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )
        response["active_users"] = active_users_result.scalar() or 0
        
        # Count new users (created today or this week)
        from datetime import timedelta
        today = datetime.utcnow().date()
        week_ago = today - timedelta(days=7)
        
        new_users_result = await db.execute(
            select(func.count(User.id)).where(
                func.date(User.created_at) >= week_ago
            )
        )
        response["new_users"] = new_users_result.scalar() or 0
    
    return response


@router.get("/recent-applications")
async def get_recent_applications(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 4
):
    """Get recent applications (last 4 by default). Only for admin/RH."""
    
    # Check permissions - allow superuser or admin/RH roles
    if not (current_user.is_superuser or current_user.role in [UserRole.ADMIN, UserRole.RH]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin and RH managers can view all applications"
        )
    
    # Get recent applications with candidate and job info
    query = select(Application).order_by(Application.created_at.desc()).limit(limit)
    result = await db.execute(query)
    applications = result.scalars().all()
    
    response_list = []
    for app in applications:
        # Fetch candidate name
        candidate = await db.get(Candidate, app.candidate_id)
        job = await db.get(JobOffer, app.job_offer_id)
        
        response_list.append({
            "id": str(app.id),
            "candidate_name": candidate.full_name if candidate else "Unknown",
            "job_title": job.title if job else "Unknown Position",
            "status": app.status,
            "date": app.created_at.isoformat()
        })
    
    return response_list


@router.get("/open-positions")
async def get_open_positions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 3
):
    """Get open positions (last 3 by default) with application counts."""
    
    # Check permissions - allow superuser or admin/RH roles
    if not (current_user.is_superuser or current_user.role in [UserRole.ADMIN, UserRole.RH]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin and RH managers can view positions"
        )
    
    # Get recent active job offers
    query = select(JobOffer).where(
        JobOffer.is_active == True
    ).order_by(JobOffer.created_at.desc()).limit(limit)
    
    result = await db.execute(query)
    jobs = result.scalars().all()
    
    response_list = []
    for job in jobs:
        # Count applications for this job
        app_count_result = await db.execute(
            select(func.count(Application.id)).where(
                Application.job_offer_id == job.id
            )
        )
        app_count = app_count_result.scalar() or 0
        
        response_list.append({
            "id": str(job.id),
            "title": job.title,
            "department": "Engineering",  # You can add department field to JobOffer model
            "applications": app_count,
            "created_at": job.created_at.isoformat()
        })
    
    return response_list


# ════════════════════════════════════════════════════════════════════
#  Composition commune et données des graphiques
#
#  L'administrateur compose le tableau de bord et décide, graphique par
#  graphique, qui le voit. Tout ce qui suit est filtré côté serveur selon le
#  rôle : un RH ou un recruteur ne reçoit ni la configuration ni les données
#  d'un graphique qui ne lui est pas destiné.
# ════════════════════════════════════════════════════════════════════

_REFUS = "Ce graphique n'est pas partagé avec votre rôle."


@router.get("/config", response_model=DashboardConfigView)
async def get_shared_config(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """La composition commune, réduite à ce que ce rôle peut voir."""
    config = await dashboard_config_service.load(db)
    return dashboard_config_service.view_for(config, current_user)


@router.put("/config", response_model=DashboardConfigView,
            dependencies=[Depends(require("dashboard", "write"))])
async def set_shared_config(
    body: DashboardConfig,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Enregistre la composition et la visibilité de chaque graphique.
    Réservé à l'administrateur : `dashboard:write` n'est accordé qu'à lui.
    """
    config = await dashboard_config_service.save(db, body, current_user)
    return dashboard_config_service.view_for(config, current_user)


@router.get("/series", response_model=SeriesCatalog,
            dependencies=[Depends(require("dashboard", "write"))])
async def dashboard_series_catalog():
    """Catalogue des sources — ne sert qu'à créer un graphique, donc à l'admin."""
    return chart_series_service.catalog()


@router.get("/series/{source_id}", response_model=ChartSeries)
async def dashboard_series_data(
    source_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Données d'une source, si un graphique visible pour ce rôle l'utilise."""
    config = await dashboard_config_service.load(db)
    if not dashboard_config_service.can_read_source(config, current_user, source_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, _REFUS)
    serie = await chart_series_service.series(db, source_id)
    if serie is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Source de graphique inconnue : {source_id}.")
    return serie


async def _autoriser_jeu(db: AsyncSession, user: User, jeu: str) -> None:
    config = await dashboard_config_service.load(db)
    if not dashboard_config_service.can_read_dataset(config, user, jeu):
        raise HTTPException(status.HTTP_403_FORBIDDEN, _REFUS)


@router.get("/recruitment-summary", response_model=RecruitmentSummary)
async def dashboard_recruitment_summary(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Agrégats des cartes Statuts, Offres, Pipeline et Performance."""
    await _autoriser_jeu(db, current_user, "recruitment_summary")
    return await analytics_service.recruitment_summary(db)


@router.get("/candidate-analytics")
async def dashboard_candidate_analytics(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Agrégats de la carte Niveau d'éducation."""
    await _autoriser_jeu(db, current_user, "candidate_analytics")
    return await analytics_service.candidate_analytics(db)


@router.get("/applications-timeline")
async def dashboard_applications_timeline(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 14,
):
    """Série de la carte Évolution des candidatures."""
    await _autoriser_jeu(db, current_user, "applications_timeline")
    return await analytics_service.applications_timeline(db, days=days)
