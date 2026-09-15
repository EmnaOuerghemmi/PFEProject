"""
Tests du pipeline de préparation des données salariales
(`scripts/salary_ml_pipeline.py`).

Ce qui est verrouillé ici est ce qui, mal fait, empoisonne silencieusement le
modèle :

* la conversion **net → brut** (barème social tunisien réel, pas un coefficient
  forfaitaire) et son inversibilité ;
* la **normalisation des unités** — annuel/mensuel, EUR/TND, net/brut : toutes
  les observations doivent finir dans la même unité, sinon le modèle apprend la
  convention de saisie plutôt que le salaire ;
* le fait qu'une valeur extrême n'est **jamais supprimée automatiquement** : un
  métier dont tous les paliers dévient du même facteur est un positionnement de
  marché, pas une anomalie.

Tests purs : ni base de données, ni event-loop.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("sklearn")
pd = pytest.importorskip("pandas")

BACKEND_DIR = Path(__file__).resolve().parents[1]
PIPELINE = BACKEND_DIR / "scripts" / "salary_ml_pipeline.py"
RAW_DATASET = BACKEND_DIR / "datasets" / "tunisia_it_salaries.csv"


def _load_pipeline():
    """
    Charge le script du pipeline comme un module.

    Il doit être enregistré dans `sys.modules` AVANT exécution : le décorateur
    `@dataclass` résout ses annotations via `sys.modules[cls.__module__]`, et
    échouerait sur un module chargé hors du registre.
    """
    spec = importlib.util.spec_from_file_location("salary_ml_pipeline", PIPELINE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pipeline():
    return _load_pipeline()


# ── Barème social : net ⇄ brut ────────────────────────────────────────────────

def test_net_et_brut_sont_reciproques(pipeline):
    """gross→net puis net→gross doit revenir au point de départ."""
    for gross in (1200, 2000, 3500, 6000, 9000):
        net = pipeline.gross_to_net_monthly(gross)
        assert pipeline.net_to_gross_monthly(net) == pytest.approx(gross, abs=1.0)


def test_le_net_est_toujours_inferieur_au_brut(pipeline):
    for gross in (1000, 2500, 5000, 10000):
        assert 0 < pipeline.gross_to_net_monthly(gross) < gross


def test_le_taux_de_prelevement_croit_avec_le_salaire(pipeline):
    """Barème progressif : un haut salaire doit subir un prélèvement relatif plus fort."""
    def rate(gross: float) -> float:
        return 1 - pipeline.gross_to_net_monthly(gross) / gross

    assert rate(1500) < rate(4000) < rate(9000)


def test_conversion_net_brut_dans_les_ordres_de_grandeur_tunisiens(pipeline):
    """
    Le net va de ~84 % du brut en bas d'échelle à ~62 % en haut, l'IRPP étant
    progressif. Bornes larges volontairement : on vérifie l'ordre de grandeur du
    barème tunisien, pas une valeur au dinar près.
    """
    for gross in (1000, 2000, 3000, 4000, 9000):
        ratio = pipeline.gross_to_net_monthly(gross) / gross
        assert 0.60 <= ratio <= 0.86, f"ratio net/brut hors normes pour {gross} : {ratio:.3f}"


def test_net_to_gross_gere_les_valeurs_degenerees(pipeline):
    assert pipeline.net_to_gross_monthly(0) == 0.0
    assert pipeline.net_to_gross_monthly(-100) == 0.0


# ── Normalisation des unités ──────────────────────────────────────────────────

def _row(**overrides) -> dict:
    base = dict(
        title="Test Developer", category="Tech", seniority="Mid",
        experience_years_min=2, experience_years_max=4,
        salary_min_tnd=2000.0, salary_avg_tnd=2500.0, salary_max_tnd=3000.0,
        currency="TND", period="mensuel_brut", education="Ingénieur",
        top_skills="python, sql", region="Tunisie", source="test",
        salary_basis="brut", population="marche_reference",
        quality_flag="ok", quality_note="",
    )
    base.update(overrides)
    return base


def test_un_salaire_annuel_est_ramene_au_mensuel(pipeline):
    df = pd.DataFrame([_row(period="annuel_brut", salary_min_tnd=24000.0,
                            salary_avg_tnd=30000.0, salary_max_tnd=36000.0)])
    report = pipeline.AuditReport()
    result = pipeline._normalize_units(df, report)
    assert result.salary_avg_tnd.iloc[0] == pytest.approx(2500.0)
    assert result.period.iloc[0] == "mensuel_brut"


def test_un_salaire_en_euros_est_converti_en_dinars(pipeline):
    df = pd.DataFrame([_row(currency="EUR", salary_min_tnd=800.0,
                            salary_avg_tnd=1000.0, salary_max_tnd=1200.0)])
    report = pipeline.AuditReport()
    result = pipeline._normalize_units(df, report)
    assert result.salary_avg_tnd.iloc[0] == pytest.approx(1000.0 * pipeline.EUR_TO_TND)
    assert result.currency.iloc[0] == "TND"


def test_un_salaire_net_est_converti_en_brut(pipeline):
    df = pd.DataFrame([_row(salary_basis="net", salary_min_tnd=1600.0,
                            salary_avg_tnd=2000.0, salary_max_tnd=2400.0)])
    report = pipeline.AuditReport()
    result = pipeline._normalize_units(df, report)
    assert result.salary_avg_tnd.iloc[0] > 2000.0
    assert result.salary_avg_tnd.iloc[0] == pytest.approx(
        round(pipeline.net_to_gross_monthly(2000.0)), abs=1
    )
    assert result.salary_basis.iloc[0] == "brut"


def test_les_conversions_se_cumulent_dans_le_bon_ordre(pipeline):
    """Annuel + EUR + net : les trois doivent s'appliquer, devise puis période puis base."""
    df = pd.DataFrame([_row(currency="EUR", period="annuel", salary_basis="net",
                            salary_min_tnd=4800.0, salary_avg_tnd=6000.0,
                            salary_max_tnd=7200.0)])
    report = pipeline.AuditReport()
    result = pipeline._normalize_units(df, report)
    attendu_net_mensuel = 6000.0 * pipeline.EUR_TO_TND / 12.0
    assert result.salary_avg_tnd.iloc[0] == pytest.approx(
        round(pipeline.net_to_gross_monthly(attendu_net_mensuel)), abs=1
    )
    assert len(report.unit_conversions) == 1
    assert len(report.unit_conversions[0]["conversions"]) == 3


def test_une_ligne_deja_normalisee_nest_pas_touchee(pipeline):
    df = pd.DataFrame([_row()])
    report = pipeline.AuditReport()
    result = pipeline._normalize_units(df, report)
    assert result.salary_avg_tnd.iloc[0] == 2500.0
    assert report.unit_conversions == []


# ── Valeurs extrêmes : diagnostiquer, pas supprimer ───────────────────────────

# Paliers de référence utilisés pour bâtir un groupe de pairs synthétique.
_PALIERS = (("Junior", 1500), ("Mid", 2500), ("Senior", 3800), ("Lead", 5000))


def _peer_group() -> list[dict]:
    """
    Groupe de pairs assez fourni pour que la médiane du palier soit stable.

    Avec deux lignes seulement par palier, la médiane serait tirée par la valeur
    testée elle-même : le diagnostic mesurerait alors le sujet contre lui-même.
    """
    return [
        _row(title=f"Pair {index} {seniority}", seniority=seniority, salary_avg_tnd=salary)
        for seniority, salary in _PALIERS
        for index in range(5)
    ]

def test_un_metier_regulierement_decale_nest_pas_signale(pipeline, capsys):
    """
    Quatre paliers tous à ~0.70× la médiane de leur famille = métier moins bien
    payé que sa catégorie, pas erreur de saisie. Aucune anomalie ne doit sortir.
    """
    rows = _peer_group()
    for seniority, peer in _PALIERS:
        rows.append(_row(title="Métier Modeste", seniority=seniority, salary_avg_tnd=peer * 0.70))
    report = pipeline.AuditReport()
    pipeline._diagnose_outliers(pd.DataFrame(rows), report)

    assert report.outliers == []
    assert "Positionnement de MÉTIER" in capsys.readouterr().out


def test_une_deviation_irreguliere_est_signalee(pipeline):
    """Un seul palier hors motif = anomalie réelle, qui doit remonter."""
    rows = _peer_group()
    rows += [
        _row(title="Métier Suspect", seniority="Junior", salary_avg_tnd=1500),
        _row(title="Métier Suspect", seniority="Mid", salary_avg_tnd=2500),
        _row(title="Métier Suspect", seniority="Senior", salary_avg_tnd=300),  # aberrant
    ]
    report = pipeline.AuditReport()
    pipeline._diagnose_outliers(pd.DataFrame(rows), report)

    assert len(report.outliers) == 1
    assert report.outliers[0]["title"] == "Métier Suspect"
    assert report.outliers[0]["seniority"] == "Senior"


def test_une_erreur_de_facteur_douze_est_diagnostiquee(pipeline):
    """Un montant annuel saisi en mensuel doit être reconnu comme tel."""
    row = pd.Series(_row(salary_avg_tnd=30000.0))
    diagnosis = pipeline._explain_deviation(row, ratio=12.0, median=2500.0)
    assert "unité" in diagnosis.lower()


def test_un_haut_de_marche_est_conserve(pipeline):
    """Un architecte ou un profil expatrié n'est pas du bruit."""
    row = pd.Series(_row(title="Solutions Architect", salary_avg_tnd=9000.0))
    diagnosis = pipeline._explain_deviation(row, ratio=1.9, median=4700.0)
    assert "Conservé" in diagnosis


def test_aucune_ligne_nest_supprimee_par_le_diagnostic(pipeline):
    """Le diagnostic est en lecture seule : il rapporte, il ne filtre pas."""
    df = pd.DataFrame([
        _row(title="A", seniority="Mid", salary_avg_tnd=2500),
        _row(title="B", seniority="Mid", salary_avg_tnd=99999),
    ])
    report = pipeline.AuditReport()
    pipeline._diagnose_outliers(df, report)
    assert len(df) == 2


# ── Le dataset livré ──────────────────────────────────────────────────────────

def test_le_dataset_brut_porte_les_colonnes_daudit():
    df = pd.read_csv(RAW_DATASET)
    for column in ("salary_basis", "population", "quality_flag", "quality_note"):
        assert column in df.columns, f"colonne d'audit manquante : {column}"


def test_le_dataset_brut_reste_coherent():
    df = pd.read_csv(RAW_DATASET)
    assert df.duplicated(subset=["title", "seniority"]).sum() == 0
    assert (df.salary_min_tnd <= df.salary_avg_tnd).all()
    assert (df.salary_avg_tnd <= df.salary_max_tnd).all()
    assert (df.experience_years_min <= df.experience_years_max).all()


def test_le_pipeline_produit_un_dataset_homogene(pipeline, tmp_path):
    """Après nettoyage, plus une seule ligne en net ou en annuel."""
    raw = pd.read_csv(RAW_DATASET)
    report = pipeline.AuditReport()
    clean = pipeline.clean(raw, report)

    assert (clean.salary_basis == "brut").all()
    assert (clean.period == "mensuel_brut").all()
    assert (clean.currency == "TND").all()
    assert clean.quality_flag.eq("ok").all()
    # Les lignes écartées le sont avec un motif écrit, jamais silencieusement.
    assert all(entry["reason"] for entry in report.excluded)
