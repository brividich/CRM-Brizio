"""Segnaposto SQL della coda, flussi installati da soli, mail collegate al flusso."""
from datetime import datetime
from unittest.mock import MagicMock, patch

from django.core import mail
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings

from .managed_flows import assicura_installati, catalog, event_flow
from .models import EmailInviata, ManagedFlow


def _cursore_finto():
    cursore = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursore
    conn.vendor = "microsoft"
    return conn, cursore


class SegnapostoCodaTests(TestCase):
    """mssql-django fa ``sql % ('?', ...)``: con segnaposto ``?`` la query esplodeva."""

    def _formatta_come_mssql(self, sql, params):
        return sql % tuple("?" * len(params))

    def test_schedule_queue_event_usa_percento_s(self):
        from . import services

        conn, cursore = _cursore_finto()
        with patch.object(services, "_queue_table_has_column", return_value=True), \
                patch("django.db.connections", {"default": conn}):
            services._schedule_queue_event(
                source_code="s", source_table="t", source_pk="1", operation_type="insert",
                event_code="e", payload_json="{}", execute_after=datetime(2026, 11, 15, 10, 0),
            )
        sql, params = cursore.execute.call_args[0]
        self.assertNotIn("(?", sql)
        self.assertIn("?", self._formatta_come_mssql(sql, params))

    def test_count_source_usa_percento_s(self):
        from . import services

        conn, cursore = _cursore_finto()
        cursore.fetchone.return_value = (3,)
        with patch("automazioni.source_registry.get_source_definition", return_value={"table_name": "tab"}), \
                patch("automazioni.source_registry.get_source_fields", return_value=[{"name": "a"}, {"name": "d"}]), \
                patch("django.db.connections", {"default": conn}):
            n = services._count_source("x", "a", 1, window_field="d", window_days=7)
        self.assertEqual(n, 3)
        sql, params = cursore.execute.call_args[0]
        self._formatta_come_mssql(sql, params)


class FlussiInstallatiDaSoliTests(TestCase):
    def test_assicura_installati_crea_i_mancanti(self):
        self.assertFalse(ManagedFlow.objects.filter(code="diario_preposto_scheda").exists())
        self.assertGreater(assicura_installati(), 0)
        for codice in ("diario_preposto_scheda", "sicurezza_scheda_segnalazione"):
            self.assertTrue(ManagedFlow.objects.filter(code=codice).exists())
        self.assertEqual(assicura_installati(), 0)
        self.assertEqual(ManagedFlow.objects.count(), len(catalog()))

    def test_non_solleva(self):
        with patch("automazioni.managed_flows.install_flows", side_effect=RuntimeError("db")):
            self.assertEqual(assicura_installati(), 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@test.local")
class MailCollegateAlFlussoTests(TestCase):
    def setUp(self):
        assicura_installati()
        self.binding = ManagedFlow.objects.select_related("rule").get(code="diario_preposto_scheda")
        self.binding.rule.is_active = True
        self.binding.rule.is_draft = False
        self.binding.rule.save()

    def test_mail_dentro_il_flusso_porta_regola_e_run_log(self):
        @event_flow("diario_preposto_scheda", skipped_result=0)
        def manda():
            return EmailMessage("Scheda prova", "corpo", to=["rspp@example.com"]).send()

        manda()
        self.assertEqual(len(mail.outbox), 1)
        riga = EmailInviata.objects.get(oggetto="Scheda prova")
        self.assertEqual(riga.sorgente, "diario_preposto_scheda")
        self.assertEqual(riga.regola_id, self.binding.rule_id)
        self.assertIsNotNone(riga.run_log_id)

    def test_flussi_per_riga_risale_dalla_sorgente(self):
        from .mail_inviate import flussi_per_riga

        vecchia = EmailInviata.objects.create(origine="modulo", sorgente="diario_preposto_scheda",
                                              destinatari="a@example.com", oggetto="x")
        libera = EmailInviata.objects.create(origine="modulo", sorgente="tickets",
                                             destinatari="a@example.com", oggetto="y")
        righe = list(EmailInviata.objects.select_related("regola").filter(pk__in=[vecchia.pk, libera.pk]))
        flussi_per_riga(righe)
        per_pk = {r.pk: r.flusso for r in righe}
        self.assertEqual(per_pk[vecchia.pk]["rule_id"], self.binding.rule_id)
        self.assertEqual(per_pk[vecchia.pk]["codice"], "diario_preposto_scheda")
        self.assertIsNone(per_pk[libera.pk])
