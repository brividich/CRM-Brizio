from __future__ import annotations

from datetime import datetime
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.models import UserOnboarding

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


class SegnalazionePrepostoExcelExportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="tester_excel",
            email="tester_excel@example.com",
            password="pwd12345",
        )
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())
        self.client.force_login(self.user)
        self.matching = SegnalazionePreposto.objects.create(
            titolo="Segnalazione filtro",
            data_segnalazione=_aware_datetime(2026, 5, 4),
            descrizione="Descrizione inclusa",
            preposto="Mario Rossi",
            chi_segnala="Luca Verdi",
            creato_da=self.user,
        )
        SegnalazionePreposto.objects.create(
            titolo="Segnalazione esclusa",
            data_segnalazione=_aware_datetime(2026, 5, 5),
            descrizione="Descrizione esclusa",
            preposto="Anna Bianchi",
            chi_segnala="Giulia Neri",
            creato_da=self.user,
        )

    def test_export_excel_response_headers_workbook_columns_and_filters(self):
        response = self.client.get(reverse("diario_preposto:export_excel"), {"preposto": "Mario"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        expected_filename = f"diario_preposto_{timezone.now().strftime('%Y%m%d')}.xlsx"
        self.assertIn(expected_filename, response["Content-Disposition"])

        workbook = load_workbook(BytesIO(response.content), read_only=True, data_only=True)
        try:
            sheet = workbook["Diario Preposto"]
            headers = [cell.value for cell in sheet[1]]
            self.assertEqual(
                [str(header).lower() for header in headers],
                [
                    "codice identificativo",
                    "data segnalazione",
                    "titolo",
                    "descrizione",
                    "preposto",
                    "chi segnala",
                    "creato da",
                    "numero allegati",
                    "created_at",
                    "updated_at",
                ],
            )
            exported_titles = [row[2] for row in sheet.iter_rows(min_row=2, values_only=True)]
            self.assertEqual(exported_titles, [self.matching.titolo])
        finally:
            workbook.close()

    def test_export_excel_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("diario_preposto:export_excel"))

        self.assertEqual(response.status_code, 302)
