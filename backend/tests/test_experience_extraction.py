"""
Tests de l'extraction des années d'expérience professionnelle
(`NLPService.extract_experience_years`).

Ce chiffre alimente le score de classement ET la négociation salariale : le
surestimer place un candidat au mauvais palier de marché et fausse la
recommandation de salaire.

Le cas de référence est celui remonté en production : un CV structuré
`PROFIL / EXPÉRIENCE / SOFT SKILLS / LANGUES`, où le bloc placé après
« SOFT SKILLS » contenait le cursus scolaire. Trois défauts se cumulaient :

1. Le repère de fin de section exigeait le mot-clé SEUL sur sa ligne :
   « SOFT SKILLS » n'était pas reconnu (qualificatif avant), « FORMATION
   ACADÉMIQUE » non plus (qualificatif après). La section « expérience »
   débordait donc sur la formation.
2. Les années d'études ainsi absorbées étaient comptées comme du travail.
3. Une période « 2025 – 2026 » était comptée jusqu'en décembre, y compris des
   mois futurs.

Résultat : 5,9 ans annoncés pour ~2,7 ans réels.

Tests purs : ni base de données, ni event-loop.
"""
from datetime import datetime

import pytest

from app.services.nlp_service import NLPService


def _annee_courante() -> int:
    return datetime.now().year


# ── Découpage en sections ─────────────────────────────────────────────────────

CV_SOFT_SKILLS = """EMNA EXEMPLE

PROFIL
Développeuse full stack.

EXPÉRIENCE
Développeuse Full Stack — PIQBIT
2024 - 2025
Développement d'applications web.

Stagiaire développement
2025 - 2026
Participation aux projets internes.

SOFT SKILLS
Travail en équipe, autonomie.

Diplôme national d'ingénieur en informatique
2021 - 2024
Institut supérieur.

LANGUES
Français, Anglais
"""


def test_le_bloc_formation_nest_pas_compte_comme_experience():
    """Le cœur du bug : 2021-2024 est un cursus, pas un emploi."""
    annees = NLPService.extract_experience_years(CV_SOFT_SKILLS)
    assert annees is not None
    # 2024 -> aujourd'hui, et surtout PAS les 3 ans d'études en plus.
    assert 2.0 <= annees <= 3.5, f"attendu ~2.7 ans, obtenu {annees}"


def test_soft_skills_ferme_la_section_experience():
    """Un qualificatif AVANT le mot-clé ne doit plus masquer l'en-tête."""
    section = NLPService._find_experience_text(CV_SOFT_SKILLS)
    assert "SOFT SKILLS" not in section
    assert "Institut supérieur" not in section
    assert "PIQBIT" in section


@pytest.mark.parametrize("entete", [
    "SOFT SKILLS", "HARD SKILLS", "FORMATION ACADÉMIQUE", "COMPÉTENCES TECHNIQUES",
    "Formation", "ÉDUCATION", "Centres d'intérêt", "CERTIFICATIONS",
    "Projets personnels", "LANGUES",
])
def test_les_entetes_de_section_courants_sont_reconnus(entete):
    cv = f"EXPÉRIENCE\nPoste A\n2024 - 2025\nMissions diverses.\n\n{entete}\nContenu hors sujet\n2010 - 2015\n"
    section = NLPService._find_experience_text(cv)
    assert "2010" not in section, f"« {entete} » n'a pas fermé la section"


# ── Garde-fou sur les lignes de cursus ────────────────────────────────────────

def test_une_date_sur_une_ligne_de_diplome_est_ignoree():
    """Protège même quand aucun en-tête de section n'est exploitable."""
    cv = ("EXPÉRIENCE\n"
          "Développeur — Société X\n2024 - 2025\n"
          "Master en informatique, Université de Tunis 2018 - 2021\n")
    annees = NLPService.extract_experience_years(cv)
    assert annees is not None
    assert annees < 3.0, f"les 3 ans de master ont été comptés ({annees})"


@pytest.mark.parametrize("ligne", [
    "Diplôme national d'ingénieur 2019 - 2022",
    "Licence en informatique 2016 - 2019",
    "Baccalauréat mathématiques 2015 - 2016",
    "Cycle préparatoire 2016 - 2018",
    "Master recherche, Faculté des Sciences 2020 - 2022",
])
def test_les_lignes_de_cursus_sont_ecartees(ligne):
    ranges = NLPService._extract_date_ranges(ligne)
    assert ranges == [], f"période retenue à tort sur : {ligne}"


def test_une_ligne_de_poste_reste_comptee():
    ranges = NLPService._extract_date_ranges("Développeur Full Stack — PIQBIT 2024 - 2025")
    assert len(ranges) == 1


# ── Plafonnement au mois courant ──────────────────────────────────────────────

def test_une_periode_ne_sétend_pas_dans_le_futur():
    """« 2025 - 2030 » ne vaut pas cinq ans d'expérience acquise."""
    futur = _annee_courante() + 4
    ranges = NLPService._extract_date_ranges(f"Développeur 2025 - {futur}")
    assert len(ranges) == 1
    _, fin = ranges[0]
    assert fin <= NLPService._month_to_abs(datetime.now().month, _annee_courante())


def test_periode_en_cours_equivaut_a_aujourdhui():
    en_cours = NLPService._extract_date_ranges("Développeur Janvier 2024 - Présent")
    borne = NLPService._extract_date_ranges(f"Développeur Janvier 2024 - Décembre {_annee_courante() + 2}")
    assert en_cours and borne
    assert en_cours[0][1] == borne[0][1], "le futur doit être ramené au mois courant"


# ── Comportements conservés ───────────────────────────────────────────────────

def test_les_periodes_qui_se_chevauchent_ne_sont_comptees_quune_fois():
    cv = "EXPÉRIENCE\nPoste A — Société X\n2020 - 2023\nPoste B — Société Y\n2022 - 2024\n"
    annees = NLPService.extract_experience_years(cv)
    assert annees is not None
    # Janvier 2020 -> décembre 2024 inclus = 5 ans, comptés une seule fois.
    assert 4.5 <= annees <= 5.5, f"2020->2024 = ~5 ans, obtenu {annees}"


def test_mention_explicite_utilisee_en_dernier_recours():
    """Sans aucune date exploitable, « 5 ans d'expérience » fait foi."""
    assert NLPService.extract_experience_years(
        "Ingénieur logiciel avec 5 ans d'expérience en développement web."
    ) == 5.0


def test_texte_vide_ou_sans_date():
    assert NLPService.extract_experience_years("") is None
    assert NLPService.extract_experience_years("Profil motivé et curieux.") is None


def test_format_mois_annee():
    ranges = NLPService._extract_date_ranges("Développeur Janvier 2023 - Décembre 2023")
    assert len(ranges) == 1
    debut, fin = ranges[0]
    assert fin - debut == 11


def test_format_mm_aaaa():
    ranges = NLPService._extract_date_ranges("Développeur 03/2022 - 09/2022")
    assert len(ranges) == 1
    debut, fin = ranges[0]
    assert fin - debut == 6


def test_le_resultat_reste_positif_et_plausible():
    """Aucun CV ne doit produire une expérience négative ou absurde."""
    for cv in (CV_SOFT_SKILLS,
               "EXPÉRIENCE\nPoste 2024 - 2025\n",
               "EXPÉRIENCE\nPoste Janvier 2010 - Présent\n"):
        annees = NLPService.extract_experience_years(cv)
        if annees is not None:
            assert 0 < annees < 50
