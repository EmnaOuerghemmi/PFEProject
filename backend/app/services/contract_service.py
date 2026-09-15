import logging
"""
Gestion du cycle de vie des contrats de travail.

    ACCEPTED ─► DRAFT ─► SENT ─► SIGNED ─► ACTIVE
                             │
                             └─► DECLINED / EXPIRED

Signature électronique auto-hébergée (gratuite, sans API externe) : lien public
à token, signature manuscrite, piste d'audit (nom, date UTC, IP, user-agent,
empreinte SHA-256 des termes, identifiant de certificat). À l'activation, un
`Employee` est créé automatiquement — la boucle recrutement→RH se referme.
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.contract import Contract, ContractStatus, ContractType
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User
from app.models.employee import Employee
from app.models.negotiation import Negotiation
from app.schemas.contract import ContractCreate, ContractUpdate
from app.models.application_status import ApplicationStatus

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _frontend_base_url() -> str:
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:4200").rstrip("/")


def public_url_for(token: str) -> str:
    return f"{_frontend_base_url()}/contract/sign/{token}"


class ContractService:

    # ── Contexte ──────────────────────────────────────────────────────────────

    async def _context(self, db: AsyncSession, application_id: UUID):
        """(application, candidate, user, job) ou 404."""
        row = (
            await db.execute(
                select(Application, Candidate, User, JobOffer)
                .join(Candidate, Application.candidate_id == Candidate.id)
                .join(User, Candidate.user_id == User.id)
                .join(JobOffer, Application.job_offer_id == JobOffer.id)
                .where(Application.id == application_id)
            )
        ).first()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidature introuvable")
        return row

    # ── Création (depuis une candidature) ─────────────────────────────────────

    async def create_from_application(
        self, db: AsyncSession, application_id: UUID, data: ContractCreate, created_by: UUID,
    ) -> Contract:
        existing = (
            await db.execute(select(Contract).where(Contract.application_id == application_id))
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Un contrat existe déjà pour cette candidature.",
            )
        app, candidate, user, job = await self._context(db, application_id)

        # Préremplissage du salaire : issue de la négociation, sinon offre.
        salary = data.salary
        if salary is None:
            neg = (
                await db.execute(
                    select(Negotiation)
                    .where(Negotiation.job_id == str(application_id))
                    .order_by(Negotiation.created_at.desc()).limit(1)
                )
            ).scalar_one_or_none()
            if neg and neg.final_salary:
                salary = neg.final_salary
            elif job.salary_max:
                salary = job.salary_max
            elif job.salary_min:
                salary = job.salary_min
        if salary is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Salaire requis (aucune négociation ni fourchette d'offre pour préremplir).",
            )

        try:
            ctype = ContractType(data.contract_type)
        except ValueError:
            ctype = ContractType.CDI

        contract = Contract(
            application_id=application_id,
            contract_type=ctype,
            position=data.position or job.title,
            department=data.department,
            salary=float(salary),
            start_date=_aware(data.start_date),
            trial_period_months=data.trial_period_months,
            weekly_hours=data.weekly_hours,
            end_date=_aware(data.end_date),
            notes=data.notes,
            employee_birth_date=_aware(data.employee_birth_date),
            employee_cin=data.employee_cin,
            employee_cin_issue_date=_aware(data.employee_cin_issue_date),
            employee_address=data.employee_address,
            status=ContractStatus.DRAFT,
            created_by=created_by,
        )
        db.add(contract)
        await db.flush()
        await db.refresh(contract)
        return contract

    async def update_draft(self, db: AsyncSession, contract_id: UUID, data: ContractUpdate) -> Contract:
        contract = await self.get(db, contract_id)
        if contract.status != ContractStatus.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Seul un contrat en brouillon peut être modifié.",
            )
        payload = data.model_dump(exclude_none=True)
        if "contract_type" in payload:
            try:
                contract.contract_type = ContractType(payload.pop("contract_type"))
            except ValueError:
                payload.pop("contract_type", None)
        for field in ("start_date", "end_date", "employee_birth_date", "employee_cin_issue_date"):
            if field in payload:
                payload[field] = _aware(payload[field])
        for field, value in payload.items():
            setattr(contract, field, value)
        await db.flush()
        await db.refresh(contract)
        return contract

    # ── Envoi (génération du lien de signature) ───────────────────────────────

    async def send(self, db: AsyncSession, contract_id: UUID, *, expires_in_days: int = 14) -> Contract:
        contract = await self.get(db, contract_id)
        if contract.status not in (ContractStatus.DRAFT, ContractStatus.SENT):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ce contrat ne peut plus être envoyé (déjà signé, refusé ou expiré).",
            )
        contract.token = secrets.token_urlsafe(32)
        contract.status = ContractStatus.SENT
        contract.sent_at = _now()
        contract.expires_at = _now() + timedelta(days=expires_in_days)
        await db.flush()
        await db.refresh(contract)
        return contract

    # ── Signature (candidat, public) ──────────────────────────────────────────

    async def get_by_token(self, db: AsyncSession, token: str) -> Contract:
        contract = (
            await db.execute(select(Contract).where(Contract.token == token))
        ).scalar_one_or_none()
        if not contract:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrat introuvable")
        # Expiration paresseuse.
        if contract.status == ContractStatus.SENT and contract.expires_at \
                and _aware(contract.expires_at) < _now():
            contract.status = ContractStatus.EXPIRED
            await db.flush()
        return contract

    @staticmethod
    def _terms_fingerprint(contract: Contract, candidate_name: str, job_title: str) -> str:
        """Empreinte SHA-256 des termes signés (scelle le contenu du contrat)."""
        canonical = "|".join(str(x) for x in [
            candidate_name, job_title,
            contract.contract_type.value if hasattr(contract.contract_type, "value") else contract.contract_type,
            contract.position, contract.department, contract.salary, contract.currency,
            contract.start_date, contract.trial_period_months, contract.weekly_hours,
            contract.end_date, contract.notes,
            contract.employee_birth_date, contract.employee_cin,
            contract.employee_cin_issue_date, contract.employee_address,
        ])
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def sign(
        self, db: AsyncSession, token: str, *, signer_name: str, signature_image: str,
        ip: str | None, user_agent: str | None,
    ) -> Contract:
        contract = await self.get_by_token(db, token)
        if contract.status == ContractStatus.SIGNED or contract.status == ContractStatus.ACTIVE:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce contrat est déjà signé.")
        if contract.status == ContractStatus.DECLINED:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Ce contrat a été refusé.")
        if contract.status != ContractStatus.SENT:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Ce lien de signature n'est plus valide.")

        app, candidate, user, job = await self._context(db, contract.application_id)

        contract.status = ContractStatus.SIGNED
        contract.signed_at = _now()
        contract.signer_name = signer_name.strip()
        contract.signer_ip = ip
        contract.signer_user_agent = (user_agent or "")[:400]
        contract.signature_image = signature_image
        contract.document_hash = self._terms_fingerprint(contract, candidate.full_name, job.title)
        contract.certificate_id = "PIQBIT-" + secrets.token_hex(6).upper()
        await db.flush()

        # ── Activation : création de l'employé (boucle recrutement → RH) ──
        await self._activate(db, contract, candidate, user, job)
        await db.refresh(contract)
        return contract

    async def _activate(self, db: AsyncSession, contract: Contract, candidate, user, job) -> None:
        """Crée l'employé, passe la candidature en HIRED, marque le contrat ACTIF."""
        parts = (candidate.full_name or "").strip().split(" ", 1)
        first = parts[0] if parts else candidate.full_name
        last = parts[1] if len(parts) > 1 else ""

        # Éviter les doublons d'email dans employees.
        employee = (
            await db.execute(select(Employee).where(Employee.email == user.email))
        ).scalar_one_or_none()
        if not employee:
            employee = Employee(
                first_name=first, last_name=last or first, email=user.email,
                phone=candidate.phone, position=contract.position,
                department=contract.department, salary=contract.salary,
                hire_date=contract.start_date or _now(), status="active",
                # Repris de ce que le contrat et le CV savent déjà. La date de
                # naissance et le genre, eux, ne sont NULLE PART en amont : ni
                # le candidat ni l'offre ne les portent. Ils resteront vides
                # jusqu'à ce qu'un humain les saisisse — d'où l'alerte qui suit.
                contract_type=(contract.contract_type.value
                               if contract.contract_type else None),
                education_level=await self._niveau_detude(db, contract),
            )
            db.add(employee)
            await db.flush()
            await self._signaler_fiche_a_completer(db, employee)

        contract.employee_id = employee.id
        contract.status = ContractStatus.ACTIVE

        app = (
            await db.execute(select(Application).where(Application.id == contract.application_id))
        ).scalar_one_or_none()
        if app:
            app.status = ApplicationStatus.HIRED.value
        await db.flush()

    @staticmethod
    async def _niveau_detude(db: AsyncSession, contract: Contract) -> str | None:
        """
        Niveau d'études, repris de l'analyse de CV quand elle existe.

        Best-effort : une analyse absente ou illisible ne doit pas empêcher la
        création de l'employé — c'est un confort de saisie, pas une donnée
        dont dépend l'embauche.
        """
        try:
            from app.models.scoring import CVAnalysis
            analyse = (await db.execute(
                select(CVAnalysis).where(
                    CVAnalysis.application_id == contract.application_id
                )
            )).scalar_one_or_none()
            if analyse and getattr(analyse, "education_level", None):
                return str(analyse.education_level)[:50]
        except Exception:                      # pragma: no cover - défensif
            pass
        return None

    @staticmethod
    async def _signaler_fiche_a_completer(db: AsyncSession, employee) -> None:
        """
        Prévient les RH qu'une fiche employé vient d'apparaître, incomplète.

        Elle est créée par un traitement de fond, sans personne devant l'écran.
        Sans ce signalement, elle resterait à moitié vide indéfiniment — et les
        répartitions par âge et par genre du tableau de bord n'auraient jamais
        de données.
        """
        manquants = employee.missing_fields
        if not manquants:
            return
        try:
            from app.models.user import UserRole
            from app.services.notification_service import notification_service
            await notification_service.notify_roles(
                db, roles=[UserRole.ADMIN, UserRole.RH],
                type="EMPLOYEE_INCOMPLETE",
                title="Fiche employé à compléter",
                message=(f"{employee.first_name} {employee.last_name} vient d'être "
                         f"enregistré·e — {len(manquants)} champ(s) restent à renseigner."),
                link=f"/admin/employees/{employee.id}",
            )
        except Exception as exc:               # pragma: no cover - défensif
            logger.warning("Signalement de fiche incomplète impossible : %s", exc)

    async def decline(self, db: AsyncSession, token: str, reason: str = "") -> Contract:
        contract = await self.get_by_token(db, token)
        if contract.status not in (ContractStatus.SENT,):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Ce contrat ne peut plus être refusé.")
        contract.status = ContractStatus.DECLINED
        contract.declined_at = _now()
        contract.decline_reason = reason
        await db.flush()
        await db.refresh(contract)
        return contract

    # ── Lecture ───────────────────────────────────────────────────────────────

    async def get(self, db: AsyncSession, contract_id: UUID) -> Contract:
        contract = (
            await db.execute(select(Contract).where(Contract.id == contract_id))
        ).scalar_one_or_none()
        if not contract:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrat introuvable")
        return contract

    async def list(self, db: AsyncSession, *, status_filter: str | None = None) -> list[dict]:
        query = (
            select(Contract, Candidate, User, JobOffer)
            .join(Application, Contract.application_id == Application.id)
            .join(Candidate, Application.candidate_id == Candidate.id)
            .join(User, Candidate.user_id == User.id)
            .join(JobOffer, Application.job_offer_id == JobOffer.id)
            .order_by(Contract.created_at.desc())
        )
        if status_filter:
            query = query.where(Contract.status == ContractStatus(status_filter))
        rows = (await db.execute(query)).all()
        return [self.enrich(c, cand, u, j) for c, cand, u, j in rows]

    async def enrich_one(self, db: AsyncSession, contract: Contract) -> dict:
        app, candidate, user, job = await self._context(db, contract.application_id)
        return self.enrich(contract, candidate, user, job)

    @staticmethod
    def enrich(contract: Contract, candidate, user, job) -> dict:
        st = contract.status.value if hasattr(contract.status, "value") else str(contract.status)
        ct = contract.contract_type.value if hasattr(contract.contract_type, "value") else str(contract.contract_type)
        return {
            "id": contract.id, "application_id": contract.application_id,
            "contract_type": ct, "position": contract.position, "department": contract.department,
            "salary": contract.salary, "currency": contract.currency,
            "start_date": contract.start_date, "trial_period_months": contract.trial_period_months,
            "weekly_hours": contract.weekly_hours, "end_date": contract.end_date, "notes": contract.notes,
            "status": st, "sent_at": contract.sent_at, "expires_at": contract.expires_at,
            "signed_at": contract.signed_at, "signer_name": contract.signer_name,
            "certificate_id": contract.certificate_id, "employee_id": contract.employee_id,
            "created_at": contract.created_at,
            "employee_birth_date": contract.employee_birth_date,
            "employee_cin": contract.employee_cin,
            "employee_cin_issue_date": contract.employee_cin_issue_date,
            "employee_address": contract.employee_address,
            "candidate_name": candidate.full_name, "candidate_email": user.email,
            "candidate_phone": candidate.phone,
            "job_title": job.title,
            "public_url": public_url_for(contract.token) if contract.token else None,
        }

    async def stats(self, db: AsyncSession) -> dict:
        rows = (
            await db.execute(select(Contract.status, func.count(Contract.id)).group_by(Contract.status))
        ).all()
        counts = {(s.value if hasattr(s, "value") else str(s)): c for s, c in rows}
        return {
            "draft": counts.get("DRAFT", 0), "sent": counts.get("SENT", 0),
            "signed": counts.get("SIGNED", 0), "active": counts.get("ACTIVE", 0),
            "declined": counts.get("DECLINED", 0), "expired": counts.get("EXPIRED", 0),
            "total": sum(counts.values()),
        }

    async def delete_draft(self, db: AsyncSession, contract_id: UUID) -> None:
        contract = await self.get(db, contract_id)
        if contract.status != ContractStatus.DRAFT:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Seul un brouillon peut être supprimé.")
        await db.delete(contract)
        await db.flush()

    async def render_pdf(self, db: AsyncSession, contract: Contract) -> bytes:
        app, candidate, user, job = await self._context(db, contract.application_id)
        from app.services.contract_pdf import render_contract_pdf
        return render_contract_pdf(
            contract=contract, candidate_name=candidate.full_name,
            candidate_email=user.email, job_title=job.title,
        )


contract_service = ContractService()
