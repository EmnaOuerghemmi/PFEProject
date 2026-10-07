"""
Remplissage de démonstration de TOUTES les tables métier (recrutement tech
tunisien). Idempotent : si le marqueur existe déjà, ne fait rien.

Usage :
    cd backend
    python scripts/seed_demo.py          # remplit si vide
    python scripts/seed_demo.py --reset  # supprime les données de démo puis re-remplit
"""
import asyncio
import sys
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, delete
from app.db.session import AsyncSessionLocal
from app.core.security import hash_password

from app.models.user import User, UserRole
from app.models.recruitment import JobOffer, Candidate, Application, SavedJob
from app.models.scoring import CVAnalysis, CandidateScore
from app.models.interview import InterviewInvitation, InterviewSlot, InvitationStatus
from app.models.negotiation import Negotiation, NegotiationRound
from app.models.career import CareerPlan
from app.models.report import ReportSnapshot
from app.models.notification import Notification
from app.models.employee import Employee
from app.models.contract import Contract, ContractStatus, ContractType

MARKER_EMAIL = "seed.marker@piqbit.demo"
PW = hash_password("Demo1234!")


def now():
    return datetime.now(timezone.utc)


async def already_seeded(db) -> bool:
    return (await db.execute(select(User).where(User.email == MARKER_EMAIL))).scalar_one_or_none() is not None


async def reset(db):
    """Supprime les données de démo (repérées par le suffixe @piqbit.demo)."""
    demo_users = (await db.execute(
        select(User.id).where(User.email.like("%@piqbit.demo"))
    )).scalars().all()
    if not demo_users:
        print("Aucune donnée de démo à supprimer.")
        return
    cand_ids = (await db.execute(
        select(Candidate.id).where(Candidate.user_id.in_(demo_users))
    )).scalars().all()
    app_ids = (await db.execute(
        select(Application.id).where(Application.candidate_id.in_(cand_ids))
    )).scalars().all() if cand_ids else []

    if app_ids:
        await db.execute(delete(Contract).where(Contract.application_id.in_(app_ids)))
        slot_inv = (await db.execute(
            select(InterviewInvitation.id).where(InterviewInvitation.application_id.in_(app_ids))
        )).scalars().all()
        if slot_inv:
            # Détacher confirmed_slot pour éviter les FK, puis purger slots & invits.
            await db.execute(
                InterviewInvitation.__table__.update()
                .where(InterviewInvitation.id.in_(slot_inv))
                .values(confirmed_slot_id=None)
            )
            await db.execute(delete(InterviewSlot).where(InterviewSlot.invitation_id.in_(slot_inv)))
            await db.execute(delete(InterviewInvitation).where(InterviewInvitation.id.in_(slot_inv)))
        await db.execute(delete(CandidateScore).where(CandidateScore.application_id.in_(app_ids)))
        await db.execute(delete(CVAnalysis).where(CVAnalysis.application_id.in_(app_ids)))
        await db.execute(delete(Negotiation).where(Negotiation.job_id.in_([str(a) for a in app_ids])))
        await db.execute(delete(Application).where(Application.id.in_(app_ids)))
    await db.execute(delete(SavedJob).where(SavedJob.user_id.in_(demo_users)))
    await db.execute(delete(CareerPlan).where(CareerPlan.user_id.in_(demo_users)))
    await db.execute(delete(Notification).where(Notification.recipient_id.in_(demo_users)))
    if cand_ids:
        await db.execute(delete(Candidate).where(Candidate.id.in_(cand_ids)))
    await db.execute(delete(JobOffer).where(JobOffer.title.like("%[demo]%")))
    await db.execute(delete(Employee).where(Employee.email.like("%@piqbit.demo")))
    await db.execute(delete(ReportSnapshot).where(ReportSnapshot.title.like("%[demo]%")))
    await db.execute(delete(User).where(User.email.like("%@piqbit.demo")))
    await db.commit()
    print(f"Données de démo supprimées ({len(demo_users)} utilisateurs).")


async def seed(db):
    counts = {}

    # ── Marqueur + comptes RH/candidats ──────────────────────────────────────
    marker = User(id=uuid4(), email=MARKER_EMAIL, username="seed_marker",
                  hashed_password=PW, full_name="Seed Marker", role=UserRole.READ_ONLY,
                  is_active=False, is_verified=True)
    db.add(marker)

    rh_users = []
    for i, (name, role) in enumerate([
        ("Rania Gharbi", UserRole.RH_MANAGER),
        ("Sami Toumi", UserRole.RH_STAFF),
        ("Leila Ben Youssef", UserRole.RH_STAFF),
    ]):
        u = User(id=uuid4(), email=f"rh{i+1}@piqbit.demo", username=f"rh{i+1}_demo",
                 hashed_password=PW, full_name=name, role=role, is_active=True, is_verified=True)
        db.add(u); rh_users.append(u)

    candidates_data = [
        ("Ahmed Ben Salah", "Frontend Developer", ["React", "TypeScript", "CSS", "HTML"], 3, "MASTER"),
        ("Ines Trabelsi", "Data Scientist", ["Python", "SQL", "Machine Learning", "Pandas"], 4, "INGENIEUR"),
        ("Mohamed Gharbi", "DevOps Engineer", ["Docker", "Kubernetes", "AWS", "Terraform"], 5, "MASTER"),
        ("Sarra Mansouri", "Backend Developer", ["Python", "FastAPI", "PostgreSQL", "REST"], 2, "BACHELOR"),
        ("Yassine Karray", "Fullstack Developer", ["Angular", "Node", "MongoDB", "TypeScript"], 4, "INGENIEUR"),
        ("Rim Chaabane", "UX/UI Designer", ["Figma", "Design", "CSS", "Prototyping"], 3, "MASTER"),
        ("Khalil Jebali", "Mobile Developer", ["Kotlin", "Swift", "Flutter", "REST"], 3, "BACHELOR"),
        ("Nour Baccouche", "QA Engineer", ["Selenium", "Python", "CI", "Testing"], 2, "BACHELOR"),
    ]
    cand_users, candidates = [], []
    for i, (name, _, _, _, _) in enumerate(candidates_data):
        u = User(id=uuid4(), email=f"candidat{i+1}@piqbit.demo", username=f"cand{i+1}_demo",
                 hashed_password=PW, full_name=name, role=UserRole.READ_ONLY,
                 is_active=True, is_verified=True, phone_number=f"+2162{i}123456")
        db.add(u); cand_users.append(u)
    await db.flush()
    for u, (name, _, _, _, _) in zip(cand_users, candidates_data):
        c = Candidate(id=uuid4(), user_id=u.id, full_name=name, phone=u.phone_number, cv_path="demo_cv.pdf")
        db.add(c); candidates.append(c)
    await db.flush()
    counts["users"] = len(cand_users) + len(rh_users) + 1
    counts["candidates"] = len(candidates)

    # ── Offres d'emploi ───────────────────────────────────────────────────────
    jobs_data = [
        ("Frontend Developer [demo]", ["React", "TypeScript", "CSS"], 2400, 3200, 3, "MASTER"),
        ("Data Scientist [demo]", ["Python", "SQL", "Machine Learning"], 3000, 4200, 4, "INGENIEUR"),
        ("DevOps Engineer [demo]", ["Docker", "Kubernetes", "AWS", "Terraform"], 3200, 4500, 4, "MASTER"),
        ("Backend Developer [demo]", ["Python", "FastAPI", "PostgreSQL"], 2200, 3400, 2, "BACHELOR"),
        ("UX/UI Designer [demo]", ["Figma", "Design", "Prototyping"], 2000, 3000, 3, "MASTER"),
        ("Mobile Developer [demo]", ["Kotlin", "Swift", "Flutter"], 2300, 3300, 3, "BACHELOR"),
    ]
    jobs = []
    for title, skills, smin, smax, exp, edu in jobs_data:
        j = JobOffer(id=uuid4(), title=title,
                     description=f"Nous recherchons un·e {title.replace(' [demo]','')} motivé·e "
                                 f"pour rejoindre notre équipe. Stack : {', '.join(skills)}. "
                                 f"Environnement agile, projets à fort impact.",
                     salary_min=smin, salary_max=smax, required_skills=skills,
                     required_experience_years=exp, required_education_level=edu,
                     is_active=True, created_by=rh_users[0].id)
        db.add(j); jobs.append(j)
    await db.flush()
    counts["job_offers"] = len(jobs)

    # ── Candidatures (statuts variés) + analyses + scores ────────────────────
    # Distribution volontairement riche en fin de pipeline pour garantir ≥4
    # lignes dans negotiations et contracts.
    statuses = ["PENDING", "REVIEWED", "INTERVIEW_SCHEDULED", "NEGOTIATION",
                "NEGOTIATION", "ACCEPTED", "ACCEPTED", "HIRED"]
    apps = []
    for i, (cand, (name, title, skills, exp, edu)) in enumerate(zip(candidates, candidates_data)):
        job = jobs[i % len(jobs)]
        app = Application(id=uuid4(), candidate_id=cand.id, job_offer_id=job.id,
                          cv_file_path=f"demo/cv_{i+1}.pdf", status=statuses[i % len(statuses)],
                          created_at=now() - timedelta(days=20 - i * 2))
        db.add(app); apps.append((app, name, title, skills, exp, edu, job))
    await db.flush()
    counts["applications"] = len(apps)

    n_analyses = n_scores = 0
    for i, (app, name, title, skills, exp, edu, job) in enumerate(apps):
        if app.status in ("PENDING",):
            continue  # non analysée
        raw = (f"{name} — {title}. Diplômé·e ({edu}). {exp} ans d'expérience. "
               f"Compétences : {', '.join(skills)}. J'ai contribué à plusieurs projets web "
               f"et participé à des équipes agiles.")
        analysis = CVAnalysis(application_id=app.id, candidate_id=app.candidate_id, raw_text=raw,
                              extracted_skills=skills, extracted_experience_years=float(exp),
                              extracted_education_level=edu, extracted_job_titles=[title],
                              extracted_keywords=skills, is_parsed=True, parsed_at=now())
        db.add(analysis); n_analyses += 1
        req = set(s.lower() for s in (job.required_skills or []))
        have = set(s.lower() for s in skills)
        sk = round(len(req & have) / max(1, len(req)) * 100, 1)
        ex = round(min(100.0, exp / max(1, job.required_experience_years or 1) * 80), 1)
        ed = 80.0
        total = round(sk * 0.5 + ex * 0.3 + ed * 0.2, 1)
        db.add(CandidateScore(application_id=app.id, job_offer_id=job.id, candidate_id=app.candidate_id,
                              total_score=total, skills_score=sk, experience_score=ex, education_score=ed,
                              rank=i + 1, score_details={"matched_skills": list(req & have),
                                                         "missing_skills": list(req - have)}))
        n_scores += 1
    await db.flush()
    counts["cv_analyses"] = n_analyses
    counts["candidate_scores"] = n_scores

    # ── Offres sauvegardées ──────────────────────────────────────────────────
    n_saved = 0
    for i, u in enumerate(cand_users[:5]):
        db.add(SavedJob(id=uuid4(), user_id=u.id, job_offer_id=jobs[(i + 1) % len(jobs)].id))
        n_saved += 1
    await db.flush()
    counts["saved_jobs"] = n_saved

    # ── Entretiens (invitations + créneaux) ──────────────────────────────────
    n_inv = n_slots = 0
    for app, name, *_ in [a for a in apps if a[0].status in ("INTERVIEW_SCHEDULED", "ACCEPTED", "HIRED")][:5]:
        inv = InterviewInvitation(id=uuid4(), application_id=app.id, token=secrets.token_urlsafe(24),
                                  status=InvitationStatus.CONFIRMED, message="Entretien technique + RH.",
                                  expires_at=now() + timedelta(days=5), confirmed_at=now(),
                                  created_by=rh_users[0].id)
        db.add(inv); n_inv += 1
        await db.flush()
        chosen = None
        for d in range(2):
            start = now() + timedelta(days=2 + d, hours=10)
            slot = InterviewSlot(id=uuid4(), invitation_id=inv.id, start_at=start,
                                 end_at=start + timedelta(minutes=45), is_selected=(d == 0))
            db.add(slot); n_slots += 1
            if d == 0:
                chosen = slot
        await db.flush()
        if chosen:
            inv.confirmed_slot_id = chosen.id
    await db.flush()
    counts["interview_invitations"] = n_inv
    counts["interview_slots"] = n_slots

    # ── Négociations + rounds ────────────────────────────────────────────────
    n_neg = n_rounds = 0
    for app, name, title, skills, exp, edu, job in [a for a in apps if a[0].status in ("NEGOTIATION", "ACCEPTED", "HIRED")][:4]:
        predicted = float(job.salary_max or 3000)
        initial = round(predicted * 0.85)
        final = round(predicted * 0.96)
        neg = Negotiation(id=uuid4(), job_id=str(app.id), candidate_id=str(app.candidate_id),
                          job_offer_id=job.id, predicted_salary=predicted, confidence=0.82,
                          initial_offer=initial, final_salary=final,
                          status="ACCEPTED" if app.status in ("ACCEPTED", "HIRED") else "ONGOING",
                          reason="Accord trouvé au round 2." , rounds_count=3, max_iterations=5)
        db.add(neg); n_neg += 1
        await db.flush()
        rounds = [("employer", initial, "pending", "Offre initiale"),
                  ("candidate", round(predicted * 0.98), "counter_offer", "Contre-proposition"),
                  ("employer", final, "accept", "Compromis accepté")]
        for k, (actor, amount, decision, reason) in enumerate(rounds):
            db.add(NegotiationRound(id=uuid4(), negotiation_id=neg.id, round_number=k + 1,
                                    actor=actor, amount=amount, decision=decision, reason=reason))
            n_rounds += 1
    await db.flush()
    counts["negotiations"] = n_neg
    counts["negotiation_rounds"] = n_rounds

    # ── Plans de carrière (sur les comptes RH internes) ──────────────────────
    plans_data = [
        (rh_users[0], "Manager RH", "Directrice RH", "PROMOTION_PLANNED", 65.0, "Leadership, Budget"),
        (rh_users[1], "Staff RH", "Manager RH", "IN_PROGRESS", 40.0, "Recrutement, Négociation"),
        (rh_users[2], "Staff RH", "Chargée de mission", "PROBATION", 15.0, "Communication, ATS"),
        (cand_users[5], "Designer Junior", "Lead Designer", "IN_PROGRESS", 50.0, "Design system, Management"),
        (cand_users[6], "Développeur", "Tech Lead", "RETIREMENT_PLANNED", 90.0, "Architecture"),
    ]
    for u, cur, tgt, st, prog, skills in plans_data:
        db.add(CareerPlan(id=uuid4(), user_id=u.id, current_position=cur, target_position=tgt,
                          status=st, progress=prog, skills_to_develop=skills,
                          notes="Plan de développement de démonstration.",
                          target_date=now() + timedelta(days=180)))
    counts["career_plans"] = len(plans_data)

    # ── Rapports archivés ────────────────────────────────────────────────────
    for i in range(4):
        summary = {"total_jobs": len(jobs), "active_jobs": len(jobs),
                   "total_applications": len(apps), "acceptance_rate": 18.0 + i,
                   "average_score": 68.0 + i, "applications_by_status": {"PENDING": 1, "ACCEPTED": 2},
                   "top_jobs": [{"title": jobs[0].title, "application_count": 3}],
                   "generated_at": now().isoformat(),
                   "report": {"narrative": "Activité de recrutement soutenue sur la période.",
                              "highlights": ["Pipeline sain"], "recommendations": ["Maintenir le rythme"],
                              "generated_by": "deterministic"}}
        db.add(ReportSnapshot(id=uuid4(), report_type="recruitment_summary",
                              title=f"Synthèse recrutement S{i+1} [demo]", data=summary,
                              created_by=rh_users[0].id, created_at=now() - timedelta(days=i * 7)))
    counts["report_snapshots"] = 4

    # ── Notifications ────────────────────────────────────────────────────────
    n_notif = 0
    for i, u in enumerate(cand_users[:5]):
        db.add(Notification(id=uuid4(), recipient_id=u.id, type="APPLICATION_STATUS_CHANGED",
                            title="Mise à jour de votre candidature",
                            message=f"Votre candidature est passée à : {statuses[i % len(statuses)]}.",
                            link="/frontoffice/applications", is_read=(i % 2 == 0),
                            created_at=now() - timedelta(hours=i * 5)))
        n_notif += 1
    counts["notifications"] = n_notif

    # ── Contrats (états variés) + employé pour le signé ──────────────────────
    accepted_apps = [a for a in apps if a[0].status in ("ACCEPTED", "HIRED")]
    n_contracts = 0
    for k, (app, name, title, skills, exp, edu, job) in enumerate(accepted_apps[:5]):
        st = [ContractStatus.DRAFT, ContractStatus.SENT, ContractStatus.ACTIVE, ContractStatus.SENT][k % 4]
        salary = float(job.salary_max or 3000)
        contract = Contract(id=uuid4(), application_id=app.id, contract_type=ContractType.CDI,
                            position=title, department="Tech", salary=salary, currency="TND",
                            start_date=now() + timedelta(days=15), trial_period_months=3, weekly_hours=40,
                            status=st, created_by=rh_users[0].id)
        if st in (ContractStatus.SENT, ContractStatus.ACTIVE):
            contract.token = secrets.token_urlsafe(24)
            contract.sent_at = now(); contract.expires_at = now() + timedelta(days=14)
        if st == ContractStatus.ACTIVE:
            emp = Employee(id=uuid4(), first_name=name.split()[0], last_name=name.split()[-1],
                           email=f"emp_{k}@piqbit.demo", position=title, department="Tech",
                           salary=salary, hire_date=now(), status="active")
            db.add(emp); await db.flush()
            contract.employee_id = emp.id
            contract.signed_at = now(); contract.signer_name = name
            contract.signer_ip = "196.203.10.20"; contract.signer_user_agent = "Mozilla/5.0"
            contract.document_hash = hashlib.sha256(name.encode()).hexdigest()
            contract.certificate_id = "PIQBIT-" + secrets.token_hex(6).upper()
        db.add(contract); n_contracts += 1
    counts["contracts"] = n_contracts

    await db.commit()
    return counts


async def main():
    do_reset = "--reset" in sys.argv
    async with AsyncSessionLocal() as db:
        if do_reset:
            await reset(db)
        elif await already_seeded(db):
            print("Déjà rempli (marqueur présent). Utilisez --reset pour ré-générer.")
            return
        counts = await seed(db)
    print("\n✅ Base remplie :")
    for table, n in counts.items():
        print(f"   {table:24} {n:>3} lignes")


if __name__ == "__main__":
    asyncio.run(main())
