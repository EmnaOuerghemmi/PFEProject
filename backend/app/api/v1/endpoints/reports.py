from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.models.report import ReportSnapshot
from app.schemas.report import RecruitmentSummary, ReportSnapshotResponse
from app.schemas.analytics import ChartSeries, SeriesCatalog
from app.services.analytics_service import analytics_service
from app.services.chart_series_service import chart_series_service
from app.agents.report_generator_agent import report_generator_agent
from app.services.notification_service import notification_service

router = APIRouter(
    dependencies=[Depends(require("reports", "read"))]
)


# ── Schémas locaux ────────────────────────────────────────────────────────────

class SnapshotCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SnapshotUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class PaginatedReports(BaseModel):
    items: list[ReportSnapshotResponse]
    total: int
    page: int
    pages: int
    page_size: int


# ── Analytics live ────────────────────────────────────────────────────────────

@router.get("/series", response_model=SeriesCatalog)
async def series_catalog():
    """
    Catalogue des sources de graphiques.

    Ce que l'écran « Nouveau graphique » propose, et surtout QUELS TYPES chaque
    source admet. La règle vit côté serveur : le navigateur ne doit pas avoir à
    deviner qu'un camembert de série temporelle détruirait l'axe du temps.
    """
    return chart_series_service.catalog()


@router.get("/series/{source_id}", response_model=ChartSeries)
async def series_data(source_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Les données d'une source, dans le format commun à tous les graphiques."""
    serie = await chart_series_service.series(db, source_id)
    if serie is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Source de graphique inconnue : {source_id}.")
    return serie


@router.get("/recruitment-summary", response_model=RecruitmentSummary)
async def recruitment_summary(db: Annotated[AsyncSession, Depends(get_db)]):
    """Live recruitment KPIs aggregated across jobs, applications and scores."""
    return await analytics_service.recruitment_summary(db)


@router.get("/candidate-analytics")
async def candidate_analytics(db: Annotated[AsyncSession, Depends(get_db)]):
    """Candidate distributions: by experience, AI score band, education, top skills."""
    return await analytics_service.candidate_analytics(db)


@router.get("/applications-timeline")
async def applications_timeline(db: Annotated[AsyncSession, Depends(get_db)], days: int = 14):
    """Daily application counts over the last N days (for the evolution chart)."""
    return await analytics_service.applications_timeline(db, days=days)


# ── Génération (agent de reporting) ──────────────────────────────────────────

@router.post("/snapshot", response_model=ReportSnapshotResponse, status_code=status.HTTP_201_CREATED)
async def create_snapshot(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    body: SnapshotCreateRequest | None = None,
):
    """
    Génère et archive un rapport : KPIs du moment + contenu rédigé par
    l'**agent de reporting** (narrative, points clés, recommandations).
    """
    summary = await analytics_service.recruitment_summary(db)

    # Contenu rédigé par l'agent (LLM si dispo, sinon fallback déterministe).
    report_content = await report_generator_agent.run(summary)

    # JSON-sérialiser les champs non natifs.
    data = {
        **summary,
        "generated_at": summary["generated_at"].isoformat(),
        "top_jobs": [{**t, "job_offer_id": str(t["job_offer_id"])} for t in summary["top_jobs"]],
        "report": report_content,
    }
    snap = ReportSnapshot(
        report_type="recruitment_summary",
        title=(body.title if body and body.title else "Synthèse recrutement"),
        data=data,
        created_by=current_user.id,
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)

    await notification_service.notify_admins(
        db, actor=current_user, type="REPORT_GENERATED",
        title="Rapport généré",
        message=f"{current_user.full_name or current_user.username} a généré le rapport « {snap.title} ».",
        link="/admin/reports",
    )
    await db.commit()
    return snap


# ── CRUD des rapports archivés ───────────────────────────────────────────────

@router.get("", response_model=PaginatedReports)
async def list_snapshots(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    """Liste paginée des rapports archivés (du plus récent au plus ancien)."""
    total = (await db.execute(select(func.count(ReportSnapshot.id)))).scalar_one()
    rows = (await db.execute(
        select(ReportSnapshot)
        .order_by(ReportSnapshot.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()
    pages = max(1, -(-total // page_size))  # ceil
    return {
        "items": list(rows),
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
    }


async def _get_snapshot(db: AsyncSession, snapshot_id: UUID) -> ReportSnapshot:
    snap = (await db.execute(
        select(ReportSnapshot).where(ReportSnapshot.id == snapshot_id)
    )).scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return snap


@router.get("/{snapshot_id}", response_model=ReportSnapshotResponse)
async def get_snapshot(snapshot_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    return await _get_snapshot(db, snapshot_id)


@router.patch("/{snapshot_id}", response_model=ReportSnapshotResponse)
async def rename_snapshot(
    snapshot_id: UUID,
    body: SnapshotUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Renomme un rapport archivé."""
    snap = await _get_snapshot(db, snapshot_id)
    snap.title = body.title
    await db.commit()
    await db.refresh(snap)
    return snap


@router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snapshot(snapshot_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """Supprime un rapport archivé."""
    snap = await _get_snapshot(db, snapshot_id)
    await db.delete(snap)
    await db.commit()


@router.get("/{snapshot_id}/pdf")
async def download_snapshot_pdf(snapshot_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """Télécharge le rapport au format **PDF** (généré côté serveur)."""
    snap = await _get_snapshot(db, snapshot_id)

    from app.services.pdf_service import render_report_pdf
    pdf_bytes = render_report_pdf(
        title=snap.title or "Rapport de recrutement",
        data=snap.data or {},
        created_at=snap.created_at,
    )
    safe_name = (snap.title or "rapport").replace(" ", "_")[:60]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="PIQBIT_{safe_name}.pdf"',
        },
    )
