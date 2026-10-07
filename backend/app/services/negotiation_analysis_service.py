"""
Moteur de décision de la négociation salariale.

Ce module ne prédit rien : il ARBITRE. Il reçoit trois grandeurs que le modèle
précédent confondait, et qui doivent rester distinctes de bout en bout :

  A. **le budget de l'offre** — la fourchette annoncée par l'entreprise
     (`salary_min` … `salary_max`). C'est le seul montant qui engage le
     recruteur, et donc la seule référence pour dire « ça rentre ou non ».
  B. **la demande du candidat** — un montant unique.
  C. **le marché** — une FOURCHETTE estimée par `SalaryPredictionService`,
     jamais un point. Elle sert de contexte (la demande est-elle haute ? le
     budget est-il compétitif ?), jamais de seuil d'acceptation.

Le bug métier corrigé ici : la version précédente comparait la demande au
`salary_min` de l'offre, puis au point de prédiction du marché. Un candidat
demandant exactement le maximum annoncé (1 700 sur une fourchette 1 400–1 700)
était donc signalé comme « dépasse le budget de plus de 15 % » et comme
« −2 400 par rapport au marché ». Les deux affirmations étaient fausses : le
dépassement est nul, et le marché n'est pas un nombre.

Règles de priorité (dans cet ordre) :

    SI demande <= budget_max ET profil suffisamment qualifié -> demande acceptable
    SI demande <= budget_max ET profil insuffisant           -> contre-proposition
    SI demande >  budget_max                                 -> négociation nécessaire
    SI demande >  marché_max        -> signal « demande élevée »
    SI demande <  marché_min        -> signal « candidat potentiellement sous-payé »
    SI budget_max < marché_min      -> signal « offre sous le marché »

Les signaux sont cumulables et n'écrasent jamais le verdict : ils l'éclairent.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services.scoring_service import ScoringService

logger = logging.getLogger(__name__)

# Seuil de qualification : en dessous, la demande — même dans le budget —
# mérite une contre-proposition plutôt qu'un accord.
QUALIFICATION_THRESHOLD = 60.0
# Au-dessus, le profil est jugé exceptionnel et peut justifier un effort
# au-delà du haut de fourchette, dans la limite du marché.
EXCEPTIONAL_THRESHOLD = 85.0
# Effort maximal toléré au-dessus du budget annoncé pour retenir un profil rare.
MAX_STRETCH_ABOVE_BUDGET = 0.15


def _round50(value: float) -> float:
    return round(float(value) / 50.0) * 50


def _tnd(value: float) -> str:
    """Montant en TND, séparateur de milliers insécable (convention FR)."""
    return f"{value:,.0f}".replace(",", " ")


def _annees(value: float) -> str:
    """« 1 an », « 1,5 an », « 3 ans » — et non « 1.0 ans »."""
    v = round(float(value), 1)
    texte = f"{v:.0f}" if v == int(v) else f"{v:.1f}".replace(".", ",")
    return f"{texte} {'an' if abs(v) < 2 else 'ans'}"


class NegotiationAnalysisService:
    """Arbitre une demande salariale. Sans état, sans I/O : purement décisionnel."""

    @staticmethod
    def compute_qualification(
        candidate_experience_years: Optional[float],
        required_experience_years: Optional[float],
        match_score: Optional[float],
    ) -> float:
        """
        Niveau de qualification du candidat pour le poste, sur 100.

        Réutilise `ScoringService.compute_experience_score` — la même fonction
        que le modèle de classement des candidatures — pour que la négociation
        et le classement ne puissent pas diverger sur l'expérience.

        Moyenne de la couverture d'expérience et du score de matching CV/poste ;
        l'une des deux suffit si l'autre est indisponible.
        """
        experience_score = ScoringService.compute_experience_score(
            required_experience_years, candidate_experience_years
        )
        has_experience_signal = candidate_experience_years is not None
        if match_score is None:
            return experience_score if has_experience_signal else 50.0
        if not has_experience_signal:
            return float(match_score)
        return (experience_score + float(match_score)) / 2.0

    @staticmethod
    def _market_position_score(requested: float, market_min: float, market_max: float) -> float:
        """
        Position de la demande dans le marché, notée du point de vue de
        l'entreprise : 100 quand le candidat demande sous le plancher du marché
        (bonne affaire), 0 quand il demande au-dessus du plafond.
        """
        if market_max <= market_min:
            return 50.0
        if requested <= market_min:
            return 100.0
        if requested >= market_max:
            return 0.0
        return 100.0 * (market_max - requested) / (market_max - market_min)

    @staticmethod
    def _budget_score(
        requested: float, budget_min: float, budget_max: float, overrun: float
    ) -> float:
        """
        Confort budgétaire : 100 au plancher, 60 au plafond annoncé — rester
        dans le budget reste une bonne note — puis chute proportionnelle au
        dépassement au-delà.
        """
        if budget_max <= 0:
            return 0.0
        if overrun <= 0:
            span = budget_max - budget_min
            position = 0.0 if span <= 0 else (requested - budget_min) / span
            return 100.0 - 40.0 * min(max(position, 0.0), 1.0)
        return max(0.0, 60.0 - 100.0 * (overrun / budget_max))

    def compute_negotiation_score(
        self,
        *,
        experience_score: float,
        match_score: Optional[float],
        market_position_score: float,
        budget_score: float,
    ) -> float:
        """
        Score de négociation sur 100, pondéré et explicable :

            expérience 30 % + matching 30 % + position marché 20 % + budget 20 %

        Aucun modèle appris ici. Une décision de négociation engage un budget et
        doit pouvoir être justifiée devant un RH ligne à ligne ; une pondération
        fixe le permet, une boîte noire non.
        """
        matching = experience_score if match_score is None else float(match_score)
        return (
            experience_score * 0.30
            + matching * 0.30
            + market_position_score * 0.20
            + budget_score * 0.20
        )

    @staticmethod
    def _position_in_range(
        requested: float, budget_min: float, budget_max: float
    ) -> Optional[float]:
        """Position de la demande dans la fourchette annoncée, en %."""
        if budget_max <= budget_min:
            return 100.0 if requested >= budget_max else 0.0
        ratio = (requested - budget_min) / (budget_max - budget_min) * 100.0
        return round(min(max(ratio, 0.0), 100.0), 1)

    def analyze(
        self,
        *,
        candidate_name: str,
        budget_min: float,
        budget_max: float,
        requested_salary: float,
        market_min: float,
        market_max: float,
        market_reference: float,
        candidate_experience_years: Optional[float] = None,
        required_experience_years: Optional[float] = None,
        match_score: Optional[float] = None,
        seniority_label: Optional[str] = None,
        experience_source: Optional[str] = None,
    ) -> dict:
        """Arbitre la demande et produit verdict, montant recommandé et explication."""
        budget_min, budget_max = min(budget_min, budget_max), max(budget_min, budget_max)

        qualification = self.compute_qualification(
            candidate_experience_years, required_experience_years, match_score
        )
        qualified = qualification >= QUALIFICATION_THRESHOLD
        experience_gap = (
            round(candidate_experience_years - required_experience_years, 1)
            if candidate_experience_years is not None and required_experience_years is not None
            else None
        )
        exceptional = bool(
            qualification >= EXCEPTIONAL_THRESHOLD
            and experience_gap is not None
            and experience_gap >= 2
        )

        budget_overrun = max(0.0, requested_salary - budget_max)
        position_in_range = self._position_in_range(requested_salary, budget_min, budget_max)

        # Écart au MARCHÉ : nul tant que la demande est dans la fourchette.
        if requested_salary > market_max:
            market_gap = requested_salary - market_max
        elif requested_salary < market_min:
            market_gap = requested_salary - market_min
        else:
            market_gap = 0.0

        signals: list[str] = []
        if requested_salary > market_max:
            signals.append("above_market")
        if requested_salary < market_min:
            signals.append("below_market")
        if budget_max < market_min:
            signals.append("budget_below_market")
        if budget_overrun == 0 and position_in_range is not None and position_in_range >= 99.5:
            signals.append("top_of_range")
        if experience_gap is not None and experience_gap >= 2:
            signals.append("overqualified")
        if not qualified:
            signals.append("underqualified")

        verdict, recommended = self._decide(
            requested_salary=requested_salary,
            budget_min=budget_min,
            budget_max=budget_max,
            market_min=market_min,
            market_max=market_max,
            market_reference=market_reference,
            qualification=qualification,
            qualified=qualified,
            exceptional=exceptional,
        )

        lines = self._explain(
            candidate_name=candidate_name,
            verdict=verdict,
            recommended=recommended,
            requested_salary=requested_salary,
            budget_min=budget_min,
            budget_max=budget_max,
            budget_overrun=budget_overrun,
            position_in_range=position_in_range,
            market_min=market_min,
            market_max=market_max,
            candidate_experience_years=candidate_experience_years,
            required_experience_years=required_experience_years,
            experience_gap=experience_gap,
            match_score=match_score,
            qualification=qualification,
            seniority_label=seniority_label,
            signals=signals,
            experience_source=experience_source,
            qualified=qualified,
        )

        # Score explicable et étiquette grossière, en plus du verdict détaillé.
        experience_score = ScoringService.compute_experience_score(
            required_experience_years, candidate_experience_years
        )
        market_position_score = self._market_position_score(requested_salary, market_min, market_max)
        budget_score = self._budget_score(requested_salary, budget_min, budget_max, budget_overrun)
        negotiation_score = self.compute_negotiation_score(
            experience_score=experience_score,
            match_score=match_score,
            market_position_score=market_position_score,
            budget_score=budget_score,
        )
        decision = self._decision_label(requested_salary, budget_max, market_max, qualified)

        return {
            "verdict": verdict,
            "decision": decision,
            "signals": signals,
            "requested_salary": float(requested_salary),
            "recommended_salary": float(recommended),
            "negotiation_score": round(negotiation_score, 1),
            "score_breakdown": {
                "experience": round(experience_score, 1),
                "matching": round(float(match_score), 1) if match_score is not None else None,
                "market_position": round(market_position_score, 1),
                "budget": round(budget_score, 1),
                "weights": {"experience": 0.30, "matching": 0.30,
                            "market_position": 0.20, "budget": 0.20},
            },
            "budget_min": float(budget_min),
            "budget_max": float(budget_max),
            "budget_overrun": float(budget_overrun),
            "position_in_range": position_in_range,
            "market_min": float(market_min),
            "market_max": float(market_max),
            "market_reference": float(market_reference),
            "market_gap": float(market_gap),
            "qualification_score": round(qualification, 1),
            "is_qualified": qualified,
            "is_exceptional": exceptional,
            "experience_gap_years": experience_gap,
            "explanation_lines": lines,
            # Version texte (chat, export) : la recommandation y garde son intitulé.
            "explanation": " ".join(
                ("Recommandation : " + line["text"]) if line["kind"] == "recommendation" else line["text"]
                for line in lines
            ),
        }

    @staticmethod
    def _decision_label(
        requested: float, budget_max: float, market_max: float, qualified: bool
    ) -> str:
        """
        Étiquette grossière, indépendante du verdict détaillé :

            demande <= budget_max   → ACCEPT (ou COUNTER si le profil ne suit pas)
            demande <= marché_max   → NEGOTIATE
            au-delà                 → HIGH_REQUEST

        Utile pour trier, filtrer et évaluer le moteur sur un jeu de scénarios ;
        le verdict reste la sortie de référence pour l'affichage.
        """
        if requested <= budget_max:
            return "ACCEPT" if qualified else "COUNTER"
        if requested <= market_max:
            return "NEGOTIATE"
        return "HIGH_REQUEST"

    # ── Décision ──────────────────────────────────────────────────────────────

    def _decide(
        self,
        *,
        requested_salary: float,
        budget_min: float,
        budget_max: float,
        market_min: float,
        market_max: float,
        market_reference: float,
        qualification: float,
        qualified: bool,
        exceptional: bool,
    ) -> tuple[str, float]:
        """Verdict principal + montant recommandé, dans l'ordre de priorité."""
        if requested_salary <= budget_max:
            if qualified:
                # Rien à négocier : le montant demandé tient dans le budget et
                # le profil le justifie. On recommande la demande telle quelle.
                return "acceptable", requested_salary
            # Dans le budget mais profil en deçà : on positionne le candidat
            # dans la fourchette au prorata de sa qualification.
            target = budget_min + (qualification / 100.0) * (budget_max - budget_min)
            return "counter_offer", _round50(min(target, requested_salary))

        # Au-delà du budget annoncé : négociation obligatoire.
        #
        # Un effort au-dessus du budget ne se justifie pas par la seule qualité
        # du profil — sinon le moteur dépenserait l'argent de l'entreprise dès
        # qu'un candidat est bon. Il faut en plus un FAIT DE MARCHÉ opposable :
        # le plafond annoncé est sous le plancher du marché, donc l'entreprise
        # ne recrutera pas à ce prix, profil exceptionnel ou non.
        if exceptional and budget_max < market_min:
            ceiling = min(
                requested_salary,
                max(market_reference, market_max),
                budget_max * (1 + MAX_STRETCH_ABOVE_BUDGET),
            )
            return "stretch", _round50(max(ceiling, budget_max))
        return "negotiation_required", float(budget_max)

    # ── Explication ───────────────────────────────────────────────────────────

    @staticmethod
    def _explain(**ctx) -> list[dict]:
        """
        Explication structurée : une ligne = un fait, avec sa tonalité ET sa
        catégorie (`kind`), pour que l'écran range chaque fait à sa place au
        lieu d'empiler la même information trois fois :

        * `recommendation` — l'action à mener (une seule ligne) ;
        * `alert`          — ce qui doit retenir l'attention du RH ;
        * `budget`, `profile`, `market` — les faits, que l'écran présente déjà
          sous forme de chiffres (conservés pour la version texte et le chat).

        Aucun pictogramme dans le texte : la tonalité suffit à l'affichage.
        """
        lines: list[dict] = []

        def add(kind: str, tone: str, text: str) -> None:
            lines.append({"kind": kind, "tone": tone, "text": text})

        name = ctx["candidate_name"]
        requested = ctx["requested_salary"]
        b_min, b_max = ctx["budget_min"], ctx["budget_max"]
        overrun = ctx["budget_overrun"]
        position = ctx["position_in_range"]
        verdict = ctx["verdict"]
        recommended = ctx["recommended"]
        signals = ctx["signals"]

        # 1. Le budget — la seule comparaison qui engage le recruteur.
        if overrun <= 0:
            add("budget", "success",
                f"{name} demande {_tnd(requested)} TND, dans la fourchette annoncée "
                f"({_tnd(b_min)} – {_tnd(b_max)} TND) : aucun dépassement du budget, "
                f"demande située à {position:.0f} % de la fourchette.")
            if "top_of_range" in signals:
                add("alert", "info", "La demande atteint le maximum annoncé pour ce poste : "
                                     "aucune marge de négociation à la hausse.")
        else:
            add("alert", "danger",
                f"La demande dépasse de {_tnd(overrun)} TND le maximum annoncé "
                f"({_tnd(b_max)} TND) : une négociation est nécessaire.")

        # 2. Le profil — ce qui justifie (ou non) la position dans la fourchette.
        cand_exp = ctx["candidate_experience_years"]
        req_exp = ctx["required_experience_years"]
        gap = ctx["experience_gap"]
        if ctx.get("experience_source") == "job_requirement" and req_exp is not None:
            # Sans analyse du CV, l'expérience retenue EST celle du poste : la
            # dire « conforme » serait affirmer ce que personne n'a mesuré.
            add("alert", "warn",
                f"Expérience non mesurée : le CV n'a pas été analysé, l'expérience requise "
                f"par le poste ({_annees(req_exp)}) est utilisée par défaut. Le critère "
                f"Expérience du score n'est donc pas fiable.")
        elif cand_exp is not None and req_exp is not None:
            if gap and gap > 0:
                add("profile", "info",
                    f"Expérience : {_annees(cand_exp)} pour {_annees(req_exp)} demandés "
                    f"(+{_annees(gap)}) — justifie le haut de fourchette, pas un dépassement du budget.")
            elif gap is not None and gap < 0:
                add("alert", "warn",
                    f"Expérience : {_annees(cand_exp)} pour {_annees(req_exp)} demandés "
                    f"({_annees(abs(gap))} de moins) — le profil n'atteint pas encore le niveau attendu.")
            else:
                add("profile", "info",
                    f"Expérience : {_annees(cand_exp)}, conforme au niveau demandé.")
        if ctx["match_score"] is not None:
            add("profile", "info",
                f"Matching CV / poste : {ctx['match_score']:.0f}/100 · "
                f"qualification globale : {ctx['qualification']:.0f}/100.")
        if not ctx.get("qualified", True):
            add("alert", "warn",
                f"Qualification globale {ctx['qualification']:.0f}/100, sous le seuil de "
                f"{QUALIFICATION_THRESHOLD:.0f} : le profil ne justifie pas le montant demandé.")

        # 3. Le marché — un contexte, exprimé en fourchette.
        seniority = ctx["seniority_label"]
        niveau = f" (niveau {seniority.lower()})" if seniority else ""
        add("market", "info",
            f"Marché estimé pour ce profil{niveau} : "
            f"{_tnd(ctx['market_min'])} – {_tnd(ctx['market_max'])} TND.")
        if "budget_below_market" in signals:
            add("alert", "warn",
                f"Le maximum du budget ({_tnd(b_max)} TND) est sous le plancher du marché estimé "
                f"({_tnd(ctx['market_min'])} TND) : risque de perdre le candidat ou de le voir "
                f"repartir rapidement.")
        elif "below_market" in signals:
            add("alert", "warn",
                "La demande est sous le plancher du marché estimé : candidat potentiellement "
                "sous-payé — l'accepter telle quelle expose à un départ à court terme.")
        elif "above_market" in signals:
            add("alert", "warn", "La demande dépasse le haut de la fourchette de marché estimée.")

        # 4. La recommandation — une seule ligne, l'action à mener.
        if verdict == "acceptable":
            add("recommendation", "success", f"Accepter la demande à {_tnd(recommended)} TND.")
        elif verdict == "counter_offer":
            add("recommendation", "warn",
                f"Contre-proposer {_tnd(recommended)} TND, au prorata du niveau réellement couvert.")
        elif verdict == "stretch":
            add("recommendation", "warn",
                f"Effort exceptionnel à {_tnd(recommended)} TND, au-dessus du budget annoncé "
                f"— à valider en interne.")
        else:
            add("recommendation", "danger",
                f"Maintenir l'offre à {_tnd(recommended)} TND (maximum du budget) "
                f"et négocier sur les avantages.")

        if recommended > b_max:
            add("alert", "danger",
                f"Ce montant dépasse le maximum du budget annoncé ({_tnd(b_max)} TND) "
                f"de {_tnd(recommended - b_max)} TND — arbitrage budgétaire requis.")
        return lines


negotiation_analysis_service = NegotiationAnalysisService()
