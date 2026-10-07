"""
Connexion temps réel refusée : le navigateur doit RECEVOIR le code 4401.

Fermée avant d'être acceptée, la connexion était refusée en HTTP 403 : le
client ne voyait qu'une coupure et réessayait toutes les 5 s, sans fin, avec
un jeton mort (compte supprimé, base recréée).
"""
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.v1.endpoints import notifications
from app.main import app


def test_un_jeton_refuse_ferme_avec_le_code_4401(monkeypatch):
    async def _aucun(_jeton):
        return None
    monkeypatch.setattr(notifications, "_authenticate_ws", _aucun)

    client = TestClient(app)
    try:
        with client.websocket_connect("/api/v1/notifications/ws?token=jeton-mort") as ws:
            ws.receive_text()
        raise AssertionError("la connexion aurait dû être fermée")
    except WebSocketDisconnect as fermeture:
        assert fermeture.code == 4401
