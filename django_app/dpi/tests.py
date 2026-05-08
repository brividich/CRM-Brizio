from __future__ import annotations

import shutil
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.models import FileField, ImageField
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import UserOnboarding
from core.upload_mime import UploadMimeValidationError
from dpi.models import CategoriaDPI, ConsegnaDPI, ModelloDPI, RichiestaDPI, StatoRichiesta, TagliaDPI, TipoDPI
from dpi.views import DPI_MIME_POLICY_FIELDS


PNG_SIGNATURE_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lx9u9QAAAABJRU5ErkJggg=="
)


def _reset_test_dir(name: str) -> Path:
    root = Path(__file__).resolve().parents[2] / ".tmp_tests"
    target = root / name
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    return target


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DpiCategoryMimeValidationTests(TestCase):
    def setUp(self):
        super().setUp()
        self._test_dir = _reset_test_dir("dpi_mime_validation")
        self._media_root = self._test_dir / "media"
        self._upload_tmp = self._test_dir / "upload_tmp"
        self._media_root.mkdir(parents=True, exist_ok=True)
        self._upload_tmp.mkdir(parents=True, exist_ok=True)
        self._media_override = override_settings(
            MEDIA_ROOT=self._media_root,
            FILE_UPLOAD_TEMP_DIR=str(self._upload_tmp),
        )
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)
        self.addCleanup(lambda: shutil.rmtree(self._test_dir, ignore_errors=True))
        self.user = get_user_model().objects.create_superuser(
            username="dpi-admin",
            email="dpi-admin@example.com",
            password="pass12345",
        )
        self.client.force_login(self.user)
        self.url = reverse("dpi:categoria_nuova")

    def _base_payload(self) -> dict:
        return {
            "nome": "Guanti anti-taglio",
            "descrizione": "Categoria test",
            "icona_emoji": "G",
            "vita_utile_giorni": "120",
            "unita_misura": "pz",
            "scorta_minima": "2",
            "is_active": "on",
            "order_index": "10",
        }

    def test_categoria_upload_accepts_valid_image_when_mime_is_valid(self):
        with patch("dpi.views.validate_extension_and_mime", return_value="image/png"):
            response = self.client.post(
                self.url,
                {
                    **self._base_payload(),
                    "immagine": SimpleUploadedFile("categoria.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"),
                },
            )

        self.assertEqual(response.status_code, 302)
        categoria = CategoriaDPI.objects.get(nome="Guanti anti-taglio")
        self.assertTrue(bool(categoria.immagine))

    def test_categoria_upload_rejects_spoofed_mime(self):
        with patch(
            "dpi.views.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("categoria.png: tipo MIME non consentito (application/x-msdownload)."),
        ) as mock_validate:
            response = self.client.post(
                self.url,
                {
                    **self._base_payload(),
                    "immagine": SimpleUploadedFile("categoria.png", b"MZ...", content_type="image/png"),
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_validate.called)
        self.assertEqual(CategoriaDPI.objects.count(), 0)

    def test_categoria_upload_fails_closed_when_mime_engine_is_unavailable(self):
        with patch(
            "dpi.views.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("Validazione MIME non disponibile sul server. Upload bloccato."),
        ) as mock_validate:
            response = self.client.post(
                self.url,
                {
                    **self._base_payload(),
                    "immagine": SimpleUploadedFile("categoria.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"),
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_validate.called)
        self.assertEqual(CategoriaDPI.objects.count(), 0)


class DpiMimePolicyCoverageTests(SimpleTestCase):
    def test_all_dpi_file_and_image_fields_are_covered_by_mime_policy(self):
        app_config = apps.get_app_config("dpi")
        discovered_fields: set[str] = set()
        for model in app_config.get_models():
            for field in model._meta.get_fields():
                if not isinstance(field, (FileField, ImageField)):
                    continue
                discovered_fields.add(f"{model.__name__}.{field.name}")

        self.assertEqual(discovered_fields, set(DPI_MIME_POLICY_FIELDS))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DpiCatalogRequestTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="dpi-user",
            email="dpi-user@example.com",
            password="pass12345",
        )
        self.admin = get_user_model().objects.create_superuser(
            username="dpi-manager",
            email="dpi-manager@example.com",
            password="pass12345",
        )
        UserOnboarding.objects.create(user=self.user, completed=True)

    def _catalogo(self, suffix: str = ""):
        categoria = CategoriaDPI.objects.create(
            nome=f"Guanti{suffix}",
            icona_emoji="G",
            vita_utile_giorni=365,
            is_active=True,
        )
        tipo = TipoDPI.objects.create(categoria=categoria, nome=f"Antitaglio{suffix}", is_active=True)
        modello = ModelloDPI.objects.create(
            tipo=tipo,
            codice=f"G-AT-{suffix or 'BASE'}",
            nome=f"Blade Safe{suffix}",
            vita_utile_giorni=180,
            is_active=True,
        )
        taglia = TagliaDPI.objects.create(modello=modello, valore=f"M{suffix}", is_active=True)
        return categoria, tipo, modello, taglia

    def _post_nuova(self, payload: dict):
        self.client.force_login(self.user)
        return self.client.post(reverse("dpi:nuova"), payload)

    def test_catalog_type_model_size_can_be_created(self):
        categoria, tipo, modello, taglia = self._catalogo()

        self.assertEqual(tipo.categoria, categoria)
        self.assertEqual(modello.tipo, tipo)
        self.assertEqual(taglia.modello, modello)
        self.assertEqual(modello.effective_vita_utile_giorni, 180)

    def test_new_request_saves_type_model_size(self):
        categoria, tipo, modello, taglia = self._catalogo()

        response = self._post_nuova({
            "categoria_id": str(categoria.pk),
            "tipo_dpi_id": str(tipo.pk),
            "modello_dpi_id": str(modello.pk),
            "taglia_dpi_id": str(taglia.pk),
            "quantita": "2",
            "motivazione": "Prima dotazione",
        })

        self.assertEqual(response.status_code, 302)
        richiesta = RichiestaDPI.objects.get()
        self.assertEqual(richiesta.categoria, categoria)
        self.assertEqual(richiesta.tipo_dpi, tipo)
        self.assertEqual(richiesta.modello_dpi, modello)
        self.assertEqual(richiesta.taglia_dpi, taglia)

    def test_new_request_with_category_only_still_works(self):
        categoria = CategoriaDPI.objects.create(nome="Occhiali", icona_emoji="O", is_active=True)

        response = self._post_nuova({
            "categoria_id": str(categoria.pk),
            "quantita": "1",
            "motivazione": "",
        })

        self.assertEqual(response.status_code, 302)
        richiesta = RichiestaDPI.objects.get()
        self.assertEqual(richiesta.categoria, categoria)
        self.assertIsNone(richiesta.tipo_dpi)
        self.assertIsNone(richiesta.modello_dpi)
        self.assertIsNone(richiesta.taglia_dpi)

    def test_new_request_rejects_incoherent_type_category(self):
        categoria, _, _, _ = self._catalogo("A")
        _, tipo_altro, _, _ = self._catalogo("B")

        response = self._post_nuova({
            "categoria_id": str(categoria.pk),
            "tipo_dpi_id": str(tipo_altro.pk),
            "quantita": "1",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RichiestaDPI.objects.count(), 0)

    def test_new_request_rejects_incoherent_model_type(self):
        categoria, tipo, _, _ = self._catalogo("A")
        _, _, modello_altro, _ = self._catalogo("B")

        response = self._post_nuova({
            "categoria_id": str(categoria.pk),
            "tipo_dpi_id": str(tipo.pk),
            "modello_dpi_id": str(modello_altro.pk),
            "quantita": "1",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RichiestaDPI.objects.count(), 0)

    def test_new_request_rejects_incoherent_size_model(self):
        categoria, tipo, modello, _ = self._catalogo("A")
        _, _, _, taglia_altra = self._catalogo("B")

        response = self._post_nuova({
            "categoria_id": str(categoria.pk),
            "tipo_dpi_id": str(tipo.pk),
            "modello_dpi_id": str(modello.pk),
            "taglia_dpi_id": str(taglia_altra.pk),
            "quantita": "1",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RichiestaDPI.objects.count(), 0)

    def test_detail_renders_type_model_size(self):
        categoria, tipo, modello, taglia = self._catalogo()
        richiesta = RichiestaDPI.objects.create(
            categoria=categoria,
            tipo_dpi=tipo,
            modello_dpi=modello,
            taglia_dpi=taglia,
            richiedente_nome="Mario Rossi",
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dpi:detail", args=[richiesta.pk]))

        self.assertContains(response, tipo.nome)
        self.assertContains(response, modello.codice)
        self.assertContains(response, taglia.valore)

    def test_management_detail_renders_type_model_size(self):
        categoria, tipo, modello, taglia = self._catalogo()
        richiesta = RichiestaDPI.objects.create(
            categoria=categoria,
            tipo_dpi=tipo,
            modello_dpi=modello,
            taglia_dpi=taglia,
            richiedente_nome="Mario Rossi",
            created_by=self.user,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dpi:gestione_detail", args=[richiesta.pk]))

        self.assertContains(response, tipo.nome)
        self.assertContains(response, modello.codice)
        self.assertContains(response, taglia.valore)

    def test_delivery_uses_model_lifetime_override(self):
        categoria, tipo, modello, taglia = self._catalogo()
        richiesta = RichiestaDPI.objects.create(
            categoria=categoria,
            tipo_dpi=tipo,
            modello_dpi=modello,
            taglia_dpi=taglia,
            stato=StatoRichiesta.APPROVATA,
            richiedente_nome="Mario Rossi",
            created_by=self.user,
        )
        self.client.force_login(self.admin)
        data_consegna = date(2026, 5, 5)

        response = self.client.post(reverse("dpi:consegna", args=[richiesta.pk]), {
            "data_consegna": data_consegna.isoformat(),
            "note_consegna": "",
            "firmato_ricevuta": "1",
        })

        self.assertEqual(response.status_code, 302)
        consegna = ConsegnaDPI.objects.get(richiesta=richiesta)
        self.assertEqual(consegna.data_scadenza_stimata, data_consegna + timedelta(days=180))

    def test_delivery_saves_signature_data_uri_and_marks_signed(self):
        categoria, tipo, modello, taglia = self._catalogo()
        richiesta = RichiestaDPI.objects.create(
            categoria=categoria,
            tipo_dpi=tipo,
            modello_dpi=modello,
            taglia_dpi=taglia,
            stato=StatoRichiesta.APPROVATA,
            richiedente_nome="Mario Rossi",
            created_by=self.user,
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse("dpi:consegna", args=[richiesta.pk]), {
            "data_consegna": date(2026, 5, 5).isoformat(),
            "firma_immagine": PNG_SIGNATURE_DATA_URI,
        })

        self.assertEqual(response.status_code, 302)
        consegna = ConsegnaDPI.objects.get(richiesta=richiesta)
        self.assertTrue(consegna.firmato_ricevuta)
        self.assertEqual(consegna.firma_immagine, PNG_SIGNATURE_DATA_URI)

    def test_scadenza_alias_and_semaforo(self):
        categoria, _, _, _ = self._catalogo()
        richiesta = RichiestaDPI.objects.create(
            categoria=categoria,
            stato=StatoRichiesta.CONSEGNATA,
            richiedente_nome="Mario Rossi",
            created_by=self.user,
        )
        consegna = ConsegnaDPI.objects.create(
            richiesta=richiesta,
            data_consegna=date.today(),
            data_scadenza_stimata=date.today() + timedelta(days=10),
        )

        self.assertEqual(consegna.scadenza_calcolata, consegna.data_scadenza_stimata)
        self.assertEqual(consegna.semaforo_scadenza, "arancione")

    def test_report_conformita_renders_for_manager(self):
        categoria, _, _, _ = self._catalogo()
        categoria.obbligatoria_mansionario = True
        categoria.save(update_fields=["obbligatoria_mansionario"])
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dpi:report_conformita"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Report conformita DPI")

    def test_modello_dpi_image_mime_policy(self):
        categoria, tipo, _, _ = self._catalogo()
        self.client.force_login(self.admin)
        with patch("dpi.views.validate_extension_and_mime", return_value="image/png") as mock_validate:
            response = self.client.post(
                reverse("dpi:modello_nuovo"),
                {
                    "tipo_id": str(tipo.pk),
                    "codice": "ELM-01",
                    "nome": "Elmetto Vertex",
                    "produttore": "ACME",
                    "descrizione": "",
                    "vita_utile_giorni": "90",
                    "is_active": "on",
                    "immagine": SimpleUploadedFile("modello.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"),
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(mock_validate.called)
        self.assertTrue(ModelloDPI.objects.get(codice="ELM-01").immagine)


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class DpiExpiryReminderCommandTests(TestCase):
    def test_command_sends_digest_for_expiring_dpi(self):
        categoria = CategoriaDPI.objects.create(nome="Elmetto", is_active=True, vita_utile_giorni=30)
        richiesta = RichiestaDPI.objects.create(
            categoria=categoria,
            stato=StatoRichiesta.CONSEGNATA,
            richiedente_nome="Mario Rossi",
        )
        ConsegnaDPI.objects.create(
            richiesta=richiesta,
            data_consegna=date.today(),
            data_scadenza_stimata=date.today() + timedelta(days=5),
        )

        out = StringIO()
        call_command("send_dpi_expiry_reminders", "--recipients", "rsp@example.com", stdout=out)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("[DPI]", mail.outbox[0].subject)
        self.assertIn(richiesta.numero, mail.outbox[0].body)
