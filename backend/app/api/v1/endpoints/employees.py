"""
Endpoints « Employés » (backoffice RH/Admin). Répond au contrat du frontend
Angular `EmployeeService` (GET/POST /employees, GET/PUT/DELETE /employees/{id})
en camelCase.
"""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, EmployeeResponse
from app.services.employee_service import employee_service
from app.services.notification_service import notification_service

router = APIRouter(
    dependencies=[Depends(require("employees", "read"))]
)


@router.get("", response_model=list[EmployeeResponse], response_model_by_alias=True)
@router.get("/", response_model=list[EmployeeResponse], response_model_by_alias=True, include_in_schema=False)
async def list_employees(
    db: Annotated[AsyncSession, Depends(get_db)],
    department: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
):
    return await employee_service.list_employees(db, department, status_filter)


@router.get("/{employee_id}", response_model=EmployeeResponse, response_model_by_alias=True)
async def get_employee(employee_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    return await employee_service.get_employee(db, employee_id)


@router.post("", response_model=EmployeeResponse, response_model_by_alias=True,
             status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    employee = await employee_service.create_employee(db, body)
    await db.commit()

    await notification_service.notify_admins(
        db, actor=current_user, type="EMPLOYEE_CREATED",
        title="Nouvel employé ajouté",
        message=(f"{current_user.full_name or current_user.username} a ajouté "
                 f"{employee.first_name} {employee.last_name} ({employee.department or 'sans département'})."),
        link="/admin/employees",
    )
    await db.commit()
    return employee


@router.put("/{employee_id}", response_model=EmployeeResponse, response_model_by_alias=True)
async def update_employee(
    employee_id: UUID, body: EmployeeUpdate, db: Annotated[AsyncSession, Depends(get_db)],
):
    employee = await employee_service.update_employee(db, employee_id, body)
    await db.commit()
    return employee


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(employee_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    await employee_service.delete_employee(db, employee_id)
    await db.commit()


@router.post("/seed", status_code=status.HTTP_201_CREATED)
async def seed_employees_demo(db: Annotated[AsyncSession, Depends(get_db)]):
    """Insère les employés de démonstration (idempotent)."""
    created = await employee_service.seed_demo_data(db)
    await db.commit()
    return {"created_employees": created}
