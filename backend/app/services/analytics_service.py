"""Analytics / reporting service — aggregates live recruitment KPIs."""
from collections import Counter
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recruitment import JobOffer, Application
from app.models import application_status
from app.models.scoring import CandidateScore, CVAnalysis

# Cette liste omettait TEST_SENT et HIRED : les candidatures en test et les
# embauchés n'apparaissaient dans aucune statistique, et la somme des statuts
# du tableau de bord était inférieure au nombre réel de candidatures. Elle
# dérive désormais du vocabulaire partagé, dans l'ordre du parcours.
APPLICATION_STATUSES = application_status.ALL


class AnalyticsService:

    async def recruitment_summary(self, db: AsyncSession) -> dict:
        total_jobs = await db.scalar(select(func.count(JobOffer.id))) or 0
        active_jobs = await db.scalar(
            select(func.count(JobOffer.id)).where(JobOffer.is_active.is_(True))
        ) or 0
        total_apps = await db.scalar(select(func.count(Application.id))) or 0

        # Applications grouped by status
        status_rows = (
            await db.execute(
                select(Application.status, func.count(Application.id)).group_by(Application.status)
            )
        ).all()
        by_status = {s: 0 for s in APPLICATION_STATUSES}
        for s, c in status_rows:
            by_status[s] = c

        accepted = by_status.get("ACCEPTED", 0)
        acceptance_rate = round((accepted / total_apps) * 100, 1) if total_apps else 0.0

        avg_score = await db.scalar(select(func.avg(CandidateScore.total_score)))
        avg_score = round(float(avg_score), 1) if avg_score is not None else None

        # Top jobs by number of applications
        top_rows = (
            await db.execute(
                select(JobOffer.id, JobOffer.title, func.count(Application.id).label("cnt"))
                .outerjoin(Application, Application.job_offer_id == JobOffer.id)
                .group_by(JobOffer.id, JobOffer.title)
                .order_by(func.count(Application.id).desc())
                .limit(5)
            )
        ).all()
        top_jobs = [
            {"job_offer_id": jid, "title": title, "application_count": cnt}
            for jid, title, cnt in top_rows
        ]

        return {
            "total_jobs": total_jobs,
            "active_jobs": active_jobs,
            "total_applications": total_apps,
            "applications_by_status": by_status,
            "acceptance_rate": acceptance_rate,
            "average_score": avg_score,
            "top_jobs": top_jobs,
            "generated_at": datetime.now(timezone.utc),
        }


    async def candidate_analytics(self, db: AsyncSession) -> dict:
        """
        Distributions computed from analysed CVs + scores:
          - by years of experience (buckets)
          - by AI score band
          - by education level
          - top extracted skills
        """
        # ── Experience buckets ──
        exp_rows = (await db.execute(
            select(CVAnalysis.extracted_experience_years)
            .where(CVAnalysis.extracted_experience_years.isnot(None))
        )).scalars().all()
        exp_buckets = {"0-2 ans": 0, "2-5 ans": 0, "5-10 ans": 0, "10+ ans": 0}
        for y in exp_rows:
            y = float(y)
            if y < 2:    exp_buckets["0-2 ans"] += 1
            elif y < 5:  exp_buckets["2-5 ans"] += 1
            elif y < 10: exp_buckets["5-10 ans"] += 1
            else:        exp_buckets["10+ ans"] += 1

        # ── AI score bands ──
        score_rows = (await db.execute(select(CandidateScore.total_score))).scalars().all()
        score_bands = {"Excellent (≥85)": 0, "Bon (65-84)": 0, "Moyen (50-64)": 0, "Faible (<50)": 0}
        for s in score_rows:
            s = float(s)
            if s >= 85:   score_bands["Excellent (≥85)"] += 1
            elif s >= 65: score_bands["Bon (65-84)"] += 1
            elif s >= 50: score_bands["Moyen (50-64)"] += 1
            else:         score_bands["Faible (<50)"] += 1

        # ── Education levels ──
        edu_rows = (await db.execute(
            select(CVAnalysis.extracted_education_level)
            .where(CVAnalysis.extracted_education_level.isnot(None))
        )).scalars().all()
        edu_labels = {"PHD": "Doctorat", "MASTER": "Master", "INGENIEUR": "Ingénieur",
                      "BACHELOR": "Licence", "HIGH_SCHOOL": "Bac", "NONE": "Non précisé"}
        edu_counter: Counter = Counter()
        for e in edu_rows:
            edu_counter[edu_labels.get((e or "").upper(), e or "Non précisé")] += 1
        education = [{"label": k, "count": v} for k, v in edu_counter.most_common()]

        # ── Top extracted skills ──
        skill_rows = (await db.execute(select(CVAnalysis.extracted_skills))).scalars().all()
        skill_counter: Counter = Counter()
        for arr in skill_rows:
            for sk in (arr or []):
                skill_counter[sk] += 1
        top_skills = [{"label": k, "count": v} for k, v in skill_counter.most_common(8)]

        return {
            "experience_buckets": [{"label": k, "count": v} for k, v in exp_buckets.items()],
            "score_bands": [{"label": k, "count": v} for k, v in score_bands.items()],
            "education": education,
            "top_skills": top_skills,
            "analyzed_cvs": len(exp_rows),
            "scored_candidates": len(score_rows),
            "generated_at": datetime.now(timezone.utc),
        }


    async def applications_timeline(self, db: AsyncSession, days: int = 14) -> dict:
        """Daily application counts over the last `days` days (zero-filled)."""
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=days - 1)
        start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)

        rows = (await db.execute(
            select(func.date(Application.created_at), func.count(Application.id))
            .where(Application.created_at >= start_dt)
            .group_by(func.date(Application.created_at))
        )).all()
        counts = {str(d): c for d, c in rows}

        series = []
        for i in range(days):
            day = start + timedelta(days=i)
            key = day.isoformat()
            series.append({
                "date": key,
                "label": day.strftime("%d/%m"),
                "count": counts.get(key, 0),
            })
        return {"series": series, "total": sum(s["count"] for s in series)}


analytics_service = AnalyticsService()
