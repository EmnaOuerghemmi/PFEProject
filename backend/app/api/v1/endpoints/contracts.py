"""
Gestion des contrats de travail + signature électronique auto-hébergée.

RH/Admin (auth) :
  POST   /contracts/from-application/{app_id}   → crée le brouillon (prérempli)
  GET    /contracts/pending                      → candidats acceptés sans contrat
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

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.contract import ContractStatus
from app.models.user import User
from app.schemas.contract import (
    ContractCreate, ContractUpdate, ContractResponse, SendContractRequest,
    SignContractRequest, DeclineContractRequest, PublicContractView, PendingContract,
    RetirerContratRequest, RetraitContratResponse,
)
from app.services.contract_service import contract_service, public_url_for
from app.services.notification_service import notification_service
from app.services.email_service import send_contract_signed, send_contract_to_sign

logger = logging.getLogger(__name__)
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


@router.get("/sign/{token}/pdf")
async def view_contract_pdf(token: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Le contrat complet en PDF, pour que le candidat le lise AVANT de signer.

    Public, protégé par le jeton comme la page de signature. Affiché dans la
    page (`inline`), jamais téléchargé d'office : il sert à la lecture.
    """
    contract = await contract_service.get_by_token(db, token)
    await db.commit()
    if contract.status not in (ContractStatus.SENT, ContractStatus.SIGNED, ContractStatus.ACTIVE):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Ce contrat n'est plus consultable.")
    pdf = await contract_service.render_pdf(db, contract)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="Contrat_PIQBIT.pdf"', "Cache-Control": "no-store"},
    )


@router.post("/sign/{token}", response_model=PublicContractView)
async def sign_contract(
    token: str, body: SignContractRequest, request: Request, background_tasks: BackgroundTasks,
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

    # Exemplaire signé envoyé au candidat. Un échec du PDF ne doit pas faire
    # échouer la signature, déjà enregistrée : l'e-mail part alors sans pièce jointe.
    try:
        pdf = await contract_service.render_pdf(db, contract)
    except Exception:
        logger.exception("PDF du contrat signé %s impossible à générer", contract.id)
        pdf = None
    background_tasks.add_task(
        send_contract_signed, to_email=user.email, candidate_name=candidate.full_name,
        job_title=job.title, pdf=pdf, reference=str(contract.id)[:8].upper(),
    )
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


@router.get("/pending", response_model=list[PendingContract], dependencies=[Depends(_RH)])
async def pending_contracts(db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Candidats ACCEPTÉS sans contrat, avec le salaire proposé et sa provenance.
    Déclarée avant `/{contract_id}` : « pending » n'est pas un identifiant.
    """
    return await contract_service.pending(db)


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


@router.post("/{contract_id}/retirer", response_model=RetraitContratResponse,
             dependencies=[Depends(require("contracts", "delete"))])
async def retirer_contrat(
    contract_id: UUID,
    body: RetirerContratRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Retire un contrat quel que soit son statut (administrateur seulement) :
    la candidature prend le statut choisi, la fiche employé créée à la
    signature passe « inactive », et le retrait entre au journal d'audit.
    """
    resultat = await contract_service.retirer(
        db, contract_id, motif=body.motif.strip(), statut_candidature=body.statut_candidature,
        admin_id=current_user.id,
    )
    await db.commit()
    return RetraitContratResponse(**resultat)


@router.post("/{contract_id}/send", response_model=ContractResponse, dependencies=[Depends(_RH)])
async def send_contract(
    contract_id: UUID, body: SendContractRequest, background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Génère le lien de signature et l'envoie au candidat par e-mail.

    Rappelé sur un contrat déjà envoyé, il en génère un nouveau (l'ancien lien
    cesse de fonctionner) et renvoie l'e-mail.
    """
    contract = await contract_service.send(db, contract_id, expires_in_days=body.expires_in_days)
    await db.commit()

    # Notifier le candidat qu'un contrat l'attend.
    ctx = await contract_service._context(db, contract.application_id)
    _, candidate, user, job = ctx
    await notification_service.notify_user(
        db, recipient_id=user.id, type="CONTRACT_SENT",
        title="Votre contrat est prêt à signer ✍️",
        message=f"Un contrat pour « {job.title} » vous attend. Consultez-le et signez en ligne.",
        # Directement la page de signature (avant : « Mes candidatures », sans lien vers le contrat).
        link=f"/contract/sign/{contract.token}",
    )
    await db.commit()
    background_tasks.add_task(
        send_contract_to_sign, to_email=user.email, candidate_name=candidate.full_name,
        job_title=job.title, sign_url=public_url_for(contract.token), expires_at=contract.expires_at,
    )
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
