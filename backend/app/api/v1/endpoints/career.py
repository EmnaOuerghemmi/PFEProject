from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.career import (
    CareerPlanCreate, CareerPlanUpdate, CareerPlanResponse, CareerStats,
)
from app.services.career_service import career_service
from app.services.notification_service import notification_service

router = APIRouter(
    dependencies=[Depends(require("career", "read"))]
)


@router.get("/stats", response_model=CareerStats)
async def career_stats(db: Annotated[AsyncSession, Depends(get_db)]):
    return await career_service.get_stats(db)


@router.get("/plans", response_model=list[CareerPlanResponse])
async def list_career_plans(
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = None,
):
    return await career_service.list_plans(db, status_filter)


@router.post("/plans", response_model=CareerPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_career_plan(
    body: CareerPlanCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    plan = await career_service.create_plan(db, body)
    await db.commit()
    await db.refresh(plan)

    await notification_service.notify_admins(
        db, actor=current_user, type="CAREER_PLAN_CREATED",
        title="Nouveau plan de carrière",
        message=(f"{current_user.full_name or current_user.username} a créé un plan de carrière "
                 f"vers « {plan.target_position or 'non défini'} »."),
        link="/admin/career",
    )
    await db.commit()
    return plan


@router.patch("/plans/{plan_id}", response_model=CareerPlanResponse)
async def update_career_plan(plan_id: UUID, body: CareerPlanUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    plan = await career_service.update_plan(db, plan_id, body)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_career_plan(plan_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    await career_service.delete_plan(db, plan_id)
    await db.commit()
