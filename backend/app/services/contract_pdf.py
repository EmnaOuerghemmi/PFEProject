"""
Génération PDF du contrat de travail PIQBIT + certificat de signature
électronique — reportlab, 100 % hors-ligne.

Le texte suit, article par article, le modèle de contrat de travail fourni par
les RH (CDI de droit tunisien, articles 1 à 17), avec PIQBIT comme employeur.
Seules les données variables sont injectées : identité du salarié (civilité,
naissance, CIN, adresse), poste, date d'entrée, période d'essai, salaire,
horaire hebdomadaire.

Les photos du modèle ne comportaient pas la page entre l'article 10-4 et
l'article 13 : la liste du 10-4 et les articles 11 (Confidentialité) et 12
(Propriété intellectuelle) ont donc été rédigés ici, dans l'esprit du reste du
contrat. À remplacer par le texte exact dès que cette page est disponible.

L'en-tête société est configurable (`COMPANY_*` dans les settings).
"""
import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.core.config import settings

INK = colors.HexColor("#1F2D2D")
MUTED = colors.HexColor("#788888")
BRAND = colors.HexColor("#0E6E70")       # teal PIQBIT (texte de l'en-tête)
BRAND_LINE = colors.HexColor("#2E8BC0")  # filet bleu en tête de page
GREEN = colors.HexColor("#3DA76F")
LINE = colors.HexColor("#D8CFBB")
SURFACE = colors.HexColor("#FBF8F1")

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "piqbit_logo.png"

TYPE_TITLES = {
    "CDI": "CONTRAT DE TRAVAIL À DURÉE INDÉTERMINÉE",
    "CDD": "CONTRAT DE TRAVAIL À DURÉE DÉTERMINÉE",
    "STAGE": "CONVENTION DE STAGE",
    "ALTERNANCE": "CONTRAT D'ALTERNANCE",
}

#: Jours fériés chômés et payés, tels qu'arrêtés par le modèle de contrat.
FERIES = [
    ("Jour de l'an", "1 janvier"), ("Pâques", "2 avril"), ("Fête du travail", "1 mai"),
    ("8 Mai 1945", "8 mai"), ("L'Ascension", "10 mai"), ("Pentecôte", "21 mai"),
    ("Fête Nationale", "14 juillet"), ("Assomption", "15 août"),
    ("La Toussaint", "1 novembre"), ("Armistice", "11 novembre"), ("Noël", "25 décembre"),
]

_MOIS_EN_LETTRES = {
    0: "zéro", 1: "un", 2: "deux", 3: "trois", 4: "quatre", 5: "cinq", 6: "six",
    7: "sept", 8: "huit", 9: "neuf", 10: "dix", 11: "onze", 12: "douze",
}


def _v(x):
    return x.value if hasattr(x, "value") else str(x)


def _fmt_date(dt, default="__/__/____"):
    return dt.strftime("%d/%m/%Y") if dt else default


def _fmt_money(amount, currency="TND"):
    return f"{amount:,.0f} {currency}".replace(",", " ")


def _accords(civilite):
    """
    Accords du texte selon la civilité. Sans civilité saisie, le contrat garde
    la forme épicène « né(e) » plutôt que de deviner.
    """
    if civilite == "Mme":
        return {"civ": "Mme", "ne": "née", "denomme": "Dénommée", "employe": "L'employée"}
    if civilite == "M.":
        return {"civ": "M.", "ne": "né", "denomme": "Dénommé", "employe": "L'employé"}
    return {"civ": "M./Mme", "ne": "né(e)", "denomme": "Dénommé(e)", "employe": "L'employé(e)"}


def _styles():
    base = getSampleStyleSheet()
    return {
        "doctitle": ParagraphStyle("dt", parent=base["Title"], textColor=INK, fontSize=14,
                                   fontName="Helvetica-Bold", alignment=1, spaceAfter=6 * mm,
                                   leading=18),
        "section": ParagraphStyle("se", parent=base["Normal"], textColor=INK, fontSize=10.5,
                                  fontName="Helvetica-Bold", spaceBefore=2 * mm, spaceAfter=2 * mm),
        "right": ParagraphStyle("r", parent=base["Normal"], textColor=INK, fontSize=10,
                                alignment=2, leading=14),
        "center": ParagraphStyle("c", parent=base["Normal"], textColor=INK, fontSize=10,
                                 alignment=1, leading=14),
        "art": ParagraphStyle("a", parent=base["Normal"], textColor=INK, fontSize=10.5,
                              fontName="Helvetica-Bold", spaceBefore=4 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("b", parent=base["Normal"], textColor=INK, fontSize=9.8,
                               leading=14.5, alignment=4, spaceAfter=1.8 * mm),
        "li": ParagraphStyle("li", parent=base["Normal"], textColor=INK, fontSize=9.8,
                             leading=14, alignment=4, leftIndent=9 * mm, bulletIndent=4 * mm,
                             spaceAfter=1 * mm),
        "small": ParagraphStyle("sm", parent=base["Normal"], textColor=MUTED, fontSize=8.5, leading=12),
        "nb": ParagraphStyle("nb", parent=base["Normal"], textColor=INK, fontSize=8.5, leading=12,
                             fontName="Helvetica-Oblique"),
        "cert": ParagraphStyle("ce", parent=base["Title"], textColor=GREEN, fontSize=15, spaceAfter=1 * mm),
    }


def _decode_signature(data_uri):
    try:
        if "," in data_uri:
            data_uri = data_uri.split(",", 1)[1]
        return BytesIO(base64.b64decode(data_uri))
    except Exception:
        return None


# ── En-tête et pied de page ───────────────────────────────────────────────────

def _numbered_canvas(brand: str):
    """
    Canevas qui connaît le nombre total de pages : le pied « Page x / y » et la
    mention « Paraphe » (le modèle demande de parapher chaque page) ne peuvent
    s'écrire qu'une fois le document entièrement mis en page.
    """

    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for etat in self._pages:
                self.__dict__.update(etat)
                self._decor(total)
                super().showPage()
            super().save()

        def _decor(self, total: int) -> None:
            largeur, hauteur = A4
            # Filet bleu en tête de page, puis logo et nom — comme le modèle.
            self.setStrokeColor(BRAND_LINE)
            self.setLineWidth(1.2)
            self.line(20 * mm, hauteur - 10 * mm, largeur - 20 * mm, hauteur - 10 * mm)
            x = 20 * mm
            if LOGO_PATH.exists():
                try:
                    self.drawImage(str(LOGO_PATH), x, hauteur - 24 * mm, width=11 * mm,
                                   height=11 * mm, mask="auto", preserveAspectRatio=True)
                    x += 13.5 * mm
                except Exception:
                    pass
            self.setFillColor(BRAND)
            self.setFont("Helvetica-Bold", 17)
            self.drawString(x, hauteur - 20.5 * mm, brand.upper())
            # Pied : paraphe à gauche, numérotation à droite.
            self.setFillColor(MUTED)
            self.setFont("Helvetica", 8)
            self.drawString(20 * mm, 9 * mm, "Paraphe : ____________")
            self.drawRightString(largeur - 20 * mm, 9 * mm, f"Page {self._pageNumber} / {total}")

    return NumberedCanvas


# ── Contrat ───────────────────────────────────────────────────────────────────

def render_contract_pdf(*, contract, candidate_name, candidate_email,
                        job_title, company_name=None):
    st = _styles()
    company = company_name or settings.COMPANY_NAME
    manager = settings.COMPANY_MANAGER
    nationality = getattr(settings, "COMPANY_MANAGER_NATIONALITY", "")
    manager_id = getattr(settings, "COMPANY_MANAGER_ID_DOC", "")
    tax_id = settings.COMPANY_TAX_ID
    address = settings.COMPANY_ADDRESS
    city = settings.COMPANY_CITY

    ctype = _v(contract.contract_type)
    status = _v(contract.status)
    acc = _accords(getattr(contract, "employee_civility", None))
    birth = _fmt_date(getattr(contract, "employee_birth_date", None))
    cin = getattr(contract, "employee_cin", None) or "________"
    cin_issue = _fmt_date(getattr(contract, "employee_cin_issue_date", None))
    emp_addr = getattr(contract, "employee_address", None) or "________"
    fonction = contract.position or job_title
    start = _fmt_date(contract.start_date)
    salaire = _fmt_money(contract.salary, contract.currency)
    essai = contract.trial_period_months or 0
    essai_txt = f"{_MOIS_EN_LETTRES.get(essai, str(essai))} mois"
    date_acte = contract.signed_at or datetime.now()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=30 * mm, bottomMargin=18 * mm,
        title=f"Contrat de travail — {candidate_name}", author=company,
    )
    S = []

    def para(texte, style="body"):
        S.append(Paragraph(texte, st[style]))

    def puces(items):
        for item in items:
            S.append(Paragraph(item, st["li"], bulletText="•"))

    def art(titre):
        S.append(Paragraph(f"<u>{titre}</u>", st["art"]))

    # ── Titre et soussignés ───────────────────────────────────────────────────
    S.append(Paragraph(f"<u>{TYPE_TITLES.get(ctype, TYPE_TITLES['CDI'])}</u>", st["doctitle"]))
    S.append(Paragraph("<u>ENTRE LES SOUSSIGNÉS</u>", st["section"]))

    matricule = f", au matricule fiscal n° {tax_id}" if tax_id else ""
    gerant = f"son gérant <b>M. {manager}</b>"
    if nationality:
        gerant += f" de nationalité {nationality}"
    if manager_id:
        gerant += f" titulaire de {manager_id}"
    para(f"La société <b>{company}</b>{matricule}, élisant domicile à {address}, "
         f"représentée par {gerant}, ci-après désignée.")
    para("Dénommée ci-après « <b>L'employeur</b> »", "right")
    para("<b><u>D'UNE PART</u></b>", "right")
    para("Et")
    para(f"<b>{acc['civ']} {candidate_name}</b>, {acc['ne']} le <b>{birth}</b>, titulaire de la "
         f"CIN n° <b>{cin}</b> délivrée le <b>{cin_issue}</b> et demeurant à <b>{emp_addr}</b>.")
    para(f"{acc['denomme']} ci-après « <b>{acc['employe']}</b> »", "right")
    para("<b><u>D'AUTRE PART</u></b>", "right")
    para("Il a été arrêté et convenu ce qui suit :")

    # ── Article 1 ─────────────────────────────────────────────────────────────
    art("Article 1 : Principes généraux :")
    para("Les parties signataires du présent contrat, conscientes :")
    puces([
        "De l'importance de leur relation professionnelle basée sur la primauté d'un service de "
        "qualité afin d'assurer la continuité d'exploitation de la société.",
        "De l'importance de la confidentialité des données professionnelles ainsi que des moyens utilisés.",
    ])
    para("Les parties contractantes dans le présent contrat s'engagent à promouvoir les intérêts "
         "de l'entreprise et à œuvrer pour son développement. Elles s'engagent à le faire dans le "
         "cadre du respect :")
    puces([
        "Des dispositions légales et conventionnelles applicables sur le territoire tunisien,",
        "De la bonne foi contractuelle,",
        "De l'éthique professionnelle.",
    ])

    # ── Article 2 ─────────────────────────────────────────────────────────────
    art("Article 2 : Déclarations sur l'Honneur :")
    para("L'employé(e) déclare sur l'honneur :")
    puces([
        "Être libre de tout engagement légalement incompatible avec la présente. Toute fausse "
        "déclaration sur ce point pouvant entraîner la résiliation immédiate et de plein droit du "
        "présent contrat si bon semble à l'employeur.",
        "De consacrer tous ses soins et diligences professionnels, pour le compte de l'employeur.",
    ])

    # ── Article 3 ─────────────────────────────────────────────────────────────
    art("Article 3 : Fonctions :")
    para(f"L'employé(e) est engagé(e) par l'employeur pour exercer les fonctions de <b>{fonction}</b> "
         f"sur tout le territoire tunisien, à compter du <b>{start}</b>.")

    # ── Article 4 ─────────────────────────────────────────────────────────────
    art("Article 4 : Durée du Contrat :")
    if ctype == "CDI":
        duree = "Le présent contrat est conclu pour <b>une période indéterminée</b>"
    else:
        fin = _fmt_date(contract.end_date)
        duree = (f"Le présent contrat est conclu pour <b>une période déterminée</b> prenant fin "
                 f"le <b>{fin}</b>")
    if essai > 0:
        para(f"{duree} assortie d'une période d'essai de {essai_txt} renouvelable une seule fois, "
             "au cours de laquelle il pourra prendre fin à la volonté de l'une ou l'autre des "
             "parties à tout moment sans indemnité en respectant une période de préavis d'un mois. "
             "La période d'essai s'entend de travail effectif, toute suspension de l'exécution du "
             "contrat, quel qu'en soit le motif entraînera une prolongation de la période d'essai "
             "d'une période équivalente à celle de la suspension.")
    else:
        para(f"{duree}, sans période d'essai.")

    # ── Article 5 ─────────────────────────────────────────────────────────────
    art("Article 5 : Obligations professionnelles :")
    para("L'employé(e) s'engage à :")
    puces([
        "Consacrer tout son temps pendant l'horaire de travail au service où il/elle est affecté(e).",
        "Respecter scrupuleusement le règlement et la procédure internes de la société ainsi que "
        "les notes de service.",
        "Se conformer strictement aux instructions et directives qui lui seront données par ses "
        "chefs hiérarchiques.",
        "Observer une discrétion absolue du secret professionnel et ne faire aucune communication "
        "écrite ou verbale à des tiers sur les questions se rattachant aux travaux, faits et "
        "informations pour lesquels il/elle est engagé(e) ou dont il/elle aura connaissance dans "
        "l'exercice de ses fonctions sans limitation dans le temps et même après la fin, pour "
        "quelque raison que ce soit, du présent contrat.",
        "Assurer ses fonctions et n'être redevable qu'à l'employeur pour tous manquements ou "
        "négligence professionnelle.",
        "Adopter une conduite professionnelle exemplaire et s'interdire tout acte ou comportement "
        "pouvant porter atteinte aux intérêts légitimes de l'employeur.",
        "Communiquer à l'employeur, à sa prise de fonction, tous les documents nécessaires à la "
        "constitution de son dossier administratif.",
        "Informer l'employeur de toutes modifications de sa situation postérieurement à sa prise "
        "de fonction.",
    ])

    # ── Article 6 ─────────────────────────────────────────────────────────────
    art("Article 6 : Rémunération :")
    para(f"L'employé(e) percevra un salaire <b>mensuel net de {salaire}</b>, à noter que toute "
         "modification ultérieure fera l'objet d'un avenant au contrat. Cette rémunération "
         "comprend toutes les primes prévues par le droit du travail.")

    # ── Article 7 ─────────────────────────────────────────────────────────────
    art("Article 7 : Horaire de travail :")
    para(f"Il est fait application du régime de travail de <b>{contract.weekly_hours} heures</b> "
         "de travail par semaine.")
    para("Les jours fériés chômés et payés sont les suivants :")
    ftab = Table([[a, b] for a, b in FERIES], colWidths=[48 * mm, 34 * mm], hAlign="CENTER")
    ftab.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BOX", (0, 0), (-1, -1), 0.6, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    S += [ftab, Spacer(1, 2.5 * mm)]
    para("Vu ce qui précède, le salarié renonce donc aux jours fériés (selon le droit de travail "
         "tunisien) et déclare par le présent acte renoncer à ses droits pour lesdits jours qui "
         "seront remplacés par les jours ci-dessus mentionnés.")
    para("La société poursuivra son exploitation durant les deux mois d'été en double séance et il "
         "n'y aura d'horaire spécifique que pendant le mois de ramadan, cet horaire sera annoncé "
         "ultérieurement par une note interne.")
    para("L'employé(e) dès à présent accepte l'horaire de travail affiché au sein de la société.")

    # ── Article 8 ─────────────────────────────────────────────────────────────
    art("Article 8 : Congés")
    para("Le régime de congés payés est de <b>22 jours ouvrés</b>. Le choix des périodes de congé "
         "est déterminé par accord entre les parties compte tenu de la nécessité de service.")

    # ── Article 9 ─────────────────────────────────────────────────────────────
    art("Article 9 : Biens de l'entreprise :")
    para("L'employé(e) est tenu(e) de garder les biens, matériels, voitures, documents, dossiers et "
         "tout autre moyen revenant à l'entreprise, en sa possession ou sous son contrôle, en "
         "parfait et bon état.")
    para("Il/Elle devra prendre les dispositions nécessaires vis-à-vis du personnel de l'entreprise "
         "pour garder intacts ces biens cités ci-dessus.")
    para("Il/Elle devra à ce titre informer la gérance de tout manquement à cette règle.")

    # ── Article 10 ────────────────────────────────────────────────────────────
    art("Article 10 : Résiliation du Contrat :")
    para("Le présent contrat sera résilié de plein droit pour l'une quelconque des raisons suivantes :")
    para("<b>10-1</b> D'un commun accord des deux parties à l'amiable. Dans ce cas, la partie "
         "demanderesse devra informer l'autre partie de la cessation définitive de la relation "
         "contractuelle par un préavis de trois (03) mois si la partie demanderesse est l'employé(e) "
         "et de trois (03) jours si la partie demanderesse est l'employeur.")
    para("<b>10-2</b> Démission de l'employé(e), notifiée à l'employeur <b>3 mois</b> à l'avance.")
    para("<b>10-3</b> Faute grave, insuffisance professionnelle, manque de discrétion ou "
         "indiscipline manifestés par l'employé(e), ainsi que son refus d'appliquer les "
         "instructions reçues de l'employeur ou de sa hiérarchie directe ou d'accomplir le travail "
         "pour lequel il/elle est engagé(e). Tout licenciement effectué pour l'une de ces causes "
         "n'est pas considéré abusif et l'employé(e) licencié(e) n'aura pas droit à la "
         "rémunération du mois de licenciement, ni à l'indemnité de licenciement.")
    para("<b>10-4</b> L'employeur a le droit de licencier tout employé qui, durant la période de "
         "son travail au sein de la société :")
    # Liste rédigée : la page correspondante manquait aux photos du modèle.
    puces([
        "aura divulgué à des tiers des informations confidentielles relatives à la société, à ses "
        "clients ou à ses projets ;",
        "aura exercé, directement ou indirectement, une activité concurrente de celle de la société ;",
        "se sera absenté(e) de manière répétée sans autorisation ni justification ;",
        "aura porté atteinte aux biens de l'entreprise ou à l'image de la société.",
    ])

    # ── Articles 11 et 12 (rédigés : page manquante du modèle) ───────────────
    art("Article 11 : Confidentialité :")
    para("L'employé(e) s'engage à ne divulguer à quiconque, pendant la durée du présent contrat et "
         "après sa cessation, les informations, documents, données techniques, commerciales ou "
         "financières dont il/elle aura eu connaissance dans l'exercice de ses fonctions. À la fin "
         "du contrat, il/elle restituera à l'employeur l'ensemble des documents, fichiers et "
         "supports appartenant à la société.")
    art("Article 12 : Propriété intellectuelle :")
    para("Les travaux, développements, logiciels, documents et créations réalisés par l'employé(e) "
         "dans l'exercice de ses fonctions ou avec les moyens de la société sont la propriété "
         "exclusive de la société, qui peut les exploiter librement, sans contrepartie autre que "
         "la rémunération prévue au présent contrat.")

    # ── Articles 13 à 17 ──────────────────────────────────────────────────────
    art("Article 13 : Obligation de fidélité")
    para("Pendant la durée du présent contrat, l'employé(e) prendra l'engagement de ne participer, "
         "sous quelque forme que ce soit, à aucune activité susceptible de concurrencer en tout ou "
         "partie, directement ou indirectement celle de la société qui l'emploie.")

    art("Article 14 : Modifications portées au contrat :")
    para("Au cas où l'un des articles du présent contrat serait annulé, modifié, remplacé, d'un "
         "commun accord entre les deux parties signataires du présent contrat, une décision écrite "
         "sera établie par l'employeur, accusée réception par l'employé(e) et annexée au présent "
         "contrat.")
    para("Toute annulation, modification ou remplacement d'un des articles ne concernera pas le "
         "reste des articles du contrat qui restent applicables.")

    art("Article 15 : Élection de Domicile :")
    para("Les deux signataires élisent domicile chacun à son adresse ci-dessus fixée.")

    art("Article 16 : Litige :")
    para("En cas de contestation ou litiges quant à l'interprétation et l'exécution du présent "
         f"contrat, les tribunaux de {city} seront compétents.")

    art("Article 17 : Non-concurrence :")
    para("Compte tenu de la nature des fonctions exercées au sein de la société, le Salarié "
         "s'engage, postérieurement à la rupture de son contrat de travail quelle qu'en soit la "
         "cause, à ne pas exercer directement ou indirectement de fonctions similaires ou "
         "concurrentes de celles exercées au sein de la société.")
    para("Il s'engage donc à ne pas travailler en qualité de salarié ou de non salarié pour une "
         "entreprise concurrente et à ne pas créer, directement ou indirectement par personne "
         "interposée, d'entreprise ayant des activités concurrentes ou similaires à celles de la "
         "société.")
    para("Cet engagement est limité au territoire tunisien, à la clientèle et aux prospects de la "
         "société et à une durée de deux ans.")
    para("Le terme de « client », tel que visé au présent article, est défini comme toute personne "
         "physique et morale de droit public ou privé avec laquelle le Salarié aura été en relation "
         "et qui, au cours des douze derniers mois précédant la rupture du présent contrat, aura eu "
         "recours aux services de la société.")
    para("Le terme de « prospect », tel que visé au présent article, est défini comme toute "
         "personne physique ou morale, de droit privé ou public avec laquelle le Salarié aura été "
         "en relation et qui au cours des six derniers mois précédant la rupture du présent contrat "
         "aura été en contact avec la société dans le cadre d'une présentation formelle auprès des "
         "dirigeants ou d'une proposition écrite à une telle personne physique ou morale de droit "
         "public ou privé.")
    para("Il est expressément convenu que chaque violation par le Salarié de l'une quelconque de "
         "ses obligations prévues à l'article ci-dessus donnera lieu à des versements de dommages "
         "et intérêts dont le montant sera déterminé par les tribunaux compétents.")

    # Dispositions propres à ce contrat, saisies par le RH (hors modèle).
    if contract.notes:
        art("Dispositions particulières :")
        para(contract.notes)

    # ── Clôture et signatures ─────────────────────────────────────────────────
    # Gardées ensemble sur la dernière page, comme dans le modèle : c'est elle
    # que le salarié signe, précédée de « lu et approuvé ».
    cloture = [
        Spacer(1, 3 * mm),
        Paragraph("Le présent contrat entre en vigueur dès sa signature par les deux parties.", st["body"]),
        Paragraph("Il sera rédigé en deux (02) copies, dont un (01) exemplaire pour l'employeur et "
                  f"un (01) exemplaire pour {acc['employe'].lower()}.", st["body"]),
    ]

    sig = Paragraph("<i>Signature en attente</i>", ParagraphStyle("sigw", parent=st["small"], alignment=1))
    if status in ("SIGNED", "ACTIVE") and contract.signature_image:
        img = _decode_signature(contract.signature_image)
        if img:
            try:
                sig = Image(img, width=46 * mm, height=20 * mm, kind="proportional")
            except Exception:
                sig = Paragraph(f"<b>{contract.signer_name}</b> — signé", st["small"])

    signataire = f"<b>{contract.signer_name or candidate_name}</b>"
    if contract.signed_at:
        signataire += ("<br/>« Lu et approuvé »<br/>Signé le "
                       f"{contract.signed_at.strftime('%d/%m/%Y à %H:%M UTC')}")

    sigtab = Table([
        [Paragraph("<b>L'employeur</b><br/>Le Gérant", st["center"]),
         Paragraph(f"<b>{acc['employe']}</b>", st["center"])],
        [Paragraph(f"{manager}<br/>{company}", st["center"]), sig],
        ["", Paragraph(signataire, st["center"])],
    ], colWidths=[85 * mm, 85 * mm])
    sigtab.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 1), (-1, 1), 8),
    ]))

    S.append(KeepTogether(cloture + [
        Spacer(1, 4 * mm),
        Paragraph(f"<b><i>{city}, le {_fmt_date(date_acte)}</i></b>", st["right"]),
        Spacer(1, 3 * mm),
        Paragraph("<b>NB :</b> Vous voudrez bien nous confirmer votre accord en apposant votre "
                  "signature précédée de la mention manuscrite « lu et approuvé » sur la dernière "
                  "page, les pages précédentes étant également à parapher par vos soins.", st["nb"]),
        Spacer(1, 5 * mm),
        sigtab,
    ]))

    # ── Certificat de signature électronique ──────────────────────────────────
    if status in ("SIGNED", "ACTIVE") and contract.certificate_id:
        S.append(PageBreak())
        S += _certificate(st, contract, candidate_name, candidate_email, company)

    doc.build(S, canvasmaker=_numbered_canvas(company))
    return buf.getvalue()


def _certificate(st, contract, candidate_name, candidate_email, company):
    # Valeurs en Paragraph : une cellule de texte brut ne retourne jamais à la
    # ligne et déborde du tableau (navigateur, empreinte SHA-256 de 64 caractères).
    from xml.sax.saxutils import escape
    st_val = ParagraphStyle("cert_val", parent=st["small"], fontSize=8.5, leading=11, textColor=INK)
    st_mono = ParagraphStyle("cert_mono", parent=st_val, fontName="Courier", fontSize=8, leading=10.5,
                             splitLongWords=1)
    st_lib = ParagraphStyle("cert_lib", parent=st["small"], fontSize=8.5, leading=11, textColor=MUTED)
    cellule = lambda texte, style=st_val: Paragraph(escape(str(texte)), style)

    audit = [
        ["Document", f"Contrat de travail — réf. {str(contract.id)[:8].upper()}"],
        ["Signataire", contract.signer_name or candidate_name],
        ["Email", candidate_email],
        ["Date de signature", contract.signed_at.strftime("%d/%m/%Y à %H:%M:%S UTC") if contract.signed_at else "—"],
        ["Adresse IP", contract.signer_ip or "—"],
        ["Navigateur", contract.signer_user_agent or "—"],
        ["Empreinte du document (SHA-256)", contract.document_hash or "—"],
        ["Identifiant de certificat", contract.certificate_id or "—"],
    ]
    mono = {"Empreinte du document (SHA-256)", "Identifiant de certificat"}
    audit = [[Paragraph(escape(lib), st_lib), cellule(val, st_mono if lib in mono else st_val)]
             for lib, val in audit]
    t = Table(audit, colWidths=[62 * mm, 98 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), SURFACE), ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), INK), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [
        Paragraph("Certificat de signature électronique", st["cert"]),
        Paragraph(
            "Ce certificat atteste que le document ci-avant a été signé électroniquement "
            "selon un procédé de signature simple (consentement explicite, horodatage et "
            "scellement par empreinte cryptographique).", st["small"]),
        Spacer(1, 4 * mm), t, Spacer(1, 4 * mm),
        Paragraph(
            "L'intégrité du document est garantie par l'empreinte SHA-256 ci-dessus : toute "
            f"modification des termes invaliderait cette empreinte. Émis par {company}.", st["small"]),
    ]
