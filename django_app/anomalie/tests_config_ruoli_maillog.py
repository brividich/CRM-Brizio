"""Test: liste derivate da Ruoli Operativi, ruoli visibili nei Permessi, log email.

Coprono i tre punti toccati dalla configurazione anomalie:
- le liste CAR / capicommessa nascono dai Ruoli Operativi scelti, con override
  per singola persona e fallback alla derivazione storica;
- il tab Permessi filtra il catalogo ruoli senza mai nascondere una regola attiva;
- ogni email del modulo finisce in ``AnomalieEmailLog`` ed e' reinviabile.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from anomalie import views as anomalie_views
from anomalie.mail_action_service import resend_logged_email, send_and_log_email
from anomalie.mail_log_models import AnomalieEmailLog


class DerivedListsFromRolesTests(TestCase):
    """La composizione delle liste derivate segue i ruoli configurati."""

    def setUp(self):
        self.sources = {
            "capi_reparto": {"ruoli": [], "extra": [], "esclusi": []},
            "capi_commessa": {"ruoli": [], "extra": [], "esclusi": []},
        }

    def test_fallback_storico_quando_nessun_ruolo_selezionato(self):
        with patch.object(
            anomalie_views, "_capireparto_from_anagrafica", return_value=["Mario Rossi"]
        ):
            values = anomalie_views._resolve_derived_list("capi_reparto", self.sources)
        self.assertEqual(values, ["Mario Rossi"])

    def test_ruoli_selezionati_sostituiscono_il_fallback(self):
        self.sources["capi_reparto"]["ruoli"] = [7]
        with patch.object(
            anomalie_views, "_names_for_ruoli_operativi", return_value=["Anna Bianchi"]
        ), patch.object(
            anomalie_views, "_capireparto_from_anagrafica", return_value=["Mario Rossi"]
        ):
            values = anomalie_views._resolve_derived_list("capi_reparto", self.sources)
        self.assertEqual(values, ["Anna Bianchi"])

    def test_override_utente_aggiunge_ed_esclude(self):
        self.sources["capi_commessa"] = {
            "ruoli": [3],
            "extra": ["Zeno Extra"],
            "esclusi": ["anna bianchi"],
        }
        with patch.object(
            anomalie_views,
            "_names_for_ruoli_operativi",
            return_value=["Anna Bianchi", "Carlo Verdi"],
        ):
            values = anomalie_views._resolve_derived_list("capi_commessa", self.sources)
        self.assertEqual(values, ["Carlo Verdi", "Zeno Extra"])

    def test_extra_gia_presente_non_duplica(self):
        self.sources["capi_commessa"] = {
            "ruoli": [3],
            "extra": ["carlo verdi"],
            "esclusi": [],
        }
        with patch.object(
            anomalie_views, "_names_for_ruoli_operativi", return_value=["Carlo Verdi"]
        ):
            values = anomalie_views._resolve_derived_list("capi_commessa", self.sources)
        self.assertEqual(values, ["Carlo Verdi"])

    def test_normalizzazione_sorgente_scarta_id_non_validi(self):
        cfg = anomalie_views._normalize_derived_source(
            {"ruoli": ["4", 4, 0, -2, "x", None], "extra": [" Tizio ", ""], "esclusi": None}
        )
        self.assertEqual(cfg["ruoli"], [4])
        self.assertEqual(cfg["extra"], ["Tizio"])
        self.assertEqual(cfg["esclusi"], [])


class DerivedSourcesPersistenceTests(TestCase):
    """Le sorgenti si salvano nello stesso JSON delle liste, senza toccarle."""

    def test_salva_e_rilegge_senza_perdere_le_liste(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anomalie_liste.json"
            path.write_text(
                json.dumps({"causali_doc": ["OP"], "menu_logo": "/x.png"}), encoding="utf-8"
            )
            with patch.object(anomalie_views, "_anomalie_lists_path", return_value=path):
                saved = anomalie_views._save_anomalie_derived_sources(
                    {"capi_reparto": {"ruoli": [2], "extra": ["Tizio"], "esclusi": []}}
                )
                self.assertEqual(saved["capi_reparto"]["ruoli"], [2])
                reloaded = anomalie_views._load_anomalie_derived_sources()
                self.assertEqual(reloaded["capi_reparto"]["extra"], ["Tizio"])
                payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["causali_doc"], ["OP"])
        self.assertEqual(payload["menu_logo"], "/x.png")

    def test_ruoli_visibili_permessi_normalizzati(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anomalie_liste.json"
            with patch.object(anomalie_views, "_anomalie_lists_path", return_value=path):
                saved = anomalie_views._save_anomalie_permessi_ruoli(["3", 3, "no", 0])
                self.assertEqual(saved, [3])
                self.assertEqual(anomalie_views._load_anomalie_permessi_ruoli(), [3])


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
)
class EmailLogTests(TestCase):
    """Ogni invio lascia una riga di log; il reinvio rispedisce il messaggio salvato."""

    def test_invio_riuscito_registra_riga_sent(self):
        sent, row = send_and_log_email(
            kind=AnomalieEmailLog.Kind.CONFERMA_AGGIORNAMENTI,
            subject="Aggiornamenti OP 123",
            body_text="corpo",
            body_html="<p>corpo</p>",
            to=["capo@example.com"],
            op_id="123",
        )
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(row.status, AnomalieEmailLog.Status.SENT)
        self.assertEqual(row.to_emails, ["capo@example.com"])
        self.assertEqual(row.op_id, "123")

    def test_invio_fallito_registra_riga_failed_e_rilancia(self):
        with patch(
            "django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp ko")
        ):
            with self.assertRaises(OSError):
                send_and_log_email(
                    kind=AnomalieEmailLog.Kind.CONFERMA_AGGIORNAMENTI,
                    subject="Oggetto",
                    body_text="corpo",
                    to=["capo@example.com"],
                )
        row = AnomalieEmailLog.objects.get()
        self.assertEqual(row.status, AnomalieEmailLog.Status.FAILED)
        self.assertIn("smtp ko", row.error)

    def test_fail_silently_non_rilancia_e_logga(self):
        with patch(
            "django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp ko")
        ):
            sent, row = send_and_log_email(
                kind=AnomalieEmailLog.Kind.ESCALATION,
                subject="Resoconto",
                body_text="corpo",
                to=["sup@example.com"],
                fail_silently=True,
            )
        self.assertFalse(sent)
        self.assertEqual(row.status, AnomalieEmailLog.Status.FAILED)

    def test_reinvio_crea_nuova_riga_collegata(self):
        User = get_user_model()
        user = User.objects.create_user(username="admin.test", password="x")
        _, original = send_and_log_email(
            kind=AnomalieEmailLog.Kind.MAIL_ACTION,
            subject="Azione richiesta",
            body_text="corpo",
            body_html="<p>corpo</p>",
            to=["car@example.com"],
            op_id="OP-9",
        )
        mail.outbox.clear()

        sent, resent = resend_logged_email(original, user=user)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Azione richiesta")
        self.assertEqual(mail.outbox[0].to, ["car@example.com"])
        self.assertEqual(resent.resend_of_id, original.pk)
        self.assertEqual(resent.created_by_id, user.pk)
        self.assertTrue(resent.is_resend)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ConfigPageRenderTests(TestCase):
    """La pagina rende le nuove sezioni senza far uscire markup di template."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="anom-admin", email="anom-admin@example.local", password="pass12345"
        )
        self.client.force_login(self.admin)

    def _get(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        # Un commento Django multi-riga eseguirebbe i tag interni: qui verifichiamo
        # solo che nulla del sorgente template finisca a video.
        self.assertNotIn("{%", html)
        self.assertNotIn("{{", html)
        return html

    def test_tab_config_espone_gli_editor_delle_liste_derivate(self):
        html = self._get("/gestione-anomalie/configurazione?tab=config")
        self.assertIn('data-derived-key="capi_reparto"', html)
        self.assertIn('data-derived-key="capi_commessa"', html)
        self.assertIn("window._CFG_DERIVED_SOURCES", html)
        self.assertIn("window._CFG_RUOLI_OPERATIVI", html)

    def test_tab_permessi_ha_tabelle_chiuse_di_default(self):
        html = self._get("/gestione-anomalie/configurazione?tab=permessi&sub=accessi")
        self.assertIn("collapse-block", html)
        self.assertIn('class="collapse-body" hidden', html)
        self.assertIn("Ruoli operativi mostrati in questa pagina", html)

    def test_tab_log_mostra_il_registro_email_con_reinvio(self):
        AnomalieEmailLog.objects.create(
            kind=AnomalieEmailLog.Kind.MAIL_ACTION,
            status=AnomalieEmailLog.Status.SENT,
            subject="Azione richiesta OP 77",
            to_emails=["car@example.com"],
            body_text="corpo della mail",
            op_id="77",
        )
        html = self._get("/gestione-anomalie/configurazione?tab=log")
        self.assertIn("Azione richiesta OP 77", html)
        self.assertIn("car@example.com", html)
        self.assertIn('value="resend_email"', html)

    def test_reinvio_dal_log_rispedisce_la_mail_salvata(self):
        row = AnomalieEmailLog.objects.create(
            kind=AnomalieEmailLog.Kind.MAIL_ACTION,
            status=AnomalieEmailLog.Status.SENT,
            subject="Azione richiesta OP 77",
            from_email="noreply@example.com",
            to_emails=["car@example.com"],
            body_text="corpo della mail",
            op_id="77",
        )
        mail.outbox.clear()
        response = self.client.post(
            "/gestione-anomalie/configurazione",
            {"action": "resend_email", "email_log_id": row.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("tab=log", response["Location"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Azione richiesta OP 77")
        self.assertTrue(AnomalieEmailLog.objects.filter(resend_of=row).exists())

    def test_salvataggio_ruoli_visibili_permessi(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anomalie_liste.json"
            with patch.object(anomalie_views, "_anomalie_lists_path", return_value=path):
                response = self.client.post(
                    "/gestione-anomalie/configurazione",
                    {"action": "save_permessi_ruoli", "permessi_ruolo_id": ["5", "9"], "sub": "accessi"},
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(anomalie_views._load_anomalie_permessi_ruoli(), [5, 9])
