"""
Notifications in-app + temps réel.

REST (authentifié) :
  GET    /notifications                → liste paginée des notifications du user
  GET    /notifications/unread-count   → compteur non-lues (pour le badge)
  PATCH  /notifications/{id}/read      → marquer une notification comme lue
  POST   /notifications/read-all       → tout marquer comme lu
  DELETE /notifications/{id}           → supprimer une notification

WebSocket :
  WS /notifications/ws?token=<access_token>  → pousse chaque nouvelle
    notification en temps réel au user authentifié via le token en query
    param (le navigateur ne permet pas d'en-têtes personnalisés sur les WS).
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.core.security import decode_token
from app.db.session import get_db, AsyncSessionLocal
from app.models.user import User
from app.services.notification_service import notification_service
from app.services.notification_ws import notification_ws_manager

router = APIRouter()


@router.get("")
@router.get("/", include_in_schema=False)
async def list_notifications(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    unread_only: bool = Query(default=False),
):
    return await notification_service.list_for_user(
        db, user_id=current_user.id, page=page, page_size=page_size, unread_only=unread_only
    )


@router.get("/unread-count")
async def unread_count(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    count = await notification_service.unread_count(db, current_user.id)
    return {"unread_count": count}


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    notif = await notification_service.mark_read(
        db, notification_id=notification_id, user_id=current_user.id
    )
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification introuvable")
    await db.commit()
    return {"id": str(notif.id), "is_read": notif.is_read}


@router.post("/read-all")
async def mark_all_notifications_read(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    count = await notification_service.mark_all_read(db, current_user.id)
    await db.commit()
    return {"marked_read": count}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    deleted = await notification_service.delete(
        db, notification_id=notification_id, user_id=current_user.id
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification introuvable")
    await db.commit()


# ── WebSocket temps réel ──────────────────────────────────────────────────────

async def _authenticate_ws(token: str) -> User | None:
    """Décode le JWT passé en query param et charge l'utilisateur (best-effort)."""
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
    except JWTError:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.id == UUID(user_id), User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()


@router.websocket("/ws")
async def notifications_websocket(websocket: WebSocket, token: str = Query(...)):
    """
    Connexion : ws://host/api/v1/notifications/ws?token=<access_token>
    Le serveur pousse `{"event": "notification", "data": {...}}` à chaque
    nouvelle notification créée pour cet utilisateur.
    """
    user = await _authenticate_ws(token)
    if not user or not user.is_active:
        # Accepter PUIS fermer : fermée avant l'acceptation, la connexion est
        # refusée en HTTP 403 et le navigateur ne reçoit jamais le code 4401.
        # Il croyait alors à une coupure réseau et réessayait sans fin avec un
        # jeton mort (compte supprimé, base recréée…).
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await notification_ws_manager.connect(user.id, websocket)
    try:
        while True:
            # Le client n'a rien à envoyer ; on lit juste pour détecter la
            # déconnexion (ping/pong géré par le protocole WS).
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        notification_ws_manager.disconnect(user.id, websocket)
