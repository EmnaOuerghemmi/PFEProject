"""
Jeu de test pour l'évaluation de la récupération.

CV SYNTHÉTIQUES, ET C'EST IMPÉRATIF. Les CV employés ici sont inventés. Le
dépôt contient 264 CV réels dans `backend/uploads/` : les utiliser pour une
évaluation reviendrait à faire circuler des données personnelles dans un
rapport, un journal d'exécution et un dépôt Git — exactement ce que la règle du
projet interdit. Les personnes décrites ci-dessous n'existent pas.

STRUCTURE D'UN CAS. Chaque cas porte :
  - la question posée ;
  - les passages du CV qui **devraient** être récupérés (vérité terrain) ;
  - la réponse attendue, en clair ;
  - les mots-clés qui doivent figurer dans l'extrait rendu.

Les passages attendus sont écrits pour correspondre au découpage réel du
moteur (phrases, lignes), afin que la vérité terrain soit atteignable. Une
vérité terrain qu'aucun découpage ne peut produire mesurerait le découpage, pas
la récupération.

CAS NÉGATIFS. Le jeu comporte des questions dont la réponse **n'est pas** dans
le CV. Un moteur de récupération qui répond toujours quelque chose n'est pas
évalué correctement si on ne lui pose que des questions auxquelles il peut
répondre : le refus est un comportement attendu, et il se mesure.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CVSynthetique:
    """CV inventé, servant de corpus à un ou plusieurs cas de test."""

    identifiant: str
    texte: str


@dataclass(frozen=True)
class CasDeTest:
    """Un cas : une question, sa vérité terrain, sa réponse attendue."""

    identifiant: str
    cv: str
    question: str
    #: Passages du CV qui devraient être récupérés. Vide = aucune réponse
    #: attendue (cas négatif).
    contextes_attendus: list[str]
    #: Réponse attendue, en clair. Sert à la lecture humaine du rapport.
    reponse_attendue: str
    #: Termes qui doivent figurer dans l'extrait rendu.
    mots_cles: list[str] = field(default_factory=list)
    #: True lorsque le moteur doit refuser de répondre.
    refus_attendu: bool = False


# ── Corpus synthétique ──────────────────────────────────────────────────────

CV_AMIRA = CVSynthetique(
    identifiant="cv_amira",
    texte=(
        "Amira Belhadj — Ingénieure logiciel.\n"
        "Courriel : amira.belhadj@exemple.test. Téléphone : +216 00 000 001.\n"
        "\n"
        "FORMATION\n"
        "Diplôme national d'ingénieur en génie logiciel, obtenu en 2021. "
        "Mastère en informatique appliquée, spécialité systèmes distribués, en 2019.\n"
        "\n"
        "EXPÉRIENCE PROFESSIONNELLE\n"
        "Ingénieure logiciel senior depuis janvier 2022, soit quatre années "
        "d'expérience en développement backend.\n"
        "Conception et maintenance d'interfaces de programmation REST en Python "
        "avec le cadriciel FastAPI, sur une base PostgreSQL.\n"
        "Développement d'interfaces web en Angular et TypeScript pour un portail "
        "de gestion interne.\n"
        "Mise en place d'une chaîne d'intégration continue et conteneurisation "
        "des services avec Docker.\n"
        "\n"
        "COMPÉTENCES TECHNIQUES\n"
        "Langages et cadriciels : Python, FastAPI, Angular, TypeScript, SQL.\n"
        "Bases de données : PostgreSQL, Redis. Outils : Docker, Git.\n"
        "\n"
        "LANGUES\n"
        "Arabe langue maternelle, français courant, anglais professionnel.\n"
    ),
)

CV_KARIM = CVSynthetique(
    identifiant="cv_karim",
    texte=(
        "Karim Trabelsi — Analyste de données.\n"
        "Courriel : karim.trabelsi@exemple.test. Téléphone : +216 00 000 002.\n"
        "\n"
        "FORMATION\n"
        "Licence appliquée en statistique et analyse de l'information, obtenue en 2023.\n"
        "\n"
        "EXPÉRIENCE PROFESSIONNELLE\n"
        "Analyste de données junior depuis septembre 2023, soit un an et demi "
        "d'expérience professionnelle.\n"
        "Construction de tableaux de bord décisionnels et automatisation de "
        "rapports mensuels en Python avec pandas.\n"
        "Nettoyage et consolidation de jeux de données commerciaux sous SQL.\n"
        "\n"
        "COMPÉTENCES TECHNIQUES\n"
        "Langages : Python, SQL, R. Bibliothèques : pandas, scikit-learn, matplotlib.\n"
        "Outils : Excel avancé, Power BI.\n"
        "\n"
        "LANGUES\n"
        "Arabe langue maternelle, français courant.\n"
    ),
)

CORPUS: dict[str, CVSynthetique] = {
    CV_AMIRA.identifiant: CV_AMIRA,
    CV_KARIM.identifiant: CV_KARIM,
}


# ── Cas de test ─────────────────────────────────────────────────────────────

CAS: list[CasDeTest] = [
    # ─ Compétences ─
    CasDeTest(
        identifiant="competences_amira",
        cv="cv_amira",
        question="Quelles compétences techniques possède le candidat ?",
        contextes_attendus=[
            "Langages et cadriciels : Python, FastAPI, Angular, TypeScript, SQL.",
            "Bases de données : PostgreSQL, Redis. Outils : Docker, Git.",
        ],
        reponse_attendue="Python, FastAPI, Angular, TypeScript, SQL, PostgreSQL, Redis, Docker, Git",
        mots_cles=["Python", "Angular", "FastAPI"],
    ),
    CasDeTest(
        identifiant="competences_karim",
        cv="cv_karim",
        question="Quels langages de programmation le candidat maîtrise-t-il ?",
        contextes_attendus=[
            "Langages : Python, SQL, R. Bibliothèques : pandas, scikit-learn, matplotlib.",
        ],
        reponse_attendue="Python, SQL, R",
        mots_cles=["Python", "SQL"],
    ),
    # ─ Expérience ─
    CasDeTest(
        identifiant="experience_amira",
        cv="cv_amira",
        question="Combien d'années d'expérience le candidat possède-t-il ?",
        contextes_attendus=[
            "Ingénieure logiciel senior depuis janvier 2022, soit quatre années "
            "d'expérience en développement backend.",
        ],
        reponse_attendue="Quatre années d'expérience — donc oui, plus de trois ans",
        mots_cles=["quatre", "expérience"],
    ),
    CasDeTest(
        identifiant="experience_karim",
        cv="cv_karim",
        question="Le candidat possède-t-il trois ans d'expérience ?",
        contextes_attendus=[
            "Analyste de données junior depuis septembre 2023, soit un an et demi "
            "d'expérience professionnelle.",
        ],
        reponse_attendue="Non — un an et demi d'expérience seulement",
        mots_cles=["an et demi"],
    ),
    # ─ Formation ─
    CasDeTest(
        identifiant="formation_amira",
        cv="cv_amira",
        question="Quel est son niveau d'études ?",
        contextes_attendus=[
            "Diplôme national d'ingénieur en génie logiciel, obtenu en 2021.",
            "Mastère en informatique appliquée, spécialité systèmes distribués, en 2019.",
        ],
        reponse_attendue="Ingénieur (diplôme national d'ingénieur), et mastère",
        mots_cles=["ingénieur"],
    ),
    CasDeTest(
        identifiant="formation_karim",
        cv="cv_karim",
        question="Quel diplôme le candidat a-t-il obtenu ?",
        contextes_attendus=[
            "Licence appliquée en statistique et analyse de l'information, obtenue en 2023.",
        ],
        reponse_attendue="Licence appliquée en statistique",
        mots_cles=["licence"],
    ),
    # ─ Langues ─
    CasDeTest(
        identifiant="langues_amira",
        cv="cv_amira",
        question="Quelles langues le candidat parle-t-il ?",
        contextes_attendus=[
            "Arabe langue maternelle, français courant, anglais professionnel.",
        ],
        reponse_attendue="Arabe, français, anglais",
        mots_cles=["français", "anglais"],
    ),
    # ─ Reformulation : même information, vocabulaire différent ─
    # Ces cas mesurent ce que le rapprochement sémantique apporte réellement.
    # Une correspondance littérale les manquerait tous.
    CasDeTest(
        identifiant="reformulation_conteneurs",
        cv="cv_amira",
        question="Le candidat a-t-il de l'expérience en conteneurisation ?",
        contextes_attendus=[
            "Mise en place d'une chaîne d'intégration continue et conteneurisation "
            "des services avec Docker.",
        ],
        reponse_attendue="Oui — conteneurisation avec Docker",
        mots_cles=["Docker"],
    ),
    CasDeTest(
        identifiant="reformulation_frontend",
        cv="cv_amira",
        question="Sait-il développer des interfaces côté navigateur ?",
        contextes_attendus=[
            "Développement d'interfaces web en Angular et TypeScript pour un portail "
            "de gestion interne.",
        ],
        reponse_attendue="Oui — Angular et TypeScript",
        mots_cles=["Angular"],
    ),
    CasDeTest(
        identifiant="reformulation_bdd",
        cv="cv_karim",
        question="A-t-il travaillé avec des bases de données relationnelles ?",
        contextes_attendus=[
            "Nettoyage et consolidation de jeux de données commerciaux sous SQL.",
        ],
        reponse_attendue="Oui — SQL",
        mots_cles=["SQL"],
    ),
    # ─ Cas négatifs : le refus est un comportement attendu ─
    CasDeTest(
        identifiant="negatif_permis",
        cv="cv_karim",
        question="Le candidat possède-t-il le permis de conduire poids lourd ?",
        contextes_attendus=[],
        reponse_attendue="Le CV ne contient pas cette information",
        refus_attendu=True,
    ),
    CasDeTest(
        identifiant="negatif_pretentions",
        cv="cv_amira",
        question="Quelles sont ses prétentions salariales ?",
        contextes_attendus=[],
        reponse_attendue="Le CV ne contient pas cette information",
        refus_attendu=True,
    ),
]


def cas_positifs() -> list[CasDeTest]:
    return [c for c in CAS if not c.refus_attendu]


def cas_negatifs() -> list[CasDeTest]:
    return [c for c in CAS if c.refus_attendu]


def statistiques() -> dict:
    return {
        "cvs": len(CORPUS),
        "cases": len(CAS),
        "positive": len(cas_positifs()),
        "negative": len(cas_negatifs()),
    }
