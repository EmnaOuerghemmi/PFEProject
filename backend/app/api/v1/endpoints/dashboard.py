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
