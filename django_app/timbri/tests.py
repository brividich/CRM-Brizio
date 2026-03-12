from __future__ import annotations

import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from . import views as timbri_views
from .models import OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine

User = get_user_model()


def _png_upload(name: str = "sample.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (255, 255, 255, 0)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _ensure_anagrafica_table() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS anagrafica_dipendenti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aliasusername VARCHAR(200) NULL,
                    nome VARCHAR(200) NULL,
                    cognome VARCHAR(200) NULL,
                    mansione VARCHAR(200) NULL,
                    reparto VARCHAR(200) NULL,
                    ruolo VARCHAR(200) NULL,
                    matricola VARCHAR(100) NULL,
                    attivo INTEGER NULL,
                    email VARCHAR(200) NULL,
                    email_notifica VARCHAR(200) NULL,
                    utente_id INTEGER NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('anagrafica_dipendenti', 'U') IS NULL
                CREATE TABLE anagrafica_dipendenti (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    aliasusername NVARCHAR(200) NULL,
                    nome NVARCHAR(200) NULL,
                    cognome NVARCHAR(200) NULL,
                    mansione NVARCHAR(200) NULL,
                    reparto NVARCHAR(200) NULL,
                    ruolo NVARCHAR(200) NULL,
                    matricola NVARCHAR(100) NULL,
                    attivo BIT NULL,
                    email NVARCHAR(200) NULL,
                    email_notifica NVARCHAR(200) NULL,
                    utente_id INT NULL
                )
                """
            )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TimbriModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="timbri-model", password="pass12345")
        self.operatore = OperatoreTimbri.objects.create(nome="Luca", cognome="Bova", matricola="A001")
        self.registro = RegistroTimbro.objects.create(operatore=self.operatore, codice_timbro="CNO A001")

    def test_png_image_variant_is_saved(self):
        image = RegistroTimbroImmagine(registro=self.registro, variante=RegistroTimbroImmagine.VARIANTE_TIMBRO, image=_png_upload())
        image.save()
        self.assertEqual(RegistroTimbroImmagine.objects.count(), 1)
        self.assertGreater(image.file_size, 0)

    def test_only_png_is_allowed(self):
        bad = SimpleUploadedFile("bad.jpg", b"fake", content_type="image/jpeg")
        image = RegistroTimbroImmagine(registro=self.registro, variante=RegistroTimbroImmagine.VARIANTE_TIMBRO, image=bad)
        with self.assertRaises(Exception):
            image.full_clean()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TimbriViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="timbri-admin", email="timbri-admin@test.local", password="pass12345")
        self.user = User.objects.create_user(username="timbri-user", password="pass12345")
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            vendor = connection.vendor
            if vendor == "sqlite":
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, mansione, reparto, ruolo, matricola, attivo, email, email_notifica, utente_id)
                    VALUES
                        ('s.gentile', 'Sara', 'Gentile', 'DIR', 'DIR', 'DIR', 'DI001', 1, 's.gentile@test.local', 's.gentile@example.com', NULL)
                    """
                )
                self.legacy_id = int(cursor.lastrowid)
            else:
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, mansione, reparto, ruolo, matricola, attivo, email, email_notifica, utente_id)
                    OUTPUT INSERTED.id
                    VALUES
                        ('s.gentile', 'Sara', 'Gentile', 'DIR', 'DIR', 'DIR', 'DI001', 1, 's.gentile@test.local', 's.gentile@example.com', NULL)
                    """
                )
                self.legacy_id = int(cursor.fetchone()[0])
        self.operatore = OperatoreTimbri.objects.create(
            legacy_anagrafica_id=self.legacy_id,
            nome="Sara",
            cognome="Gentile",
            matricola="DI001",
            reparto="DIR",
            ruolo="DIR",
        )
        self.registro = RegistroTimbro.objects.create(operatore=self.operatore, codice_timbro="CNO DIR001", is_attivo=True)

    def test_index_200_for_admin(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("timbri:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registro timbri")
        self.assertContains(response, "Gentile Sara")

    def test_index_200_when_schema_is_missing(self):
        self.client.force_login(self.admin)
        with patch("timbri.views._timbri_schema_issue", return_value="Modulo Timbri non inizializzato sul database SQL Server."):
            response = self.client.get(reverse("timbri:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Schema SQL non pronto")
        self.assertContains(response, "Modulo Timbri non inizializzato sul database SQL Server.")

    def test_caporeparto_can_view_but_cannot_create(self):
        self.client.force_login(self.user)
        legacy = SimpleNamespace(id=2, nome="Capo", ruolo="caporeparto", ruolo_id=2)
        with patch("timbri.views.get_legacy_user", return_value=legacy):
            response = self.client.get(reverse("timbri:index"))
            self.assertEqual(response.status_code, 200)
            denied = self.client.get(reverse("timbri:operatore_create"))
            self.assertEqual(denied.status_code, 403)

    def test_admin_create_route_redirects_to_anagrafica(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("timbri:operatore_create"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], reverse("anagrafica:dipendenti_list"))

    def test_config_page_can_save_mapping(self):
        self.client.force_login(self.admin)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.ini"
            config_path.write_text("[AZIENDA]\ntenant_id = test\nclient_id = test\nclient_secret = secret\nsite_id = site\n", encoding="utf-8")
            with patch("timbri.views._config_ini_path", return_value=config_path):
                response = self.client.post(
                    reverse("timbri:configurazione") + "?tab=config",
                    {
                        "action": "save_sharepoint_config",
                        "list_id": "list-test",
                        "field_operatore_lookup": "OperatoreLookupId",
                        "field_operatore_label": "Operatore",
                        "field_matricola": "Matricola",
                        "field_reparto": "Operatore: Reparto",
                        "field_qualifica": "Qualifica",
                        "field_codice_timbro": "Timbro",
                        "field_data_consegna": "Consegna Timbro",
                        "field_data_ritiro": "Data ritiro timbro",
                        "field_note": "Note",
                        "field_firma_testo": "Firma",
                        "field_attivo": "Attivo",
                        "field_tipo_timbro": "Tipo timbro",
                        "field_image_1": "URL Timbro1",
                        "field_image_2": "URL Timbro2",
                        "field_image_3": "URL Timbro3",
                    },
                )
            self.assertEqual(response.status_code, 302)
            text = config_path.read_text(encoding="utf-8")
            self.assertIn("[TIMBRI]", text)
            self.assertIn("list_id = list-test", text)
            self.assertIn("field_operatore_lookup = OperatoreLookupId", text)

    def test_config_page_normalizes_guid_like_list_id(self):
        self.client.force_login(self.admin)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.ini"
            config_path.write_text("[AZIENDA]\ntenant_id = test\nclient_id = test\nclient_secret = secret\nsite_id = site\n", encoding="utf-8")
            with patch("timbri.views._config_ini_path", return_value=config_path):
                response = self.client.post(
                    reverse("timbri:configurazione") + "?tab=config",
                    {
                        "action": "save_sharepoint_config",
                        "list_id": "7B23dddb4c-ea5f-47b7-85c7-e75c5524c653",
                    },
                )
            self.assertEqual(response.status_code, 302)
            text = config_path.read_text(encoding="utf-8")
            self.assertIn("list_id = 23dddb4c-ea5f-47b7-85c7-e75c5524c653", text)

    def test_config_page_can_reset_table_and_reimport_names(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("timbri:configurazione") + "?tab=import",
            {"action": "reset_table"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RegistroTimbro.objects.count(), 0)
        self.assertEqual(RegistroTimbroImmagine.objects.count(), 0)
        self.assertEqual(OperatoreTimbri.objects.count(), 1)
        operatore = OperatoreTimbri.objects.get()
        self.assertEqual(operatore.legacy_anagrafica_id, self.legacy_id)
        self.assertEqual(operatore.full_name, "Gentile Sara")

    def test_reset_table_deduplicates_uppercase_legacy_rows(self):
        with connection.cursor() as cursor:
            vendor = connection.vendor
            if vendor == "sqlite":
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, matricola, ruolo, email, utente_id)
                    VALUES
                        (NULL, 'DERYA', 'AKSOY', 'INT010', 'Operatore Aggiustaggio', 'legacy@test.local', NULL)
                    """
                )
                uppercase_id = int(cursor.lastrowid)
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, email, utente_id)
                    VALUES
                        ('d.aksoy', 'Derya', 'Aksoy', 'd.aksoy@example.local', 271)
                    """
                )
                proper_id = int(cursor.lastrowid)
            else:
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, matricola, ruolo, email, utente_id)
                    OUTPUT INSERTED.id
                    VALUES
                        (NULL, 'DERYA', 'AKSOY', 'INT010', 'Operatore Aggiustaggio', 'legacy@test.local', NULL)
                    """
                )
                uppercase_id = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, email, utente_id)
                    OUTPUT INSERTED.id
                    VALUES
                        ('d.aksoy', 'Derya', 'Aksoy', 'd.aksoy@example.local', 271)
                    """
                )
                proper_id = int(cursor.fetchone()[0])

        summary = timbri_views.reset_timbri_table()
        self.assertEqual(summary["imported_operatori"], 2)
        matches = list(OperatoreTimbri.objects.filter(cognome__iexact="aksoy", nome__iexact="derya"))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].legacy_anagrafica_id, proper_id)
        self.assertEqual(matches[0].matricola, "INT010")
        self.assertEqual(matches[0].ruolo, "Operatore Aggiustaggio")
        self.assertNotEqual(matches[0].legacy_anagrafica_id, uppercase_id)

    def test_import_skips_portal_edited_records(self):
        request = RequestFactory().post(reverse("timbri:configurazione"))
        request.user = self.admin
        request.legacy_user = SimpleNamespace(id=1, nome="Admin", ruolo="admin", ruolo_id=1)
        self.registro.sharepoint_item_id = "35"
        self.registro.edited_in_portal = True
        self.registro.save(update_fields=["sharepoint_item_id", "edited_in_portal"])
        with patch("timbri.views._graph_list_items", return_value=[{"id": "35", "fields": {"Operatore": "Gentile Sara", "Timbro": "CNO DI001"}}]):
            result = timbri_views._import_sharepoint_records(request)
        self.assertEqual(result["skipped"], 1)

    def test_operatore_delete_removes_related_records(self):
        operatore = OperatoreTimbri.objects.create(nome="Manuale", cognome="Test")
        registro = RegistroTimbro.objects.create(operatore=operatore, codice_timbro="TMP001")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("timbri:operatore_delete", args=[operatore.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(OperatoreTimbri.objects.filter(id=operatore.id).exists())
        self.assertFalse(RegistroTimbro.objects.filter(id=registro.id).exists())

    def test_cleanup_orphans_relinks_records_by_matricola(self):
        orphan = OperatoreTimbri.objects.create(nome="Sara", cognome="Gentile", matricola="DI001")
        record = RegistroTimbro.objects.create(operatore=orphan, codice_timbro="TMP002")
        result = timbri_views.cleanup_orphan_operatori()
        self.assertEqual(result["orphans"], 1)
        self.assertEqual(result["relinked_operatori"], 1)
        self.assertEqual(result["records_relinked"], 1)
        self.assertFalse(OperatoreTimbri.objects.filter(id=orphan.id).exists())
        record.refresh_from_db()
        self.assertEqual(record.operatore.legacy_anagrafica_id, self.legacy_id)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TimbriAnagraficaIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ana-timbri", password="pass12345")
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            vendor = connection.vendor
            if vendor == "sqlite":
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, mansione, reparto, ruolo, matricola, attivo, email, email_notifica, utente_id)
                    VALUES
                        ('s.gentile', 'Sara', 'Gentile', 'DIR', 'DIR', 'DIR', 'DI001', 1, 's.gentile@test.local', 's.gentile@example.com', NULL)
                    """
                )
                legacy_id = int(cursor.lastrowid)
            else:
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, mansione, reparto, ruolo, matricola, attivo, email, email_notifica, utente_id)
                    OUTPUT INSERTED.id
                    VALUES
                        ('s.gentile', 'Sara', 'Gentile', 'DIR', 'DIR', 'DIR', 'DI001', 1, 's.gentile@test.local', 's.gentile@example.com', NULL)
                    """
                )
                legacy_id = int(cursor.fetchone()[0])
        operatore = OperatoreTimbri.objects.create(legacy_anagrafica_id=legacy_id, nome="Sara", cognome="Gentile", reparto="DIR")
        self.legacy_id = legacy_id
        RegistroTimbro.objects.create(operatore=operatore, codice_timbro="CNO DI001")

    def test_anagrafica_list_shows_timbri_link(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("anagrafica:dipendenti_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apri timbri")
        self.assertContains(response, reverse("timbri:operatore_detail_by_legacy", args=[self.legacy_id]))
