"""
Service pour charger et utiliser le modèle de prédiction de salaire
Utilisé par l'agent de négociation

Version 2: Support complet pour tous les job titles trouvés dans les datasets
- Support pour 45+ job titles
- Classification intelligente par catégorie
- Prédiction améliorée avec confiance adaptatif
"""
import pickle
import os
import logging
import re
import unicodedata
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import warnings

logger = logging.getLogger(__name__)

# numpy/pandas are only needed for the trained-ML path. When they're absent we
# still run perfectly in the rule-based heuristic mode, so import them lazily
# and degrade gracefully instead of crashing the whole negotiations module.
try:
    import numpy as np
    import pandas as pd
    _HAS_ML_DEPS = True
except ImportError:  # pragma: no cover - optional dependency
    np = None  # type: ignore
    pd = None  # type: ignore
    _HAS_ML_DEPS = False

from app.services.salary_features import build_feature_vector, canonical_title

warnings.filterwarnings('ignore')

# Formats de modèle PIQBIT reconnus, du plus ancien au plus récent.
_SUPPORTED_FORMATS = (
    "piqbit_salary_v1", "piqbit_salary_v2", "piqbit_salary_v3", "piqbit_salary_v4",
)

# Algorithme des artefacts antérieurs à v3. Ni le script v1 ni l'ancien
# `scripts/train_salary_model.py` (v2, retiré depuis) n'enregistraient
# `model_name`, et tous deux entraînaient une forêt aléatoire : pour ces
# formats-là, et pour eux seulement, l'absence du champ vaut donc
# « Random Forest ». `scripts/salary_ml_pipeline.py`, seul script
# d'entraînement depuis v3, inscrit le nom du gagnant dans l'artefact.
_ALGO_ARTEFACTS_ANCIENS = "Random Forest"


def _identifiant(nom: str) -> str:
    """
    Nom d'algorithme lisible -> identifiant machine stable.

    « Gradient Boosting » -> « gradient_boosting », « Ridge (α=1.0) » -> « ridge_1_0 ».
    Un artefact ancien donne « random_forest », soit exactement la valeur que
    l'API renvoyait jusqu'ici en dur : la réponse ne change pas pour lui.
    """
    ascii_ = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_") or "inconnu"


class SalaryPredictionService:
    """Service pour prédire les salaires basé sur le modèle ML entraîné (version complète)"""
    
    def __init__(self, model_path: str = None):
        """
        Initialise le service avec le chemin du modèle pickle
        
        Args:
            model_path: Chemin vers le fichier model pickle
                       Si None, essaie d'abord model_comprehensive_titles.p (tous les jobs)
                       Puis model_file.p (ancien modèle)
        """
        self.model = None
        self.scaler = None
        self.classifier = None
        self.feature_names = None
        self.all_job_titles = []
        self.model_path = model_path
        self.is_comprehensive = False
        self.heuristic = False  # True when no trained model is available
        self.piqbit = None      # set when a "piqbit_salary_v1…v4" model is loaded
        self.band_model = False  # True when the model predicts [min, avg, max]
        self._title_cache: Dict[str, Optional[str]] = {}
        self._load_model()
    
    def _load_model(self):
        """Charge le modèle depuis le fichier pickle"""
        
        # Essayer d'abord le modèle complet avec tous les titles
        paths_to_try = []
        if self.model_path:
            paths_to_try.append(self.model_path)
        
        # Ajouter les chemins par défaut (priorité au modèle sérialisable)
        paths_to_try.extend([
            "salary_model_piqbit.p",
            "backend/salary_model_piqbit.p",
            "../salary_model_piqbit.p",
            "model_comprehensive_serializable.p",
            "backend/model_comprehensive_serializable.p",
            "../model_comprehensive_serializable.p",
            "model_comprehensive_titles.p",
            "backend/model_comprehensive_titles.p",
            "../model_comprehensive_titles.p",
            "model_file.p",
            "backend/model_file.p",
            "../model_file.p"
        ])
        
        for model_file in paths_to_try:
            if os.path.exists(model_file):
                try:
                    with open(model_file, "rb") as pickled:
                        data = pickle.load(pickled)
                        
                        # Vérifier si c'est le modèle complet ou ancien
                        if isinstance(data, dict):
                            # Modèles PIQBIT successifs, tous supportés :
                            #   v1 — sortie scalaire (salary_avg), pas de bandes
                            #   v2 — sortie [min, avg, max] + bandes de calibrage
                            #   v3 — idem v2 + amplitude du palier d'expérience,
                            #        modèle choisi par comparaison sur jeu de test
                            #        (`scripts/salary_ml_pipeline.py`)
                            # Le niveau d'études a été retiré des features en v3 :
                            # colinéaire avec la séniorité dans le dataset, il
                            # était appris comme un proxy de séniorité et gonflait
                            # de 53 % toute offre junior déclarant « ingénieur ».
                            if data.get("format") in _SUPPORTED_FORMATS:
                                self.piqbit = data
                                self.model = data.get("model")
                                self.band_model = len(data.get("targets") or []) == 3
                                self.feature_names = data.get("feature_names")
                                logger.info(f"PIQBIT salary model loaded: {model_file} "
                                            f"(format={self.model_version}, "
                                            f"algo={self.model_name}, "
                                            f"{len(data.get('categories', []))} catégories, "
                                            f"bandes={'oui' if self.band_model else 'non'})")
                                return
                            self.model = data.get("model")
                            self.scaler = data.get("scaler")
                            self.feature_names = data.get("feature_names")
                            
                            # Nouveau format complet (sérialisable)
                            if data.get("job_to_category") and data.get("category_mapping"):
                                self.classifier = data
                                self.all_job_titles = data.get("all_job_titles", [])
                                self.is_comprehensive = True
                                logger.info(f"Comprehensive salary model loaded: {model_file} "
                                            f"({len(self.all_job_titles)} job titles)")
                                return
                            # Ancien format avec classe CustomClassifier
                            elif data.get("classifier"):
                                self.classifier = data.get("classifier")
                                self.all_job_titles = data.get("all_job_titles", [])
                                self.is_comprehensive = True
                                logger.info(f"Salary model loaded: {model_file} "
                                            f"({len(self.all_job_titles)} job titles)")
                                return
                        else:
                            self.model = data
                            logger.info(f"Legacy salary model loaded: {model_file}")
                            return
                except Exception as e:
                    logger.warning(f"Could not load salary model {model_file}: {e}")
                    continue
        
        # No trained pickle on disk → fall back to a transparent rule-based
        # estimator so the negotiation module stays functional in V1 without
        # requiring a multi-minute training step.
        self.heuristic = True
        logger.info("No trained salary model found - using heuristic estimator (V1 fallback).")

    # ── Identité du modèle servi ────────────────────────────────────────────
    # L'artefact est la SEULE source de vérité sur l'algorithme. Un libellé
    # écrit en dur dans ce service a déjà divergé une fois : l'API annonçait
    # « random_forest » alors que le pipeline avait retenu Gradient Boosting.
    # Le gagnant peut changer à chaque réentraînement ; ces propriétés le
    # suivent sans que personne ait à y penser.

    @property
    def model_name(self) -> Optional[str]:
        """Nom lisible de l'algorithme réellement chargé, ou None sans modèle PIQBIT."""
        if self.piqbit is None:
            return None
        return self.piqbit.get("model_name") or _ALGO_ARTEFACTS_ANCIENS

    @property
    def model_type(self) -> str:
        """Identifiant machine du modèle servi, dérivé de l'artefact (ex. « ml_gradient_boosting »)."""
        if self.model_name is None:
            return "heuristic"
        return f"ml_{_identifiant(self.model_name)}"

    @property
    def model_version(self) -> Optional[str]:
        """Format de l'artefact chargé (ex. « piqbit_salary_v3 »), ou None sans modèle PIQBIT."""
        return self.piqbit.get("format") if self.piqbit else None

    def prepare_features(self, job_data: Dict) -> np.ndarray:
        """
        Prépare les features pour le modèle basé sur les données du job
        
        Version 2: Support pour le modèle complet avec classification intelligente
        
        Args:
            job_data: Dictionnaire avec les informations du job
                - title: Titre du job
                - description: Description du job
                - rating: Note de l'entreprise (0-5)
                - python, spark, aws, excel: Compétences requises (0/1)
        
        Returns:
            Array de features pour le modèle
        """
        
        if self.is_comprehensive and self.classifier:
            # Utiliser le modèle complet avec classification
            return self._prepare_features_comprehensive(job_data)
        else:
            # Fallback sur l'ancien format
            return self._prepare_features_legacy(job_data)
    
    def _prepare_features_comprehensive(self, job_data: Dict) -> np.ndarray:
        """Prépare les features pour le modèle complet"""
        
        job_title = str(job_data.get('title', 'Unknown'))
        
        # Features de base
        features = {
            'rating': float(job_data.get('rating', 3.5)),
            'python': int(job_data.get('python', 0)),
            'spark': int(job_data.get('spark', 0)),
            'aws': int(job_data.get('aws', 0)),
            'excel': int(job_data.get('excel', 0)),
            'description_length': len(str(job_data.get('description', ''))),
        }
        
        # Ajouter les features de catégorie (one-hot encoding)
        if self.classifier and isinstance(self.classifier, dict):
            # Nouveau format sérialisable
            job_to_category = self.classifier.get('job_to_category', {})
            category_mapping = self.classifier.get('category_mapping', {})
            
            category = job_to_category.get(job_title, 'Other')
            category_id = category_mapping.get(category, category_mapping.get('Other', 0))
            
            for cat_name, cat_id in category_mapping.items():
                features[f'category_{cat_name}'] = 1 if cat_id == category_id else 0
        else:
            # Ancien format avec classe
            if self.classifier:
                category = self.classifier.get_category(job_title)
                category_id = self.classifier.encode_category(job_title)
                
                for cat_name, cat_id in self.classifier.category_mapping.items():
                    features[f'category_{cat_name}'] = 1 if cat_id == category_id else 0
        
        # Créer le vecteur de features dans l'ordre des feature_names
        feature_vector = []
        if self.feature_names:
            for fname in self.feature_names:
                if fname in features:
                    feature_vector.append(features[fname])
                else:
                    feature_vector.append(0)  # Default pour les catégories manquantes
        
        return np.array(feature_vector).reshape(1, -1)
    
    def _prepare_features_legacy(self, job_data: Dict) -> np.ndarray:
        """Ancien format de features (legacy)"""
        
        features = {}
        
        # Features numériques
        features['Rating'] = float(job_data.get('rating', 3.5))
        features['Age'] = float(job_data.get('company_age', 10))
        features['desc_len'] = len(str(job_data.get('description', '')))
        features['Num_comp'] = int(job_data.get('competitors_count', 0))
        features['PerHour'] = int(job_data.get('is_hourly', 0))
        features['Employee'] = int(job_data.get('employee_provided', 0))
        features['Same State'] = int(job_data.get('same_state', 0))
        
        # Skills features
        features['Python_yn'] = int(job_data.get('python', 0))
        features['Spark'] = int(job_data.get('spark', 0))
        features['AWS_yn'] = int(job_data.get('aws', 0))
        features['Excel_yn'] = int(job_data.get('excel', 0))
        
        # Job simplification
        job_title_lower = str(job_data.get('title', '')).lower()
        if 'data scientist' in job_title_lower:
            job_simp = 'data scientist'
        elif 'data engineer' in job_title_lower:
            job_simp = 'data engineer'
        elif 'analyst' in job_title_lower:
            job_simp = 'analyst'
        elif 'machine learning' in job_title_lower:
            job_simp = 'mle'
        else:
            job_simp = 'na'
        
        features['Job_simp'] = job_simp
        
        # Seniority
        if 'sr' in job_title_lower or 'senior' in job_title_lower or 'lead' in job_title_lower:
            features['seniority'] = 'senior'
        elif 'jr' in job_title_lower:
            features['seniority'] = 'jr'
        else:
            features['seniority'] = 'na'
        
        # Categorical encoding (one-hot encoding)
        df_temp = pd.DataFrame([features])
        df_encoded = pd.get_dummies(df_temp)
        
        return df_encoded.values
    
    def predict_salary(self, job_data: Dict) -> Dict:
        """
        Prédit le salaire pour un job donné, puis ajuste selon le profil du
        candidat quand `job_data["candidate_match_score"]` est fourni (0-100 :
        score de matching CV/poste). Sans ce champ (ex. suggestion à la
        création d'une offre, avant tout candidat), la prédiction reste basée
        sur le poste seul — comportement inchangé.

        Version 2: Utilise le modèle complet avec support pour 45+ job titles

        Args:
            job_data: Dictionnaire avec les informations du job (+ optionnel
                `candidate_match_score`)

        Returns:
            Dict avec:
                - predicted_salary: Salaire prédit (en milliers)
                - confidence: Confiance de la prédiction (0-1)
                - range_min: Salaire minimum (0-1 quantile)
                - range_max: Salaire maximum (0-1 quantile)
                - job_category: Catégorie du job (si modèle complet)
                - supported_titles: Nombre de job titles supportés
        """
        result = self._predict_salary_core(job_data)
        match_score = job_data.get("candidate_match_score")
        if match_score is not None:
            result = self._apply_match_adjustment(result, match_score)
        return result

    def _apply_match_adjustment(self, result: Dict, match_score) -> Dict:
        """
        Nudge la prédiction ±10% selon la qualité du matching CV/poste : un
        candidat très en dessous du profil recherché a un pouvoir de
        négociation plus faible (et inversement). Factor linéaire borné,
        décision explicable plutôt qu'une boîte noire.

        Le facteur s'applique au POINT de référence uniquement. La fourchette
        de marché (`range_min`/`range_max`) reste celle du modèle : le score de
        matching d'un candidat déplace sa position DANS le marché, il ne
        déplace pas le marché lui-même. Le point ajusté est simplement borné
        par la fourchette pour rester cohérent.
        """
        try:
            score = max(0.0, min(100.0, float(match_score)))
        except (TypeError, ValueError):
            return result
        factor = 0.9 + 0.002 * score  # 0.90 (score=0) .. 1.10 (score=100)
        base = result.get("predicted_salary", 0)
        adjusted = max(800, int(round(base * factor / 50.0) * 50))
        range_min = result.get("range_min")
        range_max = result.get("range_max")
        if range_min is not None and range_max is not None:
            adjusted = min(max(adjusted, int(range_min)), int(range_max))
        return {
            **result,
            "predicted_salary": adjusted,
            "match_adjustment_factor": round(factor, 3),
        }

    def _predict_salary_core(self, job_data: Dict) -> Dict:
        # Trained PIQBIT model takes priority (uses seniority + experience).
        if self.piqbit is not None:
            return self._predict_piqbit(job_data)

        if self.model is None:
            # No ML model loaded → use the heuristic estimator.
            return self._predict_salary_heuristic(job_data)

        try:
            features = self.prepare_features(job_data)
            
            # Appliquer le scaler si disponible
            if self.scaler and self.is_comprehensive:
                features = self.scaler.transform(features)
            
            prediction = self.model.predict(features)[0]
            
            # Le modèle retourne une valeur en milliers
            predicted_salary = int(prediction)
            
            # Calculer une confiance basée sur la cohérence des données
            confidence = self._calculate_confidence(job_data)
            
            result = {
                "predicted_salary": predicted_salary,
                "confidence": confidence,
                "range_min": int(predicted_salary * 0.9),
                "range_max": int(predicted_salary * 1.1),
            }
            
            # Ajouter des infos du modèle complet
            if self.is_comprehensive:
                job_title = str(job_data.get('title', 'Unknown'))
                
                # Get category from classifier
                if self.classifier and isinstance(self.classifier, dict):
                    job_to_category = self.classifier.get('job_to_category', {})
                    category = job_to_category.get(job_title, 'Other')
                else:
                    category = self.classifier.get_category(job_title) if self.classifier else 'Other'
                
                result["job_category"] = category
                result["supported_titles"] = len(self.all_job_titles)
                result["model_type"] = "comprehensive"
            else:
                result["model_type"] = "legacy"
            
            return result
            
        except Exception as e:
            raise Exception(f"Erreur lors de la prédiction: {str(e)}")
    
    @staticmethod
    def _guess_category(title: str) -> str:
        t = title.lower()
        if any(k in t for k in ("data scientist", "data engineer", "data analyst", "machine learning", "ml ", "analyst")): return "Data"
        if any(k in t for k in ("design", "ux", "ui")): return "Design"
        if any(k in t for k in ("manager", "lead", "scrum", "product", "project", "architect")): return "Management"
        if any(k in t for k in ("hr", "rh", "recruit", "talent", "ressources humaines")): return "RH"
        if any(k in t for k in ("sales", "commercial", "account", "business develop")): return "Commercial"
        if any(k in t for k in ("marketing", "content", "community", "seo")): return "Marketing"
        if any(k in t for k in ("financ", "account", "comptab")): return "Finance"
        if any(k in t for k in ("support", "customer", "success")): return "Support"
        return "Tech"

    # Mots de séniorité → ordinal (aligné avec l'entraînement : Junior..Lead = 1..4).
    _SENIORITY_WORDS = {
        "junior": 1, "jr": 1, "intern": 1, "stage": 1, "stagiaire": 1, "débutant": 1, "debutant": 1,
        "mid": 2, "confirmé": 2, "confirme": 2, "intermediate": 2, "intermédiaire": 2,
        "senior": 3, "sr": 3,
        "lead": 4, "head": 4, "principal": 4, "manager": 4, "architect": 4, "director": 4,
    }

    # Mots qui désignent un MÉTIER, pas un niveau. « Software Architect » et
    # « HR Manager » existent au barème en Senior ET en Lead : les traiter comme
    # des marqueurs de séniorité classait un architecte de 7 ans en Lead et le
    # surcotait de deux paliers. Ils ne servent donc plus que de dernier recours,
    # quand ni le titre ni l'expérience ne disent rien.
    _ROLE_IMPLIED_SENIORITY = ("head", "principal", "manager", "architect", "director", "chief")

    @classmethod
    def _seniority_from_title(cls, title: str):
        """Ordinal de séniorité déduit d'un marqueur EXPLICITE du titre, sinon None."""
        t = f" {title.lower()} "
        if " lead " in t or t.strip().endswith(" lead") or "tech lead" in t: return 4
        if "senior" in t or " sr " in t or " sr." in t: return 3
        if any(k in t for k in ("junior", " jr ", "intern", "stage", "stagiaire", "débutant", "debutant")): return 1
        if any(k in t for k in (" mid ", "confirmé", "confirme", "intermediate", "intermédiaire")): return 2
        return None

    @classmethod
    def _seniority_from_role(cls, title: str):
        """Séniorité suggérée par la nature du poste — signal faible, dernier recours."""
        t = title.lower()
        return 4 if any(k in t for k in cls._ROLE_IMPLIED_SENIORITY) else None

    @staticmethod
    def _seniority_from_experience(exp) -> Optional[int]:
        """Ordinal de séniorité déduit des ANNÉES d'expérience (seuils marché TN)."""
        if exp is None:
            return None
        try:
            exp = float(exp)
        except (TypeError, ValueError):
            return None
        if exp < 2: return 1
        if exp < 5: return 2
        if exp < 8: return 3
        return 4

    @classmethod
    def _normalize_seniority(cls, value) -> Optional[int]:
        """Normalise une séniorité fournie explicitement (mot ou ordinal 1..4)."""
        if value is None:
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            v = int(value)
            return v if 1 <= v <= 4 else None
        return cls._SENIORITY_WORDS.get(str(value).strip().lower())

    @classmethod
    def _resolve_seniority(cls, title: str, exp=None, explicit=None) -> int:
        """
        Séniorité effective, par ordre de priorité :
        1) valeur explicite (job_data['seniority'])
        2) marqueur explicite de niveau dans le titre (junior / senior / lead…)
        3) déduction depuis les années d'expérience — plus fiable qu'un
           intitulé de métier, c'est la donnée réelle du profil
        4) nature du poste (manager, architecte…) quand rien d'autre n'est connu
        5) défaut = Mid (2)
        """
        return (
            cls._normalize_seniority(explicit)
            or cls._seniority_from_title(title)
            or cls._seniority_from_experience(exp)
            or cls._seniority_from_role(title)
            or 2
        )

    @classmethod
    def _guess_seniority(cls, title: str) -> int:
        """Rétro-compat : séniorité depuis le titre seul, défaut Mid."""
        return cls._seniority_from_title(title) or 2

    # Ratios min/avg et max/avg du barème de référence, utilisés pour dériver une
    # fourchette quand le modèle chargé ne prédit qu'un point (format v1).
    _BAND_RATIO_MIN = 0.845
    _BAND_RATIO_MAX = 1.180

    # Élargissement toléré autour de la bande empirique de référence : la sortie
    # ML peut sortir du barème (interpolation entre paliers), mais pas dériver.
    _BAND_CLAMP_LOW = 0.92
    _BAND_CLAMP_HIGH = 1.08

    # Poids de l'ancrage sur le barème (shrinkage vers le prior empirique).
    # Une bande observée au niveau du TITRE est une mesure directe de la cible ;
    # au niveau de la CATÉGORIE, c'est une agrégation, donc moins fiable.
    _ANCHOR_WEIGHT_TITLE = 0.70
    _ANCHOR_WEIGHT_CATEGORY = 0.45

    # Bornes d'expérience par palier, alignées sur le dataset (repli quand le
    # titre n'y figure pas).
    _DEFAULT_EXPERIENCE_BANDS = {1: (0.0, 2.0), 2: (2.0, 4.0), 3: (5.0, 8.0), 4: (8.0, 15.0)}

    @staticmethod
    def _round50(value: float) -> int:
        return int(round(float(value) / 50.0) * 50)

    def canonical_title(self, title: str) -> Optional[str]:
        """
        Titre du barème correspondant à l'intitulé de l'offre, ou `None`.

        Le barème est en anglais, les offres PIQBIT en français : sans cette
        normalisation, la recherche par titre échouait TOUJOURS en production et
        le service retombait systématiquement sur la bande — plus grossière — de
        la catégorie. Le résultat est mémoïsé : la normalisation compare
        l'intitulé aux 57 titres connus, inutile de la refaire à chaque appel.
        """
        if self.piqbit is None:
            return None
        cle = str(title or "").strip().lower()
        if cle not in self._title_cache:
            self._title_cache[cle] = canonical_title(
                title, (self.piqbit.get("title_to_category") or {}).keys()
            )
        return self._title_cache[cle]

    def _reference_band(
        self, title: str, category: str, seniority: int
    ) -> Tuple[Optional[List[float]], float]:
        """
        Bande empirique (min, avg, max) issue du dataset pour ce couple
        titre × séniorité, avec repli sur catégorie × séniorité, accompagnée du
        poids d'ancrage à lui accorder. `(None, 0.0)` si le modèle chargé ne
        l'embarque pas (format v1).
        """
        p = self.piqbit or {}
        title_bands = p.get("title_bands") or {}
        category_bands = p.get("category_bands") or {}
        canonique = self.canonical_title(title)
        if canonique:
            band = title_bands.get(f"{canonique}|{seniority}")
            if band:
                return list(band), self._ANCHOR_WEIGHT_TITLE
        band = category_bands.get(f"{category}|{seniority}")
        if band:
            return list(band), self._ANCHOR_WEIGHT_CATEGORY
        return None, 0.0

    def _palier_experience(self, title: str, seniority: int) -> Tuple[float, float]:
        """Bornes d'expérience du palier de séniorité, telles qu'observées dans le barème."""
        p = self.piqbit or {}
        canonique = self.canonical_title(title)
        observed = (p.get("title_experience") or {}).get(f"{canonique}|{seniority}") if canonique else None
        if observed and len(observed) >= 2 and observed[1] > observed[0]:
            return float(observed[0]), float(observed[1])
        return self._DEFAULT_EXPERIENCE_BANDS.get(seniority, (2.0, 4.0))

    def _predict_band_raw(self, vec: List[float]) -> List[float]:
        """
        Sortie brute du modèle sous forme de triplet (min, avg, max).

        Le modèle v2 prédit les trois cibles ; le v1 ne prédit que la moyenne,
        auquel cas la fourchette est dérivée des ratios du barème.
        """
        out = self.model.predict(np.array(vec, dtype=float).reshape(1, -1))[0]
        values = np.atleast_1d(out).astype(float).tolist()
        if len(values) >= 3:
            return values[:3]
        avg = values[0]
        return [avg * self._BAND_RATIO_MIN, avg, avg * self._BAND_RATIO_MAX]

    def _predict_piqbit(self, job_data: Dict) -> Dict:
        """
        Prédit avec le modèle entraîné chargé (catégorie + séniorité + expérience
        + compétences). L'algorithme est celui que le pipeline a retenu et inscrit
        dans l'artefact : `model_type` et `model_version` le déclarent tel quel.
        """
        band = self.market_band(job_data)
        confidence = self._calculate_confidence(job_data)
        return {
            "predicted_salary": band["avg"],
            "confidence": round(confidence, 2),
            "range_min": band["min"],
            "range_max": band["max"],
            "model_type": self.model_type,
            "model_version": self.model_version,
            "job_category": band["category"],
            "seniority": band["seniority"],
            "currency": "TND",
            "period": "mensuel",
        }

    def market_band(self, job_data: Dict) -> Dict:
        """
        Fourchette de marché (min / avg / max) pour un poste donné.

        C'est le point d'entrée « marché » du service : il rend une FOURCHETTE,
        pas un point, parce qu'un salaire de marché n'est jamais un nombre
        unique. Le point (`avg`) reste disponible comme référence centrale.

        Pipeline :
          1. Résolution du palier de séniorité (titre explicite > expérience).
          2. Inférence multi-sortie du modèle chargé AU CENTRE du palier — les
             lignes d'entraînement portent l'expérience médiane de leur palier,
             interroger le modèle sur une année de frontière (2 ans, 5 ans…)
             produisait sinon une bande écrasée vers le palier inférieur.
          3. Plancher de monotonie sur les paliers inférieurs (un ensemble
             d'arbres n'est pas monotone : il peut coter un Senior sous un Mid).
          4. Ancrage (shrinkage) sur la bande empirique du barème puis bornage
             dans son enveloppe ±8 %.
          5. `avg` = point positionné DANS la bande selon les années réelles.

        Repli sur l'estimateur heuristique si aucun modèle n'est chargé.
        """
        if self.piqbit is None or self.model is None:
            fallback = self._predict_salary_heuristic(job_data)
            title = str(job_data.get("title", ""))
            seniority = self._resolve_seniority(
                title, job_data.get("experience_years"), job_data.get("seniority")
            )
            return {
                "min": fallback["range_min"],
                "avg": fallback["predicted_salary"],
                "band_avg": fallback["predicted_salary"],
                "max": fallback["range_max"],
                "seniority": seniority,
                "seniority_label": self.SENIORITY_LABELS.get(seniority, "Confirmé"),
                "experience_band": list(self._DEFAULT_EXPERIENCE_BANDS.get(seniority, (2.0, 4.0))),
                "position_in_band": 0.5,
                "category": self._guess_category(title),
                "source": "heuristic",
                "reference_band": None,
                "currency": "TND",
                "period": "mensuel",
            }

        p = self.piqbit
        title = str(job_data.get("title", ""))
        canonique = self.canonical_title(title)
        category = (
            p["title_to_category"].get(canonique) if canonique else None
        ) or self._guess_category(title)
        explicit_seniority = job_data.get("seniority")

        # Multi-hot over the trained skill vocabulary, built from the offer's
        # skills text (falls back to the legacy python/spark/aws/excel flags).
        vocab = p.get("skill_vocab") or p.get("skill_flags") or []
        skills_text = str(job_data.get("skills_text", ""))
        if not skills_text.strip():
            skills_text = " ".join(
                s for s in ("python", "spark", "aws", "excel") if int(job_data.get(s, 0))
            )

        def band_for(seniority: int) -> List[float]:
            """Bande du palier, interrogée au centre de sa plage d'expérience."""
            exp_lo, exp_hi = self._palier_experience(title, seniority)
            centre = (exp_lo + exp_hi) / 2.0
            if p.get("format") in ("piqbit_salary_v3", "piqbit_salary_v4"):
                # Vecteur construit par le module PARTAGÉ avec l'entraînement :
                # les deux chemins ne peuvent pas diverger.
                vec = build_feature_vector(
                    category=category, categories=p["categories"],
                    seniority=seniority, experience_years=centre,
                    experience_span=exp_hi - exp_lo,
                    skills_text=skills_text, skill_vocab=vocab,
                )
            else:
                # Formats v1/v2 : pas d'amplitude, détection de compétences par
                # sous-chaîne (telle qu'à leur entraînement).
                bits = [1 if term in skills_text.lower() else 0 for term in vocab]
                vec = ([1 if category == c else 0 for c in p["categories"]]
                       + [seniority, centre] + bits)
            return self._predict_band_raw(vec)

        exp_input = job_data.get("experience_years")
        years = None if exp_input is None else float(exp_input)
        seniority = self._resolve_seniority(title, years, explicit_seniority)

        band = band_for(seniority)

        # Monotonie : jamais moins que ce que le même poste vaudrait à un palier
        # inférieur. Le modèle, entraîné sur peu d'exemples, ne le garantit pas.
        for lower in range(1, seniority):
            floor = band_for(lower)
            band = [max(band[i], floor[i]) for i in range(3)]

        # Ancrage sur le barème (shrinkage vers le prior empirique) puis bornage
        # dans son enveloppe ±8 % : le modèle interpole, le barème encadre.
        reference, weight = self._reference_band(title, category, seniority)
        if reference and weight:
            band = [weight * reference[i] + (1 - weight) * band[i] for i in range(3)]
            low, high = reference[0] * self._BAND_CLAMP_LOW, reference[2] * self._BAND_CLAMP_HIGH
            band = [min(max(v, low), high) for v in band]

        lo, mid, hi = sorted(band)
        # Largeur minimale : une fourchette collapsée n'aurait aucun sens métier.
        lo = min(lo, mid * 0.93)
        hi = max(hi, mid * 1.07)

        # Le point de référence se positionne DANS la bande selon les années
        # réelles : à l'entrée du palier on vise le bas de fourchette, à sa
        # sortie le haut. Sans expérience connue, on reste au centre.
        exp_lo, exp_hi = self._palier_experience(title, seniority)
        if years is None or exp_hi <= exp_lo:
            ratio = 0.5
        else:
            ratio = min(max((years - exp_lo) / (exp_hi - exp_lo), 0.0), 1.0)
        point = lo + ratio * (hi - lo)

        return {
            "min": max(600, self._round50(lo)),
            "avg": max(700, self._round50(point)),
            "band_avg": max(700, self._round50(mid)),
            "max": max(800, self._round50(hi)),
            "seniority": seniority,
            "seniority_label": self.SENIORITY_LABELS.get(seniority, "Confirmé"),
            "experience_band": [exp_lo, exp_hi],
            "position_in_band": round(ratio, 3),
            "category": category,
            "source": self.model_type,
            "reference_band": reference,
            "currency": "TND",
            "period": "mensuel",
        }

    # Libellés des paliers de séniorité, pour les explications lisibles.
    SENIORITY_LABELS = {1: "Junior", 2: "Confirmé", 3: "Senior", 4: "Lead"}

    def negotiation_bands(
        self,
        *,
        title: str,
        skills_text: str = "",
        description: str = "",
        required_experience_years: Optional[float] = None,
        candidate_experience_years: Optional[float] = None,
        seniority_hint: Optional[str] = None,
    ) -> Dict:
        """
        Les DEUX bandes de marché nécessaires à une analyse de négociation :

          - `job` : ce que le POSTE vaut sur le marché, au niveau réellement
            demandé par l'offre (`required_experience_years`).
          - `candidate` : ce que le CANDIDAT vaut sur le marché, au niveau de
            son expérience réelle.

        Les confondre est l'erreur métier corrigée ici : un candidat de 6 ans
        qui postule sur un poste ouvert à 2 ans d'expérience ne transforme pas
        le poste en poste senior — mais il ne vaut pas non plus le prix d'un
        profil de 2 ans.

        La fourchette de marché retenue interpole donc entre les deux, avec un
        poids `w` égal à la PART DE L'EXPÉRIENCE DU CANDIDAT QUI EXCÈDE le
        niveau demandé :

            w = (années_candidat − années_requises) / années_candidat

        * expérience égale au requis  → w = 0 → fourchette du poste ;
        * expérience double du requis → w = 0.5 → à mi-chemin ;
        * offre sans exigence         → w = 1 → fourchette du candidat.

        Grandeur bornée, monotone, et lisible par un RH sans connaître le
        modèle : c'est l'écart au poste qui déplace le marché, rien d'autre.
        """
        base = {"title": title, "skills_text": skills_text, "description": description}

        job_band = self.market_band({
            **base,
            "experience_years": required_experience_years,
            "seniority": seniority_hint,
        })
        candidate_band = (
            self.market_band({**base, "experience_years": candidate_experience_years})
            if candidate_experience_years is not None
            else dict(job_band)
        )

        weight = self._excess_experience_weight(
            candidate_experience_years, required_experience_years
        )

        def blend(key: str) -> int:
            return self._round50(
                job_band[key] + weight * (candidate_band[key] - job_band[key])
            )

        return {
            "job": job_band,
            "candidate": candidate_band,
            "market_min": blend("min"),
            "market_max": blend("max"),
            "market_reference": blend("avg"),
            "candidate_weight": round(weight, 3),
            "category": job_band["category"],
            "source": job_band["source"],
            "currency": "TND",
            "period": "mensuel",
        }

    @staticmethod
    def _excess_experience_weight(
        candidate_years: Optional[float], required_years: Optional[float]
    ) -> float:
        """Part de l'expérience du candidat qui dépasse l'exigence du poste, dans [0, 1]."""
        if candidate_years is None:
            return 0.0
        try:
            candidate = float(candidate_years)
        except (TypeError, ValueError):
            return 0.0
        if candidate <= 0:
            return 0.0
        if required_years is None:
            return 1.0  # aucune exigence affichée : le candidat fait référence
        try:
            required = max(float(required_years), 0.0)
        except (TypeError, ValueError):
            return 1.0
        return min(max((candidate - required) / candidate, 0.0), 1.0)

    def _predict_salary_heuristic(self, job_data: Dict) -> Dict:
        """
        Rule-based estimate of a realistic **Tunisian monthly salary (TND)** used
        when no trained ML model is available. Anchors on a base monthly wage and
        adds premiums for role family, seniority and in-demand skills. Values are
        rounded to the nearest 50 TND. Deterministic and explainable.
        """
        title = str(job_data.get("title", "")).lower()

        base = 1500.0  # base monthly salary in TND
        # Role family premium
        if any(k in title for k in ("data scientist", "machine learning", "ml ", "ai ")):
            base += 1500
        elif any(k in title for k in ("data engineer", "devops", "cloud", "architect")):
            base += 1300
        elif any(k in title for k in ("developer", "engineer", "software", "developpeur", "développeur")):
            base += 900
        elif any(k in title for k in ("analyst", "analyste")):
            base += 500

        # Seniority premium
        if any(k in title for k in ("senior", "sr ", "lead", "principal", "head", "manager")):
            base += 1000
        elif any(k in title for k in ("junior", "jr ", "intern", "stage", "stagiaire")):
            base -= 500

        # In-demand skills premium
        base += 300 * int(job_data.get("python", 0))
        base += 250 * int(job_data.get("spark", 0))
        base += 300 * int(job_data.get("aws", 0))
        base += 80 * int(job_data.get("excel", 0))

        # Company rating nudges the estimate slightly (~0.92x at 0★ to ~1.12x at 5★)
        rating = float(job_data.get("rating", 3.5))
        base *= (0.92 + 0.04 * rating)

        predicted = max(1000, int(round(base / 50.0) * 50))  # round to nearest 50 TND
        confidence = self._calculate_confidence(job_data)
        return {
            "predicted_salary": predicted,
            "confidence": round(min(confidence, 0.7), 2),  # cap confidence for heuristic
            "range_min": int(round(predicted * 0.9 / 50.0) * 50),
            "range_max": int(round(predicted * 1.1 / 50.0) * 50),
            "model_type": "heuristic",
            "currency": "TND",
            "period": "mensuel",
        }

    # Plafonds de confiance selon la QUALITÉ DE LA SOURCE du chiffre, et non la
    # quantité de champs remplis. Le barème lui-même n'est qu'une estimation de
    # marché (cf. README du dataset) : même parfaitement appariée, une bande ne
    # mérite pas 90 %.
    _CONFIDENCE_EXACT_TITLE = 0.75      # bande titre × séniorité trouvée
    _CONFIDENCE_CATEGORY = 0.55         # repli sur la famille de métier
    _CONFIDENCE_EXTRAPOLATION = 0.40    # aucune bande : sortie ML seule
    _CONFIDENCE_HEURISTIC = 0.30        # aucun modèle chargé

    def _calculate_confidence(self, job_data: Dict) -> float:
        """
        Confiance (0-1) dans la fourchette produite.

        Elle exprime la QUALITÉ DE LA SOURCE, pas la complétude du formulaire.
        La version précédente additionnait un point par champ renseigné et
        atteignait 90 % dès qu'une offre était bien remplie — un chiffre
        rassurant mais faux : remplir la description ne rend pas le marché plus
        certain. Le plafond dépend désormais de ce sur quoi la prédiction
        s'appuie réellement :

          * bande du barème pour ce titre ET ce palier      -> 0.75
          * repli sur la famille de métier                  -> 0.55
          * extrapolation du modèle, aucune bande connue    -> 0.40
          * estimateur heuristique (aucun modèle chargé)    -> 0.30

        Ce plafond est ensuite abaissé quand un signal manque : sans années
        d'expérience ni mot de séniorité, le palier lui-même est une supposition.
        """
        title = str(job_data.get("title", ""))
        if self.piqbit is None:
            base = self._CONFIDENCE_HEURISTIC
        else:
            seniority = self._resolve_seniority(
                title, job_data.get("experience_years"), job_data.get("seniority")
            )
            category = self.canonical_title(title)
            category = (self.piqbit["title_to_category"].get(category)
                        if category else None) or self._guess_category(title)
            _, poids = self._reference_band(title, category, seniority)
            base = {
                self._ANCHOR_WEIGHT_TITLE: self._CONFIDENCE_EXACT_TITLE,
                self._ANCHOR_WEIGHT_CATEGORY: self._CONFIDENCE_CATEGORY,
            }.get(poids, self._CONFIDENCE_EXTRAPOLATION)

        # Le palier est-il connu, ou deviné ? C'est le facteur qui pèse le plus
        # sur le résultat : se tromper de palier, c'est se tromper de fourchette.
        if job_data.get("experience_years") is None and not self._seniority_from_title(title):
            base -= 0.15
        # Compétences renseignées : elles nuancent la position dans la bande.
        has_skills = bool(str(job_data.get("skills_text", "")).strip()) or any(
            job_data.get(k) for k in ("python", "spark", "aws", "excel")
        )
        if not has_skills:
            base -= 0.05

        return round(max(0.2, min(base, 0.75)), 2)


# Instance globale du service
salary_service = None

def get_salary_service() -> SalaryPredictionService:
    """Récupère l'instance du service de prédiction de salaire"""
    global salary_service
    if salary_service is None:
        salary_service = SalaryPredictionService()
    return salary_service
