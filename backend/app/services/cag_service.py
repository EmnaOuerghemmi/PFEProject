"""
Moteur CAG (Cache-Augmented Generation) — 100 % hors-ligne, sans LLM externe.

Principe :
  1. Un corpus (base de connaissances RH + passages de CV) est embeddé UNE
     seule fois ; les vecteurs sont mis en **cache** (colonne `vector_json` +
     cache mémoire). C'est le « cache-augmented ».
  2. À la question, on n'embed QUE la question, puis on récupère les passages
     les plus proches par cosinus (corpus petit → instantané, marche sur SQLite).
  3. La « génération » est **extractive** : on renvoie le passage/l'entrée
     source le/la plus pertinent·e, tel·le quel·le, avec sa citation et un score
     de confiance. Aucune génération de texte → **zéro hallucination possible**.
  4. Un cache de réponses (question → réponse) rend les questions répétées
     instantanées.

Réutilise `embedding_service` (sentence-transformers si dispo, sinon hash
déterministe) — aucune dépendance à Claude.
"""
import hashlib
import logging
import re
from collections import OrderedDict
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeEntry, CVChunk
from app.models.recruitment import Application, Candidate
from app.models.scoring import CVAnalysis
from app.observability.langfuse_client import (
    TYPE_EMBEDDING,
    TYPE_RETRIEVER,
    langfuse_client,
)
from app.observability.redaction import (
    masquer_identifiant,
    masquer_passages,
    masquer_texte,
    metadonnees_sures,
)
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)

# En-dessous de ce cosinus, on considère qu'aucune source n'est pertinente.
MIN_CONFIDENCE = 0.12

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _split_passages(text: str, *, min_len: int = 20, max_len: int = 400) -> list[str]:
    """Découpe un texte en passages exploitables (phrases / lignes)."""
    raw = [p.strip(" \t•-–·").strip() for p in _SENT_SPLIT.split(text or "")]
    passages: list[str] = []
    for p in raw:
        if len(p) < min_len:
            continue
        # Un passage très long sans ponctuation (fréquent dans les CV) est coupé.
        while len(p) > max_len:
            cut = p.rfind(" ", 0, max_len)
            cut = cut if cut > min_len else max_len
            passages.append(p[:cut].strip())
            p = p[cut:].strip()
        if len(p) >= min_len:
            passages.append(p)
    return passages


class CAGService:
    def __init__(self) -> None:
        # Cache mémoire des vecteurs de la base de connaissances : (id, title,
        # content, category, source, vector). Chargé une fois, invalidé au reindex.
        self._kb_cache: Optional[list[dict]] = None
        self._kb_cache_backend: Optional[str] = None
        # Cache de réponses (LRU simple) : clé (backend, question normalisée).
        self._answer_cache: "OrderedDict[str, dict]" = OrderedDict()
        self._answer_cache_max = 256

    # ── Base de connaissances : seed + indexation (cache) ─────────────────────

    async def seed_default_kb(self, db: AsyncSession) -> int:
        """
        Insère la FAQ et le guide du back-office (idempotent).

        Entrée par entrée, d'après le titre : une base déjà remplie reçoit
        quand même les entrées ajoutées depuis, sans doublon ni écrasement des
        modifications faites à la main.
        """
        existants = set((await db.execute(select(KnowledgeEntry.title))).scalars().all())
        demo = [
            ("Comment postuler à une offre ?", "CANDIDATURE",
             "Pour postuler, ouvrez la page de l'offre depuis « Offres d'emploi », "
             "cliquez sur « Postuler » et téléversez votre CV au format PDF, DOC ou "
             "DOCX (5 Mo maximum). Votre candidature est enregistrée immédiatement et "
             "analysée automatiquement par notre IA."),
            ("Combien de temps pour recevoir une réponse ?", "PROCESS",
             "Le délai moyen de réponse est de 48 heures. Vous êtes notifié·e à chaque "
             "étape : réception de la candidature, planification d'entretien, décision "
             "et négociation."),
            ("Comment se déroule un entretien ?", "ENTRETIEN",
             "Si votre profil est retenu, le recruteur vous propose plusieurs créneaux "
             "d'entretien. Vous choisissez le créneau qui vous convient via un lien "
             "sécurisé, sans avoir à créer de compte supplémentaire. L'entretien est "
             "ajouté à votre agenda et un rappel vous est envoyé."),
            ("Qu'est-ce que le score IA de ma candidature ?", "CANDIDATURE",
             "Chaque candidature reçoit un score de 0 à 100 calculé à partir de trois "
             "critères pondérés : l'adéquation des compétences, l'expérience et la "
             "formation par rapport aux exigences du poste. Un score élevé indique un "
             "profil fortement aligné."),
            ("Comment est déterminé mon salaire ?", "PROCESS",
             "En phase de négociation, un modèle estime une fourchette de salaire de "
             "référence pour le poste sur le marché tunisien. Le recruteur s'appuie sur "
             "cette estimation pour formuler une offre, et la négociation vise le meilleur "
             "accord pour les deux parties."),
            ("Puis-je suivre mes candidatures ?", "CANDIDATURE",
             "Oui. La page « Mes candidatures » affiche en temps réel le statut de "
             "chacune de vos candidatures (en attente, examinée, entretien, acceptée, "
             "rejetée), votre score IA et les prochaines étapes."),
            ("Le matching sémantique, qu'est-ce que c'est ?", "RECRUTEMENT",
             "Le matching sémantique compare le sens de votre CV avec celui de l'offre, "
             "pas seulement les mots-clés exacts. Ainsi, une compétence proche (par "
             "exemple Vue.js pour une offre React) est reconnue comme pertinente."),
            ("Comment protégez-vous mes données ?", "POLITIQUE",
             "Vos données personnelles et votre CV sont stockés de façon isolée par "
             "utilisateur. L'accès est protégé par authentification (JWT), les mots de "
             "passe sont chiffrés, et vos fichiers sont supprimés lorsque vous supprimez "
             "la candidature associée."),
            # ── Guide du back-office (RH, recruteurs, administrateurs) ──
            ("Comment créer une offre d'emploi ?", "GUIDE",
             "Dans « Offres d'emploi », créez une offre. Ouvrez « Décrire le poste », écrivez le "
             "poste en quelques phrases et cliquez sur « Générer les champs » : titre, description, "
             "compétences, expérience, formation, mode de travail et contrat sont proposés. Relisez, "
             "cliquez sur « Suggérer un salaire », puis passez l'offre en « Publiée »."),
            ("Comment envoyer un test technique ?", "GUIDE",
             "Dans « Test technique », générez des questions depuis la banque, validez-les et "
             "mettez-les en service. Dans « Préparer le test », choisissez le candidat puis cliquez "
             "sur « Envoyer le test au candidat » : il reçoit un lien par e-mail, et ses résultats "
             "apparaissent dans « Résultats & évaluation »."),
            ("Comment planifier un entretien ?", "GUIDE",
             "Cliquez sur « Planifier un entretien » (page Entretiens, Test technique ou Décision), "
             "choisissez l'offre puis le candidat, proposez deux ou trois créneaux et ajoutez les "
             "membres qui mèneront l'entretien. Le candidat choisit son créneau depuis l'e-mail reçu ; "
             "un lien Google Meet est créé si votre compte Google est relié."),
            ("Comment évaluer un entretien ?", "GUIDE",
             "Dans « Entretiens », onglet « Passés » puis « À évaluer », cliquez sur « Évaluer "
             "l'entretien ». Saisissez vos notes, demandez si besoin « Proposer une évaluation » "
             "(calculée en local, par critère), puis fixez la note retenue sur 100. Seuls les membres "
             "de l'entretien peuvent l'évaluer."),
            ("Comment appliquer une décision d'embauche ?", "GUIDE",
             "Dans « Décision », choisissez l'offre : chaque candidat a une recommandation expliquée "
             "(Recruter, À confirmer, En réserve, Rejeter). « Appliquer » en fait le statut de la "
             "candidature : acceptée, rejetée avec un e-mail, ou mise en réserve."),
            ("Comment fonctionne la mise en réserve ?", "GUIDE",
             "Un candidat mis « En réserve » reçoit un e-mail l'informant qu'il est gardé dans le "
             "vivier. Dès qu'une offre proche de son profil est publiée, il y est invité "
             "automatiquement."),
            ("Comment envoyer un contrat à signer ?", "GUIDE",
             "Pour un candidat accepté, cliquez sur « Générer le contrat de travail » (Candidatures). "
             "Dans « Contrats », complétez l'identité du salarié et les termes, puis « Envoyer au "
             "candidat pour signature ». Le candidat lit le contrat complet, le signe en ligne, et "
             "l'employé est créé automatiquement."),
            ("Qui peut faire quoi selon son rôle ?", "GUIDE",
             "Le recruteur mène le parcours des candidats : candidatures, classement, tests, "
             "entretiens. Le RH ajoute les offres, les décisions, la négociation, les contrats, les "
             "employés et le budget. L'administrateur ajoute les comptes utilisateurs et les rapports."),
        ]
        nouveaux = [(t, c, txt) for t, c, txt in demo if t not in existants]
        for title, category, content in nouveaux:
            db.add(KnowledgeEntry(title=title, category=category, content=content, source="FAQ PIQBIT"))
        if nouveaux:
            await db.flush()
            self._invalidate_caches()
        return len(nouveaux)

    async def index_knowledge(self, db: AsyncSession) -> int:
        """Embed (met en cache) toutes les entrées dont le vecteur manque ou est
        obsolète (backend d'embedding changé). Retourne le nombre (ré)indexé."""
        backend = embedding_service.backend
        entries = (await db.execute(select(KnowledgeEntry))).scalars().all()
        # Encodage PAR LOT et hors de la boucle d'événements : le modèle batche
        # nativement, et un `embed()` synchrone par entrée figeait toute l'API
        # le temps de la réindexation.
        a_indexer = [e for e in entries if not (e.vector_json and e.model == backend)]
        count = len(a_indexer)
        if count:
            vecteurs = await embedding_service.aembed_many(
                [f"{e.title}\n{e.content}" for e in a_indexer]
            )
            for e, vec in zip(a_indexer, vecteurs):
                e.vector_json = vec
                e.model = backend
            await db.flush()
        self._invalidate_caches()
        return count

    async def _load_kb_cache(self, db: AsyncSession) -> list[dict]:
        """Charge (une fois) les vecteurs KB en cache mémoire pour un backend donné."""
        backend = embedding_service.backend
        if self._kb_cache is not None and self._kb_cache_backend == backend:
            return self._kb_cache
        entries = (await db.execute(select(KnowledgeEntry))).scalars().all()
        # Même traitement par lot que `index_knowledge` : ce cache se remplit
        # au premier /cag/ask, sur potentiellement toute la base de connaissances.
        manquants = [e for e in entries if not e.vector_json or e.model != backend]
        if manquants:
            vecteurs = await embedding_service.aembed_many(
                [f"{e.title}\n{e.content}" for e in manquants]
            )
            for e, vec in zip(manquants, vecteurs):
                e.vector_json = vec
                e.model = backend

        cache: list[dict] = []
        for e in entries:
            cache.append({
                "id": str(e.id), "title": e.title, "content": e.content,
                "category": e.category, "source": e.source, "vector": e.vector_json,
            })
        await db.flush()
        self._kb_cache = cache
        self._kb_cache_backend = backend
        return cache

    def _invalidate_caches(self) -> None:
        self._kb_cache = None
        self._kb_cache_backend = None
        self._answer_cache.clear()

    # ── Question → base de connaissances (RH copilot / assistant) ─────────────

    async def ask(
        self,
        db: AsyncSession,
        question: str,
        *,
        top_k: int = 4,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Répond à une question à partir de la base de connaissances, en mode
        extractif (renvoie l'entrée source la plus pertinente + sources liées).

        `user_id` et `session_id` ne servent qu'au traçage : ils permettent de
        filtrer les traces par personne et de regrouper les questions d'une
        même séance. Ils sont pseudonymisés avant tout envoi.
        """
        question = (question or "").strip()
        if not question:
            return {"answer": "Posez une question.", "confidence": 0.0, "sources": [], "from_cache": False}

        with langfuse_client.trace(
            # Nom actif et à faible cardinalité : il désigne l'opération, pas
            # son exécution. « cag.ask » décrivait le module, pas l'action.
            "answer-knowledge-question",
            entree=masquer_texte(question, etiquette="question"),
            metadata={"top_k": top_k, "embedding_backend": embedding_service.backend},
            user_id=masquer_identifiant(user_id),
            session_id=masquer_identifiant(session_id),
            tags=["cag", "knowledge-base"],
        ) as trace:
            return await self._ask(db, question, top_k, trace)

    async def _ask(self, db: AsyncSession, question: str, top_k: int, trace) -> dict:
        cache_key = self._answer_cache_key(question)
        if cache_key in self._answer_cache:
            cached = dict(self._answer_cache[cache_key])
            cached["from_cache"] = True
            self._answer_cache.move_to_end(cache_key)
            # Le taux de service depuis le cache est l'indicateur le plus utile
            # de ce chemin : il conditionne la latence perçue.
            trace.sortie(**metadonnees_sures(outcome="ok", cache="hit",
                                             confidence=cached.get("confidence")))
            return cached

        kb = await self._load_kb_cache(db)
        if not kb:
            trace.sortie(**metadonnees_sures(outcome="empty", cache="miss"))
            return {"answer": "La base de connaissances est vide.", "confidence": 0.0,
                    "sources": [], "from_cache": False}

        with trace.span("embed-question", type_=TYPE_EMBEDDING,
                        entree=masquer_texte(question, etiquette="question"),
                        modele=embedding_service.backend):
            qv = await embedding_service.aembed(question)

        with trace.span("retrieve-knowledge", type_=TYPE_RETRIEVER,
                        entree=masquer_texte(question, etiquette="question")) as etape:
            scored = sorted(
                ((embedding_service.cosine(qv, e["vector"]), e) for e in kb),
                key=lambda t: t[0], reverse=True,
            )
            best_score, best = scored[0]
            etape.sortie(**metadonnees_sures(
                corpus_size=len(kb),
                retrieved=sum(1 for s, _ in scored[:top_k] if s >= MIN_CONFIDENCE),
                best_score=round(best_score, 4),
                top_scores=[round(s, 4) for s, _ in scored[:top_k]],
            ))

        trace.score("retrieval_confidence", round(best_score, 4))
        trace.sortie(**metadonnees_sures(
            outcome="ok" if best_score >= MIN_CONFIDENCE else "low_confidence",
            cache="miss",
            confidence=round(best_score * 100, 1),
        ))

        if best_score < MIN_CONFIDENCE:
            result = {
                "answer": "Je n'ai pas trouvé de réponse fiable dans la base de "
                          "connaissances. Reformulez votre question ou contactez le support.",
                "confidence": round(best_score * 100, 1),
                "sources": [], "from_cache": False,
            }
        else:
            result = {
                "answer": best["content"],
                "confidence": round(best_score * 100, 1),
                "sources": [
                    {"id": e["id"], "title": e["title"], "category": e["category"],
                     "source": e["source"], "score": round(s * 100, 1)}
                    for s, e in scored[:top_k] if s >= MIN_CONFIDENCE
                ],
                "from_cache": False,
            }

        self._store_answer(cache_key, result)
        return result

    # ── Question → CV d'un candidat (Q&A extractif sourcé) ────────────────────

    async def _ensure_cv_chunks(self, db: AsyncSession, application_id: UUID) -> list[dict]:
        """Découpe + embed (met en cache) les passages d'un CV, une seule fois."""
        backend = embedding_service.backend
        rows = (
            await db.execute(
                select(CVChunk).where(CVChunk.application_id == application_id)
                .order_by(CVChunk.chunk_index)
            )
        ).scalars().all()
        if rows and all(r.model == backend for r in rows):
            return [{"index": r.chunk_index, "content": r.content, "vector": r.vector_json} for r in rows]

        # (Re)construire les chunks depuis le texte brut du CV analysé.
        analysis = (
            await db.execute(select(CVAnalysis).where(CVAnalysis.application_id == application_id))
        ).scalar_one_or_none()
        if not analysis or not (analysis.raw_text or "").strip():
            return []

        for r in rows:  # purge des chunks obsolètes (backend changé)
            await db.delete(r)
        await db.flush()

        passages = _split_passages(analysis.raw_text)
        # Un CV se découpe en dizaines de passages : les encoder un par un
        # multipliait d'autant le gel de la boucle d'événements.
        vecteurs = await embedding_service.aembed_many(passages)
        chunks: list[dict] = []
        for i, (passage, vec) in enumerate(zip(passages, vecteurs)):
            db.add(CVChunk(application_id=application_id, chunk_index=i,
                           content=passage, vector_json=vec, model=backend))
            chunks.append({"index": i, "content": passage, "vector": vec})
        await db.flush()
        return chunks

    async def ask_cv(self, db: AsyncSession, application_id: UUID, question: str,
                     *, top_k: int = 3, user_id: str | None = None,
                     session_id: str | None = None) -> dict:
        """
        Répond à une question sur un CV : renvoie le passage exact du CV le plus
        pertinent (extraction, pas de génération) + le contexte voisin.

        Tracé de bout en bout (Langfuse) lorsque le traçage est actif. Le
        contenu — question, passages, nom du candidat — est masqué par défaut :
        ce chemin manipule des données personnelles de CV.
        """
        question = (question or "").strip()
        with langfuse_client.trace(
            "answer-cv-question",
            entree=masquer_texte(question, etiquette="question"),
            metadata={
                "application": masquer_identifiant(application_id),
                "top_k": top_k,
                "embedding_backend": embedding_service.backend,
            },
            user_id=masquer_identifiant(user_id),
            session_id=masquer_identifiant(session_id),
            # L'étiquette `pii-source` signale que ce chemin manipule des
            # données personnelles : elle permet de retrouver et de purger ces
            # traces en priorité si la rétention devait être revue.
            tags=["cag", "cv", "pii-source"],
        ) as trace:
            app = (
                await db.execute(select(Application).where(Application.id == application_id))
            ).scalar_one_or_none()
            if not app:
                trace.sortie(outcome="not_found")
                return {"error": "application_not_found"}

            with trace.span("chunk-cv", modele=embedding_service.backend) as etape:
                chunks = await self._ensure_cv_chunks(db, application_id)
                etape.sortie(**metadonnees_sures(chunk_count=len(chunks)))

            if not chunks:
                trace.sortie(outcome="not_analyzed")
                return {"error": "cv_not_analyzed"}
            if not question:
                trace.sortie(outcome="empty")
                return {"answer": "Posez une question sur ce CV.", "confidence": 0.0,
                        "passages": []}

            with trace.span("embed-question", type_=TYPE_EMBEDDING,
                            entree=masquer_texte(question, etiquette="question"),
                            modele=embedding_service.backend):
                qv = await embedding_service.aembed(question)

            with trace.span("retrieve-cv-passages", type_=TYPE_RETRIEVER,
                            entree=masquer_texte(question, etiquette="question")) as etape:
                scored = sorted(
                    ((embedding_service.cosine(qv, c["vector"]), c) for c in chunks),
                    key=lambda t: t[0], reverse=True,
                )
                best_score, best = scored[0]
                retenus = [c for s, c in scored[:top_k] if s >= MIN_CONFIDENCE]
                etape.sortie(
                    **metadonnees_sures(
                        corpus_size=len(chunks),
                        retrieved=len(retenus),
                        best_score=round(best_score, 4),
                        # La distribution des scores voisins dit si la
                        # récupération a tranché ou hésité : un écart faible
                        # entre le 1er et le 2e signale une question ambiguë.
                        top_scores=[round(s, 4) for s, _ in scored[:top_k]],
                    ),
                    passages=masquer_passages([c["content"] for c in retenus]),
                )

            # Score exploitable dans le temps : c'est lui qui permettra de
            # détecter une dérive de la récupération après un changement de
            # modèle d'embedding ou de découpage.
            trace.score("retrieval_confidence", round(best_score, 4))

            candidate = (
                await db.execute(select(Candidate).where(Candidate.id == app.candidate_id))
            ).scalar_one_or_none()

            trace.sortie(
                **metadonnees_sures(
                    outcome="ok" if best_score >= MIN_CONFIDENCE else "low_confidence",
                    confidence=round(best_score * 100, 1),
                )
            )
            return self._reponse_cv(scored, best, best_score, candidate, top_k)

    def _reponse_cv(self, scored, best, best_score, candidate, top_k) -> dict:
        """
        Mise en forme de la réponse à une question sur un CV.
        Extraite de `ask_cv` pour que la trace n'ait pas à enjamber deux
        chemins de retour.
        """

        if best_score < MIN_CONFIDENCE:
            return {
                "answer": "Le CV ne semble pas contenir d'information sur ce point.",
                "confidence": round(best_score * 100, 1),
                "passages": [],
                "candidate_name": candidate.full_name if candidate else None,
            }
        return {
            "answer": best["content"],
            "confidence": round(best_score * 100, 1),
            "passages": [
                {"content": c["content"], "score": round(s * 100, 1)}
                for s, c in scored[:top_k] if s >= MIN_CONFIDENCE
            ],
            "candidate_name": candidate.full_name if candidate else None,
        }

    # ── CRUD base de connaissances ────────────────────────────────────────────

    async def list_knowledge(self, db: AsyncSession) -> list[KnowledgeEntry]:
        return list((await db.execute(
            select(KnowledgeEntry).order_by(KnowledgeEntry.category, KnowledgeEntry.title)
        )).scalars().all())

    async def add_knowledge(self, db: AsyncSession, *, title: str, content: str,
                            category: str, source: Optional[str] = None) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            title=title, content=content, category=category, source=source,
            vector_json=await embedding_service.aembed(f"{title}\n{content}"),
            model=embedding_service.backend,
        )
        db.add(entry)
        await db.flush()
        self._invalidate_caches()
        return entry

    async def delete_knowledge(self, db: AsyncSession, entry_id: UUID) -> bool:
        entry = (
            await db.execute(select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id))
        ).scalar_one_or_none()
        if not entry:
            return False
        await db.delete(entry)
        await db.flush()
        self._invalidate_caches()
        return True

    async def stats(self, db: AsyncSession) -> dict:
        kb = (await db.execute(select(func.count(KnowledgeEntry.id)))).scalar_one()
        chunks = (await db.execute(select(func.count(CVChunk.id)))).scalar_one()
        return {
            "backend": embedding_service.backend,
            "knowledge_entries": kb,
            "cached_cv_chunks": chunks,
            "answer_cache_size": len(self._answer_cache),
            "kb_cache_loaded": self._kb_cache is not None,
            "mode": "extractif (sans LLM) — zéro hallucination",
        }

    # ── Cache de réponses ─────────────────────────────────────────────────────

    def _answer_cache_key(self, question: str) -> str:
        norm = re.sub(r"\s+", " ", question.lower().strip())
        raw = f"{embedding_service.backend}::{norm}"
        # Clé de cache, pas une protection : md5 suffit et reste stable.
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

    def _store_answer(self, key: str, result: dict) -> None:
        self._answer_cache[key] = dict(result)
        self._answer_cache.move_to_end(key)
        while len(self._answer_cache) > self._answer_cache_max:
            self._answer_cache.popitem(last=False)


cag_service = CAGService()
