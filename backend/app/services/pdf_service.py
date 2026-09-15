"""
Génération PDF des rapports de recrutement (reportlab, 100 % hors-ligne).
Rend un `ReportSnapshot` (KPIs + contenu rédigé par l'agent) en PDF A4.
"""
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.models import application_status

# Palette alignée sur le design system backoffice (forest-teal / gold).
INK = colors.HexColor("#1F2D2D")
MUTED = colors.HexColor("#788888")
GOLD = colors.HexColor("#D9A23F")
LINE = colors.HexColor("#ECE3CF")
SURFACE = colors.HexColor("#FBF8F1")

# Réutilise la table du service de notifications plutôt que d'en tenir une
# seconde : les deux divergeaient déjà.
STATUS_LABELS = application_status.LABELS_FR


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], textColor=INK,
                                fontSize=20, spaceAfter=2 * mm),
        "meta": ParagraphStyle("meta", parent=base["Normal"], textColor=MUTED, fontSize=9),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=GOLD,
                             fontSize=13, spaceBefore=6 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("body", parent=base["Normal"], textColor=INK,
                               fontSize=10.5, leading=15),
        "bullet": ParagraphStyle("bullet", parent=base["Normal"], textColor=INK,
                                 fontSize=10.5, leading=15, leftIndent=6 * mm,
                                 bulletIndent=2 * mm),
    }


def _kpi_table(data: dict) -> Table:
    rows = [
        ["Offres totales", str(data.get("total_jobs", 0)),
         "Offres actives", str(data.get("active_jobs", 0))],
        ["Candidatures", str(data.get("total_applications", 0)),
         "Taux d'acceptation", f"{data.get('acceptance_rate', 0)}%"],
        ["Score IA moyen",
         str(data.get("average_score")) if data.get("average_score") is not None else "N/A",
         "", ""],
    ]
    t = Table(rows, colWidths=[45 * mm, 30 * mm, 45 * mm, 30 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _status_table(by_status: dict) -> Table:
    rows = [["Statut", "Candidatures"]]
    for key, label in STATUS_LABELS.items():
        rows.append([label, str(by_status.get(key, 0))])
    t = Table(rows, colWidths=[75 * mm, 40 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GOLD),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _top_jobs_table(top_jobs: list) -> Table:
    rows = [["Offre", "Candidatures"]]
    for j in top_jobs[:5]:
        rows.append([str(j.get("title", "—")), str(j.get("application_count", 0))])
    t = Table(rows, colWidths=[115 * mm, 35 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GOLD),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def render_report_pdf(*, title: str, data: dict, created_at: datetime | None = None) -> bytes:
    """
    Rend un rapport (snapshot) en PDF. `data` est le JSON du snapshot :
    KPIs du recruitment_summary + clé optionnelle `report` (contenu de l'agent).
    """
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=title, author="PIQBIT",
    )

    story = [
        Paragraph("PIQBIT — Rapport de recrutement", styles["title"]),
        Paragraph(
            f"{title} · généré le "
            f"{(created_at or datetime.now()).strftime('%d/%m/%Y %H:%M')}",
            styles["meta"],
        ),
        Spacer(1, 6 * mm),
        Paragraph("Indicateurs clés", styles["h2"]),
        _kpi_table(data),
    ]

    report = data.get("report") or {}
    if report.get("narrative"):
        story += [
            Paragraph("Synthèse", styles["h2"]),
            Paragraph(report["narrative"], styles["body"]),
        ]
    if report.get("highlights"):
        story.append(Paragraph("Points clés", styles["h2"]))
        for h in report["highlights"]:
            story.append(Paragraph(str(h), styles["bullet"], bulletText="•"))
    if report.get("recommendations"):
        story.append(Paragraph("Recommandations", styles["h2"]))
        for r in report["recommendations"]:
            story.append(Paragraph(str(r), styles["bullet"], bulletText="→"))

    if data.get("applications_by_status"):
        story += [
            Paragraph("Candidatures par statut", styles["h2"]),
            _status_table(data["applications_by_status"]),
        ]
    if data.get("top_jobs"):
        story += [
            Paragraph("Offres les plus attractives", styles["h2"]),
            _top_jobs_table(data["top_jobs"]),
        ]

    doc.build(story)
    return buffer.getvalue()
