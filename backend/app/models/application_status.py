"""
Vocabulaire des statuts de candidature — source unique.

Avant ce module, quatre endroits déclaraient chacun leur liste et ces listes ne
se recouvraient pas : une regex de schéma limitée à quatre valeurs, des
écritures directes sur le modèle qui la contournaient, une liste analytique
amputée de `TEST_SENT` et `HIRED` (qui n'apparaissaient donc dans aucune
statistique), et deux tables de libellés incomplètes.

Tout en dérive désormais. La colonne reste un `String(50)` : un `ENUM`
PostgreSQL échouerait sur la première valeur inattendue, et ce vocabulaire
bouge encore. La contrainte vit ici et dans les schémas Pydantic.
"""
from __future__ import annotations

import enum


class ApplicationStatus(str, enum.Enum):
    """Les états qu'une candidature peut traverser, dans l'ordre du parcours."""

    PENDING = "PENDING"                          # déposée, pas encore regardée
    REVIEWED = "REVIEWED"                        # CV analysé et noté
    TEST_SENT = "TEST_SENT"                      # test technique envoyé, lien non ouvert
    EN_TEST = "EN_TEST"                          # le candidat compose
    TEST_DONE = "TEST_DONE"                      # test corrigé, résultats disponibles
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"  # entretien planifié ou confirmé
    NEGOTIATION = "NEGOTIATION"                  # négociation salariale ouverte
    ACCEPTED = "ACCEPTED"                        # retenu — contrat à établir
    HIRED = "HIRED"                              # contrat signé, employé créé
    REJECTED = "REJECTED"                        # écarté, à n'importe quelle étape


#: Libellés français, partagés par les notifications, les PDF et le frontend.
LABELS_FR: dict[str, str] = {
    ApplicationStatus.PENDING.value: "En attente",
    ApplicationStatus.REVIEWED.value: "Examinée",
    ApplicationStatus.TEST_SENT.value: "Test envoyé",
    ApplicationStatus.EN_TEST.value: "Test en cours",
    ApplicationStatus.TEST_DONE.value: "Test passé",
    ApplicationStatus.INTERVIEW_SCHEDULED.value: "Entretien planifié",
    ApplicationStatus.NEGOTIATION.value: "Négociation",
    ApplicationStatus.ACCEPTED.value: "Acceptée",
    ApplicationStatus.HIRED.value: "Recrutée",
    ApplicationStatus.REJECTED.value: "Rejetée",
}

#: Toutes les valeurs, dans l'ordre du parcours — pour les statistiques et les
#: filtres, qui doivent présenter les statuts dans un ordre lisible.
ALL: list[str] = [s.value for s in ApplicationStatus]

#: Fins de parcours : aucune transition n'en sort.
TERMINAL: frozenset[str] = frozenset(
    {ApplicationStatus.HIRED.value, ApplicationStatus.REJECTED.value}
)

#: Rang dans le parcours. Sert à distinguer « avancer » de « reculer » — la
#: seule distinction qui vaille ici.
_RANG: dict[str, int] = {valeur: i for i, valeur in enumerate(ALL) if valeur != "REJECTED"}

#: Les deux seuls retours en arrière qui ont un sens métier.
#:
#: * `ACCEPTED → NEGOTIATION` — le candidat a refusé son contrat ; on rouvre la
#:   discussion plutôt que de le perdre.
#: * `NEGOTIATION → INTERVIEW_SCHEDULED` — la négociation bute, on se revoit.
_RETOURS_ADMIS: frozenset[tuple[str, str]] = frozenset({
    (ApplicationStatus.ACCEPTED.value, ApplicationStatus.NEGOTIATION.value),
    (ApplicationStatus.NEGOTIATION.value, ApplicationStatus.INTERVIEW_SCHEDULED.value),
})


def is_valid(status: str | None) -> bool:
    """Vrai si la valeur appartient au vocabulaire."""
    return status in LABELS_FR


def label(status: str | None) -> str:
    """Libellé français, ou la clé brute si elle est inconnue — jamais vide."""
    if not status:
        return "—"
    return LABELS_FR.get(status, status)


def can_transition(current: str | None, target: str) -> bool:
    """
    Vrai si le passage de `current` à `target` est permis.

    La règle est délibérément permissive vers l'avant. Un RH doit pouvoir
    accepter directement quelqu'un dont il a lu le CV hors de l'outil, ou
    sauter le test technique : c'est son métier, pas une anomalie. Interdire
    ces raccourcis reviendrait à lui opposer un formalisme que le produit n'a
    jamais eu — et que rien ne justifie.

    Ce qui est refusé, en revanche, l'est pour de bonnes raisons :

    * **Revenir en arrière**, sauf les deux cas où cela a un sens (un contrat
      refusé, une négociation qui échoue). Sans ce garde-fou, un clic maladroit
      renvoie une candidature en attente et efface tout l'historique visible.
    * **Rouvrir une fin de parcours.** Un candidat recruté ou rejeté ne repart
      pas : ce sont deux états sur lesquels d'autres traitements s'appuient.
    * **Une cible hors vocabulaire**, évidemment.

    Un statut inconnu EN ENTRÉE n'est pas une raison de bloquer : des données
    peuvent précéder ce vocabulaire, et leur propriétaire doit pouvoir les
    corriger.
    """
    if not is_valid(target):
        return False
    if current is None or not is_valid(current):
        return True
    if current in TERMINAL:
        return False
    if target == ApplicationStatus.REJECTED.value:
        return True                       # sortie possible à tout moment

    depart, arrivee = _RANG.get(current), _RANG.get(target)
    if depart is None or arrivee is None:
        return True
    if arrivee > depart:
        return True                       # avancer, même en sautant des étapes
    if arrivee == depart:
        # Un second entretien est courant ; rien d'autre ne se répète.
        return target == ApplicationStatus.INTERVIEW_SCHEDULED.value
    return (current, target) in _RETOURS_ADMIS
