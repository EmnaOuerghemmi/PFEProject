"""
Agent de négociation automatique
Gère:
- Lancement de négociation automatique
- Proposition salariale initiale
- Gestion des contre-offres
- Décision automatique: acceptation, rejet, compromis
"""
import asyncio
from typing import Dict, Optional, Callable
from datetime import datetime
import logging

from app.services.salary_prediction_service import get_salary_service
from app.services.decision_service import (
    get_decision_service,
    NegotiationDecision,
    NegotiationContext
)

logger = logging.getLogger(__name__)


class NegotiationAgent:
    """Agent automatique pour la négociation de salaire"""
    
    def __init__(self):
        self.salary_service = get_salary_service()
        self.decision_service = get_decision_service()
        self.websocket_callback: Optional[Callable] = None
    
    def set_websocket_callback(self, callback: Callable):
        """
        Définit un callback pour envoyer les mises à jour via WebSocket
        
        Args:
            callback: Fonction async callback(message: Dict)
        """
        self.websocket_callback = callback
    
    async def _broadcast(self, message: Dict):
        """Envoie un message via WebSocket si un callback est défini"""
        if self.websocket_callback:
            try:
                await self.websocket_callback(message)
            except Exception as e:
                logger.error(f"Erreur lors de l'envoi du message WebSocket: {e}")
    
    async def initiate_negotiation(self,
                                  job_id: str,
                                  candidate_id: str,
                                  job_data: Dict,
                                  employer_offer: float) -> Dict:
        """
        Lance une négociation automatique
        
        Args:
            job_id: ID du job
            candidate_id: ID du candidat
            job_data: Données du job
            employer_offer: Offre initiale de l'employeur
        
        Returns:
            Dict avec le résultat de la négociation
        """
        
        logger.info(f"Démarrage de la négociation pour job {job_id}, candidat {candidate_id}")
        
        await self._broadcast({
            "type": "negotiation_started",
            "job_id": job_id,
            "candidate_id": candidate_id,
            "timestamp": datetime.now().isoformat()
        })
        
        # Créer le contexte de négociation
        context = self.decision_service.create_negotiation(
            job_id, candidate_id, job_data, employer_offer
        )
        
        # Prédire le salaire avec le modèle ML
        try:
            prediction = self.salary_service.predict_salary(job_data)
            predicted_salary = prediction["predicted_salary"]
            confidence = prediction["confidence"]
            
            logger.info(f"Salaire prédit: {predicted_salary}k (confiance: {confidence:.1%})")
            
            await self._broadcast({
                "type": "prediction_made",
                "job_id": job_id,
                "predicted_salary": predicted_salary,
                "predicted_range_min": prediction["range_min"],
                "predicted_range_max": prediction["range_max"],
                "confidence": confidence
            })
            
        except Exception as e:
            logger.error(f"Erreur lors de la prédiction: {e}")
            return {
                "status": "error",
                "message": f"Erreur lors de la prédiction: {str(e)}"
            }
        
        # Évaluer l'offre initiale
        decision, reason, counter_amount = self.decision_service.evaluate_offer(
            predicted_salary,
            employer_offer,
            confidence
        )
        
        logger.info(f"Décision initiale: {decision} - {reason}")
        
        # Enregistrer la décision
        context.add_decision(decision, reason)
        
        await self._broadcast({
            "type": "initial_decision",
            "job_id": job_id,
            "decision": decision.value,
            "reason": reason,
            "counter_offer": counter_amount
        })
        
        # Gérer les contre-propositions selon la décision
        final_result = await self._handle_negotiation(
            context,
            decision,
            counter_amount,
            predicted_salary,
            confidence
        )

        # Expose the prediction so the UI can display it alongside the outcome.
        if isinstance(final_result, dict):
            final_result["predicted_salary"] = predicted_salary
            final_result["confidence"] = confidence
            final_result.setdefault("initial_offer", context.initial_offer)

        return final_result
    
    async def _handle_negotiation(self,
                                 context: NegotiationContext,
                                 decision: NegotiationDecision,
                                 counter_amount: Optional[float],
                                 predicted_salary: float,
                                 confidence: float) -> Dict:
        """Gère l'évolution de la négociation"""
        
        if decision == NegotiationDecision.ACCEPT:
            # Acceptation directe
            result = await self._finalize_negotiation(
                context,
                "ACCEPTED",
                context.initial_offer,
                "Offre acceptée"
            )
            return result
        
        elif decision == NegotiationDecision.REJECT:
            # Rejet de l'offre
            result = await self._finalize_negotiation(
                context,
                "REJECTED",
                context.initial_offer,
                "Offre rejetée - trop faible"
            )
            return result
        
        elif decision == NegotiationDecision.COUNTER_OFFER:
            # Proposer une contre-offre et simuler les échanges
            result = await self._simulate_counter_offers(
                context,
                counter_amount,
                predicted_salary,
                confidence
            )
            return result
        
        else:
            return {
                "status": "pending",
                "job_id": context.job_id,
                "message": "Négociation en attente"
            }
    
    async def _simulate_counter_offers(self,
                                      context: NegotiationContext,
                                      initial_counter: float,
                                      predicted_salary: float,
                                      confidence: float) -> Dict:
        """Simule les échanges de contre-offres"""
        
        logger.info(f"Simulation des contre-offres pour {context.job_id}")
        
        current_counter = initial_counter
        employer_last_offer = context.initial_offer
        
        for round_num in range(context.max_iterations):
            
            # Le candidat propose une contre-offre
            context.add_counter_offer(
                current_counter,
                f"Contre-proposition round {round_num + 1}"
            )
            
            logger.info(f"Round {round_num + 1}: Candidat propose {current_counter}k")
            
            await self._broadcast({
                "type": "counter_offer_sent",
                "job_id": context.job_id,
                "round": round_num + 1,
                "amount": current_counter,
                "timestamp": datetime.now().isoformat()
            })
            
            # Simuler la réaction de l'employeur
            employer_response = self._simulate_employer_response(
                current_counter,
                employer_last_offer,
                predicted_salary,
                round_num
            )
            
            logger.info(f"Réaction employeur: {employer_response['decision']} - {employer_response['reason']}")
            
            await self._broadcast({
                "type": "employer_response",
                "job_id": context.job_id,
                "round": round_num + 1,
                "decision": employer_response["decision"],
                "reason": employer_response["reason"],
                "new_offer": employer_response.get("new_offer")
            })
            
            # Vérifier si un accord est trouvé
            if employer_response["decision"] == "ACCEPT":
                return await self._finalize_negotiation(
                    context,
                    "ACCEPTED",
                    current_counter,
                    f"Accord trouvé au round {round_num + 1}: {current_counter}k"
                )
            
            elif employer_response["decision"] == "REJECT":
                return await self._finalize_negotiation(
                    context,
                    "REJECTED",
                    employer_last_offer,
                    f"Employeur a rejeté après round {round_num + 1}"
                )
            
            # Employer contre-propose
            elif employer_response["decision"] == "COUNTER":
                employer_last_offer = employer_response["new_offer"]
                
                # Évaluer la nouvelle offre
                decision, reason, new_counter = self.decision_service.evaluate_offer(
                    predicted_salary,
                    employer_last_offer,
                    confidence
                )
                
                if decision == NegotiationDecision.ACCEPT:
                    return await self._finalize_negotiation(
                        context,
                        "ACCEPTED",
                        employer_last_offer,
                        f"Acceptation de l'offre employeur: {employer_last_offer}k"
                    )
                
                current_counter = new_counter
            
            # Attendre avant le prochain round
            await asyncio.sleep(0.5)
        
        # Max iterations atteint
        return await self._finalize_negotiation(
            context,
            "COMPROMIS",
            (current_counter + employer_last_offer) / 2,
            f"Compromis après {context.max_iterations} rounds"
        )
    
    def _simulate_employer_response(self,
                                   candidate_offer: float,
                                   employer_last: float,
                                   predicted_salary: float,
                                   round_num: int) -> Dict:
        """
        Simule la réaction de l'employeur
        
        Note: Dans un vrai système, cette réaction viendrait de l'employeur réel
        """
        
        ratio = candidate_offer / predicted_salary
        
        # Accepter si proche du salaire prédit
        if ratio >= 0.98:
            return {
                "decision": "ACCEPT",
                "reason": "Offre très proche du budget"
            }
        
        # Rejeter si beaucoup trop haut
        elif candidate_offer > predicted_salary * 1.1:
            return {
                "decision": "REJECT",
                "reason": "Offre au-delà du budget disponible"
            }
        
        # Contre-proposer
        else:
            # Employer proposer un compromis
            compromise = employer_last + (candidate_offer - employer_last) * 0.4
            compromise = round(compromise)
            
            # Mais jamais au-dessus du salaire prédit
            compromise = min(compromise, int(predicted_salary))
            
            return {
                "decision": "COUNTER",
                "reason": "Volonté de négocier",
                "new_offer": compromise
            }
    
    async def _finalize_negotiation(self,
                                   context: NegotiationContext,
                                   status: str,
                                   final_salary: float,
                                   reason: str) -> Dict:
        """Finalise la négociation"""
        
        logger.info(f"Négociation finalisée: {status} - Salaire: {final_salary}k")
        
        await self._broadcast({
            "type": "negotiation_completed",
            "job_id": context.job_id,
            "status": status,
            "final_salary": final_salary,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        
        return {
            "status": "completed",
            "job_id": context.job_id,
            "candidate_id": context.candidate_id,
            "negotiation_status": status,
            "initial_offer": context.initial_offer,
            "final_salary": int(final_salary),
            "negotiation_rounds": context.iteration_count,
            "reason": reason,
            "summary": self.decision_service.get_negotiation_summary(context.job_id)
        }
    
    async def process_employer_counter_offer(self,
                                            job_id: str,
                                            employer_offer: float,
                                            predicted_salary: float,
                                            confidence: float) -> Dict:
        """
        Traite une contre-offre réelle de l'employeur
        
        Args:
            job_id: ID du job
            employer_offer: Nouvelle offre de l'employeur
            predicted_salary: Salaire prédit
            confidence: Confiance du modèle
        
        Returns:
            Décision du candidat
        """
        
        context = self.decision_service.get_negotiation(job_id)
        if not context:
            return {"status": "error", "message": "Négociation non trouvée"}
        
        # Vérifier si nous n'avons pas dépassé le nombre d'itérations
        if context.iteration_count >= context.max_iterations:
            return {
                "status": "error",
                "message": "Nombre d'itérations maximal atteint"
            }
        
        # Évaluer l'offre
        decision, reason, counter_amount = self.decision_service.evaluate_offer(
            predicted_salary,
            employer_offer,
            confidence
        )
        
        context.add_decision(decision, reason)
        
        await self._broadcast({
            "type": "negotiation_decision",
            "job_id": job_id,
            "decision": decision.value,
            "reason": reason,
            "counter_offer": counter_amount
        })
        
        if decision == NegotiationDecision.ACCEPT:
            return await self._finalize_negotiation(
                context,
                "ACCEPTED",
                employer_offer,
                reason
            )
        else:
            return {
                "status": "counter_offer",
                "decision": decision.value,
                "reason": reason,
                "counter_amount": counter_amount
            }


# Instance globale
negotiation_agent = None

def get_negotiation_agent() -> NegotiationAgent:
    """Récupère l'instance de l'agent de négociation"""
    global negotiation_agent
    if negotiation_agent is None:
        negotiation_agent = NegotiationAgent()
    return negotiation_agent
