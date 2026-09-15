"""
Gestion des contrats de travail + signature électronique auto-hébergée.

RH/Admin (auth) :
  POST   /contracts/from-application/{app_id}   → crée le brouillon (prérempli)
  GET    /contracts                              → liste (filtre statut)
  GET    /contracts/stats                        → compteurs par statut
  GET    /contracts/{id}                         → détail
  PATCH  /contracts/{id}                          → édite le brouillon
  DELETE /contracts/{id}                          → supprime un brouillon
  POST   /contracts/{id}/send                    → génère le lien de signature
  GET    /contracts/{id}/pdf                      → télécharge le PDF (contrat + certificat)

Public (candidat, via token — pas de login) :
  GET    /contracts/sign/{token}                 → vue du contrat à signer
  POST   /contracts/sign/{token}                 → signature (audit + activation)
  POST   /contracts/decline/{token}              → refus
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.contract import (
    ContractCreate, ContractUpdate, ContractResponse, SendContractRequest,
    SignContractRequest, DeclineContractRequest, PublicContractView,
)
from app.services.contract_service import contract_service, public_url_for
from app.services.notification_service import notification_service

router = APIRouter()
_RH = require("contracts", "write")


# ════════════════════════════════════════════════════════════════════
#  PUBLIC — signature par le candidat (token, sans authentification)
# ════════════════════════════════════════════════════════════════════

def _public_view(contract, ctx) -> PublicContractView:
    app, candidate, user, job = ctx
    st = contract.status.value if hasattr(contract.status, "value") else str(contract.status)
    ct = contract.contract_type.value if hasattr(contract.contract_type, "value") else str(contract.contract_type)
    return PublicContractView(
        status=st, contract_type=ct, position=contract.position, department=contract.department,
        salary=contract.salary, currency=contract.currency, start_date=contract.start_date,
        trial_period_months=contract.trial_period_months, weekly_hours=contract.weekly_hours,
        end_date=contract.end_date, candidate_name=candidate.full_name, job_title=job.title,
        expires_at=contract.expires_at, signed_at=contract.signed_at,
        certificate_id=contract.certificate_id,
    )


@router.get("/sign/{token}", response_model=PublicContractView)
async def view_contract_to_sign(token: str, db: Annotated[AsyncSession, Depends(get_db)]):
    contract = await contract_service.get_by_token(db, token)
    ctx = await contract_service._context(db, contract.application_id)
    await db.commit()
    return _public_view(contract, ctx)


@router.post("/sign/{token}", response_model=PublicContractView)
async def sign_contract(
    token: str, body: SignContractRequest, request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not body.consent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Le consentement est requis pour signer.")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    contract = await contract_service.sign(
        db, token, signer_name=body.signer_name, signature_image=body.signature_image,
        ip=ip, user_agent=ua,
    )
    await db.commit()

    # Notifications : bienvenue au candidat + info aux admins (le candidat est
    # l'acteur ; on notifie tous les admins via un acteur système = le créateur).
    ctx = await contract_service._context(db, contract.application_id)
    _, candidate, user, job = ctx
    await notification_service.notify_user(
        db, recipient_id=user.id, type="CONTRACT_SIGNED",
        title="Contrat signé — bienvenue ! 🎉",
        message=f"Votre contrat pour « {job.title} » est signé. Bienvenue chez PIQBIT !",
        link="/frontoffice/applications",
    )
    if contract.created_by:
        await notification_service.notify_user(
            db, recipient_id=contract.created_by, type="CONTRACT_SIGNED",
            title="Contrat signé",
            message=f"{candidate.full_name} a signé son contrat ({job.title}). Employé créé automatiquement.",
            link="/admin/contracts",
        )
    await db.commit()
    return _public_view(contract, ctx)


@router.post("/decline/{token}", response_model=PublicContractView)
async def decline_contract(
    token: str, body: DeclineContractRequest, db: Annotated[AsyncSession, Depends(get_db)],
):
    contract = await contract_service.decline(db, token, reason=body.reason)
    await db.commit()
    ctx = await contract_service._context(db, contract.application_id)
    _, candidate, user, job = ctx
    if contract.created_by:
        await notification_service.notify_user(
            db, recipient_id=contract.created_by, type="CONTRACT_DECLINED",
            title="Contrat refusé",
            message=f"{candidate.full_name} a refusé le contrat ({job.title}).",
            link="/admin/contracts",
        )
        await db.commit()
    return _public_view(contract, ctx)


# ════════════════════════════════════════════════════════════════════
#  RH / ADMIN — authentifié
# ════════════════════════════════════════════════════════════════════

@router.post("/from-application/{application_id}", response_model=ContractResponse,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(_RH)])
async def create_contract(
    application_id: UUID, body: ContractCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    contract = await contract_service.create_from_application(db, application_id, body, current_user.id)
    await db.commit()
    return await contract_service.enrich_one(db, contract)


@router.get("/stats", dependencies=[Depends(_RH)])
async def contract_stats(db: Annotated[AsyncSession, Depends(get_db)]):
    return await contract_service.stats(db)


@router.get("", dependencies=[Depends(_RH)])
@router.get("/", include_in_schema=False, dependencies=[Depends(_RH)])
async def list_contracts(
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = None,
):
    return await contract_service.list(db, status_filter=status_filter)


@router.get("/{contract_id}", response_model=ContractResponse, dependencies=[Depends(_RH)])
async def get_contract(contract_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    contract = await contract_service.get(db, contract_id)
    return await contract_service.enrich_one(db, contract)


@router.patch("/{contract_id}", response_model=ContractResponse, dependencies=[Depends(_RH)])
async def update_contract(
    contract_id: UUID, body: ContractUpdate, db: Annotated[AsyncSession, Depends(get_db)],
):
    contract = await contract_service.update_draft(db, contract_id, body)
    await db.commit()
    return await contract_service.enrich_one(db, contract)


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(_RH)])
async def delete_contract(contract_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    await contract_service.delete_draft(db, contract_id)
    await db.commit()


@router.post("/{contract_id}/send", response_model=ContractResponse, dependencies=[Depends(_RH)])
async def send_contract(
    contract_id: UUID, body: SendContractRequest, db: Annotated[AsyncSession, Depends(get_db)],
):
    contract = await contract_service.send(db, contract_id, expires_in_days=body.expires_in_days)
    await db.commit()

    # Notifier le candidat qu'un contrat l'attend.
    ctx = await contract_service._context(db, contract.application_id)
    _, candidate, user, job = ctx
    await notification_service.notify_user(
        db, recipient_id=user.id, type="CONTRACT_SENT",
        title="Votre contrat est prêt à signer ✍️",
        message=f"Un contrat pour « {job.title} » vous attend. Consultez-le et signez en ligne.",
        link="/frontoffice/applications",
    )
    await db.commit()
    return await contract_service.enrich_one(db, contract)


@router.get("/{contract_id}/pdf", dependencies=[Depends(_RH)])
async def download_contract_pdf(contract_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    contract = await contract_service.get(db, contract_id)
    pdf = await contract_service.render_pdf(db, contract)
    ref = str(contract.id)[:8].upper()
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Contrat_PIQBIT_{ref}.pdf"'},
    )
