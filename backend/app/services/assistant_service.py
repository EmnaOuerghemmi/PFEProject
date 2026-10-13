"""
Assistant PIQBIT : répondre à toute question, à partir des données réelles.

L'ancien assistant renvoyait l'entrée de FAQ la plus proche, quelle qu'elle
soit : « bonjour » obtenait le délai de réponse aux candidatures, à 20 % de
confiance. Celui-ci traite chaque message en trois étages, du plus sûr au plus
large, et dit franchement quand il ne sait pas :

1. **La conversation** — salutations, remerciements, « que sais-tu faire ? ».
2. **Les données** — un catalogue FERMÉ d'outils de lecture : offres,
   candidatures, classement, entretiens, tests, contrats, employés, budget,
   comptes. Chaque outil exige le même droit RBAC que la page correspondante,
   et applique les mêmes restrictions (un recruteur ne voit que ses
   entretiens). Aucune requête n'est fabriquée à partir du message : il
   choisit un outil et ses paramètres (une offre, un candidat, une période),
   jamais du SQL.
3. **La base de connaissances** (moteur CAG existant) — seulement si la
   réponse est vraiment pertinente.

Sinon : « je n'ai pas compris », avec des questions qu'il sait traiter.

Le choix de l'outil se fait par mots-clés et par reconnaissance des offres et
des candidats cités : instantané, hors ligne, et vérifiable — aucun modèle ne
voit les données. Les messages peuvent citer des personnes : ils ne sont
jamais journalisés, seul l'outil choisi l'est.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rbac import autorise
from app.models.application_status import LABELS_FR, ApplicationStatus
from app.models.assessment import SessionStatus, TestSession
from app.models.budget import BudgetExpense, DepartmentBudget
from app.models.contract import Contract, ContractStatus
from app.models.employee import Employee
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.models.user import User, UserRole
from app.services.analytics_service import analytics_service
from app.services.cag_service import cag_service
from app.services.email_service import formater_date_heure
from app.services.hiring_decision_service import load_job_evidence, rank
from app.services.interview_service import (
    ETAPE_A_EVALUER, ETAPE_A_VENIR, ETAPE_ABSENT, ETAPE_ANNULE, ETAPE_EN_ATTENTE, ETAPE_EVALUE,
    etape_entretien, interview_service,
)

logger = logging.getLogger(__name__)

#: Une réponse de la base de connaissances n'est donnée qu'au-dessus de ce
#: seuil (en %) : en dessous, elle tomberait à côté, comme « bonjour ».
SEUIL_CONNAISSANCES = 35.0

_LIBELLES_RECOMMANDATION = {
    "HIRE": "Recruter", "INTERVIEW": "À confirmer", "HOLD": "En réserve", "REJECT": "Rejeter",
}
_LIBELLES_OFFRE = {"PUBLISHED": "Publiée", "DRAFT": "Brouillon", "CLOSED": "Fermée"}
_LIBELLES_TEST = {
    SessionStatus.ENVOYE.value: "Envoyé, pas commencé", SessionStatus.EN_COURS.value: "En cours",
    SessionStatus.TERMINE.value: "Terminé", SessionStatus.EXPIRE.value: "Terminé (temps écoulé)",
    SessionStatus.ABANDONNE.value: "Abandonné",
}
_LIBELLES_CONTRAT = {
    ContractStatus.DRAFT.value: "Brouillon", ContractStatus.SENT.value: "En attente de signature",
    ContractStatus.SIGNED.value: "Signé", ContractStatus.ACTIVE.value: "Actif",
    ContractStatus.DECLINED.value: "Refusé", ContractStatus.EXPIRED.value: "Expiré",
}
_LIBELLES_ETAPE = {
    ETAPE_A_VENIR: "À venir", ETAPE_A_EVALUER: "À évaluer", ETAPE_EVALUE: "Évalué",
    ETAPE_EN_ATTENTE: "En attente de réponse", ETAPE_ABSENT: "Candidat absent", ETAPE_ANNULE: "Annulé",
}
_LIBELLES_ROLE = {"ADMIN": "Administrateur", "RH": "RH", "RECRUTEUR": "Recruteur", "CANDIDAT": "Candidat"}

#: Mots trop courants pour reconnaître une offre ou un candidat dans un message.
_MOTS_VIDES = {
    "les", "des", "une", "pour", "sur", "dans", "avec", "par", "qui", "que", "quoi", "est", "sont",
    "mes", "nos", "vos", "son", "ses", "leur", "aux", "du", "de", "la", "le", "et", "ou", "en",
    "offre", "offres", "poste", "postes", "candidat", "candidats", "candidature", "candidatures",
    "meilleurs", "meilleur", "combien", "quels", "quelles", "quel", "quelle", "liste", "statut",
    "senior", "junior", "stage", "confirme", "h/f",
}


# ── Réponse ───────────────────────────────────────────────────────────────────

@dataclass
class Element:
    """Une ligne de résultat : un libellé, un détail, et la page où agir."""
    libelle: str
    detail: str = ""
    lien: Optional[str] = None
    parametres: dict[str, str] = field(default_factory=dict)


@dataclass
class Reponse:
    texte: str
    elements: list[Element] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    #: L'outil utilisé — renvoyé par le client au message suivant, pour les
    #: questions de relance (« et pour l'offre Data ? »).
    outil: Optional[str] = None
    offre_id: Optional[UUID] = None
    sources: list[dict] = field(default_factory=list)
    confiance: Optional[float] = None


@dataclass
class Contexte:
    """Ce que le client rappelle de l'échange précédent."""
    outil: Optional[str] = None
    offre_id: Optional[UUID] = None


@dataclass
class _Demande:
    """Le message analysé : texte normalisé, entités reconnues, contexte."""
    brut: str
    texte: str
    utilisateur: User
    offre: Optional[JobOffer]
    candidat: Optional[Candidate]
    contexte: Contexte


# ── Texte ─────────────────────────────────────────────────────────────────────

def normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation : « Entretiens à venir ? » → « entretiens a venir »."""
    sans_accents = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", sans_accents.lower())).strip()


def _a(texte: str, motif: str) -> bool:
    return re.search(motif, texte) is not None


def _mots_significatifs(texte: str) -> list[str]:
    return [m for m in normaliser(texte).split() if len(m) >= 3 and m not in _MOTS_VIDES]


def _prenom(user: User) -> str:
    """Le prénom tiré du nom complet — jamais l'identifiant de connexion (« emna_o »)."""
    return (user.full_name or "").strip().split(" ")[0]


def _bonjour(user: User) -> str:
    prenom = _prenom(user)
    return f"Bonjour {prenom}" if prenom else "Bonjour"


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role) or ""


def _peut(user: User, ressource: str, action: str = "read") -> bool:
    return bool(user.is_superuser) or autorise(_role(user), ressource, action)


def _date(dt: Optional[datetime]) -> str:
    """Date et heure à l'heure de la plateforme, comme dans les e-mails."""
    return formater_date_heure(dt) if dt else "date à définir"


# ── Conversation courante ─────────────────────────────────────────────────────

_SALUTATION = r"^(bonjour|bonsoir|salut|hello|hi|hey|coucou|salam|aslema|ahla|yo)( .{0,30})?$"
_MERCI = r"^(merci|thanks|thank you|parfait|super|top|genial|nickel|d accord|ok|okay|cool)( .{0,30})?$"
_AU_REVOIR = r"^(au revoir|bye|a plus|a bientot|bonne (journee|soiree|nuit))( .{0,30})?$"
_CA_VA = r"\b(ca va|comment vas tu|comment allez vous|tu vas bien)\b"
_AIDE = (r"^(aide|help|\?)$|\b(que (sais|peux) tu|tu (sais|peux) faire|qui es tu|"
         r"que fais tu|comment (ca marche|t utiliser)|quelles questions)\b")
_SALUTATION_EN_TETE = r"^(bonjour|bonsoir|salut|hello|hi|hey|coucou|salam|aslema|ahla)\b"
_MODE_EMPLOI = (r"^(comment|pourquoi|puis je|peut on|est ce que je peux|ou (trouver|se trouve)|"
                r"c est quoi|qu est ce qu?)\b")


def _conversation(d: _Demande, suggestions: list[str]) -> Optional[Reponse]:
    t, prenom = d.texte, _prenom(d.utilisateur)
    bonjour = _bonjour(d.utilisateur)
    if _a(t, _AIDE):
        return Reponse(
            "Je réponds à partir des données de PIQBIT, en temps réel : offres, candidatures, "
            "meilleurs candidats d'une offre, entretiens, tests techniques, candidats en réserve"
            + (", contrats, employés, budget" if _peut(d.utilisateur, "contracts") else "")
            + ". Citez une offre ou un candidat par son nom, je le retrouve. Je réponds aussi aux "
            "questions sur le fonctionnement de la plateforme. Essayez par exemple :",
            suggestions=suggestions, outil="aide")
    if _a(t, _SALUTATION):
        return Reponse(f"{bonjour} 👋 Que voulez-vous savoir ? Je consulte vos données en "
                       "direct — offres, candidats, entretiens…", suggestions=suggestions, outil="salutation")
    if _a(t, _CA_VA):
        return Reponse("Très bien, merci ! Prêt à chercher ce dont vous avez besoin.",
                       suggestions=suggestions, outil="salutation")
    if _a(t, _MERCI):
        return Reponse("Avec plaisir ! Autre chose ?", suggestions=suggestions[:3], outil="merci")
    if _a(t, _AU_REVOIR):
        return Reponse(f"À bientôt {prenom} !" if prenom else "À bientôt !", outil="au_revoir")
    return None


def _incompris(suggestions: list[str]) -> Reponse:
    return Reponse(
        "Je n'ai pas compris votre question. Je peux vous renseigner sur vos offres, vos candidats, "
        "les entretiens, les tests techniques et le fonctionnement de la plateforme. Par exemple :",
        suggestions=suggestions)


# ── Outils de données ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Outil:
    cle: str
    libelle: str
    ressource: str
    motif: str
    executer: Callable[["AssistantService", AsyncSession, _Demande], Awaitable[Reponse]]


class AssistantService:

    # ── Entrée ────────────────────────────────────────────────────────────────

    async def repondre(self, db: AsyncSession, message: str, user: User,
                       contexte: Optional[Contexte] = None) -> Reponse:
        contexte = contexte or Contexte()
        texte = normaliser(message)
        suggestions = self._suggestions_role(user)
        if not texte:
            return _incompris(suggestions)

        offre = await self._trouver_offre(db, texte)
        candidat = await self._trouver_candidat(db, texte)
        demande = _Demande(message, texte, user, offre, candidat, contexte)

        reponse: Optional[Reponse] = None
        if _a(texte, _AIDE):
            reponse = _conversation(demande, suggestions)
        # « Comment créer une offre ? » demande un mode d'emploi, pas la liste
        # des offres : la base de connaissances passe d'abord, si elle sait.
        if reponse is None and _a(texte, _MODE_EMPLOI):
            reponse = await self._connaissances(db, demande, suggestions, repli=False)
        if reponse is None:
            outil = self._choisir_outil(demande)
            if outil is not None:
                reponse = await self._executer(db, outil, demande, suggestions)
                # « Bonjour, combien d'offres ? » : on salue ET on répond.
                if _a(texte, _SALUTATION_EN_TETE):
                    reponse.texte = f"{_bonjour(user)} ! {reponse.texte}"
        if reponse is None:
            reponse = _conversation(demande, suggestions)
        if reponse is None:
            reponse = await self._connaissances(db, demande, suggestions)

        logger.info("Assistant : outil=%s", reponse.outil or "aucun")
        return reponse

    async def _executer(self, db: AsyncSession, outil: "_Outil", d: _Demande,
                        suggestions: list[str]) -> Reponse:
        user = d.utilisateur
        if not _peut(user, outil.ressource):
            return Reponse(
                f"Cette information ({outil.libelle.lower()}) n'est pas accessible avec votre "
                f"rôle ({_LIBELLES_ROLE.get(_role(user), _role(user))}).",
                suggestions=suggestions, outil=outil.cle)
        reponse = await outil.executer(self, db, d)
        reponse.outil = outil.cle
        reponse.suggestions = [s for s in reponse.suggestions if self._suggestion_permise(s, user)]
        return reponse

    # ── Choix de l'outil ──────────────────────────────────────────────────────

    def _choisir_outil(self, d: _Demande) -> Optional[_Outil]:
        """
        L'outil dont les mots-clés reviennent le plus souvent ; à égalité, le
        plus précis (ordre du catalogue). Un message qui ne cite qu'un candidat
        ou qu'une offre va à sa fiche ; une relance sans mot-clé reprend
        l'outil précédent.
        """
        scores = [(len(re.findall(o.motif, d.texte)), -i, o) for i, o in enumerate(_CATALOGUE)]
        meilleur = max(scores, key=lambda s: (s[0], s[1]))
        if meilleur[0] > 0:
            # « Où en est Sami Ben Ali ? » : le nom l'emporte sur un mot-clé générique.
            if d.candidat is not None and meilleur[2].cle in ("candidatures", "offres"):
                return _PAR_CLE["candidat"]
            return meilleur[2]
        if d.candidat is not None:
            return _PAR_CLE["candidat"]
        if d.contexte.outil in _PAR_CLE and d.offre is not None:
            return _PAR_CLE[d.contexte.outil]
        if d.offre is not None:
            return _PAR_CLE["offres"]
        return None

    async def _trouver_offre(self, db: AsyncSession, texte: str) -> Optional[JobOffer]:
        """L'offre dont le titre est cité dans le message, même partiellement."""
        mots = set(texte.split())
        meilleure, meilleur_score = None, 0.0
        for offre in (await db.execute(select(JobOffer).limit(500))).scalars():
            titre = normaliser(offre.title)
            if titre and f" {titre} " in f" {texte} ":
                return offre
            significatifs = _mots_significatifs(offre.title)
            if not significatifs:
                continue
            trouves = [m for m in significatifs
                       if m in mots or any(x.startswith(m[:5]) and len(m) >= 5 for x in mots)]
            score = len(trouves) / len(significatifs)
            if score > meilleur_score and any(len(m) >= 4 for m in trouves):
                meilleure, meilleur_score = offre, score
        return meilleure if meilleur_score >= 0.6 else None

    async def _trouver_candidat(self, db: AsyncSession, texte: str) -> Optional[Candidate]:
        """Le candidat cité par son nom complet, ou par un nom de famille sans homonyme."""
        mots = set(texte.split())
        candidats = (await db.execute(select(Candidate).limit(2000))).scalars().all()
        complets, partiels = [], []
        for c in candidats:
            parties = [p for p in normaliser(c.full_name).split() if len(p) >= 2]
            if len(parties) >= 2 and all(p in mots for p in parties):
                complets.append(c)
            elif parties and len(parties[-1]) >= 4 and parties[-1] in mots:
                partiels.append(c)
        if len(complets) == 1:
            return complets[0]
        return partiels[0] if not complets and len(partiels) == 1 else None

    # ── Outils ────────────────────────────────────────────────────────────────

    async def _resume(self, db: AsyncSession, d: _Demande) -> Reponse:
        s = await analytics_service.recruitment_summary(db)
        par_statut = s["applications_by_status"]
        moyenne = f"{s['average_score']:.0f}/100" if s.get("average_score") is not None else "—"
        texte = (f"Vue d'ensemble : {s['active_jobs']} offre(s) active(s) sur {s['total_jobs']}, "
                 f"{s['total_applications']} candidature(s), score CV moyen {moyenne}, "
                 f"taux d'acceptation {s['acceptance_rate']} %.")
        elements = [Element(LABELS_FR.get(k, k), f"{n} candidature(s)")
                    for k, n in sorted(par_statut.items(), key=lambda kv: -kv[1]) if n]
        return Reponse(texte, elements[:8], suggestions=[
            "Quelles offres reçoivent le plus de candidatures ?", "Entretiens à venir",
            "Candidats en réserve"])

    async def _offres(self, db: AsyncSession, d: _Demande) -> Reponse:
        if d.offre is not None:
            return await self._fiche_offre(db, d.offre)
        t = d.texte
        statut = ("DRAFT" if _a(t, r"\bbrouillons?\b") else
                  "CLOSED" if _a(t, r"\b(fermees?|cloturees?|closes?)\b") else
                  "PUBLISHED" if _a(t, r"\b(publiees?|ouvertes?|actives?|en ligne)\b") else None)
        nb_candidatures = (select(Application.job_offer_id, func.count(Application.id).label("n"))
                           .group_by(Application.job_offer_id).subquery())
        requete = (select(JobOffer, func.coalesce(nb_candidatures.c.n, 0))
                   .outerjoin(nb_candidatures, nb_candidatures.c.job_offer_id == JobOffer.id))
        if statut:
            requete = requete.where(JobOffer.status == statut)
        tri_par_volume = _a(t, r"\b(plus|moins) de candidatures\b|\bpopulaires?\b")
        lignes = (await db.execute(requete.order_by(
            func.coalesce(nb_candidatures.c.n, 0).desc() if tri_par_volume else JobOffer.created_at.desc()
        ).limit(8))).all()
        total = await db.scalar(select(func.count(JobOffer.id)).where(JobOffer.status == statut)
                                if statut else select(func.count(JobOffer.id))) or 0
        qualif = {"DRAFT": " en brouillon", "CLOSED": " fermée(s)", "PUBLISHED": " publiée(s)"}.get(statut or "", "")
        if not total:
            return Reponse(f"Aucune offre{qualif} pour le moment.", suggestions=["Vue d'ensemble"])
        elements = [Element(o.title, f"{_LIBELLES_OFFRE.get(o.status, o.status)} · {n} candidature(s)",
                            "/admin/decision", {"offre": str(o.id)}) for o, n in lignes]
        premiere = lignes[0][0].title
        return Reponse(f"{total} offre(s){qualif}" + (" — les plus demandées d'abord :" if tri_par_volume else " :"),
                       elements, suggestions=[f"Meilleurs candidats pour {premiere}",
                                              f"Candidatures pour {premiere}", "Offres en brouillon"])

    async def _fiche_offre(self, db: AsyncSession, offre: JobOffer) -> Reponse:
        lignes = (await db.execute(
            select(Application.status, func.count(Application.id))
            .where(Application.job_offer_id == offre.id).group_by(Application.status)
        )).all()
        total = sum(n for _, n in lignes)
        texte = (f"« {offre.title} » — {_LIBELLES_OFFRE.get(offre.status, offre.status).lower()}, "
                 f"{total} candidature(s).")
        elements = [Element(LABELS_FR.get(s, s), f"{n} candidature(s)", "/admin/decision", {"offre": str(offre.id)})
                    for s, n in sorted(lignes, key=lambda x: -x[1])]
        return Reponse(texte, elements, offre_id=offre.id, suggestions=[
            f"Meilleurs candidats pour {offre.title}", f"Entretiens pour {offre.title}"])

    async def _candidatures(self, db: AsyncSession, d: _Demande) -> Reponse:
        t = d.texte
        statut = next((s for motif, s in (
            (r"\b(en attente|nouvelles?|non (traitees?|lues?))\b", ApplicationStatus.PENDING.value),
            (r"\b(rejetees?|refusees?|ecartees?)\b", ApplicationStatus.REJECTED.value),
            (r"\b(acceptees?|retenues?)\b", ApplicationStatus.ACCEPTED.value),
            (r"\b(negociations?)\b", ApplicationStatus.NEGOTIATION.value),
            (r"\b(recrutees?|embauchees?)\b", ApplicationStatus.HIRED.value),
            (r"\b(retirees?)\b", ApplicationStatus.WITHDRAWN.value),
        ) if _a(t, motif)), None)
        requete = (select(Application, Candidate.full_name, JobOffer.title)
                   .join(Candidate, Candidate.id == Application.candidate_id)
                   .join(JobOffer, JobOffer.id == Application.job_offer_id))
        compte = select(Application.status, func.count(Application.id)).group_by(Application.status)
        if d.offre is not None:
            requete = requete.where(Application.job_offer_id == d.offre.id)
            compte = compte.where(Application.job_offer_id == d.offre.id)
        if statut:
            requete = requete.where(Application.status == statut)
        par_statut = dict((await db.execute(compte)).all())
        lignes = (await db.execute(requete.order_by(Application.created_at.desc()).limit(8))).all()
        portee = f" pour « {d.offre.title} »" if d.offre is not None else ""
        if statut:
            texte = f"{par_statut.get(statut, 0)} candidature(s) « {LABELS_FR[statut].lower()} »{portee}."
        else:
            total = sum(par_statut.values())
            repartition = ", ".join(f"{n} {LABELS_FR.get(s, s).lower()}"
                                    for s, n in sorted(par_statut.items(), key=lambda x: -x[1]) if n)
            texte = f"{total} candidature(s){portee}" + (f" : {repartition}." if repartition else ".")
        elements = [Element(nom, f"{titre} · {LABELS_FR.get(a.status, a.status)}", "/admin/decision",
                            {"offre": str(a.job_offer_id), "candidature": str(a.id)}) for a, nom, titre in lignes]
        if elements:
            texte += " Les plus récentes :"
        return Reponse(texte, elements, offre_id=d.offre.id if d.offre else None, suggestions=[
            "Candidatures en attente", "Candidats en réserve", "Entretiens à venir"])

    async def _classement(self, db: AsyncSession, d: _Demande) -> Reponse:
        offre = d.offre
        if offre is None and d.contexte.offre_id:
            offre = await db.get(JobOffer, d.contexte.offre_id)
        if offre is None:
            offres = (await db.execute(
                select(JobOffer.title).join(Application, Application.job_offer_id == JobOffer.id)
                .group_by(JobOffer.id, JobOffer.title).order_by(func.count(Application.id).desc()).limit(4)
            )).scalars().all()
            if not offres:
                return Reponse("Aucune offre n'a encore de candidature à classer.")
            return Reponse("Pour quelle offre ? Choisissez-en une, ou citez son titre :",
                           suggestions=[f"Meilleurs candidats pour {t}" for t in offres])
        classes = rank(await load_job_evidence(db, offre.id))
        if not classes:
            return Reponse(f"Aucun candidat à classer pour « {offre.title} » : les CV n'ont pas encore "
                           "été analysés, ou toutes les candidatures sont closes.", offre_id=offre.id)
        elements = []
        for item in classes[:5]:
            e, a = item["evidence"], item["analysis"]
            score = a["composite"]["score"]
            elements.append(Element(
                f"#{item['decision_rank']} {e.candidate_name}",
                f"{_LIBELLES_RECOMMANDATION[a['recommendation']]} · {round(score) if score is not None else '—'}/100",
                "/admin/decision", {"offre": str(offre.id), "candidature": str(e.application_id)}))
        tete = classes[0]["analysis"]
        return Reponse(
            f"Classement pour « {offre.title} » ({len(classes)} candidat(s)). En tête : "
            f"{classes[0]['evidence'].candidate_name} — {tete['explanation']}",
            elements, offre_id=offre.id,
            suggestions=[f"Entretiens pour {offre.title}", f"Candidatures pour {offre.title}"])

    async def _candidat(self, db: AsyncSession, d: _Demande) -> Reponse:
        c = d.candidat
        lignes = (await db.execute(
            select(Application, JobOffer.title, CandidateScore.total_score)
            .join(JobOffer, JobOffer.id == Application.job_offer_id)
            .outerjoin(CandidateScore, CandidateScore.application_id == Application.id)
            .where(Application.candidate_id == c.id).order_by(Application.created_at.desc())
        )).all()
        if not lignes:
            return Reponse(f"{c.full_name} n'a aucune candidature en cours.")
        elements = [Element(titre, f"{LABELS_FR.get(a.status, a.status)}"
                            + (f" · CV {round(score)}/100" if score is not None else ""),
                            "/admin/decision", {"offre": str(a.job_offer_id), "candidature": str(a.id)})
                    for a, titre, score in lignes]
        return Reponse(f"{c.full_name} : {len(lignes)} candidature(s).", elements,
                       suggestions=[f"Meilleurs candidats pour {lignes[0][1]}", "Entretiens à venir"])

    async def _entretiens(self, db: AsyncSession, d: _Demande) -> Reponse:
        t, user = d.texte, d.utilisateur
        maintenant = datetime.now(timezone.utc)
        fuseau = ZoneInfo(settings.APP_TIMEZONE)
        aujourd_hui = maintenant.astimezone(fuseau).date()
        jour = (aujourd_hui if _a(t, r"\baujourd ?hui\b") else
                aujourd_hui + timedelta(days=1) if _a(t, r"\bdemain\b") else None)
        semaine = _a(t, r"\bsemaine\b")
        etapes = ({ETAPE_A_EVALUER} if _a(t, r"\b(a evaluer|evaluer|noter|a noter)\b") else
                  {ETAPE_EN_ATTENTE} if _a(t, r"\b(en attente|attente|sans reponse|confirm\w*)\b") else
                  {ETAPE_ANNULE, ETAPE_ABSENT} if _a(t, r"\b(annul\w*|absents?|expir\w*)\b") else
                  {ETAPE_A_EVALUER, ETAPE_EVALUE} if _a(t, r"\b(passes?|termines?|evalues?)\b") else
                  {ETAPE_A_VENIR})
        # Un recruteur ne voit que les entretiens dont il est membre — comme à l'écran.
        restreint = _role(user) == UserRole.RECRUTEUR and not user.is_superuser
        items = await interview_service.list_invitations(db, recruiter_id=user.id if restreint else None)

        retenus = []
        for it in items:
            inv = it["invitation"]
            if d.offre is not None and it["job_offer_id"] != d.offre.id:
                continue
            if d.candidat is not None and normaliser(it["candidate_name"]) != normaliser(d.candidat.full_name):
                continue
            etape = etape_entretien(inv, maintenant)
            creneau = next((s for s in inv.slots if s.id == inv.confirmed_slot_id), None)
            debut = creneau.start_at if creneau else min((s.start_at for s in inv.slots), default=None)
            if jour is not None or semaine:
                if creneau is None or etape in (ETAPE_ANNULE, ETAPE_ABSENT):
                    continue
                date_locale = creneau.start_at.astimezone(fuseau).date()
                if jour is not None and date_locale != jour:
                    continue
                if semaine and not (aujourd_hui <= date_locale <= aujourd_hui + timedelta(days=7)):
                    continue
            elif etape not in etapes:
                continue
            retenus.append((debut, it, etape))

        retenus.sort(key=lambda r: (r[0] is None, r[0] or maintenant))
        periode = ("aujourd'hui" if jour == aujourd_hui else "demain" if jour is not None else
                   "dans les 7 prochains jours" if semaine else
                   " / ".join(_LIBELLES_ETAPE[e].lower() for e in sorted(etapes)))
        portee = f" pour « {d.offre.title} »" if d.offre is not None else ""
        if not retenus:
            return Reponse(f"Aucun entretien ({periode}){portee}.",
                           suggestions=["Entretiens à évaluer", "Entretiens en attente de réponse",
                                        "Entretiens de la semaine"])
        elements = [Element(it["candidate_name"],
                            f"{it['job_title']} · {_date(debut)} · {_LIBELLES_ETAPE[etape]}",
                            "/admin/interviews")
                    for debut, it, etape in retenus[:8]]
        return Reponse(f"{len(retenus)} entretien(s) ({periode}){portee} :", elements,
                       suggestions=["Entretiens à évaluer", "Entretiens de la semaine", "Candidats en réserve"])

    async def _tests(self, db: AsyncSession, d: _Demande) -> Reponse:
        t = d.texte
        statuts = ([SessionStatus.ENVOYE.value] if _a(t, r"\b(en attente|envoyes?|pas commences?)\b") else
                   [SessionStatus.EN_COURS.value] if _a(t, r"\ben cours\b") else
                   [SessionStatus.ABANDONNE.value] if _a(t, r"\babandon\w*\b") else
                   [SessionStatus.TERMINE.value, SessionStatus.EXPIRE.value]
                   if _a(t, r"\b(termines?|corriges?|resultats?|passes?|notes?)\b") else None)
        par_statut = dict((await db.execute(
            select(TestSession.status, func.count(TestSession.id)).group_by(TestSession.status))).all())
        par_statut = {getattr(k, "value", k): n for k, n in par_statut.items()}
        requete = (select(TestSession, Candidate.full_name, JobOffer.title, Application.job_offer_id)
                   .join(Application, Application.id == TestSession.application_id)
                   .join(Candidate, Candidate.id == Application.candidate_id)
                   .join(JobOffer, JobOffer.id == Application.job_offer_id))
        if statuts:
            requete = requete.where(TestSession.status.in_(statuts))
        if d.offre is not None:
            requete = requete.where(Application.job_offer_id == d.offre.id)
        lignes = (await db.execute(requete.order_by(TestSession.sent_at.desc()).limit(8))).all()
        repartition = ", ".join(f"{n} {_LIBELLES_TEST.get(k, k).lower()}" for k, n in par_statut.items() if n)
        texte = (f"Tests techniques : {repartition}." if repartition else "Aucun test technique envoyé.")
        elements = [Element(nom, f"{titre} · {_LIBELLES_TEST.get(getattr(s.status, 'value', s.status), s.status)}"
                            + (f" · {round(s.score)}/100" if s.score is not None else ""),
                            "/admin/assessment")
                    for s, nom, titre, _ in lignes]
        return Reponse(texte, elements, suggestions=["Tests terminés", "Tests en attente", "Entretiens à venir"])

    async def _reserve(self, db: AsyncSession, d: _Demande) -> Reponse:
        requete = (select(Application, Candidate.full_name, JobOffer.title)
                   .join(Candidate, Candidate.id == Application.candidate_id)
                   .join(JobOffer, JobOffer.id == Application.job_offer_id)
                   .where(Application.status == ApplicationStatus.ON_HOLD.value))
        if d.offre is not None:
            requete = requete.where(Application.job_offer_id == d.offre.id)
        lignes = (await db.execute(requete.order_by(Application.updated_at.desc()).limit(20))).all()
        if not lignes:
            return Reponse("Aucun candidat en réserve pour le moment.")
        elements = [Element(nom, titre, "/admin/decision", {"offre": str(a.job_offer_id), "candidature": str(a.id)})
                    for a, nom, titre in lignes]
        return Reponse(f"{len(lignes)} candidat(s) en réserve — ils seront invités automatiquement quand "
                       "une offre proche de leur profil paraîtra :", elements,
                       suggestions=["Offres publiées", "Meilleurs candidats"])

    async def _contrats(self, db: AsyncSession, d: _Demande) -> Reponse:
        par_statut = dict((await db.execute(
            select(Contract.status, func.count(Contract.id)).group_by(Contract.status))).all())
        par_statut = {getattr(k, "value", k): n for k, n in par_statut.items()}
        if not par_statut:
            return Reponse("Aucun contrat établi pour le moment.")
        lignes = (await db.execute(
            select(Contract, Candidate.full_name)
            .join(Application, Application.id == Contract.application_id)
            .join(Candidate, Candidate.id == Application.candidate_id)
            .where(Contract.status == ContractStatus.SENT).order_by(Contract.sent_at.desc()).limit(8)
        )).all()
        repartition = ", ".join(f"{n} {_LIBELLES_CONTRAT.get(k, k).lower()}" for k, n in par_statut.items() if n)
        elements = [Element(nom, f"{c.position} · à signer avant le {_date(c.expires_at)}", "/admin/contracts")
                    for c, nom in lignes]
        return Reponse(f"Contrats : {repartition}." + (" En attente de signature :" if elements else ""),
                       elements, suggestions=["Employés par département", "Candidats acceptés"])

    async def _employes(self, db: AsyncSession, d: _Demande) -> Reponse:
        lignes = (await db.execute(
            select(Employee.department, func.count(Employee.id))
            .where(Employee.status == "active").group_by(Employee.department)
        )).all()
        total = sum(n for _, n in lignes)
        if not total:
            return Reponse("Aucun employé actif enregistré.")
        elements = [Element(dep or "Sans département", f"{n} employé(s)", "/admin/employees")
                    for dep, n in sorted(lignes, key=lambda x: -x[1])]
        return Reponse(f"{total} employé(s) actif(s), répartis ainsi :", elements,
                       suggestions=["Budget par département", "Contrats en attente de signature"])

    async def _budget(self, db: AsyncSession, d: _Demande) -> Reponse:
        annee = datetime.now(timezone.utc).year
        depenses = (select(BudgetExpense.budget_id, func.sum(BudgetExpense.amount).label("total"))
                    .group_by(BudgetExpense.budget_id).subquery())
        lignes = (await db.execute(
            select(DepartmentBudget, func.coalesce(depenses.c.total, 0.0))
            .outerjoin(depenses, depenses.c.budget_id == DepartmentBudget.id)
            .where(DepartmentBudget.year == annee).order_by(DepartmentBudget.department)
        )).all()
        if not lignes:
            return Reponse(f"Aucun budget saisi pour {annee}.")
        alloue = sum(b.allocated_amount for b, _ in lignes)
        consomme = sum(dep for _, dep in lignes)
        elements = [Element(b.department, f"{dep:,.0f} / {b.allocated_amount:,.0f} TND consommés".replace(",", " "),
                            "/admin/budget") for b, dep in lignes]
        return Reponse(f"Budget {annee} : {consomme:,.0f} TND consommés sur {alloue:,.0f} TND alloués."
                       .replace(",", " "), elements, suggestions=["Employés par département"])

    async def _utilisateurs(self, db: AsyncSession, d: _Demande) -> Reponse:
        lignes = (await db.execute(
            select(User.role, func.count(User.id)).where(User.deleted_at.is_(None)).group_by(User.role))).all()
        total = sum(n for _, n in lignes)
        elements = [Element(_LIBELLES_ROLE.get(getattr(r, "value", r), r), f"{n} compte(s)", "/admin/users")
                    for r, n in sorted(lignes, key=lambda x: -x[1])]
        return Reponse(f"{total} compte(s) utilisateur :", elements, suggestions=["Vue d'ensemble"])

    # ── Base de connaissances, puis repli ─────────────────────────────────────

    async def _connaissances(self, db: AsyncSession, d: _Demande, suggestions: list[str],
                             repli: bool = True) -> Optional[Reponse]:
        """La FAQ, si elle répond vraiment ; sinon le repli honnête (ou rien, si `repli` est faux)."""
        resultat = await cag_service.ask(db, d.brut, user_id=str(d.utilisateur.id))
        sources = resultat.get("sources") or []
        # Une question qui reprend le titre d'une entrée (« Comment planifier un
        # entretien ? ») la désigne, même si la similarité vectorielle est basse.
        reprend_le_titre = bool(sources) and SequenceMatcher(
            None, normaliser(sources[0]["title"]), d.texte).ratio() >= 0.8
        if sources and ((resultat.get("confidence") or 0) >= SEUIL_CONNAISSANCES or reprend_le_titre):
            return Reponse(resultat["answer"], sources=sources[:2],
                           confiance=resultat["confidence"], outil="connaissances", suggestions=suggestions[:3])
        return _incompris(suggestions) if repli else None

    # ── Suggestions ───────────────────────────────────────────────────────────

    def _suggestions_role(self, user: User) -> list[str]:
        candidates = ["Vue d'ensemble", "Entretiens à venir", "Meilleurs candidats",
                      "Candidatures en attente", "Tests terminés", "Candidats en réserve",
                      "Contrats en attente de signature", "Employés par département"]
        return [s for s in candidates if self._suggestion_permise(s, user)][:6]

    def _suggestion_permise(self, suggestion: str, user: User) -> bool:
        """Ne jamais proposer une question dont la réponse serait un refus."""
        outil = max(_CATALOGUE, key=lambda o: len(re.findall(o.motif, normaliser(suggestion))))
        if not re.search(outil.motif, normaliser(suggestion)):
            return True
        return _peut(user, outil.ressource)


# Ordre = priorité à égalité : du plus précis au plus général.
_CATALOGUE: list[_Outil] = [
    _Outil("resume", "Vue d'ensemble", "dashboard",
           r"\b(resume|statistiques?|stats|chiffres?|bilan|vue d ensemble|tableau de bord|kpis?|indicateurs?|synthese)\b",
           AssistantService._resume),
    _Outil("classement", "Classement des candidats", "decision",
           r"\b(meilleurs?|top|classement|classer|recommand\w*|recruter|embaucher|retenir|choisir|favoris?|shortlist)\b",
           AssistantService._classement),
    _Outil("entretiens", "Entretiens", "interviews",
           r"\b(entretiens?|interviews?|rdv|rendez vous|meet|visio)\b", AssistantService._entretiens),
    _Outil("tests", "Tests techniques", "assessment",
           r"\b(tests?|quiz|qcm)\b", AssistantService._tests),
    _Outil("reserve", "Candidats en réserve", "applications",
           r"\b(reserve|vivier|on hold)\b", AssistantService._reserve),
    _Outil("contrats", "Contrats", "contracts",
           r"\b(contrats?|signatures?|signer)\b", AssistantService._contrats),
    _Outil("employes", "Employés", "employees",
           r"\b(employes?|salaries?|effectifs?|personnel|collaborateurs?)\b", AssistantService._employes),
    _Outil("budget", "Budget", "budget",
           r"\b(budgets?|depenses?|couts?|masse salariale)\b", AssistantService._budget),
    _Outil("utilisateurs", "Comptes utilisateurs", "users",
           r"\b(utilisateurs?|comptes?|roles?)\b", AssistantService._utilisateurs),
    _Outil("candidatures", "Candidatures", "applications",
           r"\b(candidatures?|postul\w*|dossiers?|candidats?)\b", AssistantService._candidatures),
    _Outil("offres", "Offres d'emploi", "jobs",
           r"\b(offres?|postes?|annonces?|jobs?|emplois?)\b", AssistantService._offres),
    # Sans mot-clé propre : choisi quand le message cite un candidat.
    _Outil("candidat", "Fiche candidat", "applications", r"(?!)", AssistantService._candidat),
]
_PAR_CLE = {o.cle: o for o in _CATALOGUE}

assistant_service = AssistantService()
