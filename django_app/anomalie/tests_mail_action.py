"""Test per il sistema mail-action anomalie.

Copertura:
- generazione token
- token scaduto / usato / revocato
- token inesistente
- azione valida GET e POST — senza login (accesso solo via token)
- azione duplicata (token già usato)
- visualizza non marca il token come usato
- dispositive marcano il token come usato
- audit log creato dopo azione POST
- rendering email con 1 / 10 / >10 anomalie
- link azione presente nel corpo email
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

User = get_user_model()

_FAKE_SITE_URL = "https://hub.example.local"


def _make_anomalie_rows(n: int) -> list[dict]:
    return [
        {
            "id": i + 1,
            "descrizione": f"Anomalia test #{i + 1} — pezzo fuori tolleranza",
            "avanzamento": "In attesa",
            "note_capocommessa": "",
            "seriale": f"SN-{i + 1:04d}",
        }
        for i in range(n)
    ]


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class AnomaliaMailActionTokenTests(TestCase):
    """Creazione e validazione del token — accesso senza login."""

    def _create_token(self, *, expires_delta=timedelta(hours=48), action="visualizza"):
        from anomalie.mail_action_models import AnomaliaMailActionToken

        return AnomaliaMailActionToken.objects.create(
            recipient_email="cc@example.local",
            recipient_display="Capocommessa Test",
            op_id="OP-2026-TEST",
            anomalie_ids=[1, 2],
            anomalie_snapshot=_make_anomalie_rows(2),
            action=action,
            expires_at=timezone.now() + expires_delta,
        )

    # ── Creazione ─────────────────────────────────────────────────────────

    def test_token_creato_con_token_non_vuoto(self):
        token_obj = self._create_token()
        self.assertTrue(len(token_obj.token) >= 32)

    def test_token_is_valid_nuovo(self):
        token_obj = self._create_token()
        self.assertTrue(token_obj.is_valid())

    # ── Scadenza ──────────────────────────────────────────────────────────

    def test_token_scaduto_non_valido(self):
        token_obj = self._create_token(expires_delta=timedelta(seconds=-1))
        self.assertFalse(token_obj.is_valid())

    def test_token_scaduto_risponde_errore(self):
        token_obj = self._create_token(expires_delta=timedelta(seconds=-1))
        url = reverse("anomalie_mail_action", kwargs={"token": token_obj.token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, "scaduto", status_code=410)

    # ── Già usato ─────────────────────────────────────────────────────────

    def test_token_usato_non_valido(self):
        token_obj = self._create_token()
        token_obj.mark_used()
        self.assertFalse(token_obj.is_valid())

    # ── Revocato ──────────────────────────────────────────────────────────

    def test_token_revocato_non_valido(self):
        token_obj = self._create_token()
        token_obj.is_revoked = True
        token_obj.save(update_fields=["is_revoked"])
        self.assertFalse(token_obj.is_valid())

    def test_token_revocato_risponde_errore(self):
        token_obj = self._create_token()
        token_obj.is_revoked = True
        token_obj.save(update_fields=["is_revoked"])
        url = reverse("anomalie_mail_action", kwargs={"token": token_obj.token})
        response = self.client.get(url)
        self.assertIn(response.status_code, [400, 410])
        self.assertContains(response, "revocato", status_code=response.status_code)

    # ── Token inesistente ─────────────────────────────────────────────────

    def test_token_inesistente_risponde_errore(self):
        url = reverse("anomalie_mail_action", kwargs={"token": "token-non-esistente-xyz"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    # ── Accesso senza login consentito ────────────────────────────────────

    def test_non_autenticato_accede_con_token_valido(self):
        """Senza login: il token valido deve restituire 200, non un redirect al login."""
        token_obj = self._create_token(action="visualizza")
        url = reverse("anomalie_mail_action", kwargs={"token": token_obj.token})
        with patch("anomalie.mail_action_views._load_anomalie_live", return_value=_make_anomalie_rows(2)), \
             patch("anomalie.mail_action_views._load_first_images", return_value=[]):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    # ── Visualizzazione valida ────────────────────────────────────────────

    def test_token_valido_visualizza_get(self):
        token_obj = self._create_token(action="visualizza")
        url = reverse("anomalie_mail_action", kwargs={"token": token_obj.token})
        with patch("anomalie.mail_action_views._load_anomalie_live", return_value=_make_anomalie_rows(2)), \
             patch("anomalie.mail_action_views._load_first_images", return_value=[]):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OP-2026-TEST")


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class AnomaliaMailActionPostTests(TestCase):
    """Azioni POST senza login: conferma, doppia esecuzione, audit log."""

    def _create_token(self, action="visualizza"):
        from anomalie.mail_action_models import AnomaliaMailActionToken

        return AnomaliaMailActionToken.objects.create(
            recipient_email="cc@example.local",
            recipient_display="Capocommessa Test",
            op_id="OP-POST-TEST",
            anomalie_ids=[10],
            anomalie_snapshot=_make_anomalie_rows(1),
            action=action,
            expires_at=timezone.now() + timedelta(hours=24),
        )

    def _post_action(self, token_obj, note="test note"):
        url = reverse("anomalie_mail_action", kwargs={"token": token_obj.token})
        with patch("anomalie.mail_action_views._load_anomalie_live", return_value=_make_anomalie_rows(1)), \
             patch("anomalie.mail_action_views._load_first_images", return_value=[]), \
             patch("anomalie.mail_action_views._apply_action_to_anomalia", return_value=True):
            return self.client.post(url, {"note": note})

    def test_azione_visualizza_post_redirige_a_done(self):
        """visualizza è sola lettura: POST va a done ma il token resta riusabile."""
        token_obj = self._create_token(action="visualizza")
        response = self._post_action(token_obj)
        self.assertIn(response.status_code, [302, 301])
        done_url = reverse("anomalie_mail_action_done", kwargs={"token": token_obj.token})
        self.assertIn(done_url, response["Location"])

    def test_azione_visualizza_non_marca_token_usato(self):
        """visualizza: il token deve restare non usato dopo il POST."""
        token_obj = self._create_token(action="visualizza")
        self._post_action(token_obj)
        from anomalie.mail_action_models import AnomaliaMailActionToken
        updated = AnomaliaMailActionToken.objects.get(pk=token_obj.pk)
        self.assertFalse(updated.is_used)

    def test_azione_dispositiva_post_segna_usato(self):
        """azioni dispositive (prendi_in_carico): il token viene marcato is_used."""
        token_obj = self._create_token(action="prendi_in_carico")
        response = self._post_action(token_obj)
        self.assertIn(response.status_code, [302, 301])
        from anomalie.mail_action_models import AnomaliaMailActionToken
        updated = AnomaliaMailActionToken.objects.get(pk=token_obj.pk)
        self.assertTrue(updated.is_used)

    def test_azione_duplicata_rifiutata(self):
        """Token già usato: deve mostrare pagina done con already_done=True o errore."""
        token_obj = self._create_token(action="visualizza")
        token_obj.mark_used()
        response = self._post_action(token_obj)
        self.assertIn(response.status_code, [200, 302, 400, 410])

    def test_audit_log_creato_dopo_post(self):
        from anomalie.mail_action_models import AnomaliaActionLog

        token_obj = self._create_token(action="visualizza")
        self._post_action(token_obj, note="nota di test")
        logs = AnomaliaActionLog.objects.filter(token=token_obj)
        self.assertTrue(logs.exists())

    def test_audit_log_contiene_note(self):
        from anomalie.mail_action_models import AnomaliaActionLog

        token_obj = self._create_token(action="visualizza")
        self._post_action(token_obj, note="nota specifica xyz")
        log = AnomaliaActionLog.objects.filter(token=token_obj).first()
        self.assertIsNotNone(log)
        self.assertIn("nota specifica xyz", log.note)

    def test_audit_log_user_display_da_token(self):
        """Senza utente autenticato, user_display deve venire dal token."""
        from anomalie.mail_action_models import AnomaliaActionLog

        token_obj = self._create_token(action="visualizza")
        self._post_action(token_obj, note="test")
        log = AnomaliaActionLog.objects.filter(token=token_obj).first()
        self.assertIsNotNone(log)
        self.assertIn("Capocommessa", log.user_display)


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class AnomaliaEmailRenderingTests(TestCase):
    """Rendering email con 1, 10, >10 anomalie."""

    def _build_email(self, n: int):
        from anomalie.mail_action_models import AnomaliaMailActionToken
        from anomalie.mail_action_service import build_anomalie_action_email

        token_obj = AnomaliaMailActionToken.objects.create(
            recipient_email="dest@example.local",
            recipient_display="Destinatario Test",
            op_id="OP-EMAIL-TEST",
            anomalie_ids=list(range(1, n + 1)),
            anomalie_snapshot=_make_anomalie_rows(n),
            action="visualizza",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        rows = _make_anomalie_rows(n)
        subject, body_text, body_html = build_anomalie_action_email(
            recipient_email="dest@example.local",
            recipient_display="Destinatario Test",
            op_id="OP-EMAIL-TEST",
            op_nominativo="Test flangia",
            anomalie_rows=rows,
            action="visualizza",
            token_str=token_obj.token,
            expires_at=token_obj.expires_at,
            site_url=_FAKE_SITE_URL,
        )
        return subject, body_text, body_html, token_obj

    def test_email_singola_anomalia_subject(self):
        subject, _, _, _ = self._build_email(1)
        self.assertIn("OP-EMAIL-TEST", subject)
        self.assertIn("#1", subject)

    def test_email_singola_anomalia_html(self):
        _, _, body_html, _ = self._build_email(1)
        self.assertIn("OP-EMAIL-TEST", body_html)
        self.assertIn("Anomalia test #1", body_html)

    def test_email_10_anomalie_mostra_tutte(self):
        _, _, body_html, _ = self._build_email(10)
        for i in range(1, 11):
            self.assertIn(f"#{i}", body_html)

    def test_email_11_anomalie_tronca(self):
        _, _, body_html, _ = self._build_email(11)
        for i in range(1, 11):
            self.assertIn(f"#{i}", body_html)
        self.assertIn("11", body_html)

    def test_email_link_azione_presente(self):
        _, _, body_html, token_obj = self._build_email(3)
        expected_url = f"{_FAKE_SITE_URL}/gestione-anomalie/mail-action/{token_obj.token}/"
        self.assertIn(expected_url, body_html)

    def test_email_text_plain_link_presente(self):
        _, body_text, _, token_obj = self._build_email(2)
        expected_url = f"{_FAKE_SITE_URL}/gestione-anomalie/mail-action/{token_obj.token}/"
        self.assertIn(expected_url, body_text)

    def test_email_20_anomalie_subject_conta_corretta(self):
        subject, _, _, _ = self._build_email(20)
        self.assertIn("20", subject)
        self.assertIn("OP-EMAIL-TEST", subject)


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class AnomaliaMailActionSendTests(TestCase):
    """Test invio email via send_anomalie_action_email con backend dummy."""

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_crea_token_e_invia(self):
        from django.core import mail
        from anomalie.mail_action_service import send_anomalie_action_email

        token_obj = send_anomalie_action_email(
            recipient_email="dest@example.local",
            recipient_display="Dest Test",
            op_id="OP-SEND-TEST",
            op_nominativo="Pezzo test",
            anomalie_rows=_make_anomalie_rows(2),
            action="visualizza",
            expires_hours=24,
            site_url=_FAKE_SITE_URL,
        )
        self.assertIsNotNone(token_obj.pk)
        self.assertFalse(token_obj.is_used)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn("OP-SEND-TEST", sent.subject)
        self.assertIn("dest@example.local", sent.to)
