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


class SegnalazioneAllegatoDownloadTests(TestCase):
    """Verifica che gli allegati delle segnalazioni siano accessibili
    solo agli utenti autenticati (e non via URL pubblico /media/)."""

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from .models import SegnalazioneAllegato

        self.user = get_user_model().objects.create_user(
            username="dp_user",
            email="dp_user@example.com",
            password="pwd12345",
        )
        # Crea onboarding completato per evitare redirect
        from core.models import UserOnboarding, Profile
        UserOnboarding.objects.create(user=self.user, completed=True, skipped=True)
        # Crea legacy_user per ACL
        from core.legacy_models import UtenteLegacy, Ruolo
        role = Ruolo.objects.create(id=999, nome="Test Role")
        legacy_user = UtenteLegacy.objects.create(
            id=999,
            nome="Test User",
            email="dp_user@example.com",
            password="hash",
            ruolo=role.nome,
            ruolo_id=role.id,
            attivo=True,
        )
        # Crea Profile per collegare l'utente Django al legacy_user
        Profile.objects.create(user=self.user, legacy_user_id=legacy_user.id, legacy_ruolo_id=role.id, legacy_ruolo=role.nome)
        self.segnalazione = SegnalazionePreposto.objects.create(
            titolo="Segn allegato",
            data_segnalazione=_aware_datetime(2026, 1, 10),
            descrizione="Test allegato",
        )
        self.allegato = SegnalazioneAllegato.objects.create(
            segnalazione=self.segnalazione,
            nome_file="prova.txt",
            file=SimpleUploadedFile("prova.txt", b"contenuto riservato", content_type="text/plain"),
        )

    def tearDown(self):
        # Rimuove il file temporaneo creato dal test dallo storage privato.
        try:
            if self.allegato.file and self.allegato.file.name:
                self.allegato.file.storage.delete(self.allegato.file.name)
        except Exception:
            pass

    def test_allegato_download_requires_login(self):
        url = reverse("diario_preposto:allegato_download", args=[self.allegato.pk])
        response = self.client.get(url)
        # Utente anonimo: redirect verso login (non 200, non file).
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("contenuto riservato", response.content.decode(errors="ignore"))

    def test_allegato_download_authenticated_returns_file(self):
        self.client.force_login(self.user)
        url = reverse("diario_preposto:allegato_download", args=[self.allegato.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])
        body = b"".join(response.streaming_content) if response.streaming else response.content
        self.assertEqual(body, b"contenuto riservato")

    def test_allegato_download_authenticated_creates_audit_log(self):
        from core.models import AuditLog

        self.client.force_login(self.user)
        before = AuditLog.objects.count()
        url = reverse("diario_preposto:allegato_download", args=[self.allegato.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        created = AuditLog.objects.filter(
            azione="download_allegato", modulo="diario_preposto",
        ).order_by("-id").first()
        self.assertIsNotNone(created)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        payload = created.dettaglio or {}
        self.assertEqual(payload.get("esito"), "success")
        self.assertEqual(payload.get("allegato_id"), self.allegato.id)
        self.assertEqual(payload.get("segnalazione_id"), self.segnalazione.id)
        # Nessun contenuto file nel payload audit
        serialized = repr(payload)
        self.assertNotIn("contenuto riservato", serialized)
