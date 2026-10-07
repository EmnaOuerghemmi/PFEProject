from typing import Annotated
from uuid import UUID
from pathlib import Path
import logging
from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, status, UploadFile,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rbac import autorise, require
from app.core.dependencies import (
    get_current_active_user,
    get_current_user_optional,
    rate_limit,
)
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.recruitment import Application, Candidate, JobOffer
from app.schemas.candidate_feedback import ApplicationScoreDetail
from app.services.candidate_feedback_service import candidate_feedback_service
from app.schemas.recruitment import (
    JobOfferCreate, JobOfferUpdate, JobOfferResponse, PaginatedJobOffers,
    CandidateCreate, CandidateResponse, ApplicationCreate, ApplicationUpdate, ApplicationResponse,
    MyApplicationResponse, CandidateCvResponse, CvVerificationResponse, ExpectedSalaryUpdate,
    JobExtractionRequest, JobExtractionResponse, JobExtractionFields,
    JobRecommendations,
    WORK_MODE_PATTERN, CONTRACT_TYPE_PATTERN, JOB_STATUS_PATTERN,
)
from app.agents.job_extraction_agent import job_extraction_agent
from app.services.recruitment_service import recruitment_service
from app.services.notification_service import notification_service, APPLICATION_STATUS_LABELS
from app.agents.scoring_agent import scoring_agent
from app.services.recommendation_service import recommendation_service
from app.services import cv_storage
from app.services.cv_detection import verifier_document
from app.utils.helpers import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/jobs", response_model=PaginatedJobOffers)
async def list_jobs(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: str | None = None,
    sort_by: str | None = None,
    work_mode: str | None = Query(None, pattern=WORK_MODE_PATTERN),
    contract_type: str | None = Query(None, pattern=CONTRACT_TYPE_PATTERN),
):
    """
    Listing **public** (frontoffice) : uniquement les offres publiées et non
    expirées. Les brouillons et les offres fermées ne sortent jamais d'ici —
    le backoffice passe par `/jobs/manage`.
    """
    total, jobs = await recruitment_service.get_job_offers(
        db, page, size, is_active=True, search=search, sort_by=sort_by,
        published_only=True, work_mode=work_mode, contract_type=contract_type,
    )
    return PaginatedJobOffers(total=total, page=page, size=size, items=jobs)


@router.post("/jobs/extract-from-text", response_model=JobExtractionResponse,
             dependencies=[Depends(require("jobs", "write"))])
async def extract_job_from_text(body: JobExtractionRequest):
    """
    Pré-remplit le formulaire de création d'offre à partir d'un texte libre.

    Une PROPOSITION, jamais une création : aucune offre n'est enregistrée ici.
    Le RH relit les champs renvoyés, les corrige au besoin, puis crée l'offre
    par l'endpoint habituel — exactement comme la suggestion de salaire, qui
    s'applique d'un clic explicite plutôt que de s'imposer.

    Un champ absent du texte source reste absent de la réponse : le RH doit
    pouvoir distinguer « non mentionné » d'une valeur que le modèle aurait
    supposée à sa place.
    """
    rapport = await job_extraction_agent.run(body.text)
    return JobExtractionResponse(
        ok=rapport["ok"],
        fields=JobExtractionFields(**rapport["fields"]),
        reason=rapport["reason"],
    )


# ⚠️ Doit rester déclarée AVANT `/jobs/{job_id}`, sinon « manage » serait
# interprété comme un identifiant d'offre.
@router.get("/jobs/manage", response_model=PaginatedJobOffers,
            dependencies=[Depends(require("jobs", "read"))])
async def list_jobs_for_management(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: str | None = None,
    sort_by: str | None = None,
    status: str | None = Query(None, pattern=JOB_STATUS_PATTERN),
    work_mode: str | None = Query(None, pattern=WORK_MODE_PATTERN),
    contract_type: str | None = Query(None, pattern=CONTRACT_TYPE_PATTERN),
):
    """Listing **backoffice** : inclut brouillons, offres fermées et expirées."""
    total, jobs = await recruitment_service.get_job_offers(
        db, page, size, is_active=True, search=search, sort_by=sort_by,
        published_only=False, status=status,
        work_mode=work_mode, contract_type=contract_type,
    )
    return PaginatedJobOffers(total=total, page=page, size=size, items=jobs)


@router.get("/jobs/{job_id}", response_model=JobOfferResponse)
async def get_job(
    job_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    viewer: Annotated[User | None, Depends(get_current_user_optional)] = None,
):
    """
    Détail d'une offre, avec la même visibilité que le listing.

    Route MIXTE : ouverte à tous, mais un visiteur anonyme — comme un candidat
    ou un agent RH sans droits de gestion — ne voit que les offres publiées et
    non expirées. Seuls ADMIN et RH, qui pilotent le catalogue via
    `/jobs/manage`, accèdent aux brouillons et aux offres fermées.

    Sans ce contrôle, connaître l'identifiant suffisait à lire n'importe quel
    brouillon, fourchette de salaire comprise.
    """
    gestionnaire = bool(
        viewer
        and (viewer.is_superuser or viewer.role in (UserRole.ADMIN, UserRole.RH))
    )
    return await recruitment_service.get_job_offer(
        db, job_id, published_only=not gestionnaire
    )


@router.get("/jobs/{job_id}/applications", response_model=list[ApplicationResponse],
            dependencies=[Depends(require("applications", "read"))])
async def get_job_applications(job_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    _, apps = await recruitment_service.get_applications(db, job_id)
    return apps


@router.get("/jobs/{job_id}/similar", response_model=list[JobOfferResponse])
async def get_similar_jobs(
    job_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(4, ge=1, le=12),
):
    """
    Offres « similaires » à afficher en bas de la page de détail — classées
    par compétences requises communes, puis expérience et mode de travail
    proches. Route publique : mêmes offres visibles qu'un candidat anonyme.
    """
    return await recruitment_service.get_similar_jobs(db, job_id, limit=limit)


@router.post("/jobs", response_model=JobOfferResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require("jobs", "write"))])
async def create_job(
    body: JobOfferCreate,
    background: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await recruitment_service.create_job_offer(db, body, current_user.id)
    await db.commit()
    await db.refresh(job)

    # Indexation sémantique : APRÈS la réponse, jamais pendant.
    # Elle déclenche un encodage neuronal qui coûtait jusqu'à ~120 s au premier
    # appel (chargement du modèle) — l'utilisateur restait bloqué tout ce temps
    # sur le bouton « Créer », alors que l'offre était déjà enregistrée et que
    # le résultat de l'indexation ne lui est pas rendu.
    from app.services.semantic_service import semantic_service
    background.add_task(semantic_service.index_job_later, job.id)

    await notification_service.notify_admins(
        db, actor=current_user, type="JOB_CREATED",
        title="Nouvelle offre publiée",
        message=f"{current_user.full_name or current_user.username} a publié l'offre « {job.title} ».",
        link="/admin/jobs",
    )
    await db.commit()
    return job


@router.patch("/jobs/{job_id}", response_model=JobOfferResponse,
              dependencies=[Depends(require("jobs", "write"))])
async def update_job(
    job_id: UUID,
    body: JobOfferUpdate,
    background: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await recruitment_service.update_job_offer(db, job_id, body)
    await db.commit()
    await db.refresh(job)
    # Le contenu a changé → réindexation, différée pour les mêmes raisons que
    # sur la création (cf. create_job).
    from app.services.semantic_service import semantic_service
    background.add_task(semantic_service.index_job_later, job.id)
    return job


@router.put("/jobs/{job_id}", response_model=JobOfferResponse,
            dependencies=[Depends(require("jobs", "write"))])
async def replace_job(
    job_id: UUID,
    body: JobOfferUpdate,
    background: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Full update of a job offer (cahier des charges PUT /jobs/{id}).
    Shares the service-level update with PATCH; the difference is semantic —
    PUT expects the complete representation.
    """
    job = await recruitment_service.update_job_offer(db, job_id, body)
    await db.commit()
    await db.refresh(job)
    # PATCH réindexait, pas PUT : l'offre modifiée par cette route gardait un
    # embedding périmé et remontait donc sur ses anciens mots-clés dans la
    # recherche sémantique. Même traitement différé que les deux autres.
    from app.services.semantic_service import semantic_service
    background.add_task(semantic_service.index_job_later, job.id)
    return job


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require("jobs", "delete"))])
async def delete_job(job_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    await recruitment_service.delete_job_offer(db, job_id)
    await db.commit()


@router.post("/apply/{job_id}", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def apply_to_job(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
    cv_file: UploadFile | None = File(default=None),
    save_to_profile: bool = Form(default=True),
):
    """
    Dépose une candidature.

    Le fichier est désormais FACULTATIF : sans lui, on reprend le CV enregistré
    dans le profil du candidat. C'est ce qui permet à la modale de candidature
    de proposer « utiliser mon CV » sans redemander un fichier à chaque offre.

    Quand un fichier est fourni, il devient aussi le CV de référence du profil
    (`save_to_profile`, activé par défaut) : le candidat qui met son CV à jour
    en postulant n'a pas à le redéposer ensuite dans son espace.

    Dans les deux cas, la candidature conserve sa PROPRE copie du document
    (cf. `app.services.cv_storage`) : un remplacement ultérieur du CV de profil
    ne réécrit pas les dossiers déjà déposés.
    """
    candidate = await recruitment_service.get_or_create_candidate(
        db, current_user.id, current_user.full_name or ""
    )

    ancien_cv_profil = candidate.cv_path
    if cv_file is not None and cv_file.filename:
        contenu, extension = await cv_storage.read_and_validate(cv_file)
        # Avant toute écriture : un document refusé n'est jamais enregistré.
        await verifier_document(contenu, extension)
        cv_path = cv_storage.store_application_cv(current_user.id, job_id, contenu, extension)
        if save_to_profile:
            candidate.cv_path = cv_storage.store_profile_cv(current_user.id, contenu, extension)
            candidate.cv_filename = cv_file.filename
            candidate.cv_uploaded_at = utcnow()
    elif candidate.cv_path:
        cv_path = cv_storage.copy_profile_cv_to_application(candidate.cv_path, current_user.id, job_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun CV : déposez un fichier ou enregistrez-en un dans votre profil.",
        )

    try:
        app = await recruitment_service.apply_to_job(db, candidate.id, job_id, cv_path)
        await db.commit()
        await db.refresh(app)
    except HTTPException:
        # Refus métier (offre fermée/expirée, candidature déjà déposée) : on
        # laisse remonter le vrai code et le vrai message, sinon ils seraient
        # masqués en « 500 File upload failed ». Le fichier tout juste écrit
        # n'a plus de raison d'être puisque la candidature n'existe pas.
        await db.rollback()
        cv_storage.discard(cv_path)
        raise
    except Exception as e:
        await db.rollback()
        cv_storage.discard(cv_path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"File upload failed: {str(e)}")

    # L'ancien CV de profil n'est supprimé qu'une fois la candidature validée,
    # et jamais s'il sert encore à ce dossier.
    if candidate.cv_path != ancien_cv_profil:
        cv_storage.discard(ancien_cv_profil, keep=cv_path)

    logger.info(f"Auto-queuing CV analysis for new application {app.id}")
    background_tasks.add_task(scoring_agent.run_analysis_task, app.id)
    return app


@router.patch(
    "/applications/{app_id}/expected-salary",
    response_model=ApplicationResponse,
)
async def set_expected_salary(
    app_id: UUID,
    body: ExpectedSalaryUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Enregistre la prétention salariale du candidat pour CETTE candidature.

    Étape volontairement séparée du dépôt : la candidature existe déjà quand la
    question est posée, si bien qu'un candidat qui préfère ne pas répondre — ou
    qui ferme la fenêtre — ne perd pas son dossier.

    Réservé au propriétaire de la candidature : un montant de négociation ne
    doit pouvoir être renseigné que par l'intéressé.
    """
    application = await recruitment_service.get_own_application(db, app_id, current_user.id)
    application.expected_salary = body.expected_salary
    await db.commit()
    await db.refresh(application)
    return application


# ── CV de référence du candidat ────────────────────────────────────────────────
#
# Facultatif à l'inscription et modifiable à tout moment : le candidat dépose
# son CV une fois, puis postule sans le rejoindre à chaque offre.

@router.post(
    "/cv/verification",
    response_model=CvVerificationResponse,
    dependencies=[Depends(rate_limit("cv_verification", *settings.RATE_LIMIT_CV_CHECK))],
)
async def verify_cv_document(cv_file: UploadFile = File(...)):
    """
    Vérifie qu'un document est un CV, SANS l'enregistrer.

    Sert au formulaire d'inscription : le compte n'existe pas encore quand le
    candidat choisit son CV, qui n'est déposé qu'après la saisie du code reçu
    par e-mail. Sans cette vérification, un document refusé ne l'était qu'une
    fois le compte créé.

    Elle ne remplace pas le contrôle de `POST /me/cv`, qui reste la garantie :
    un client peut toujours l'ignorer. Route publique, donc limitée par IP.
    """
    contenu, extension = await cv_storage.read_and_validate(cv_file)
    verdict = await verifier_document(contenu, extension)
    return CvVerificationResponse(decision=verdict.decision)


@router.get("/me/cv", response_model=CandidateCvResponse)
async def get_my_cv(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """État du CV enregistré. Renvoie `has_cv: false` plutôt qu'un 404 : « pas
    encore de CV » est un état normal, pas une erreur."""
    candidate = await recruitment_service.get_or_create_candidate(
        db, current_user.id, current_user.full_name or ""
    )
    await db.commit()
    return CandidateCvResponse.from_candidate(candidate)


@router.post("/me/cv", response_model=CandidateCvResponse)
async def upload_my_cv(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cv_file: UploadFile = File(...),
):
    """
    Dépose ou remplace le CV de référence.

    Les candidatures DÉJÀ déposées ne sont pas affectées : chacune conserve la
    copie du document envoyé ce jour-là.
    """
    contenu, extension = await cv_storage.read_and_validate(cv_file)
    # Le CV de profil est réutilisé par chaque candidature : il est vérifié ici
    # aussi, sinon il suffirait de passer par le profil pour contourner le contrôle.
    await verifier_document(contenu, extension)
    candidate = await recruitment_service.get_or_create_candidate(
        db, current_user.id, current_user.full_name or ""
    )
    ancien = candidate.cv_path
    candidate.cv_path = cv_storage.store_profile_cv(current_user.id, contenu, extension)
    candidate.cv_filename = cv_file.filename
    candidate.cv_uploaded_at = utcnow()
    await db.commit()
    await db.refresh(candidate)

    cv_storage.discard(ancien)
    logger.info("CV de profil mis à jour pour le candidat %s", candidate.id)
    return CandidateCvResponse.from_candidate(candidate)


@router.delete("/me/cv", response_model=CandidateCvResponse)
async def delete_my_cv(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retire le CV du profil. Les candidatures passées gardent le leur."""
    candidate = await recruitment_service.get_or_create_candidate(
        db, current_user.id, current_user.full_name or ""
    )
    ancien = candidate.cv_path
    candidate.cv_path = None
    candidate.cv_filename = None
    candidate.cv_uploaded_at = None
    await db.commit()
    await db.refresh(candidate)

    cv_storage.discard(ancien)
    return CandidateCvResponse.from_candidate(candidate)


@router.get("/my-applications/{app_id}/score-detail",
            response_model=ApplicationScoreDetail,
            response_model_exclude_none=True)
async def my_application_score_detail(
    app_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Le détail de SA propre candidature, vu par le candidat.

    Deux garde-fous, et le second n'est pas évident :

    * **La propriété est vérifiée, pas seulement l'authentification.** Le
      service ne renvoie la candidature que si elle appartient au demandeur —
      sinon n'importe quel candidat connecté lirait le dossier d'un autre en
      changeant l'identifiant dans l'URL.
    * **`exclude_none` est indispensable.** Note de test et retour d'entretien
      ne sont ajoutés que si le RH a ouvert le partage ; sans cette exclusion,
      ils ressortiraient à `null` et apprendraient au candidat qu'il existe
      quelque chose qu'on lui refuse.

    Une candidature inexistante et une candidature qui n'est pas la sienne
    renvoient le même 404 — les distinguer permettrait d'énumérer les dossiers
    des autres.
    """
    vue = await candidate_feedback_service.build(db, app_id, current_user.id)
    if vue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidature introuvable.")
    return vue


@router.get("/me/recommended-jobs", response_model=JobRecommendations)
async def my_recommended_jobs(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(6, ge=1, le=20),
):
    """
    Offres recommandées AU CANDIDAT CONNECTÉ, d'après son CV analysé le plus
    récent (cf. `recommendation_service` pour le pipeline complet).

    Route au nom de l'utilisateur courant plutôt que paramétrée par
    identifiant : le frontoffice connaît le compte, pas la ligne `candidates`,
    et une route `/{candidate_id}` exposée au candidat inviterait à sonder les
    profils voisins.

    Renvoie `{"recommendations": []}` plutôt qu'une erreur quand rien ne
    correspond — l'écran masque alors la section. C'est le cas nominal tant
    que le CV n'a pas été analysé, ou si aucune offre ouverte n'atteint le
    seuil de compatibilité.
    """
    candidate_id = (await db.execute(
        select(Candidate.id).where(Candidate.user_id == current_user.id)
    )).scalar_one_or_none()
    if not candidate_id:
        return JobRecommendations(recommendations=[])

    offres = await recommendation_service.recommend_for_candidate(
        db, candidate_id, limit=limit)
    return JobRecommendations(recommendations=offres)


@router.post("/my-applications/{app_id}/withdraw", response_model=ApplicationResponse)
async def withdraw_my_application(
    app_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Le candidat retire SA PROPRE candidature.

    Passe le dossier en `WITHDRAWN` plutôt que de le supprimer : contrairement
    à `DELETE /applications/{id}` (réservé à l'admin), le recruteur doit
    pouvoir voir qu'un candidat s'est désisté, pas simplement constater qu'un
    dossier a disparu.
    """
    app = await recruitment_service.withdraw_application(db, app_id, current_user.id)
    await db.commit()
    await db.refresh(app)

    # Le recrutement doit savoir qu'un dossier ne sera plus traité — pas de
    # notification au candidat lui-même, qui vient de faire le geste.
    ctx = (await db.execute(
        select(Candidate, JobOffer)
        .join(JobOffer, JobOffer.id == app.job_offer_id)
        .where(Candidate.id == app.candidate_id)
    )).first()
    if ctx:
        candidate, job = ctx
        await notification_service.notify_admins(
            db, actor=current_user, type="APPLICATION_STATUS_CHANGED",
            title="Candidature retirée",
            message=f"{candidate.full_name or current_user.full_name or current_user.username} a retiré sa candidature pour « {job.title} ».",
            link="/admin/applications",
        )
        await db.commit()

    return app


@router.get("/my-applications", response_model=list[MyApplicationResponse])
async def list_my_applications(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Return the authenticated user's own applications, enriched with the
    associated job offer details (title, salary range, skills, etc.) and
    optional scoring data when available. Accessible to any authenticated
    user — designed for the frontoffice "Mes Candidatures" page.
    """
    return await recruitment_service.get_my_applications(db, current_user.id)


@router.get("/applications", response_model=list[ApplicationResponse],
            dependencies=[Depends(require("applications", "read"))])
async def list_applications(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_id: UUID | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    total, apps = await recruitment_service.get_applications(db, job_id, page, size)
    return apps


@router.patch("/applications/{app_id}", response_model=ApplicationResponse,
              dependencies=[Depends(require("applications", "write"))])
async def update_application(
    app_id: UUID,
    body: ApplicationUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = await recruitment_service.update_application_status(db, app_id, body)
    await db.commit()
    await db.refresh(app)

    # Contexte pour les notifications : candidat (destinataire) + offre.
    ctx = (await db.execute(
        select(Candidate, JobOffer)
        .join(JobOffer, JobOffer.id == app.job_offer_id)
        .where(Candidate.id == app.candidate_id)
    )).first()
    if ctx:
        candidate, job = ctx
        status_label = APPLICATION_STATUS_LABELS.get(app.status, app.status)

        await notification_service.notify_user(
            db, recipient_id=candidate.user_id, type="APPLICATION_STATUS_CHANGED",
            title="Mise à jour de votre candidature",
            message=f"Votre candidature pour « {job.title} » est maintenant : {status_label}.",
            link="/frontoffice/applications",
        )
        await notification_service.notify_admins(
            db, actor=current_user, type="APPLICATION_STATUS_CHANGED",
            title="Statut de candidature modifié",
            message=(f"{current_user.full_name or current_user.username} a changé le statut de "
                     f"la candidature de {candidate.full_name} ({job.title}) → {status_label}."),
            link="/admin/applications",
        )
        await db.commit()

    return app


@router.delete("/applications/{app_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require("applications", "delete"))])
async def delete_application(app_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """CAND-08 — delete an application + clean up its CV file and derived data (Admin only)."""
    await recruitment_service.delete_application(db, app_id)
    await db.commit()


# ── Saved jobs (frontoffice bookmarks) ──────────────────────────────────────

@router.get("/saved-jobs", response_model=list[JobOfferResponse])
async def list_saved_jobs(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await recruitment_service.get_saved_jobs(db, current_user.id)


@router.post("/saved-jobs/{job_id}", response_model=JobOfferResponse, status_code=status.HTTP_201_CREATED)
async def save_job(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await recruitment_service.save_job(db, current_user.id, job_id)
    await db.commit()
    return job


@router.delete("/saved-jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsave_job(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await recruitment_service.unsave_job(db, current_user.id, job_id)
    await db.commit()


# ── Export ──────────────────────────────────────────────────────────────────

@router.get("/applications/export",
            dependencies=[Depends(require("applications", "read"))])
async def export_applications(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_id: UUID | None = None,
):
    """Export applications as CSV (optionally filtered by job offer)."""
    import csv, io
    from sqlalchemy import select as _select
    from app.models.recruitment import Application as _App, Candidate as _Cand, JobOffer as _Job
    from app.models.user import User as _User

    query = (
        _select(_App, _Cand, _User, _Job)
        .join(_Cand, _App.candidate_id == _Cand.id)
        .join(_User, _Cand.user_id == _User.id)
        .join(_Job, _App.job_offer_id == _Job.id)
        .order_by(_App.created_at.desc())
    )
    if job_id:
        query = query.where(_App.job_offer_id == job_id)
    rows = (await db.execute(query)).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["candidate_name", "email", "job_title", "status", "applied_at", "cv_file"])
    for app, cand, user, job in rows:
        writer.writerow([
            cand.full_name or "",
            user.email,
            job.title,
            app.status,
            app.created_at.isoformat() if app.created_at else "",
            app.cv_file_path,
        ])
    buffer.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )


async def _cv_autorise(
    file_path: str, viewer: User, db: AsyncSession,
) -> Path:
    """
    Résout un chemin de CV et vérifie que cet utilisateur a le droit de le lire.

    Deux contrôles, tous deux indispensables :

    1. **Confinement.** Le paramètre est un `:path` : il acceptait
       `../../etc/passwd` aussi bien qu'un nom de CV, et `FileResponse`
       servait alors n'importe quel fichier lisible par le processus. On
       résout le chemin et on exige qu'il tombe SOUS le répertoire des CV.
    2. **Propriété.** L'endpoint n'était protégé que par l'authentification :
       un candidat connecté téléchargeait le CV de n'importe qui. Le
       back-office (permission `cv:read`) consulte tous les CV — c'est son
       métier ; un candidat n'accède qu'aux siens.

    Un fichier absent, hors du répertoire, ou appartenant à quelqu'un d'autre
    rendent le MÊME 404 : distinguer « ce CV n'existe pas » de « ce CV ne vous
    appartient pas » dirait à un curieux quand il a visé juste.
    """
    from app.services.cv_storage import CV_ROOT

    introuvable = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="CV introuvable."
    )

    racine = CV_ROOT.resolve()
    try:
        chemin = (Path(file_path) if Path(file_path).is_absolute()
                  else Path(file_path)).resolve()
        chemin.relative_to(racine)
    except (ValueError, OSError):
        raise introuvable
    if not chemin.is_file():
        raise introuvable

    if viewer.is_superuser or autorise(viewer.role, "cv", "read"):
        return chemin

    # Candidat : uniquement un chemin rattaché à SON dossier — le CV de
    # référence de son profil, ou la copie figée d'une de ses candidatures.
    candidate = (await db.execute(
        select(Candidate).where(Candidate.user_id == viewer.id)
    )).scalar_one_or_none()
    if not candidate:
        raise introuvable

    siens = {candidate.cv_path} if candidate.cv_path else set()
    siens |= {
        row for row in (await db.execute(
            select(Application.cv_file_path)
            .where(Application.candidate_id == candidate.id)
        )).scalars().all() if row
    }
    if not any(Path(p).resolve() == chemin for p in siens):
        raise introuvable
    return chemin


@router.get("/cv-download/{file_path:path}")
async def download_cv(
    file_path: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from fastapi.responses import FileResponse
    chemin = await _cv_autorise(file_path, current_user, db)
    return FileResponse(chemin, media_type="application/octet-stream", filename=chemin.name)


@router.get("/cv-preview/{file_path:path}")
async def preview_cv(
    file_path: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from fastapi.responses import FileResponse
    chemin = await _cv_autorise(file_path, current_user, db)

    media_type = "application/pdf"
    if chemin.suffix == ".docx":
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif chemin.suffix == ".doc":
        media_type = "application/msword"

    return FileResponse(chemin, media_type=media_type)
