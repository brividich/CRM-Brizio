from __future__ import annotations

import io
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import skip
from unittest.mock import patch
from uuid import uuid4

# Nota: l'import timbri via Microsoft Graph/SharePoint è stato rimosso
# (commit 81ab983). L'import avviene ora da cartella/CSV (import_timbri_csv,
# import_timbri_da_share). I test che esercitavano il vecchio flusso Graph
# restano marcati @skip come traccia storica, non vanno riattivati.
_GRAPH_REMOVED = "Flusso import Graph/SharePoint rimosso: import ora da cartella/CSV."

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from . import views as timbri_views
from .models import OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine, TimbriImportIssue

User = get_user_model()


def _make_workspace_tempdir(prefix: str) -> Path:
    root = Path.cwd() / "django_app" / ".tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{prefix}-{uuid4().hex}"
    target.mkdir(parents=True, exist_ok=False)
    return target


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
            cursor.execute("PRAGMA table_info(anagrafica_dipendenti)")
            existing_columns = {str(row[1]).lower() for row in cursor.fetchall()}
            required_columns = {
                "aliasusername": "VARCHAR(200) NULL",
                "nome": "VARCHAR(200) NULL",
                "cognome": "VARCHAR(200) NULL",
                "mansione": "VARCHAR(200) NULL",
                "reparto": "VARCHAR(200) NULL",
                "ruolo": "VARCHAR(200) NULL",
                "matricola": "VARCHAR(100) NULL",
                "attivo": "INTEGER NULL",
                "email": "VARCHAR(200) NULL",
                "email_notifica": "VARCHAR(200) NULL",
                "utente_id": "INTEGER NULL",
            }
            for column_name, column_def in required_columns.items():
                if column_name not in existing_columns:
                    cursor.execute(f"ALTER TABLE anagrafica_dipendenti ADD COLUMN {column_name} {column_def}")
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


def _mark_onboarding_done(user) -> None:
    """Esenta l'utente dal redirect /onboarding/ del middleware ACL.

    Senza questo, gli utenti non-superuser vengono rediretti (302) prima di
    raggiungere le view del modulo (vedi core/middleware onboarding gate).
    """
    from core.models import UserOnboarding

    UserOnboarding.objects.update_or_create(
        user=user,
        defaults={"completed": True, "skipped": False},
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
        _mark_onboarding_done(self.user)
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

    @skip(_GRAPH_REMOVED)
    def test_config_page_can_save_mapping(self):
        self.client.force_login(self.admin)
        tmpdir = _make_workspace_tempdir("timbri-config")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text(
                "GRAPH_TENANT_ID=test\nGRAPH_CLIENT_ID=test\nGRAPH_CLIENT_SECRET=secret\nGRAPH_SITE_ID=site\n",
                encoding="utf-8",
            )
            with patch("config.env_config.default_env_path", return_value=env_path), patch.dict(
                "timbri.views.os.environ",
                {},
                clear=True,
            ):
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
            text = env_path.read_text(encoding="utf-8")
            self.assertIn("GRAPH_LIST_ID_TIMBRI=list-test", text)
            self.assertIn("TIMBRI_FIELD_OPERATORE_LOOKUP=OperatoreLookupId", text)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @skip(_GRAPH_REMOVED)
    def test_config_page_normalizes_guid_like_list_id(self):
        self.client.force_login(self.admin)
        tmpdir = _make_workspace_tempdir("timbri-config-guid")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text(
                "GRAPH_TENANT_ID=test\nGRAPH_CLIENT_ID=test\nGRAPH_CLIENT_SECRET=secret\nGRAPH_SITE_ID=site\n",
                encoding="utf-8",
            )
            with patch("config.env_config.default_env_path", return_value=env_path), patch.dict(
                "timbri.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.post(
                    reverse("timbri:configurazione") + "?tab=config",
                    {
                        "action": "save_sharepoint_config",
                        "list_id": "7B23dddb4c-ea5f-47b7-85c7-e75c5524c653",
                    },
                )
            self.assertEqual(response.status_code, 302)
            text = env_path.read_text(encoding="utf-8")
            self.assertIn("GRAPH_LIST_ID_TIMBRI=23dddb4c-ea5f-47b7-85c7-e75c5524c653", text)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

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
            # La riga "proper" ha utente_id valorizzato: serve la riga reale in
            # 'utenti' per soddisfare la FK (il valore vince il tie-break dedup).
            utenti_insert = (
                "INSERT INTO utenti (id, nome, password, attivo, deve_cambiare_password) "
                "VALUES (271, 'Derya Aksoy', 'x', 1, 0)"
            )
            if vendor == "sqlite":
                cursor.execute(utenti_insert)
            else:
                cursor.execute("SET IDENTITY_INSERT utenti ON")
                cursor.execute(utenti_insert)
                cursor.execute("SET IDENTITY_INSERT utenti OFF")
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

    @skip(_GRAPH_REMOVED)
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

    def test_record_edit_prefills_html5_dates(self):
        self.registro.data_consegna = datetime(2025, 3, 10).date()
        self.registro.data_ritiro = datetime(2025, 3, 12).date()
        self.registro.note = "Nota compilata"
        self.registro.firma_testo = "Firma compilata"
        self.registro.save(update_fields=["data_consegna", "data_ritiro", "note", "firma_testo"])
        self.client.force_login(self.admin)
        response = self.client.get(reverse("timbri:registro_edit", args=[self.registro.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="2025-03-10"', html=False)
        self.assertContains(response, 'value="2025-03-12"', html=False)
        self.assertContains(response, "Nota compilata")
        self.assertContains(response, "Firma compilata")

    def test_index_shows_pending_import_issues(self):
        TimbriImportIssue.objects.create(
            source_file="Registro timbri.csv",
            csv_row_number=42,
            sharepoint_item_id="999",
            operatore_label="Operatore Test",
            matricola="MISS001",
            codice_timbro="CNO MISS001",
            tipo_timbro_raw="Fisico e digitale",
            motivo_scarto="Operatore non trovato nell'anagrafica centrale",
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("timbri:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Da gestire")
        self.assertContains(response, "Operatore Test")
        self.assertContains(response, "MISS001")

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
        _mark_onboarding_done(self.user)
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

    def test_anagrafica_detail_shows_timbri_link(self):
        # Il collegamento ai timbri è stato spostato dalla lista anagrafica
        # alla scheda di dettaglio del dipendente (dipendente_detail.html).
        self.client.force_login(self.user)
        response = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("timbri:operatore_detail_by_legacy", args=[self.legacy_id]))

    def test_anagrafica_detail_has_timbri_embed_tab(self):
        # Il tab Timbri della scheda dipendente carica il frammento in lazy via HTMX.
        self.client.force_login(self.user)
        response = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("timbri:operatore_embed", args=[self.legacy_id]))
        self.assertContains(response, 'data-tab-target="timbri"')

    def test_operatore_embed_renders_records(self):
        self.client.force_login(self.user)
        with patch("timbri.views._can_view_timbri", return_value=True):
            response = self.client.get(reverse("timbri:operatore_embed", args=[self.legacy_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Record attivi")
        self.assertContains(response, "CNO DI001")

    def test_operatore_embed_forbidden_hides_data(self):
        self.client.force_login(self.user)
        with patch("timbri.views._can_view_timbri", return_value=False):
            response = self.client.get(reverse("timbri:operatore_embed", args=[self.legacy_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "permessi")
        self.assertNotContains(response, "CNO DI001")

    def test_operatore_detail_uses_private_anagrafica_photo_route(self):
        from anagrafica.models import DipendenteAnagraficaCivile

        private_root = _make_workspace_tempdir("timbri-anagrafica-photo")
        try:
            with override_settings(ANAGRAFICA_PRIVATE_ROOT=str(private_root)):
                civile = DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=self.legacy_id)
                civile.foto.save("profilo.png", _png_upload("profilo.png"), save=True)

                self.client.force_login(self.user)
                with patch("timbri.views._can_view_timbri", return_value=True):
                    response = self.client.get(reverse("timbri:operatore_detail_by_legacy", args=[self.legacy_id]))
        finally:
            shutil.rmtree(private_root, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("anagrafica:foto_dipendente", args=[self.legacy_id]))
        self.assertNotContains(response, "/media/anagrafica/dipendenti/")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TimbriDownloadAuditTests(TestCase):
    """Verifica che il download di immagini timbri sia tracciato in AuditLog (Patch 21H)."""

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(
            username="timbri-audit-admin",
            email="timbri-audit-admin@test.local",
            password="pass12345",
        )
        self.basic_user = User.objects.create_user(
            username="timbri-audit-basic",
            password="pass12345",
        )
        _mark_onboarding_done(self.basic_user)
        self.operatore = OperatoreTimbri.objects.create(nome="Audit", cognome="Test", matricola="AUD1")
        self.registro = RegistroTimbro.objects.create(operatore=self.operatore, codice_timbro="CNO AUD1")

    def test_serve_timbri_image_authorized_creates_success_audit(self):
        from core.models import AuditLog

        private_root = _make_workspace_tempdir("timbri-audit-private")
        try:
            with override_settings(TIMBRI_PRIVATE_ROOT=str(private_root)):
                image = RegistroTimbroImmagine(
                    registro=self.registro,
                    variante=RegistroTimbroImmagine.VARIANTE_TIMBRO,
                    image=_png_upload("audit.png"),
                )
                image.save()
                self.client.force_login(self.admin)
                # NB: si conta l'azione SPECIFICA, non il totale globale di
                # AuditLog: altri insert (es. policy 2FA) rendono fragile un
                # assert sul count complessivo.
                view_audit_qs = AuditLog.objects.filter(azione="timbri_image_view", modulo="timbri")
                before = view_audit_qs.count()
                response = self.client.get(reverse("timbri:serve_image", args=[image.pk]))
                self.assertEqual(response.status_code, 200)
                created = view_audit_qs.order_by("-id").first()
                self.assertIsNotNone(created)
                self.assertEqual(view_audit_qs.count(), before + 1)
                payload = created.dettaglio or {}
                self.assertEqual(payload.get("image_id"), image.id)
                serialized = repr(payload)
                self.assertNotIn(str(private_root), serialized)
        finally:
            shutil.rmtree(private_root, ignore_errors=True)

    def test_serve_timbri_image_denied_creates_denied_audit_without_path(self):
        from core.models import AuditLog

        private_root = _make_workspace_tempdir("timbri-audit-private-denied")
        try:
            with override_settings(TIMBRI_PRIVATE_ROOT=str(private_root)):
                image = RegistroTimbroImmagine(
                    registro=self.registro,
                    variante=RegistroTimbroImmagine.VARIANTE_TIMBRO,
                    image=_png_upload("denied.png"),
                )
                image.save()
                self.client.force_login(self.basic_user)
                response = self.client.get(reverse("timbri:serve_image", args=[image.pk]))
                self.assertEqual(response.status_code, 403)
                created = AuditLog.objects.filter(
                    azione="timbri_image_denied", modulo="timbri",
                ).order_by("-id").first()
                self.assertIsNotNone(created)
                payload = created.dettaglio or {}
                self.assertEqual(payload.get("motivo"), "permission_denied")
                serialized = repr(payload)
                self.assertNotIn(str(private_root), serialized)
                # Su denied non viene esposto neanche il nome file fisico
                self.assertNotIn("denied.png", serialized)
        finally:
            shutil.rmtree(private_root, ignore_errors=True)


@skip(_GRAPH_REMOVED)
class TimbriDownloadImageHostAllowlistTests(TestCase):
    """SEC-PREPROD-02 (M2): il token Graph non deve raggiungere host arbitrari."""

    @staticmethod
    def _png_bytes() -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (4, 4), (255, 255, 255)).save(buffer, format="PNG")
        return buffer.getvalue()

    def _ok_response(self):
        return SimpleNamespace(
            status_code=200,
            content=self._png_bytes(),
            raise_for_status=lambda: None,
        )

    def test_trusted_graph_host_receives_authorization(self):
        with patch("timbri.views._graph_token", return_value="tok-abc"), patch(
            "timbri.views.requests.get", return_value=self._ok_response()
        ) as mock_get:
            timbri_views._download_image("https://graph.microsoft.com/v1.0/sites/x/img")
        self.assertEqual(mock_get.call_count, 1)
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["headers"].get("Authorization"), "Bearer tok-abc")

    def test_trusted_sharepoint_host_receives_authorization(self):
        with patch("timbri.views._graph_token", return_value="tok-abc"), patch(
            "timbri.views.requests.get", return_value=self._ok_response()
        ) as mock_get:
            timbri_views._download_image("https://contoso.sharepoint.com/sites/x/img.png")
        self.assertEqual(mock_get.call_count, 1)
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["headers"].get("Authorization"), "Bearer tok-abc")

    def test_untrusted_host_is_not_downloaded(self):
        with patch("timbri.views._graph_token", return_value="tok-abc"), patch(
            "timbri.views.requests.get"
        ) as mock_get:
            with self.assertRaises(RuntimeError):
                timbri_views._download_image("https://attacker.local/img.png")
        mock_get.assert_not_called()

    def test_sharepoint_in_query_only_is_rejected(self):
        with patch("timbri.views._graph_token", return_value="tok-abc"), patch(
            "timbri.views.requests.get"
        ) as mock_get:
            with self.assertRaises(RuntimeError):
                timbri_views._download_image("https://attacker.local/?ref=sharepoint.com")
        mock_get.assert_not_called()

    def test_missing_scheme_or_host_is_rejected(self):
        for bad_url in ("", "graph.microsoft.com/v1.0/x", "ftp://graph.microsoft.com/x", "/relative/img.png"):
            with patch("timbri.views.requests.get") as mock_get:
                with self.assertRaises(RuntimeError):
                    timbri_views._download_image(bad_url)
            mock_get.assert_not_called()
