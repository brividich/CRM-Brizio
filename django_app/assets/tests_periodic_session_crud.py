"""Verifiche periodiche: modifica ed eliminazione di una singola verifica registrata."""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    PeriodicCheckAttachment,
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
)
from assets.services import periodic_checks as checks

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class SessioneModificaEliminaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="pc-crud", password="x", email="c@y.z")
        self.client.force_login(self.admin)
        self._tmp = tempfile.TemporaryDirectory()
        override = override_settings(ASSETS_PRIVATE_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._tmp.cleanup)
        system = PeriodicCheckSystem.objects.create(name="Impianto elettrico")
        self.check_type = PeriodicCheckType.objects.create(
            system=system, name="Verifica quadri", frequency_months=12, method=PeriodicCheckType.METHOD_REPORT
        )
        today = timezone.localdate()
        self.old = self._session(today - timedelta(days=400))
        self.recent = self._session(today - timedelta(days=10))

    def _session(self, performed_on: date) -> PeriodicCheckSession:
        return checks.register_session(
            checks.SessionInput(
                check_type=self.check_type,
                performed_on=performed_on,
                outcome=PeriodicCheckSession.OUTCOME_OK,
                results=[checks.ResultInput(label="Rilievo", kind=PeriodicCheckResult.KIND_REMARK,
                                            result=PeriodicCheckResult.RESULT_KO)],
            ),
            user=self.admin,
            files=[SimpleUploadedFile("verbale.pdf", b"%PDF-1.4\nx\n%%EOF\n", content_type="application/pdf")],
        )

    def test_pulsanti_in_storico_e_dettaglio(self):
        storico = self.client.get(reverse("assets:periodic_check_type_detail", args=[self.check_type.id]) + "?tab=storico")
        self.assertContains(storico, reverse("assets:periodic_check_session_edit", args=[self.recent.id]))
        self.assertContains(storico, reverse("assets:periodic_check_session_delete", args=[self.recent.id]))
        dettaglio = self.client.get(reverse("assets:periodic_check_session_detail", args=[self.recent.id]))
        self.assertContains(dettaglio, reverse("assets:periodic_check_session_edit", args=[self.recent.id]))
        self.assertContains(dettaglio, reverse("assets:periodic_check_session_delete", args=[self.recent.id]))

    def test_modifica_aggiorna_dati_e_scadenza_del_tipo(self):
        url = reverse("assets:periodic_check_session_edit", args=[self.recent.id])
        self.assertEqual(self.client.get(url).status_code, 200)
        new_date = timezone.localdate() - timedelta(days=100)
        response = self.client.post(url, {
            "performed_on": new_date.isoformat(),
            "outcome": PeriodicCheckSession.OUTCOME_REMARKS,
            "technician": "Mario Rossi",
            "notes": "corretta",
        })
        self.assertRedirects(response, reverse("assets:periodic_check_session_detail", args=[self.recent.id]))
        self.recent.refresh_from_db()
        self.check_type.refresh_from_db()
        self.assertEqual(self.recent.performed_on, new_date)
        self.assertEqual(self.recent.outcome, PeriodicCheckSession.OUTCOME_REMARKS)
        self.assertEqual(self.recent.technician, "Mario Rossi")
        self.assertEqual(self.check_type.next_due_date, self.check_type.next_due_from(new_date))
        # Esiti e allegati restano.
        self.assertEqual(self.recent.results.count(), 1)
        self.assertEqual(self.recent.attachments.count(), 1)

    def test_modifica_rifiuta_scadenza_prima_della_data(self):
        url = reverse("assets:periodic_check_session_edit", args=[self.recent.id])
        performed = timezone.localdate()
        response = self.client.post(url, {
            "performed_on": performed.isoformat(),
            "outcome": PeriodicCheckSession.OUTCOME_OK,
            "next_due_date": (performed - timedelta(days=1)).isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "deve essere dopo la data della verifica")

    def test_elimina_rimuove_esiti_allegati_file_e_ricalcola_scadenza(self):
        attachment = self.recent.attachments.get()
        file_path = Path(attachment.file.storage.path(attachment.file.name))
        self.assertTrue(file_path.exists())
        response = self.client.post(reverse("assets:periodic_check_session_delete", args=[self.recent.id]))
        self.assertRedirects(
            response,
            reverse("assets:periodic_check_type_detail", args=[self.check_type.id]) + "?tab=storico",
            fetch_redirect_response=False,
        )
        self.assertFalse(PeriodicCheckSession.objects.filter(pk=self.recent.id).exists())
        self.assertFalse(PeriodicCheckAttachment.objects.filter(pk=attachment.pk).exists())
        self.assertFalse(PeriodicCheckResult.objects.filter(session_id=self.recent.id).exists())
        self.assertFalse(file_path.exists())
        # La scadenza torna a quella calcolata dalla verifica precedente.
        self.check_type.refresh_from_db()
        self.assertEqual(self.check_type.next_due_date, self.check_type.next_due_from(self.old.performed_on))
        self.assertTrue(PeriodicCheckSession.objects.filter(pk=self.old.id).exists())

    def test_elimina_solo_post(self):
        response = self.client.get(reverse("assets:periodic_check_session_delete", args=[self.recent.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PeriodicCheckSession.objects.filter(pk=self.recent.id).exists())

    def test_utente_senza_permesso_non_modifica_ne_elimina(self):
        plain = User.objects.create_user(username="pc-plain", password="x")
        self.client.force_login(plain)
        self.client.post(reverse("assets:periodic_check_session_delete", args=[self.recent.id]))
        self.assertTrue(PeriodicCheckSession.objects.filter(pk=self.recent.id).exists())
        self.client.post(reverse("assets:periodic_check_session_edit", args=[self.recent.id]), {
            "performed_on": "2020-01-01", "outcome": "KO",
        })
        self.recent.refresh_from_db()
        self.assertNotEqual(self.recent.performed_on, date(2020, 1, 1))
