from fastapi import APIRouter

from app.api.v1.endpoints import (
    assessment,
    auth, agents, recruitment, scoring, dashboard, workflow, interview,
    career, reports, decision, budget, employees, notifications, semantic, cag,
    contracts,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(agents.router, prefix="/users", tags=["Users"])
api_router.include_router(recruitment.router, prefix="/recruitment", tags=["Recruitment"])
api_router.include_router(scoring.router, prefix="/recruitment", tags=["Recruitment"])
api_router.include_router(workflow.router, prefix="/recruitment", tags=["Workflow"])
api_router.include_router(interview.router, prefix="/interview", tags=["Interview"])
api_router.include_router(assessment.router, prefix="/assessment", tags=["Assessment"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(career.router, prefix="/career", tags=["Career"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(decision.router, prefix="/decision", tags=["Decision"])
api_router.include_router(budget.router, prefix="/budget", tags=["Budget"])
api_router.include_router(employees.router, prefix="/employees", tags=["Employees"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(semantic.router, prefix="/semantic", tags=["Semantic Matching"])
api_router.include_router(cag.router, prefix="/cag", tags=["CAG Assistant"])
api_router.include_router(contracts.router, prefix="/contracts", tags=["Contracts"])
