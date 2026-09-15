"""
Endpoints « Budget par département » (backoffice RH/Admin).
GET /budget/stats est la source du dashboard frontend.
"""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.budget import (
    BudgetStats, DepartmentBudgetCreate, DepartmentBudgetUpdate,
    DepartmentBudgetResponse, BudgetExpenseCreate, BudgetExpenseResponse,
)
from app.services.budget_service import budget_service
from app.services.notification_service import notification_service

router = APIRouter(
    dependencies=[Depends(require("budget", "read"))]
)


@router.get("/stats", response_model=BudgetStats)
async def budget_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    year: int | None = Query(default=None, ge=2000, le=2100),
):
    """Stats agrégées par département (alloué / dépensé / restant / effectif)."""
    return await budget_service.get_stats(db, year)


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department_budget(
    body: DepartmentBudgetCreate, db: Annotated[AsyncSession, Depends(get_db)],
):
    budget = await budget_service.create_budget(db, body)
    await db.commit()
    return {"id": str(budget.id), "department": budget.department, "year": budget.year}


@router.patch("/departments/{budget_id}")
async def update_department_budget(
    budget_id: UUID, body: DepartmentBudgetUpdate, db: Annotated[AsyncSession, Depends(get_db)],
):
    budget = await budget_service.update_budget(db, budget_id, body)
    await db.commit()
    return {"id": str(budget.id), "allocated_amount": budget.allocated_amount}


@router.delete("/departments/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department_budget(
    budget_id: UUID, db: Annotated[AsyncSession, Depends(get_db)],
):
    await budget_service.delete_budget(db, budget_id)
    await db.commit()


@router.get("/departments/{budget_id}/expenses", response_model=list[BudgetExpenseResponse])
async def list_expenses(budget_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    return await budget_service.list_expenses(db, budget_id)


@router.post(
    "/departments/{budget_id}/expenses",
    response_model=BudgetExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_expense(
    budget_id: UUID,
    body: BudgetExpenseCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    expense = await budget_service.add_expense(db, budget_id, body)
    await db.commit()

    from sqlalchemy import select
    from app.models.budget import DepartmentBudget
    dept = (await db.execute(
        select(DepartmentBudget.department).where(DepartmentBudget.id == budget_id)
    )).scalar_one_or_none()
    await notification_service.notify_admins(
        db, actor=current_user, type="BUDGET_EXPENSE_ADDED",
        title="Nouvelle dépense budget",
        message=(f"{current_user.full_name or current_user.username} a ajouté une dépense "
                 f"« {expense.label} » ({expense.amount:.0f} TND) au budget {dept or ''}."),
        link="/admin/budget",
    )
    await db.commit()
    return expense


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(expense_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    await budget_service.delete_expense(db, expense_id)
    await db.commit()


@router.post("/seed", status_code=status.HTTP_201_CREATED)
async def seed_budget_demo(db: Annotated[AsyncSession, Depends(get_db)]):
    """Insère les données de démonstration (idempotent)."""
    created = await budget_service.seed_demo_data(db)
    await db.commit()
    return {"created_departments": created}
