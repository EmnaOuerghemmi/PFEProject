"""
Service de gestion des décisions pour l'agent de négociation
Évalue les offres salariales et prend des décisions (acceptation/rejet/compromis)
"""
from typing import Dict, Literal, Tuple, Optional
from enum import Enum
from datetime import datetime

def _tnd(montant: float) -> str:
    """Montant mensuel en TND, avec séparateur de milliers : « 2 650 TND ».

    Remplace l'ancien suffixe « k », faux : 2650 n'est pas 2 650 000 TND.
    """
    return f"{montant:,.0f}".replace(",", " ") + " TND"


class NegotiationDecision(str, Enum):
    """Types de décisions possibles"""
    ACCEPT = "accept"
    REJECT = "reject"
    COUNTER_OFFER = "counter_offer"
    PENDING = "pending"


class NegotiationContext:
    """Contexte pour une négociation"""
    
    def __init__(self, 
                 job_id: str,
                 candidate_id: str,
                 job_data: Dict,
                 initial_offer: float):
        self.job_id = job_id
        self.candidate_id = candidate_id
        self.job_data = job_data
        self.initial_offer = initial_offer
        self.counter_offers = []
        self.last_offer = initial_offer
        self.decision_history = []
        self.created_at = datetime.now()
        self.max_iterations = 5
        self.iteration_count = 0
    
    def add_counter_offer(self, amount: float, reason: str = ""):
        """Ajoute une contre-proposition"""
        self.counter_offers.append({
            "amount": amount,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        self.last_offer = amount
        self.iteration_count += 1
    
    def add_decision(self, decision: NegotiationDecision, reason: str):
        """Enregistre une décision"""
        self.decision_history.append({
            "decision": decision,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "offer_amount": self.last_offer
        })


class DecisionService:
    """Service pour prendre des décisions de négociation"""
    
    # Thresholds pour la prise de décision
    ACCEPT_THRESHOLD = 0.95  # Accepter si l'offre est > 95% du salaire prédit
    COUNTER_THRESHOLD = 0.85  # Proposer contre-offre si 85-95%
    REJECT_THRESHOLD = 0.70   # Rejeter si < 70%
    
    def __init__(self):
        self.negotiations = {}
    
    def evaluate_offer(self, 
                      predicted_salary: float,
                      offered_salary: float,
                      confidence: float) -> Tuple[NegotiationDecision, str, Optional[float]]:
        """
        Évalue une offre salariale et retourne une décision
        
        Args:
            predicted_salary: Salaire prédit par le modèle
            offered_salary: Salaire proposé
            confidence: Confiance du modèle (0-1)
        
        Returns:
            Tuple (decision, reason, counter_offer_amount)
        """
        
        # Calculer le ratio offre/prédiction
        ratio = offered_salary / predicted_salary if predicted_salary > 0 else 0
        
        # Ajuster les thresholds en fonction de la confiance
        accept_threshold = self.ACCEPT_THRESHOLD * (0.8 + confidence * 0.2)
        counter_threshold = self.COUNTER_THRESHOLD * (0.8 + confidence * 0.2)
        reject_threshold = self.REJECT_THRESHOLD * (0.8 + confidence * 0.2)
        
        # Prendre une décision
        if ratio >= accept_threshold:
            return NegotiationDecision.ACCEPT, \
                   f"Offre excellente: {ratio:.1%} du salaire prédit", \
                   None
        
        elif ratio >= counter_threshold:
            # Proposer une contre-offre
            counter_amount = self._calculate_counter_offer(
                predicted_salary, 
                offered_salary,
                confidence
            )
            reason = f"Offre acceptable mais négociation possible. " \
                    f"Proposée {ratio:.1%} du salaire prédit. " \
                    f"Contre-offre : {_tnd(counter_amount)}"
            return NegotiationDecision.COUNTER_OFFER, reason, counter_amount
        
        elif ratio >= reject_threshold:
            # Proposer une contre-offre plus agressivement
            counter_amount = self._calculate_counter_offer(
                predicted_salary,
                offered_salary,
                confidence,
                aggressive=True
            )
            reason = f"Offre faible ({ratio:.1%} du prédit). " \
                    f"Contre-offre requise : {_tnd(counter_amount)}"
            return NegotiationDecision.COUNTER_OFFER, reason, counter_amount
        
        else:
            return NegotiationDecision.REJECT, \
                   f"Offre inacceptable: {ratio:.1%} du salaire prédit", \
                   None
    
    def _calculate_counter_offer(self,
                                predicted_salary: float,
                                offered_salary: float,
                                confidence: float,
                                aggressive: bool = False) -> float:
        """
        Calcule une contre-proposition intelligente
        
        Args:
            predicted_salary: Salaire prédit
            offered_salary: Offre actuelle
            confidence: Confiance du modèle
            aggressive: Si True, proposer une augmentation plus agressive
        
        Returns:
            Montant de la contre-proposition
        """
        
        if aggressive:
            # Proposer 92% du salaire prédit
            counter = predicted_salary * 0.92
        else:
            # Proposer un compromis entre l'offre et le salaire prédit
            counter = offered_salary + (predicted_salary - offered_salary) * 0.6
        
        # Ajuster selon la confiance
        confidence_adjustment = 1.0 - (1.0 - confidence) * 0.1
        counter = counter * confidence_adjustment
        
        # Arrondi au dinar (le commentaire « à mille » était faux : `round`
        # sans précision arrondit à l'unité).
        return round(counter)
    
    def create_negotiation(self,
                          job_id: str,
                          candidate_id: str,
                          job_data: Dict,
                          initial_offer: float) -> NegotiationContext:
        """Crée un nouveau contexte de négociation"""
        context = NegotiationContext(job_id, candidate_id, job_data, initial_offer)
        self.negotiations[job_id] = context
        return context
    
    def get_negotiation(self, job_id: str) -> Optional[NegotiationContext]:
        """Récupère un contexte de négociation"""
        return self.negotiations.get(job_id)
    
    def get_negotiation_summary(self, job_id: str) -> Dict:
        """Récupère un résumé de la négociation"""
        context = self.get_negotiation(job_id)
        if not context:
            return {}
        
        return {
            "job_id": context.job_id,
            "candidate_id": context.candidate_id,
            "initial_offer": context.initial_offer,
            "last_offer": context.last_offer,
            "counter_offers": context.counter_offers,
            "iteration_count": context.iteration_count,
            "max_iterations": context.max_iterations,
            "decision_history": context.decision_history,
            "is_ongoing": context.iteration_count < context.max_iterations
        }


# Instance globale
decision_service = None

def get_decision_service() -> DecisionService:
    """Récupère l'instance du service de décision"""
    global decision_service
    if decision_service is None:
        decision_service = DecisionService()
    return decision_service
