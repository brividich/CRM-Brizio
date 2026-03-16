from __future__ import annotations

from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import SegnalazionePreposto


def _aware_datetime(year: int, month: int, day: int, hour: int = 9, minute: int = 0):
    return timezone.make_aware(
        datetime(year, month, day, hour, minute),
        timezone.get_current_timezone(),
    )


class SegnalazionePrepostoCodiceTests(TestCase):
    def test_assigns_yearly_codes_starting_from_zero(self):
        first_2025 = SegnalazionePreposto.objects.create(
            titolo="Segnalazione 1",
            data_segnalazione=_aware_datetime(2025, 1, 10),
            descrizione="Descrizione 1",
        )
        second_2025 = SegnalazionePreposto.objects.create(
            titolo="Segnalazione 2",
            data_segnalazione=_aware_datetime(2025, 2, 11),
            descrizione="Descrizione 2",
        )
        first_2026 = SegnalazionePreposto.objects.create(
            titolo="Segnalazione 3",
            data_segnalazione=_aware_datetime(2026, 1, 5),
            descrizione="Descrizione 3",
        )

        self.assertEqual(first_2025.codice_identificativo, "DP-2025-0000")
        self.assertEqual(second_2025.codice_identificativo, "DP-2025-0001")
        self.assertEqual(first_2026.codice_identificativo, "DP-2026-0000")

    def test_save_with_update_fields_restores_missing_code(self):
        first = SegnalazionePreposto.objects.create(
            titolo="Segnalazione 1",
            data_segnalazione=_aware_datetime(2025, 1, 10),
            descrizione="Descrizione 1",
        )
        second = SegnalazionePreposto.objects.create(
            titolo="Segnalazione 2",
            data_segnalazione=_aware_datetime(2025, 2, 11),
            descrizione="Descrizione 2",
        )

        SegnalazionePreposto.objects.filter(pk=second.pk).update(codice_identificativo="")
        second.refresh_from_db()
        second.descrizione = "Descrizione aggiornata"
        second.save(update_fields=["descrizione", "updated_at"])

        self.assertEqual(first.codice_identificativo, "DP-2025-0000")
        self.assertEqual(second.codice_identificativo, "DP-2025-0001")

    def test_existing_code_does_not_change_when_record_is_edited(self):
        segnalazione = SegnalazionePreposto.objects.create(
            titolo="Segnalazione 1",
            data_segnalazione=_aware_datetime(2025, 1, 10),
            descrizione="Descrizione 1",
        )

        segnalazione.data_segnalazione = _aware_datetime(2026, 1, 10)
        segnalazione.descrizione = "Descrizione aggiornata"
        segnalazione.save()

        self.assertEqual(segnalazione.codice_identificativo, "DP-2025-0000")

    def test_export_pdf_is_rendered_inline(self):
        user = get_user_model().objects.create_superuser(
            username="tester_pdf",
            email="tester_pdf@example.com",
            password="pwd12345",
        )
        segnalazione = SegnalazionePreposto.objects.create(
            titolo="Segnalazione PDF",
            data_segnalazione=_aware_datetime(2025, 3, 5),
            descrizione="Descrizione PDF",
        )

        self.client.force_login(user)
        response = self.client.get(reverse("diario_preposto:export_pdf", args=[segnalazione.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline;", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
