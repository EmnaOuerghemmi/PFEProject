"""
Endpoints pour la gestion de la négociation automatique
"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query
from pydantic import BaseModel, Field, field_validator
from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.agents.decision_agent import get_negotiation_agent
from app.core.rbac import require
from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.negotiation_repository import negotiation_repository
from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)


class SalaryPredictionRequest(BaseModel):
    """
    Requête de prédiction salariale standalone (sans lancer de négociation).

    Le corps vient d'un formulaire encore en cours de saisie : un champ texte
    vidé remonte à `null`, un champ numérique vidé peut remonter à `""`. Une
    suggestion d'aide à la décision n'a aucune raison de refuser ces valeurs —
    elle les traite comme « non renseigné ». Les bornes de `experience_years`,
    elles, sont conservées : accepter 60 ans d'expérience en le ramenant
    silencieusement à 50 rendrait une estimation fausse sans le dire.
    """

    title: str = Field(..., description="Titre du poste")
    description: str = Field(default="", description="Description du poste")
    skills_text: str = Field(default="", description="Compétences (texte libre)")
    experience_years: Optional[float] = Field(default=None, ge=0, le=50)
    seniority: Optional[str] = Field(default=None, description="junior/mid/senior/lead")
    rating: float = Field(default=3.5, ge=0, le=5)

    @field_validator("description", "skills_text", mode="before")
    @classmethod
    def _texte_absent_vaut_vide(cls, v):
        return "" if v is None else v

    @field_validator("experience_years", "seniority", mode="before")
    @classmethod
    def _chaine_vide_vaut_absent(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

# Prédictions salariales et contre-offres : réservées au back-office. Seule
# l'authentification les protégeait — un candidat connecté pouvait lancer une
# négociation et lire les salaires prédits pour n'importe quelle offre.
router = APIRouter(
    prefix="/api/v1/negotiations",
    tags=["negotiations"],
    dependencies=[Depends(require("negotiations", "read"))],
)


class JobDataRequest(BaseModel):
    """Données du job pour la négociation (features du modèle salaire TN)."""
    job_id: str = Field(..., description="ID du job")
    title: str = Field(..., description="Titre du job")
    description: str = Field(default="", description="Description du job")

    # ── Features principales du modèle TN (salary_model_piqbit.p) ─────────────
    skills_text: str = Field(
        default="", description="Compétences requises (texte libre, ex. 'React, SQL, AWS')"
    )
    experience_years: Optional[float] = Field(
        default=None, ge=0, le=50, description="Années d'expérience requises"
    )
    seniority: Optional[str] = Field(
        default=None, description="Séniorité explicite (junior/mid/senior/lead) — optionnel"
    )

    # ── Compat / signaux secondaires ─────────────────────────────────────────
    rating: float = Field(default=3.5, ge=0, le=5, description="Note de l'entreprise")
    python: int = Field(default=0, description="Python requis (0/1)")
    spark: int = Field(default=0, description="Spark requis (0/1)")
    aws: int = Field(default=0, description="AWS requis (0/1)")
    excel: int = Field(default=0, description="Excel requis (0/1)")


class NegotiationRequest(BaseModel):
    """Requête pour lancer une négociation"""
    candidate_id: str = Field(..., description="ID du candidat")
    job_data: JobDataRequest = Field(..., description="Données du job")
    employer_offer: float = Field(..., gt=0, description="Offre initiale de l'employeur (en k)")


class CounterOfferRequest(BaseModel):
    """Requête pour traiter une contre-offre employeur"""
    job_id: str = Field(..., description="ID du job")
    employer_offer: float = Field(..., gt=0, description="Nouvelle offre de l'employeur")
    predicted_salary: float = Field(..., gt=0, description="Salaire prédit")
    confidence: float = Field(default=0.7, ge=0, le=1, description="Confiance du modèle")


class NegotiationSummaryResponse(BaseModel):
    """Résumé d'une négociation"""
    job_id: str
    candidate_id: str
    initial_offer: float
    final_salary: int
    negotiation_rounds: int
    negotiation_status: str
    reason: str


@router.post("/initiate")
async def initiate_negotiation(
    request: NegotiationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict:
    """
    Lance une négociation automatique de salaire

    - Prédit le salaire avec le modèle ML
    - Évalue l'offre initiale
    - Gère les contre-offres automatiquement
    - Persiste la négociation et ses rounds en base
    - Retourne la décision finale
    """
    try:
        agent = get_negotiation_agent()

        # Convertir job_data en dict
        job_data = request.job_data.model_dump()

        result = await agent.initiate_negotiation(
            job_id=request.job_data.job_id,
            candidate_id=request.candidate_id,
            job_data=job_data,
            employer_offer=request.employer_offer
        )

        # Persister la négociation (best-effort : ne bloque pas la réponse live).
        try:
            await negotiation_repository.persist_agent_run(
                db, candidate_id=request.candidate_id, result=result
            )
        except Exception as persist_exc:  # pragma: no cover - defensive
            logger.warning(f"Persistance de la négociation échouée: {persist_exc}")

        try:
            await notification_service.notify_admins(
                db, actor=current_user, type="NEGOTIATION_STARTED",
                title="Négociation salariale lancée",
                message=(f"{current_user.full_name or current_user.username} a lancé une négociation "
                         f"pour « {request.job_data.title} »."),
                link="/admin/negotiation",
            )
            await db.commit()
        except Exception as notif_exc:  # pragma: no cover - defensive
            logger.warning(f"Notification admin (négociation) échouée: {notif_exc}")

        return result

    except Exception as e:
        logger.error(f"Erreur lors du lancement de la négociation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-counter-offer")
async def process_counter_offer(
    request: CounterOfferRequest,
    current_user: User = Depends(get_current_user)
) -> Dict:
    """
    Traite une contre-offre réelle de l'employeur
    
    Utilisé pour continuer une négociation en attente avec une nouvelle offre employeur
    """
    try:
        agent = get_negotiation_agent()
        
        result = await agent.process_employer_counter_offer(
            job_id=request.job_id,
            employer_offer=request.employer_offer,
            predicted_salary=request.predicted_salary,
            confidence=request.confidence
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement de la contre-offre: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/{job_id}")
async def get_negotiation_summary(
    job_id: str,
    current_user: User = Depends(get_current_user)
) -> Dict:
    """Récupère le résumé d'une négociation"""
    try:
        agent = get_negotiation_agent()
        summary = agent.decision_service.get_negotiation_summary(job_id)
        
        if not summary:
            raise HTTPException(status_code=404, detail="Négociation non trouvée")
        
        return summary
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du résumé: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/predict-salary")
async def predict_salary(
    request: SalaryPredictionRequest,
    current_user: User = Depends(get_current_user),
) -> Dict:
    """
    Prédit le salaire (TND mensuel) pour un poste **sans lancer de négociation**.

    Utile pour afficher une fourchette de référence côté RH (avant de fixer
    l'offre) et pour tester le modèle ML directement. Utilise le modèle entraîné
    `salary_model_piqbit.p` s'il est présent, sinon l'estimateur heuristique.

    La réponse déclare le modèle qui l'a produite, lu dans l'artefact chargé et
    non écrit dans ce code : `model_type` (ex. `ml_gradient_boosting`, ou
    `heuristic` sans modèle) et `model_version` (ex. `piqbit_salary_v3`).
    """
    import asyncio

    from app.services.salary_prediction_service import get_salary_service

    job_data = {
        "title": request.title,
        "description": request.description,
        "skills_text": request.skills_text,
        "experience_years": request.experience_years,
        "seniority": request.seniority,
        "rating": request.rating,
    }

    # scikit-learn et pandas sont synchrones : appelés directement ici, ils
    # figent la boucle d'événements — donc toute l'API — pendant le calcul,
    # et surtout pendant le dépicklage du modèle au premier appel (~2,5 s
    # mesurées). `to_thread` sort ce travail du fil de la boucle.
    def _predire() -> Dict:
        return get_salary_service().predict_salary(job_data)

    return await asyncio.to_thread(_predire)


@router.get("/history/{job_id}")
async def get_negotiation_history(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict:
    """Récupère la dernière négociation **persistée** (avec ses rounds) pour un job."""
    negotiation = await negotiation_repository.get_latest_by_job(db, job_id)
    if not negotiation:
        raise HTTPException(status_code=404, detail="Aucune négociation persistée pour ce job")
    rounds = await negotiation_repository.list_rounds(db, negotiation.id)
    return negotiation_repository.to_summary(negotiation, rounds)


@router.get("/")
async def list_negotiations(
    status: Optional[str] = Query(default=None, description="Filtrer par statut"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict:
    """Liste les négociations persistées (backoffice RH)."""
    items = await negotiation_repository.list(db, status=status, limit=limit, offset=offset)
    return {
        "items": [negotiation_repository.to_summary(n, list(n.rounds)) for n in items],
        "count": len(items),
    }


@router.get("/stats")
async def negotiation_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict:
    """Statistiques agrégées des négociations (par statut)."""
    return await negotiation_repository.stats(db)


@router.websocket("/ws/{job_id}")
async def websocket_negotiation_updates(websocket: WebSocket, job_id: str):
    """
    WebSocket pour recevoir les mises à jour en temps réel de la négociation
    
    Connectez-vous avec: ws://localhost:8000/api/v1/negotiations/ws/{job_id}
    """
    await websocket.accept()
    
    try:
        agent = get_negotiation_agent()
        
        # Définir le callback pour envoyer les mises à jour
        async def send_update(message: Dict):
            await websocket.send_json(message)
        
        agent.set_websocket_callback(send_update)
        
        # Garder la connexion ouverte
        while True:
            # Attendre les messages du client (pour les cas où l'employeur envoie une réponse)
            data = await websocket.receive_json()
            
            if data.get("type") == "employer_response":
                # Traiter la réponse réelle de l'employeur
                result = await agent.process_employer_counter_offer(
                    job_id=job_id,
                    employer_offer=data.get("amount"),
                    predicted_salary=data.get("predicted_salary", 0),
                    confidence=data.get("confidence", 0.7)
                )
                await websocket.send_json(result)
    
    except WebSocketDisconnect:
        logger.info(f"Client déconnecté du WebSocket pour job {job_id}")
    except Exception as e:
        logger.error(f"Erreur WebSocket: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})
