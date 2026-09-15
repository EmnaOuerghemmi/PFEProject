"""
Le filet qui empêche la suite de test d'envoyer de vrais e-mails.

Contexte : le service ne bascule en mode journal que si le SMTP n'est PAS
configuré. Sur un poste de développement où il l'est, chaque exécution de
`pytest` expédiait réellement des invitations, confirmations et refus vers des
adresses `@example.com` — domaine réservé qui n'accepte rien (RFC 2606) — d'où
une volée d'avis de non-remise dans la boîte d'expédition à chaque `pytest`.

Ce test protège le garde-fou lui-même : si quelqu'un retire la fixture ou
qu'une nouvelle fonction d'envoi contourne `_send_sync`, il échoue ici plutôt
que dans la boîte mail de quelqu'un.
"""
import smtplib

import pytest

from app.services.email_service import send_email


@pytest.mark.asyncio
async def test_aucun_message_ne_quitte_la_suite_de_test(monkeypatch):
    """Une tentative de connexion SMTP pendant les tests doit être impossible."""
    def _interdit(*args, **kwargs):
        raise AssertionError(
            "La suite de test a tenté d'ouvrir une connexion SMTP : "
            "le garde-fou de conftest n'est plus en place."
        )

    monkeypatch.setattr(smtplib, "SMTP", _interdit)

    # Passe par le chemin normal : si le garde-fou tient, rien n'atteint smtplib.
    assert await send_email(
        to_email="testuser@example.com",
        subject="Test",
        html="<p>Contenu</p>",
    ) is True


@pytest.mark.asyncio
async def test_les_envois_restent_observables(_aucun_email_reel):
    """
    Couper l'envoi ne doit pas rendre les tests aveugles : ce qui aurait été
    expédié reste consultable, pour les tests qui vérifient qu'un message
    PART bien (sans vérifier son contenu détaillé).
    """
    avant = len(_aucun_email_reel)
    await send_email(to_email="destinataire@example.com", subject="Sujet vérifiable", html="<p>x</p>")

    assert len(_aucun_email_reel) == avant + 1
    assert _aucun_email_reel[-1] == ("destinataire@example.com", "Sujet vérifiable")
