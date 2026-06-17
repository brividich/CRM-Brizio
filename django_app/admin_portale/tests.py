from __future__ import annotations

import json
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import ANY, MagicMock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ai_assistant.models import AiKnowledgeEntry
from ai_assistant.tools import RuntimeContext
from admin_portale.forms import PulsanteForm, UtenteCreateForm
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import AnagraficaDipendente, Permesso, Pulsante, Ruolo, UtenteLegacy
from core.legacy_utils import legacy_table_columns
from core.models import (
    AnagraficaRisposta,
    AnagraficaVoce,
    ChecklistEsecuzione,
    EmployeeBoardConfig,
    LegacyRedirect,
    NavigationItem,
    NavigationRoleAccess,
    Notifica,
    OptioneConfig,
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    SiteConfig,
    UserDashboardConfig,
    UserDashboardLayout,
    UserExtraInfo,
    UserModuleVisibility,
    UserOnboarding,
    UserPermissionGrant,
    UserPermissionOverride,
)
from core.pdf import PdfTheme

User = get_user_model()


class AdminPortaleModuleCatalogTests(SimpleTestCase):
    def test_anagrafica_hr_and_fornitori_are_separate_permission_modules(self):
        from admin_portale.views import MODULE_CATALOG

        anagrafica = MODULE_CATALOG["anagrafica"]
        fornitori = MODULE_CATALOG["fornitori"]

        self.assertEqual(anagrafica["label"], "Anagrafica HR")
        self.assertEqual(fornitori["label"], "Anagrafica Fornitori")
        self.assertNotIn(
            "view_anagrafica_fornitori",
            {button["codice"] for button in anagrafica["buttons"]},
        )
        self.assertIn("fornitori_list", {button["codice"] for button in fornitori["buttons"]})


def _make_workspace_tempdir(prefix: str) -> Path:
    root = Path.cwd() / ".tmp_tests"
    root.mkdir(exist_ok=True)
    target = root / f"{prefix}{uuid4().hex}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def _legacy_table_has_identity(table_name: str) -> bool:
    if connection.vendor == "sqlite":
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM sys.identity_columns
            WHERE object_id = OBJECT_ID(%s)
            """,
            [table_name],
        )
        row = cursor.fetchone()
    return bool(row and int(row[0] or 0))


def _legacy_upsert_by_id(table_name: str, record_id: int, values: dict[str, object]) -> None:
    assignments = ", ".join(f"{column} = %s" for column in values)
    insert_columns = ["id", *values.keys()]
    insert_placeholders = ", ".join(["%s"] * len(insert_columns))
    update_params = [*values.values(), record_id]
    insert_params = [record_id, *values.values()]

    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table_name} SET {assignments} WHERE id = %s", update_params)
        if cursor.rowcount and cursor.rowcount > 0:
            return

        if _legacy_table_has_identity(table_name):
            cursor.execute(f"SET IDENTITY_INSERT {table_name} ON")
            try:
                cursor.execute(
                    f"INSERT INTO {table_name} ({', '.join(insert_columns)}) VALUES ({insert_placeholders})",
                    insert_params,
                )
            finally:
                cursor.execute(f"SET IDENTITY_INSERT {table_name} OFF")
            return

        cursor.execute(
            f"INSERT INTO {table_name} ({', '.join(insert_columns)}) VALUES ({insert_placeholders})",
            insert_params,
        )


def _ensure_utenti_table() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS utenti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome VARCHAR(200) NOT NULL,
                    email VARCHAR(200) NULL,
                    password VARCHAR(500) NOT NULL,
                    ruolo VARCHAR(100) NULL,
                    attivo INTEGER NOT NULL DEFAULT 1,
                    deve_cambiare_password INTEGER NOT NULL DEFAULT 0,
                    ruolo_id INTEGER NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('utenti', 'U') IS NULL
                CREATE TABLE utenti (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    nome NVARCHAR(200) NOT NULL,
                    email NVARCHAR(200) NULL,
                    password NVARCHAR(500) NOT NULL,
                    ruolo NVARCHAR(100) NULL,
                    attivo BIT NOT NULL DEFAULT 1,
                    deve_cambiare_password BIT NOT NULL DEFAULT 0,
                    ruolo_id INT NULL
                )
                """
                )


def _ensure_ruoli_table() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ruoli (
                    id INTEGER PRIMARY KEY,
                    nome VARCHAR(100) NOT NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('ruoli', 'U') IS NULL
                CREATE TABLE ruoli (
                    id INT NOT NULL PRIMARY KEY,
                    nome NVARCHAR(100) NOT NULL
                )
                """
            )


def _ensure_anagrafica_table() -> None:
    # legacy_table_columns è lru_cache per-processo: se un test precedente ha
    # popolato la cache quando la tabella aveva uno schema diverso (o non
    # esisteva), il cache stale provoca INSERT con colonne inesistenti.
    # Invalidiamo dopo aver garantito lo schema corrente.
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
    legacy_table_columns.cache_clear()


def _ensure_pulsanti_table() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pulsanti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codice VARCHAR(100) NOT NULL,
                    nome_visibile VARCHAR(200) NULL,
                    icona VARCHAR(20) NULL,
                    modulo VARCHAR(100) NOT NULL,
                    url VARCHAR(500) NOT NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('pulsanti', 'U') IS NULL
                CREATE TABLE pulsanti (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    codice NVARCHAR(100) NOT NULL,
                    nome_visibile NVARCHAR(200) NULL,
                    icona NVARCHAR(20) NULL,
                    modulo NVARCHAR(100) NOT NULL,
                    url NVARCHAR(500) NOT NULL
                )
                """
            )


def _ensure_permessi_table() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS permessi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    modulo VARCHAR(100) NOT NULL,
                    azione VARCHAR(100) NOT NULL,
                    ruolo_id INTEGER NOT NULL,
                    consentito INTEGER NULL,
                    can_view INTEGER NULL,
                    can_edit INTEGER NULL,
                    can_delete INTEGER NULL,
                    can_approve INTEGER NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('permessi', 'U') IS NULL
                CREATE TABLE permessi (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    modulo NVARCHAR(100) NOT NULL,
                    azione NVARCHAR(100) NOT NULL,
                    ruolo_id INT NOT NULL,
                    consentito INT NULL,
                    can_view INT NULL,
                    can_edit INT NULL,
                    can_delete INT NULL,
                    can_approve INT NULL
                )
                """
            )


def _clear_acl_navigation_seed_tables() -> None:
    with connection.cursor() as cursor:
        for table_name in ("permessi", "pulsanti", "ruoli", "utenti"):
            try:
                cursor.execute(f"DELETE FROM {table_name}")
            except Exception:
                continue


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortalePdfTemplateConfigTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-pdf-template",
            email="admin.pdf.template@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin PDF Template",
            email="admin.pdf.template@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )

    def _as_admin_get(self, url, params=None):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            return self.client.get(url, params or {})

    def _as_admin_post(self, url, data):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            return self.client.post(url, data, follow=True)

    def test_pdf_template_config_page_renders(self):
        response = self._as_admin_get(reverse("admin_portale:pdf_template_config"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Template PDF", html=False)
        self.assertContains(response, reverse("admin_portale:pdf_template_preview"), html=False)
        self.assertContains(response, 'name="pdf_template_primary_color"', html=False)
        self.assertContains(response, 'name="pdf_template_footer_text"', html=False)

    def test_pdf_template_preview_returns_pdf(self):
        response = self._as_admin_get(reverse("admin_portale:pdf_template_preview"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_template_config_save_updates_site_config_and_theme(self):
        response = self._as_admin_post(
            reverse("admin_portale:api_pdf_template_config_save"),
            {
                "pdf_template_logo_url": "",
                "pdf_template_primary_color": "#123456",
                "pdf_template_accent_color": "#abcdef",
                "pdf_template_footer_text": "Documentazione Novicrom",
                "pdf_template_show_generated_at": "0",
                "pdf_template_show_page_number": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SiteConfig.get("pdf_template_primary_color"), "#123456")
        self.assertEqual(SiteConfig.get("pdf_template_accent_color"), "#abcdef")
        self.assertEqual(SiteConfig.get("pdf_template_footer_text"), "Documentazione Novicrom")
        self.assertEqual(SiteConfig.get("pdf_template_show_generated_at"), "0")

        theme = PdfTheme.from_branding()
        self.assertEqual(theme.primary, "#123456")
        self.assertEqual(theme.accent, "#abcdef")
        self.assertEqual(theme.footer_text, "Documentazione Novicrom")
        self.assertFalse(theme.show_generated_at)
        self.assertTrue(theme.show_page_number)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleUserDeleteTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-delete",
            email="admin@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Portale",
            email="admin@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_legacy = UtenteLegacy.objects.create(
            nome="Andrea Badalassi",
            email="a.badalassi@example.local",
            password="*AD_MANAGED*",
            ruolo="utente",
            ruolo_id=6,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_django = User.objects.create_user(
            username="target-delete",
            email="a.badalassi@example.local",
            password="pass12345",
        )
        Profile.objects.create(
            user=self.target_django,
            legacy_user_id=self.target_legacy.id,
            legacy_ruolo_id=self.target_legacy.ruolo_id,
            legacy_ruolo=self.target_legacy.ruolo,
        )
        UserPermissionOverride.objects.create(
            legacy_user_id=self.target_legacy.id,
            modulo="timbri",
            azione="timbri_edit",
            can_view=True,
            can_edit=True,
        )
        UserDashboardConfig.objects.create(
            legacy_user_id=self.target_legacy.id,
            pulsante_id=10,
            visible=False,
        )
        UserModuleVisibility.objects.create(
            legacy_user_id=self.target_legacy.id,
            modulo="timbri",
            visible=False,
        )
        UserDashboardLayout.objects.create(
            legacy_user_id=self.target_legacy.id,
            layout={"cards": ["tasks"]},
        )
        EmployeeBoardConfig.objects.create(
            legacy_user_id=self.target_legacy.id,
            layout=["profilo"],
        )
        UserExtraInfo.objects.create(
            legacy_user_id=self.target_legacy.id,
            reparto="CN5",
        )
        voce = AnagraficaVoce.objects.create(label="Telefono")
        AnagraficaRisposta.objects.create(
            legacy_user_id=self.target_legacy.id,
            voce=voce,
            valore="12345",
        )
        ChecklistEsecuzione.objects.create(
            legacy_user_id=self.target_legacy.id,
            utente_nome="Andrea Badalassi",
            tipo_checklist="checkin",
        )
        Notifica.objects.create(
            legacy_user_id=self.target_legacy.id,
            tipo="generico",
            messaggio="Test notifica",
        )
        self.anagrafica_row = AnagraficaDipendente.objects.create(
            aliasusername="a.badalassi",
            nome="Andrea",
            cognome="Badalassi",
            email="a.badalassi@example.local",
            utente=self.target_legacy,
        )

    def test_delete_user_removes_local_dependencies_and_unlinks_anagrafica(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:utente_delete", args=[self.target_legacy.id]),
                {"next": reverse("admin_portale:utenti_list")},
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(UtenteLegacy.objects.filter(id=self.target_legacy.id).exists())
        self.assertFalse(Profile.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertFalse(User.objects.filter(id=self.target_django.id).exists())
        self.assertFalse(UserPermissionOverride.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertFalse(UserDashboardConfig.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertFalse(UserModuleVisibility.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertFalse(UserDashboardLayout.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertFalse(EmployeeBoardConfig.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertFalse(UserExtraInfo.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertFalse(AnagraficaRisposta.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertFalse(ChecklistEsecuzione.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertFalse(Notifica.objects.filter(legacy_user_id=self.target_legacy.id).exists())

        self.anagrafica_row.refresh_from_db()
        self.assertIsNone(self.anagrafica_row.utente_id)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleUserAnagraficaSyncTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-sync",
            email="admin.sync@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Portale",
            email="admin.sync@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_legacy = UtenteLegacy.objects.create(
            nome="Andrea Badalassi",
            email="a.badalassi@example.local",
            password="*AD_MANAGED*",
            ruolo="utente",
            ruolo_id=6,
            attivo=True,
            deve_cambiare_password=False,
        )

    def test_toggle_active_moves_user_into_central_anagrafica(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:utente_toggle_active", args=[self.target_legacy.id]),
                {"next": reverse("admin_portale:utenti_list")},
            )

        self.assertEqual(response.status_code, 302)
        self.target_legacy.refresh_from_db()
        self.assertFalse(self.target_legacy.attivo)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT nome, cognome, attivo, utente_id
                FROM anagrafica_dipendenti
                WHERE LOWER(email) = LOWER(%s)
                """,
                [self.target_legacy.email],
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Andrea")
        self.assertEqual(row[1], "Badalassi")
        self.assertEqual(int(row[2] or 0), 0)
        self.assertIsNone(row[3])

    def test_utente_edit_renders_json_script_blocks(self):
        """La pagina utente_edit serializza i payload JSON via json_script."""
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(
                reverse("admin_portale:utente_edit", args=[self.target_legacy.id])
            )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('id="anagrafica-risposte-data"', html)
        self.assertIn('id="overrides-map-data"', html)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleCaporepartoRoleSyncTests(TestCase):
    def setUp(self):
        _ensure_ruoli_table()
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")
            cursor.execute("DELETE FROM ruoli")
        _legacy_upsert_by_id("ruoli", 1, {"nome": "admin"})
        _legacy_upsert_by_id("ruoli", 2, {"nome": "caporeparto"})
        _legacy_upsert_by_id("ruoli", 6, {"nome": "utente"})

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-caporeparto",
            email="admin.caporeparto@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Portale",
            email="admin.caporeparto@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_legacy = UtenteLegacy.objects.create(
            nome="Francesco Ballerini",
            email="f.ballerini@example.com",
            password="*AD_MANAGED*",
            ruolo="utente",
            ruolo_id=6,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_django = User.objects.create_user(
            username="target-caporeparto",
            email="f.ballerini@example.com",
            password="pass12345",
        )
        Profile.objects.create(
            user=self.target_django,
            legacy_user_id=self.target_legacy.id,
            legacy_ruolo_id=self.target_legacy.ruolo_id,
            legacy_ruolo=self.target_legacy.ruolo,
        )

    def test_create_caporeparto_option_promotes_legacy_user_role(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:api_opzione_create"),
                data='{"tipo":"caporeparto","valore":"f.ballerini@example.com","ordine":100}',
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        option = OptioneConfig.objects.get(tipo="caporeparto")
        self.assertEqual(option.valore, "f.ballerini@example.com")
        self.assertEqual(option.legacy_user_id, self.target_legacy.id)

        self.target_legacy.refresh_from_db()
        self.assertEqual(self.target_legacy.ruolo_id, 2)
        self.assertEqual(self.target_legacy.ruolo, "caporeparto")

        profile = Profile.objects.get(legacy_user_id=self.target_legacy.id)
        self.assertEqual(profile.legacy_ruolo_id, 2)
        self.assertEqual(profile.legacy_ruolo, "caporeparto")


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
    DEFAULT_FROM_EMAIL="noreply@test.local",
)
class AdminPortaleConfigSrvSmtpTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-smtp",
            email="admin.smtp@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin SMTP",
            email="admin.smtp@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.url = reverse("admin_portale:ldap_diagnostica")

    def test_config_srv_can_send_test_email(self):
        self.client.force_login(self.admin_user)
        connection_mock = MagicMock()
        message_mock = MagicMock()
        message_mock.send.return_value = 1

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views.get_connection", return_value=connection_mock) as connection_factory, patch(
            "admin_portale.views.EmailMultiAlternatives",
            return_value=message_mock,
        ) as email_factory:
            response = self.client.post(
                self.url,
                {
                    "action": "test_smtp_send",
                    "smtp_host": "smtp.test.local",
                    "smtp_port": "587",
                    "smtp_user": "mailer",
                    "smtp_password": "secret",
                    "smtp_default_from_email": "noreply@test.local",
                    "smtp_test_to": "dest@test.local",
                    "smtp_timeout": "10",
                    "smtp_use_tls": "on",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mail di test inviata con successo")
        connection_factory.assert_called_once_with(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host="smtp.test.local",
            port=587,
            username="mailer",
            password="secret",
            use_tls=True,
            use_ssl=False,
            timeout=10,
            fail_silently=False,
        )
        email_factory.assert_called_once_with(
            subject="Test SMTP Portale Applicativo",
            body=ANY,
            from_email="noreply@test.local",
            to=["dest@test.local"],
            connection=connection_mock,
        )
        message_mock.send.assert_called_once_with(fail_silently=False)
        connection_mock.close.assert_called_once()

    def test_config_srv_rejects_invalid_test_recipient(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views.get_connection") as connection_factory, patch(
            "admin_portale.views.EmailMultiAlternatives",
        ) as email_factory:
            response = self.client.post(
                self.url,
                {
                    "action": "test_smtp_send",
                    "smtp_host": "smtp.test.local",
                    "smtp_port": "587",
                    "smtp_user": "mailer",
                    "smtp_password": "secret",
                    "smtp_default_from_email": "noreply@test.local",
                    "smtp_test_to": "destinazione-non-valida",
                    "smtp_timeout": "10",
                    "smtp_use_tls": "on",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Indirizzo email non valido")
        connection_factory.assert_not_called()
        email_factory.assert_not_called()

    def test_config_srv_can_run_approval_imap_poll(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views.run_approval_imap_poll_now") as poll_runner:
            poll_runner.return_value = {
                "ok": True,
                "message": "Polling mailbox completato: 1 processate, 1 approvate, 0 rifiutate, 0 ignorate, 0 errori.",
                "output": "[run] Completato - processed=1 approved=1 rejected=0 skipped=0 error=0",
                "stats": {"processed": 1, "approved": 1, "rejected": 0, "skipped": 0, "error": 0},
            }
            response = self.client.post(
                self.url,
                {
                    "action": "run_approval_imap_poll",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Polling IMAP approvazioni")
        self.assertContains(response, "Polling mailbox completato")
        poll_runner.assert_called_once_with()

    def test_config_srv_can_save_approval_imap_config(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views.save_approval_imap_settings") as save_imap:
            save_imap.return_value = (
                True,
                "Configurazione IMAP salvata in .env e aggiornata nel runtime corrente.",
            )
            response = self.client.post(
                self.url,
                {
                    "action": "save_approval_imap_config",
                    "approval_imap_host": "imap.changed.local",
                    "approval_imap_port": "995",
                    "approval_imap_user": "approvazioni-changed@test.local",
                    "approval_imap_password": "nuova-password",
                    "approval_imap_folder": "Archivio",
                    "approval_imap_use_ssl": "on",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configurazione IMAP salvata")
        save_imap.assert_called_once_with(
            host="imap.changed.local",
            port=995,
            user="approvazioni-changed@test.local",
            password="nuova-password",
            use_ssl=True,
            folder="Archivio",
            dotenv_path=ANY,
        )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleConfigSrvLdapTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-ldap",
            email="admin.ldap@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin LDAP",
            email="admin.ldap@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.url = reverse("admin_portale:ldap_diagnostica")

    def test_config_srv_can_save_ldap_config(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ldap-config-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text("LDAP_SERVER=ldap://old.local\nLDAP_ENABLED=0\n", encoding="utf-8")

            with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch("admin_portale.views._dotenv_path", return_value=env_path), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.post(
                    self.url,
                    {
                        "action": "save_ldap_config",
                        "enabled": "on",
                        "server": "ldap://dc1.example.local",
                        "domain": "EXAMPLE",
                        "upn_suffix": "@example.local",
                        "timeout": "8",
                        "base_dn": "DC=EXAMPLE,DC=LOCAL",
                        "user_filter": "(&(objectCategory=person)(objectClass=user))",
                        "group_allowlist": "EMPLOYEES,ADMINS",
                        "sync_page_size": "750",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Configurazione LDAP salvata")

            content = env_path.read_text(encoding="utf-8")
            self.assertIn("LDAP_ENABLED=1", content)
            self.assertIn("LDAP_SERVER=ldap://dc1.example.local", content)
            self.assertIn("LDAP_DOMAIN=EXAMPLE", content)
            self.assertIn("LDAP_UPN_SUFFIX=@example.local", content)
            self.assertIn("LDAP_TIMEOUT=8", content)
            self.assertIn("LDAP_BASE_DN=DC=EXAMPLE,DC=LOCAL", content)
            self.assertIn("LDAP_USER_FILTER=(&(objectCategory=person)(objectClass=user))", content)
            self.assertIn("LDAP_GROUP_ALLOWLIST=EMPLOYEES,ADMINS", content)
            self.assertIn("LDAP_SYNC_PAGE_SIZE=750", content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_config_srv_shows_ollama_card(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Assistente AI / Ollama")
        self.assertContains(response, "name=\"ollama_base_url\"")
        self.assertContains(response, "name=\"ollama_rag_source_paths\"")
        self.assertContains(response, "Knowledge base RAG abilitata")
        self.assertContains(response, "FAQ AI")
        self.assertContains(response, reverse("admin_portale:ai_settings"))
        self.assertContains(response, reverse("admin_portale:ai_knowledge"))
        self.assertNotContains(response, "/admin/ai_assistant/aiknowledgeentry/")
        self.assertContains(response, "Test Ollama")
        self.assertContains(response, "Salva config AI")

    def test_ai_settings_page_renders_all_ai_components(self):
        self.client.force_login(self.admin_user)
        AiKnowledgeEntry.objects.create(
            question="Come risponde l'assistente?",
            answer="Usa FAQ curate e documenti indicizzati.",
            source_label="FAQ Test",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(reverse("admin_portale:ai_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestione AI")
        self.assertContains(response, "Provider e Runtime")
        self.assertContains(response, "Stato Componenti")
        self.assertContains(response, "Knowledge base RAG")
        self.assertContains(response, "FAQ Curate")
        self.assertContains(response, "Come risponde l&#x27;assistente?")
        self.assertContains(response, reverse("ai_assistant:chat"))
        self.assertContains(response, reverse("admin_portale:ldap_diagnostica"))

    def test_ai_settings_page_renders_live_tools_console(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(reverse("admin_portale:ai_settings"), {"tab": "tools"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tool live")
        self.assertContains(response, "Router cross-dominio")
        self.assertContains(response, "Anagrafica HR")
        self.assertContains(response, "anagrafica_summary")
        self.assertContains(response, "tickets_summary")
        self.assertContains(response, "Timbri / Presenze")
        self.assertContains(response, "disabilitato")
        self.assertContains(response, "Esegui test metadata-only")

    def test_ai_settings_can_run_live_tool_test_without_sensitive_output(self):
        from core.models import AuditLog

        self.client.force_login(self.admin_user)
        secret = "SEGRETO_DESCRIZIONE_NON_DEVE_APPARIRE"
        mocked_context = RuntimeContext(
            text=f"Ticket TCK-001 {secret}",
            sources=("tool:tickets:riepilogo",),
            audit={
                "tools": [
                    {
                        "tool": "tickets_summary",
                        "allowed": True,
                        "scope": "personale",
                        "row_count": 1,
                    }
                ],
                "tool_count": 1,
                "context_chars": 44,
                "context_lines": 1,
                "truncated": False,
            },
        )

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views.build_runtime_context", return_value=mocked_context):
            response = self.client.post(
                reverse("admin_portale:ai_settings"),
                {
                    "action": "test_ai_runtime_tool",
                    "tab": "tools",
                    "runtime_tool_key": "tickets_summary",
                    "runtime_test_prompt": "quali ticket aperti ho?",
                    "runtime_simulated_user": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test tool live completato")
        self.assertContains(response, "tool:tickets:riepilogo")
        self.assertContains(response, "tickets_summary")
        self.assertNotContains(response, secret)
        audit = AuditLog.objects.get(azione="ai_runtime_tool_test")
        audit_payload = json.dumps(audit.dettaglio)
        self.assertIn("tickets_summary", audit_payload)
        self.assertNotIn(secret, audit_payload)
        self.assertNotIn("quali ticket aperti ho?", audit_payload)

    def test_ai_settings_clear_runtime_cache_button_clears_cache_and_audits(self):
        from core.models import AuditLog

        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views.clear_knowledge_cache") as mocked_clear:
            response = self.client.post(
                reverse("admin_portale:ai_settings"),
                {"action": "clear_ai_runtime_cache", "tab": "tools"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('admin_portale:ai_settings')}?tab=tools")
        mocked_clear.assert_called_once()
        audit = AuditLog.objects.get(azione="ai_runtime_cache_clear")
        self.assertEqual(audit.dettaglio["cache"], "rag_runtime")
        self.assertNotIn("prompt", audit.dettaglio)

    def test_ai_settings_filters_live_tool_audit_and_keeps_metadata_only(self):
        from core.models import AuditLog

        self.client.force_login(self.admin_user)
        tickets = AuditLog.objects.create(
            utente_display="Audit Tickets User",
            azione="ai_chat",
            modulo="ai_assistant",
            dettaglio={
                "runtime_tools": ["tickets_summary"],
                "runtime_tools_allowed": [True],
                "runtime_context_chars": 321,
                "runtime_sources_count": 1,
                "prompt_chars": 24,
                "elapsed_ms": 120,
                "prompt": "SEGRETO_PROMPT_NON_VISIBILE",
            },
        )
        AuditLog.objects.create(
            utente_display="Audit Tasks User",
            azione="ai_chat_error",
            modulo="ai_assistant",
            dettaglio={
                "runtime_tools": ["tasks_summary"],
                "runtime_tools_allowed": [True],
                "runtime_context_chars": 99,
                "elapsed_ms": 900,
            },
        )
        AuditLog.objects.filter(pk=tickets.pk).update(created_at=timezone.now())

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(
                reverse("admin_portale:ai_settings"),
                {
                    "tab": "tools",
                    "runtime_tool": "tickets_summary",
                    "runtime_outcome": "allowed",
                    "runtime_days": "30",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Audit Tickets User")
        self.assertContains(response, "tickets_summary")
        self.assertContains(response, "321 char")
        self.assertNotContains(response, "Audit Tasks User")
        self.assertNotContains(response, "SEGRETO_PROMPT_NON_VISIBILE")

    def test_ai_settings_page_can_create_entry(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:ai_settings"),
                {
                    "action": "save_knowledge",
                    "question": "Dove gestisco l'AI?",
                    "answer": "Usa la pagina Gestione AI in Admin Portale.",
                    "source_label": "FAQ Portale",
                    "is_active": "on",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("admin_portale:ai_settings"))
        entry = AiKnowledgeEntry.objects.get(question="Dove gestisco l'AI?")
        self.assertTrue(entry.is_active)
        self.assertEqual(entry.created_by, self.admin_user)

    def test_ai_knowledge_page_renders_in_admin_portale(self):
        self.client.force_login(self.admin_user)
        AiKnowledgeEntry.objects.create(
            question="Dove configuro Ollama?",
            answer="In Admin Portale Config SRV.",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(reverse("admin_portale:ai_knowledge"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FAQ AI")
        self.assertContains(response, "Dove configuro Ollama?")
        self.assertContains(response, "Config SRV")

    def test_ai_knowledge_page_can_create_entry(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:ai_knowledge"),
                {
                    "action": "save",
                    "question": "Come salvo conoscenza AI?",
                    "answer": "Usa la pagina FAQ AI in Admin Portale.",
                    "source_label": "FAQ Portale",
                    "is_active": "on",
                },
            )

        self.assertEqual(response.status_code, 302)
        entry = AiKnowledgeEntry.objects.get(question="Come salvo conoscenza AI?")
        self.assertTrue(entry.is_active)
        self.assertEqual(entry.created_by, self.admin_user)

    def test_ai_knowledge_page_rejects_empty_entry(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:ai_knowledge"),
                {
                    "action": "save",
                    "question": "",
                    "answer": "",
                    "source_label": "FAQ Portale",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Domanda e risposta sono obbligatorie")
        self.assertFalse(AiKnowledgeEntry.objects.exists())

    def test_config_srv_can_save_ollama_config(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ollama-config-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text("OLLAMA_CHAT_ENABLED=0\nOLLAMA_BASE_URL=http://old.local:11434\n", encoding="utf-8")

            with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch("admin_portale.views._dotenv_path", return_value=env_path), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.post(
                    self.url,
                    {
                        "action": "save_ollama_config",
                        "ollama_enabled": "on",
                        "ollama_provider": "ollama",
                        "ollama_base_url": "http://ollama.test.local:11434/",
                        "ollama_model": "llama3.1",
                        "ollama_timeout": "45",
                        "ollama_temperature": "0.3",
                        "ollama_max_prompt_chars": "5000",
                        "ollama_max_history_messages": "12",
                        "ollama_rag_enabled": "on",
                        "ollama_rag_source_paths": "README.md,docs/ai,docs/help",
                        "ollama_rag_max_chunks": "5",
                        "ollama_rag_max_context_chars": "7000",
                        "ollama_rag_cache_seconds": "120",
                        "ollama_rag_max_db_entries": "250",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Configurazione Assistente AI salvata")
            content = env_path.read_text(encoding="utf-8")
            self.assertIn("OLLAMA_CHAT_ENABLED=1", content)
            self.assertIn("OLLAMA_API_PROVIDER=ollama", content)
            self.assertIn("OLLAMA_BASE_URL=http://ollama.test.local:11434", content)
            self.assertIn("OLLAMA_CHAT_MODEL=llama3.1", content)
            self.assertIn("OLLAMA_REQUEST_TIMEOUT_SECONDS=45", content)
            self.assertIn("OLLAMA_CHAT_TEMPERATURE=0.3", content)
            self.assertIn("OLLAMA_CHAT_MAX_PROMPT_CHARS=5000", content)
            self.assertIn("OLLAMA_CHAT_MAX_HISTORY_MESSAGES=12", content)
            self.assertIn("OLLAMA_RAG_ENABLED=1", content)
            self.assertIn("OLLAMA_RAG_SOURCE_PATHS=README.md,docs/ai,docs/help", content)
            self.assertIn("OLLAMA_RAG_MAX_CHUNKS=5", content)
            self.assertIn("OLLAMA_RAG_MAX_CONTEXT_CHARS=7000", content)
            self.assertIn("OLLAMA_RAG_CACHE_SECONDS=120", content)
            self.assertIn("OLLAMA_RAG_MAX_DB_ENTRIES=250", content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ai_settings_page_can_save_openwebui_config(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ai-settings-openwebui-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text(
                "OLLAMA_CHAT_ENABLED=0\nOLLAMA_API_PROVIDER=ollama\nOLLAMA_BASE_URL=http://old.local:11434\n",
                encoding="utf-8",
            )

            with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch("admin_portale.views._dotenv_path", return_value=env_path), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.post(
                    reverse("admin_portale:ai_settings"),
                    {
                        "action": "save_ollama_config",
                        "ollama_enabled": "on",
                        "ollama_provider": "openwebui",
                        "ollama_base_url": "http://openwebui.test.local:3000",
                        "ollama_model": "llama3.1",
                        "openwebui_api_key": "sk-test",
                        "ollama_timeout": "45",
                        "ollama_temperature": "0.3",
                        "ollama_max_prompt_chars": "5000",
                        "ollama_max_history_messages": "12",
                        "ollama_rag_enabled": "on",
                        "ollama_rag_source_paths": "README.md,docs/ai",
                        "ollama_rag_max_chunks": "4",
                        "ollama_rag_max_context_chars": "5000",
                        "ollama_rag_cache_seconds": "300",
                        "ollama_rag_max_db_entries": "200",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Configurazione Assistente AI salvata")
            content = env_path.read_text(encoding="utf-8")
            self.assertIn("OLLAMA_CHAT_ENABLED=1", content)
            self.assertIn("OLLAMA_API_PROVIDER=openwebui", content)
            self.assertIn("OLLAMA_BASE_URL=http://openwebui.test.local:3000", content)
            self.assertIn("OLLAMA_CHAT_MODEL=llama3.1", content)
            self.assertIn("OPENWEBUI_API_KEY=sk-test", content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_config_srv_rejects_invalid_ollama_config_without_overwrite(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ollama-invalid-")
        try:
            env_path = tmpdir / ".env"
            original = "OLLAMA_CHAT_ENABLED=1\nOLLAMA_BASE_URL=http://valid.local:11434\nOLLAMA_CHAT_MODEL=llama3.1\n"
            env_path.write_text(original, encoding="utf-8")

            with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch("admin_portale.views._dotenv_path", return_value=env_path), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.post(
                    self.url,
                    {
                        "action": "save_ollama_config",
                        "ollama_enabled": "on",
                        "ollama_provider": "ollama",
                        "ollama_base_url": "ftp://ollama.test.local",
                        "ollama_model": "llama3.1",
                        "ollama_timeout": "45",
                        "ollama_temperature": "0.3",
                        "ollama_max_prompt_chars": "5000",
                        "ollama_max_history_messages": "12",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "URL Ollama non valido")
            self.assertEqual(env_path.read_text(encoding="utf-8"), original)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_config_srv_rejects_invalid_ollama_numeric_values_without_overwrite(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ollama-invalid-numeric-")
        try:
            env_path = tmpdir / ".env"
            original = "OLLAMA_CHAT_ENABLED=1\nOLLAMA_BASE_URL=http://valid.local:11434\nOLLAMA_CHAT_MODEL=llama3.1\n"
            env_path.write_text(original, encoding="utf-8")

            with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch("admin_portale.views._dotenv_path", return_value=env_path), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.post(
                    self.url,
                    {
                        "action": "save_ollama_config",
                        "ollama_enabled": "on",
                        "ollama_provider": "ollama",
                        "ollama_base_url": "http://ollama.test.local:11434",
                        "ollama_model": "llama3.1",
                        "ollama_timeout": "abc",
                        "ollama_temperature": "0.3",
                        "ollama_max_prompt_chars": "5000",
                        "ollama_max_history_messages": "12",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Timeout Ollama non valido")
            self.assertEqual(env_path.read_text(encoding="utf-8"), original)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_config_srv_rejects_sensitive_ollama_rag_paths_without_overwrite(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ollama-invalid-rag-")
        try:
            env_path = tmpdir / ".env"
            original = (
                "OLLAMA_CHAT_ENABLED=1\n"
                "OLLAMA_BASE_URL=http://valid.local:11434\n"
                "OLLAMA_CHAT_MODEL=llama3.1\n"
                "OLLAMA_RAG_SOURCE_PATHS=README.md,docs/ai\n"
            )
            env_path.write_text(original, encoding="utf-8")

            with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch("admin_portale.views._dotenv_path", return_value=env_path), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.post(
                    self.url,
                    {
                        "action": "save_ollama_config",
                        "ollama_enabled": "on",
                        "ollama_provider": "ollama",
                        "ollama_base_url": "http://ollama.test.local:11434",
                        "ollama_model": "llama3.1",
                        "ollama_timeout": "45",
                        "ollama_temperature": "0.3",
                        "ollama_max_prompt_chars": "5000",
                        "ollama_max_history_messages": "12",
                        "ollama_rag_enabled": "on",
                        "ollama_rag_source_paths": ".env,README.md",
                        "ollama_rag_max_chunks": "4",
                        "ollama_rag_max_context_chars": "5000",
                        "ollama_rag_cache_seconds": "300",
                        "ollama_rag_max_db_entries": "200",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Percorsi knowledge base non validi")
            self.assertEqual(env_path.read_text(encoding="utf-8"), original)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_config_srv_can_test_ollama_connection(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views._ollama_json_get") as json_get:
            json_get.side_effect = [
                {"version": "0.5.7"},
                {"models": [{"name": "llama3.1:latest"}]},
            ]
            response = self.client.post(
                self.url,
                {
                    "action": "test_ollama_config",
                    "ollama_enabled": "on",
                    "ollama_provider": "ollama",
                    "ollama_base_url": "http://ollama.test.local:11434",
                    "ollama_model": "llama3.1",
                    "ollama_timeout": "30",
                    "ollama_temperature": "0.2",
                    "ollama_max_prompt_chars": "4000",
                    "ollama_max_history_messages": "10",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Connessione Ollama riuscita")
        json_get.assert_any_call("http://ollama.test.local:11434/api/version", 30)
        json_get.assert_any_call("http://ollama.test.local:11434/api/tags", 30)

    def test_config_srv_ollama_connection_handles_invalid_tags_json(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views._ollama_json_get") as json_get:
            json_get.side_effect = [
                {"version": "0.9.5"},
                json.JSONDecodeError("Expecting value", "", 0),
            ]
            response = self.client.post(
                self.url,
                {
                    "action": "test_ollama_config",
                    "ollama_enabled": "on",
                    "ollama_provider": "ollama",
                    "ollama_base_url": "http://ollama.test.local:11434",
                    "ollama_model": "nemotron-3-nano:30b",
                    "ollama_timeout": "30",
                    "ollama_temperature": "0.2",
                    "ollama_max_prompt_chars": "4000",
                    "ollama_max_history_messages": "10",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Connessione Ollama riuscita")
        self.assertContains(response, "/api/tags non ha restituito JSON valido")
        self.assertNotContains(response, "line 1 column 1")

    def test_config_srv_can_test_openwebui_connection(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views._ollama_json_get") as json_get:
            json_get.return_value = {"data": [{"id": "llama3.1"}]}
            response = self.client.post(
                self.url,
                {
                    "action": "test_ollama_config",
                    "ollama_enabled": "on",
                    "ollama_provider": "openwebui",
                    "ollama_base_url": "http://openwebui.test.local:3000",
                    "ollama_model": "llama3.1",
                    "openwebui_api_key": "sk-test",
                    "ollama_timeout": "30",
                    "ollama_temperature": "0.2",
                    "ollama_max_prompt_chars": "4000",
                    "ollama_max_history_messages": "10",
                    "ollama_rag_enabled": "on",
                    "ollama_rag_source_paths": "README.md,docs/ai",
                    "ollama_rag_max_chunks": "4",
                    "ollama_rag_max_context_chars": "5000",
                    "ollama_rag_cache_seconds": "300",
                    "ollama_rag_max_db_entries": "200",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open WebUI raggiunto")
        json_get.assert_any_call(
            "http://openwebui.test.local:3000/api/models",
            30,
            headers={"Authorization": "Bearer sk-test"},
        )

    def test_ai_settings_openwebui_401_shows_key_rotation_hint_once(self):
        self.client.force_login(self.admin_user)

        http_error = urllib.error.HTTPError(
            url="http://openwebui.test.local:3000/api/models",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views._ollama_json_get", side_effect=http_error):
            response = self.client.post(
                reverse("admin_portale:ai_settings"),
                {
                    "action": "test_ollama_config",
                    "ollama_enabled": "on",
                    "ollama_provider": "openwebui",
                    "ollama_base_url": "http://openwebui.test.local:3000",
                    "ollama_model": "nemotron-3-nano:30b",
                    "openwebui_api_key": "sk-old",
                    "ollama_timeout": "60",
                    "ollama_temperature": "0.2",
                    "ollama_max_prompt_chars": "4000",
                    "ollama_max_history_messages": "10",
                    "ollama_rag_enabled": "on",
                    "ollama_rag_source_paths": "README.md,docs/ai",
                    "ollama_rag_max_chunks": "4",
                    "ollama_rag_max_context_chars": "5000",
                    "ollama_rag_cache_seconds": "300",
                    "ollama_rag_max_db_entries": "200",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("Open WebUI ha risposto HTTP 401", body)
        self.assertIn("Rigenera la key", body)
        self.assertEqual(body.count("Open WebUI ha risposto HTTP 401"), 1)

    def test_config_srv_ollama_connection_reports_network_error(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views._ollama_json_get", side_effect=urllib.error.URLError("no route")):
            response = self.client.post(
                self.url,
                {
                    "action": "test_ollama_config",
                    "ollama_enabled": "on",
                    "ollama_provider": "ollama",
                    "ollama_base_url": "http://ollama.test.local:11434",
                    "ollama_model": "llama3.1",
                    "ollama_timeout": "30",
                    "ollama_temperature": "0.2",
                    "ollama_max_prompt_chars": "4000",
                    "ollama_max_history_messages": "10",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ollama non raggiungibile")

    def test_config_srv_ollama_connection_reports_openwebui_hint_on_405(self):
        self.client.force_login(self.admin_user)

        http_error = urllib.error.HTTPError(
            url="http://10.0.0.34:3000/api/version",
            code=405,
            msg="Method Not Allowed",
            hdrs=None,
            fp=None,
        )
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ), patch("admin_portale.views._ollama_json_get", side_effect=http_error):
            response = self.client.post(
                self.url,
                {
                    "action": "test_ollama_config",
                    "ollama_enabled": "on",
                    "ollama_provider": "ollama",
                    "ollama_base_url": "http://10.0.0.34:3000",
                    "ollama_model": "llama3.1",
                    "ollama_timeout": "30",
                    "ollama_temperature": "0.2",
                    "ollama_max_prompt_chars": "4000",
                    "ollama_max_history_messages": "10",
                    "ollama_rag_enabled": "on",
                    "ollama_rag_source_paths": "README.md,docs/ai",
                    "ollama_rag_max_chunks": "4",
                    "ollama_rag_max_context_chars": "5000",
                    "ollama_rag_cache_seconds": "300",
                    "ollama_rag_max_db_entries": "200",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open WebUI")
        self.assertContains(response, "http://10.0.0.34:11434")

    def test_config_srv_deploy_runtime_writes_persistent_env_not_release_env(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ldap-deploy-env-")
        try:
            env_root = tmpdir / "test"
            current_app = env_root / "current" / "django_app"
            config_dir = env_root / "config"
            current_app.mkdir(parents=True)
            config_dir.mkdir(parents=True)

            shared_env_path = config_dir / ".env"
            release_env_path = current_app / ".env"
            shared_env_path.write_text("LDAP_SERVER=ldap://shared-old.local\nLDAP_ENABLED=0\n", encoding="utf-8")
            release_env_path.write_text("LDAP_SERVER=ldap://release-old.local\nLDAP_ENABLED=0\n", encoding="utf-8")

            with override_settings(BASE_DIR=current_app), patch(
                "admin_portale.decorators.get_legacy_user",
                return_value=self.admin_legacy,
            ), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.post(
                    self.url,
                    {
                        "action": "save_ldap_config",
                        "enabled": "on",
                        "server": "ldap://dc-test.example.local",
                        "domain": "TEST",
                        "upn_suffix": "@test.local",
                        "timeout": "8",
                        "base_dn": "DC=TEST,DC=LOCAL",
                        "user_filter": "(&(objectCategory=person)(objectClass=user))",
                        "group_allowlist": "EMPLOYEES",
                        "sync_page_size": "750",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "config/.env persistente")

            shared_content = shared_env_path.read_text(encoding="utf-8")
            release_content = release_env_path.read_text(encoding="utf-8")
            self.assertIn("LDAP_SERVER=ldap://dc-test.example.local", shared_content)
            self.assertIn("LDAP_ENABLED=1", shared_content)
            self.assertIn("LDAP_SERVER=ldap://release-old.local", release_content)
            self.assertNotIn("ldap://dc-test.example.local", release_content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_config_srv_shows_runtime_vs_next_restart_when_config_differs(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ldap-runtime-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "LDAP_ENABLED=1",
                        "LDAP_SERVER=ldap://config.example.local",
                        "LDAP_DOMAIN=CONFIG",
                        "LDAP_UPN_SUFFIX=@config.local",
                        "LDAP_TIMEOUT=9",
                        "LDAP_SERVICE_USER=svc_config",
                        "LDAP_BASE_DN=DC=CONFIG,DC=LOCAL",
                        "LDAP_USER_FILTER=(objectClass=user)",
                        "LDAP_GROUP_ALLOWLIST=EMPLOYEES,ADMINS",
                        "LDAP_SYNC_PAGE_SIZE=750",
                    ]
                ),
                encoding="utf-8",
            )

            with override_settings(
                LDAP_ENABLED=False,
                LDAP_SERVER="ldap://runtime.example.local",
                LDAP_DOMAIN="RUNTIME",
                LDAP_UPN_SUFFIX="@runtime.local",
                LDAP_TIMEOUT=5,
                LDAP_SERVICE_USER="svc_runtime",
                LDAP_BASE_DN="DC=RUNTIME,DC=LOCAL",
                LDAP_USER_FILTER="(&(objectCategory=person)(objectClass=user))",
                LDAP_GROUP_ALLOWLIST=["RUNTIME"],
                LDAP_SYNC_PAGE_SIZE=500,
            ), patch(
                "admin_portale.decorators.get_legacy_user",
                return_value=self.admin_legacy,
            ), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch(
                "admin_portale.views._dotenv_path",
                return_value=env_path,
            ), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.get(self.url)

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Runtime LDAP attivo")
            self.assertContains(response, "Configurazione LDAP")
            self.assertContains(response, "ldap://runtime.example.local")
            self.assertContains(response, "ldap://config.example.local")
            self.assertContains(response, "Riavvio necessario")
            self.assertContains(response, "Il processo Django attuale non e' ancora allineato")
            self.assertContains(response, '<input class="input" type="text" name="server" value="ldap://config.example.local">', html=True)
            self.assertContains(response, '<input class="input" type="text" name="group_allowlist" value="EMPLOYEES, ADMINS" placeholder="EMPLOYEES,MANAGERS,ADMINS">', html=True)
            self.assertContains(response, '<input class="input" type="number" min="100" max="2000" name="sync_page_size" value="750">', html=True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_config_srv_uses_dotenv_values_for_effective_form_and_connection_test(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ldap-dotenv-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "LDAP_ENABLED=1",
                        "LDAP_SERVER=ldap://dotenv.example.local",
                        "LDAP_DOMAIN=DOTENV",
                        "LDAP_UPN_SUFFIX=@dotenv.local",
                        "LDAP_TIMEOUT=7",
                        "LDAP_SERVICE_USER=svc_dotenv",
                        "LDAP_SERVICE_PASSWORD=dotenv-secret",
                        "LDAP_BASE_DN=DC=DOTENV,DC=LOCAL",
                        "LDAP_USER_FILTER=(&(objectCategory=person)(objectClass=user))",
                        "LDAP_GROUP_ALLOWLIST=EMPLOYEES,ADMINS",
                        "LDAP_SYNC_PAGE_SIZE=640",
                    ]
                ),
                encoding="utf-8",
            )

            with override_settings(
                LDAP_ENABLED=True,
                LDAP_SERVER="ldap://dotenv.example.local",
                LDAP_DOMAIN="DOTENV",
                LDAP_UPN_SUFFIX="@dotenv.local",
                LDAP_TIMEOUT=7,
                LDAP_SERVICE_USER="svc_dotenv",
                LDAP_SERVICE_PASSWORD="dotenv-secret",
                LDAP_BASE_DN="DC=DOTENV,DC=LOCAL",
                LDAP_USER_FILTER="(&(objectCategory=person)(objectClass=user))",
                LDAP_GROUP_ALLOWLIST=["EMPLOYEES", "ADMINS"],
                LDAP_SYNC_PAGE_SIZE=640,
            ), patch(
                "admin_portale.decorators.get_legacy_user",
                return_value=self.admin_legacy,
            ), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch(
                "admin_portale.views._dotenv_path",
                return_value=env_path,
            ), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.get(self.url)

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Test LDAP pronti.")
            self.assertContains(response, '<input class="input" type="text" name="server" value="ldap://dotenv.example.local">', html=True)
            self.assertContains(response, "da .env")
            self.assertContains(response, "Service account effettivo configurato")
            self.assertContains(response, "svc_dotenv")

            with override_settings(
                LDAP_ENABLED=True,
                LDAP_SERVER="ldap://dotenv.example.local",
                LDAP_DOMAIN="DOTENV",
                LDAP_UPN_SUFFIX="@dotenv.local",
                LDAP_TIMEOUT=7,
                LDAP_SERVICE_USER="svc_dotenv",
                LDAP_SERVICE_PASSWORD="dotenv-secret",
                LDAP_BASE_DN="DC=DOTENV,DC=LOCAL",
                LDAP_USER_FILTER="(&(objectCategory=person)(objectClass=user))",
                LDAP_GROUP_ALLOWLIST=["EMPLOYEES", "ADMINS"],
                LDAP_SYNC_PAGE_SIZE=640,
            ), patch(
                "admin_portale.decorators.get_legacy_user",
                return_value=self.admin_legacy,
            ), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch(
                "admin_portale.views._dotenv_path",
                return_value=env_path,
            ), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ), patch(
                "admin_portale.views._ldap_test_connect",
                return_value=(True, "Connessione LDAP riuscita."),
            ) as mocked_test_connect:
                response = self.client.post(self.url, {"action": "test_connect"})

            self.assertEqual(response.status_code, 200)
            mocked_test_connect.assert_called_once_with("ldap://dotenv.example.local", 7)
            self.assertContains(response, "Connessione LDAP riuscita.")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_config_srv_sync_uses_effective_dotenv_credentials_without_restart(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ldap-sync-effective-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "LDAP_ENABLED=1",
                        "LDAP_SERVER=ldap://dotenv.example.local",
                        "LDAP_DOMAIN=DOTENV",
                        "LDAP_UPN_SUFFIX=@dotenv.local",
                        "LDAP_TIMEOUT=7",
                        "LDAP_SERVICE_USER=svc_dotenv",
                        "LDAP_SERVICE_PASSWORD=dotenv-secret",
                        "LDAP_BASE_DN=DC=DOTENV,DC=LOCAL",
                        "LDAP_USER_FILTER=(&(objectCategory=person)(objectClass=user))",
                        "LDAP_GROUP_ALLOWLIST=EMPLOYEES,ADMINS",
                        "LDAP_SYNC_PAGE_SIZE=640",
                    ]
                ),
                encoding="utf-8",
            )

            with override_settings(
                LDAP_ENABLED=False,
                LDAP_SERVER="",
                LDAP_DOMAIN="",
                LDAP_UPN_SUFFIX="",
                LDAP_TIMEOUT=5,
                LDAP_SERVICE_USER="",
                LDAP_SERVICE_PASSWORD="",
                LDAP_BASE_DN="",
                LDAP_USER_FILTER="",
                LDAP_GROUP_ALLOWLIST=[],
                LDAP_SYNC_PAGE_SIZE=500,
            ), patch(
                "admin_portale.decorators.get_legacy_user",
                return_value=self.admin_legacy,
            ), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch(
                "admin_portale.views._dotenv_path",
                return_value=env_path,
            ), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ), patch(
                "admin_portale.views.call_command",
            ) as mocked_call:
                response = self.client.post(
                    self.url,
                    {
                        "action": "sync_users",
                        "sync_limit": "20",
                        "sync_dry_run": "on",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Sync utenti LDAP completata")
            mocked_call.assert_called_once()
            self.assertEqual(mocked_call.call_args.args[0], "sync_ldap_users")
            kwargs = mocked_call.call_args.kwargs
            self.assertTrue(kwargs["ldap_enabled"])
            self.assertEqual(kwargs["server"], "ldap://dotenv.example.local")
            self.assertEqual(kwargs["domain"], "DOTENV")
            self.assertEqual(kwargs["upn_suffix"], "@dotenv.local")
            self.assertEqual(kwargs["timeout"], 7)
            self.assertEqual(kwargs["service_user"], "svc_dotenv")
            self.assertEqual(kwargs["service_password"], "dotenv-secret")
            self.assertEqual(kwargs["search_base"], "DC=DOTENV,DC=LOCAL")
            self.assertEqual(kwargs["user_filter"], "(&(objectCategory=person)(objectClass=user))")
            self.assertEqual(kwargs["group_allowlist"], "EMPLOYEES, ADMINS")
            self.assertEqual(kwargs["page_size"], 640)
            self.assertEqual(kwargs["limit"], 20)
            self.assertTrue(kwargs["dry_run"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_config_srv_save_service_account_preserves_existing_password_when_blank(self):
        self.client.force_login(self.admin_user)

        tmpdir = _make_workspace_tempdir("ldap-svc-preserve-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "LDAP_SERVICE_USER=svc_old",
                        "LDAP_SERVICE_PASSWORD=existing-secret",
                    ]
                ),
                encoding="utf-8",
            )

            with patch(
                "admin_portale.decorators.get_legacy_user",
                return_value=self.admin_legacy,
            ), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch(
                "admin_portale.views._dotenv_path",
                return_value=env_path,
            ), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ):
                response = self.client.post(
                    self.url,
                    {
                        "action": "save_service_account",
                        "service_user": "svc_new",
                        "service_password": "",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Service account salvato")
            content = env_path.read_text(encoding="utf-8")
            self.assertIn("LDAP_SERVICE_USER=svc_new", content)
            self.assertIn("LDAP_SERVICE_PASSWORD=existing-secret", content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ldap_import_search_handles_referral_socket_errors(self):
        self.client.force_login(self.admin_user)

        class FakeLDAPException(Exception):
            pass

        class FakeLDAPSocketOpenError(FakeLDAPException):
            pass

        fake_conn = MagicMock()
        fake_conn.bind.return_value = True
        fake_conn.search.side_effect = FakeLDAPSocketOpenError("invalid server address")
        fake_conn.entries = []

        fake_ldap3 = ModuleType("ldap3")
        fake_ldap3.AUTO_BIND_NO_TLS = "AUTO_BIND_NO_TLS"
        fake_ldap3.NONE = "NONE"
        fake_ldap3.NTLM = "NTLM"
        fake_ldap3.SIMPLE = "SIMPLE"
        fake_ldap3.SUBTREE = "SUBTREE"
        fake_ldap3.Connection = MagicMock(return_value=fake_conn)
        fake_ldap3.Server = MagicMock(return_value=object())

        fake_ldap3_core = ModuleType("ldap3.core")
        fake_ldap3_exceptions = ModuleType("ldap3.core.exceptions")
        fake_ldap3_exceptions.LDAPException = FakeLDAPException
        fake_ldap3_exceptions.LDAPSocketOpenError = FakeLDAPSocketOpenError

        tmpdir = _make_workspace_tempdir("ldap-import-effective-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "LDAP_ENABLED=1",
                        "LDAP_SERVER=ldap://dc1.example.local",
                        "LDAP_DOMAIN=EXAMPLE",
                        "LDAP_UPN_SUFFIX=@example.local",
                        "LDAP_TIMEOUT=5",
                        "LDAP_SERVICE_USER=svc_ldap@example.local",
                        "LDAP_SERVICE_PASSWORD=secret",
                        "LDAP_BASE_DN=DC=EXAMPLE,DC=LOCAL",
                        "LDAP_USER_FILTER=(&(objectCategory=person)(objectClass=user))",
                    ]
                ),
                encoding="utf-8",
            )

            with override_settings(
                LDAP_ENABLED=True,
                LDAP_SERVER="ldap://dc1.example.local",
                LDAP_DOMAIN="EXAMPLE",
                LDAP_UPN_SUFFIX="@example.local",
                LDAP_TIMEOUT=5,
                LDAP_SERVICE_USER="svc_ldap@example.local",
                LDAP_SERVICE_PASSWORD="secret",
                LDAP_BASE_DN="DC=EXAMPLE,DC=LOCAL",
                LDAP_USER_FILTER="(&(objectCategory=person)(objectClass=user))",
            ), patch(
                "admin_portale.decorators.get_legacy_user",
                return_value=self.admin_legacy,
            ), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch(
                "admin_portale.views._dotenv_path",
                return_value=env_path,
            ), patch.dict(
                "admin_portale.views.os.environ",
                {},
                clear=True,
            ), patch.dict(
                sys.modules,
                {
                    "ldap3": fake_ldap3,
                    "ldap3.core": fake_ldap3_core,
                    "ldap3.core.exceptions": fake_ldap3_exceptions,
                },
                clear=False,
            ):
                response = self.client.post(
                    reverse("admin_portale:ldap_import_utenti"),
                    {"action": "search", "q": "Mario"},
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(
            response.content,
            {"ok": False, "error": "Ricerca LDAP fallita: invalid server address"},
        )
        self.assertEqual(fake_ldap3.Connection.call_count, 1)
        self.assertIs(fake_ldap3.Connection.call_args.kwargs["auto_referrals"], False)
        fake_conn.unbind.assert_called_once()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleNavigationIconTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-nav-icons",
            email="admin.nav.icons@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Navigation",
            email="admin.nav.icons@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )

    def test_api_navigation_item_create_persists_image_icon(self):
        from core.models import NavigationItem

        self.client.force_login(self.admin_user)
        payload = {
            "code": "assets-icon-test",
            "label": "Assets",
            "section": "topbar",
            "route_name": "dashboard_home",
            "icon": "/media/icons/assets-menu.ico",
            "is_visible": True,
            "is_enabled": True,
        }

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:api_navigation_item_create"),
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        item = NavigationItem.objects.get(code="assets-icon-test")
        self.assertEqual(item.icon, "/media/icons/assets-menu.ico")

    def test_api_navigation_icon_upload_stores_file_in_library(self):
        self.client.force_login(self.admin_user)
        upload = SimpleUploadedFile(
            "assets-menu.ico",
            b"\x00\x00\x01\x00test-ico",
            content_type="image/x-icon",
        )

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root, MEDIA_URL="/media/"), patch(
            "admin_portale.decorators.get_legacy_user",
            return_value=self.admin_legacy,
        ), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:api_navigation_icon_upload"),
                {"icon": upload},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["icon"]["value"].startswith("navigation/icons/"))
        self.assertTrue(payload["icon"]["url"].startswith("/media/navigation/icons/"))


class AdminPortaleReleaseOpsTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="admin_release_ops",
            email="admin-release@example.com",
            password="x",
        )

    def _login(self):
        self.client.force_login(self.admin_user)

    def _deploy_tree(self) -> Path:
        root = _make_workspace_tempdir("release-ops-")
        django_app = root / "test" / "current" / "django_app"
        django_app.mkdir(parents=True)
        (django_app / "manage.py").write_text("print('manage')\n", encoding="utf-8")
        venv_scripts = root / "test" / "venv" / "Scripts"
        venv_scripts.mkdir(parents=True)
        (venv_scripts / "python.exe").write_text("", encoding="utf-8")
        return root

    def test_crea_release_page_exposes_server_operations(self):
        self._login()
        deploy_root = self._deploy_tree()
        try:
            with patch("admin_portale.decorators.get_legacy_user", return_value=None), patch(
                "admin_portale.views._release_deploy_base_dir",
                return_value=deploy_root,
            ):
                response = self.client.get(reverse("admin_portale:crea_release"))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Operazioni server")
            self.assertContains(response, "Riavvia servizio IIS")
            self.assertContains(response, "release-terminal-command")
            self.assertContains(response, "PortaleNovicrom-TEST")
        finally:
            shutil.rmtree(deploy_root, ignore_errors=True)

    def test_release_terminal_runs_manage_py_with_environment_venv(self):
        self._login()
        deploy_root = self._deploy_tree()
        try:
            url = reverse("admin_portale:api_release_terminal_command")
            with patch("admin_portale.decorators.get_legacy_user", return_value=None), patch(
                "admin_portale.views._release_deploy_base_dir",
                return_value=deploy_root,
            ), patch(
                "admin_portale.views.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="System check identified no issues.", stderr=""),
            ) as mocked_run:
                response = self.client.post(
                    url,
                    data=json.dumps({"environment": "test", "command": "manage.py check"}),
                    content_type="application/json",
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["command_ok"])
            self.assertIn("System check", payload["stdout"])
            argv = mocked_run.call_args.args[0]
            self.assertEqual(argv[0], str(deploy_root / "test" / "venv" / "Scripts" / "python.exe"))
            self.assertEqual(argv[1:], ["manage.py", "check"])
            self.assertEqual(mocked_run.call_args.kwargs["cwd"], str(deploy_root / "test" / "current" / "django_app"))
            env = mocked_run.call_args.kwargs["env"]
            self.assertEqual(env["DJANGO_SETTINGS_MODULE"], "config.settings.prod")
            self.assertEqual(env["PORTAL_SKIP_RUNTIME_BOOTSTRAP"], "1")
        finally:
            shutil.rmtree(deploy_root, ignore_errors=True)

    def test_release_restart_service_starts_scheduled_task(self):
        self._login()
        url = reverse("admin_portale:api_release_restart_service")
        with patch("admin_portale.decorators.get_legacy_user", return_value=None), patch(
            "admin_portale.views.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="Task restart IIS avviato", stderr=""),
        ) as mocked_run:
            response = self.client.post(
                url,
                data=json.dumps({"environment": "test"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["service_ok"])
        self.assertEqual(payload["restart_mode"], "scheduled_task")
        self.assertEqual(payload["task_name"], r"\PortaleNovicrom\IISRestart_TEST")
        command = mocked_run.call_args.args[0]
        self.assertIn("powershell.exe", command[0])
        self.assertIn("IISRestart_TEST", command[-1])

    def test_release_restart_service_uses_direct_iis_when_task_missing(self):
        self._login()
        url = reverse("admin_portale:api_release_restart_service")
        with patch("admin_portale.decorators.get_legacy_user", return_value=None), patch(
            "admin_portale.views.subprocess.run",
            side_effect=[
                SimpleNamespace(returncode=3, stdout="Task restart IIS non configurato", stderr=""),
                SimpleNamespace(returncode=0, stdout="Riavvio schedulato", stderr=""),
            ],
        ) as mocked_run:
            response = self.client.post(
                url,
                data=json.dumps({"environment": "test"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["service_ok"])
        self.assertEqual(mocked_run.call_count, 2)
        direct_command = mocked_run.call_args_list[1].args[0]
        self.assertIn("PortaleNovicrom-TEST", direct_command[-1])

    def test_release_restart_service_falls_back_on_access_denied(self):
        self._login()
        url = reverse("admin_portale:api_release_restart_service")
        with patch("admin_portale.decorators.get_legacy_user", return_value=None), patch(
            "admin_portale.views.subprocess.run",
            side_effect=PermissionError("[WinError 5] Accesso negato"),
        ), patch(
            "admin_portale.views._release_schedule_process_restart",
            return_value=True,
        ) as mocked_restart:
            response = self.client.post(
                url,
                data=json.dumps({"environment": "test"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["service_ok"])
        self.assertTrue(payload["fallback_used"])
        self.assertEqual(payload["restart_mode"], "django_process")
        mocked_restart.assert_called_once()


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
    ADMIN_PORTALE_SENSITIVE_ALLOWED_ROLE_NAMES=(),
    ADMIN_PORTALE_SENSITIVE_ALLOWED_ROLE_IDS=(),
)
class AdminPortaleSensitiveOperationSecurityTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="sensitive-admin",
            email="sensitive-admin@example.com",
            password="secret123",
        )
        self.normal_user = User.objects.create_user(
            username="sensitive-user",
            email="sensitive-user@example.com",
            password="secret123",
        )
        UserOnboarding.objects.create(user=self.normal_user, skipped=True)
        self.legacy_admin = SimpleNamespace(id=99000, ruolo="admin", ruolo_id=1)

    def _json_request(self, user, *, legacy_user=None):
        request = RequestFactory().post(
            "/admin-portale/crea-release/api/terminal/",
            data=json.dumps({"environment": "test", "command": "manage.py shell --secret-token"}),
            content_type="application/json",
        )
        request.user = user
        if legacy_user is not None:
            request.legacy_user = legacy_user
        return request

    def _protected_probe(self, request):
        from admin_portale.security import sensitive_admin_operation_required

        called = False

        @sensitive_admin_operation_required("release_terminal_command")
        def protected_view(request):
            nonlocal called
            called = True
            return HttpResponse("ok")

        response = protected_view(request)
        return response, called

    def test_superuser_can_run_protected_restart_and_audit_is_allowed(self):
        from core.models import AuditLog

        self.client.force_login(self.admin_user)
        url = reverse("admin_portale:api_release_restart_service")
        with patch(
            "admin_portale.views.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="Task restart IIS avviato", stderr=""),
        ):
            response = self.client.post(
                url,
                data=json.dumps({"environment": "test"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        audit = AuditLog.objects.filter(
            azione="admin_sensitive_operation_attempt",
            dettaglio__operation="release_restart_service",
        ).latest("created_at")
        self.assertEqual(audit.dettaglio["outcome"], "allowed")
        self.assertEqual(audit.dettaglio["reason"], "superuser")

    def test_normal_user_is_denied_with_safe_response_and_audit(self):
        from core.models import AuditLog

        request = self._json_request(self.normal_user)

        with self.assertLogs(
            "admin_portale.security",
            level="INFO",
        ) as logs:
            response, called = self._protected_probe(request)

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "forbidden")
        self.assertNotIn("secret-token", response.content.decode("utf-8"))
        self.assertFalse(called)
        self.assertTrue(any('"outcome": "denied"' in line for line in logs.output))

        audit = AuditLog.objects.filter(
            azione="admin_sensitive_operation_attempt",
            dettaglio__operation="release_terminal_command",
        ).latest("created_at")
        self.assertEqual(audit.dettaglio["outcome"], "denied")
        self.assertEqual(audit.dettaglio["reason"], "not_authorized")
        self.assertNotIn("command", audit.dettaglio)

    def test_api_denied_returns_consistent_json(self):
        self.client.force_login(self.normal_user)
        url = reverse("admin_portale:api_release_terminal_command")

        response = self.client.post(
            url,
            data=json.dumps({"environment": "test", "command": "manage.py check"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        payload = response.json()
        self.assertEqual(
            payload,
            {
                "ok": False,
                "error": "Operazione non autorizzata.",
                "reason": "forbidden",
            },
        )
        self.assertNotIn("manage.py check", response.content.decode("utf-8"))

    def test_legacy_admin_is_denied_when_sensitive_settings_are_not_configured(self):
        from core.models import AuditLog

        request = self._json_request(self.normal_user, legacy_user=self.legacy_admin)

        with self.assertLogs("admin_portale.security", level="INFO"):
            response, called = self._protected_probe(request)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(called)
        audit = AuditLog.objects.filter(
            azione="admin_sensitive_operation_attempt",
            dettaglio__operation="release_terminal_command",
        ).latest("created_at")
        self.assertEqual(audit.dettaglio["outcome"], "denied")
        self.assertEqual(audit.dettaglio["reason"], "not_authorized")
        self.assertIn("admin", audit.dettaglio["role_names"])

    @override_settings(ADMIN_PORTALE_SENSITIVE_ALLOWED_ROLE_NAMES=("admin",))
    def test_legacy_admin_is_allowed_only_when_role_name_is_configured(self):
        from core.models import AuditLog

        request = self._json_request(self.normal_user, legacy_user=self.legacy_admin)

        response, called = self._protected_probe(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(called)
        audit = AuditLog.objects.filter(
            azione="admin_sensitive_operation_attempt",
            dettaglio__operation="release_terminal_command",
        ).latest("created_at")
        self.assertEqual(audit.dettaglio["outcome"], "allowed")
        self.assertEqual(audit.dettaglio["reason"], "technical_role")
        self.assertEqual(audit.dettaglio["matched_role_names"], ["admin"])

    @override_settings(ADMIN_PORTALE_SENSITIVE_ALLOWED_ROLE_NAMES=("tecnico",))
    def test_configured_technical_profile_role_is_allowed(self):
        from admin_portale.security import sensitive_admin_operation_required

        Profile.objects.create(
            user=self.normal_user,
            legacy_user_id=99001,
            legacy_ruolo_id=77,
            legacy_ruolo="tecnico",
        )
        request = RequestFactory().get("/admin-portale/probe/")
        request.user = self.normal_user

        @sensitive_admin_operation_required("probe_get")
        def probe_view(request):
            return HttpResponse("ok")

        response = probe_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_decorator_does_not_break_simple_get_view_for_superuser(self):
        from admin_portale.security import sensitive_admin_operation_required

        request = RequestFactory().get("/admin-portale/probe/")
        request.user = self.admin_user

        @sensitive_admin_operation_required("probe_get")
        def probe_view(request):
            return HttpResponse("ok")

        response = probe_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleNavigationBuilderVisualTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-nav-visual",
            email="admin.nav.visual@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Navigation Visual",
            email="admin.nav.visual@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )

        self.item_topbar_1 = NavigationItem.objects.create(
            code="nav-topbar-1",
            label="Topbar One",
            section="topbar",
            route_name="dashboard_home",
            order=10,
            is_visible=True,
            is_enabled=True,
        )
        self.item_topbar_2 = NavigationItem.objects.create(
            code="nav-topbar-2",
            label="Topbar Two",
            section="topbar",
            route_name="dashboard_home",
            order=20,
            is_visible=True,
            is_enabled=True,
        )
        self.item_sidebar = NavigationItem.objects.create(
            code="nav-sidebar-1",
            label="Sidebar One",
            section="sidebar",
            route_name="dashboard_home",
            order=10,
            is_visible=True,
            is_enabled=True,
        )
        self.item_subnav = NavigationItem.objects.create(
            code="nav-subnav-1",
            label="Subnav One",
            section="subnav",
            parent_code="dashboard",
            route_name="dashboard_home",
            order=10,
            is_visible=True,
            is_enabled=True,
        )
        NavigationRoleAccess.objects.create(item=self.item_topbar_1, legacy_role_id=2, can_view=True)

    def _as_admin_get(self, url, params=None):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            return self.client.get(url, params or {})

    def _as_admin_post_json(self, url, payload):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            return self.client.post(
                url,
                data=json.dumps(payload),
                content_type="application/json",
            )

    def test_navigation_builder_renders_visual_board(self):
        response = self._as_admin_get(
            reverse("admin_portale:navigation_builder"),
            {"section": "all"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visual Builder", html=False)
        self.assertContains(response, 'class="visual-lane"', html=False)
        self.assertContains(response, 'data-section="topbar"', html=False)
        self.assertContains(response, 'data-section="sidebar"', html=False)
        self.assertContains(response, "Apri in tabella", html=False)

        visual_sections = response.context["visual_sections"]
        by_key = {row["key"]: row for row in visual_sections}
        self.assertIn("topbar", by_key)
        self.assertIn("sidebar", by_key)
        self.assertTrue(any(item["id"] == self.item_topbar_1.id for item in by_key["topbar"]["items"]))
        self.assertFalse(bool(response.context["advanced_mode"]))

    def test_navigation_builder_binds_visual_card_actions_with_async_click_handler(self):
        response = self._as_admin_get(
            reverse("admin_portale:navigation_builder"),
            {"section": "all"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'document.addEventListener("click", async function (ev) {', html=False)
        self.assertContains(response, 'const deleteCardBtn = target.closest(".nav-delete-card");', html=False)
        self.assertContains(response, 'const cloneCardBtn = target.closest(".nav-clone-card");', html=False)
        self.assertContains(response, 'const focusBtn = target.closest(".nav-focus-row");', html=False)

    def test_navigation_builder_advanced_mode_can_be_enabled_via_query_param(self):
        response = self._as_admin_get(
            reverse("admin_portale:navigation_builder"),
            {"section": "all", "advanced": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(bool(response.context["advanced_mode"]))
        self.assertContains(response, 'data-advanced="1"', html=False)
        self.assertContains(response, "Passa a modalità standard", html=False)

    def test_api_navigation_reorder_supports_section_orders_payload(self):
        response = self._as_admin_post_json(
            reverse("admin_portale:api_navigation_reorder"),
            {
                "section_orders": {
                    "topbar": [self.item_topbar_2.id],
                    "sidebar": [self.item_topbar_1.id, self.item_sidebar.id],
                    "subnav": [self.item_subnav.id],
                    "admin_subnav": [],
                    "page": [],
                }
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "section_orders")

        self.item_topbar_1.refresh_from_db()
        self.item_topbar_2.refresh_from_db()
        self.item_sidebar.refresh_from_db()
        self.item_subnav.refresh_from_db()

        self.assertEqual(self.item_topbar_2.section, "topbar")
        self.assertEqual(self.item_topbar_2.order, 10)
        self.assertEqual(self.item_topbar_1.section, "sidebar")
        self.assertEqual(self.item_topbar_1.order, 10)
        self.assertEqual(self.item_sidebar.section, "sidebar")
        self.assertEqual(self.item_sidebar.order, 20)
        self.assertEqual(self.item_subnav.section, "subnav")
        self.assertEqual(self.item_subnav.order, 10)

    def test_api_navigation_reorder_keeps_ordered_ids_backward_compatible(self):
        response = self._as_admin_post_json(
            reverse("admin_portale:api_navigation_reorder"),
            {"ordered_ids": [self.item_topbar_2.id, self.item_topbar_1.id]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        self.item_topbar_1.refresh_from_db()
        self.item_topbar_2.refresh_from_db()
        self.assertEqual(self.item_topbar_2.order, 10)
        self.assertEqual(self.item_topbar_1.order, 20)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Security tests
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€



@override_settings(
    LEGACY_AUTH_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
    NAVIGATION_REGISTRY_ENABLED=True,
    NAVIGATION_LEGACY_FALLBACK_ENABLED=True,
)
class AdminPortaleAclDiagnosticViewTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        _ensure_ruoli_table()
        _ensure_pulsanti_table()
        _ensure_permessi_table()
        _clear_acl_navigation_seed_tables()

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-acl-diagnostic",
            email="admin.acl.diagnostic@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin ACL",
            email="admin.acl.diagnostic@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_legacy = UtenteLegacy.objects.create(
            nome="Utente ACL",
            email="utente.acl@test.local",
            password="*AD_MANAGED*",
            ruolo="operatore",
            ruolo_id=2,
            attivo=True,
            deve_cambiare_password=False,
        )

        Ruolo.objects.create(id=1, nome="admin")
        Ruolo.objects.create(id=2, nome="operatore")
        Ruolo.objects.create(id=3, nome="ospite")
        Pulsante.objects.create(
            codice="gestione_assenze",
            nome_visibile="Gestione Assenze",
            icona="calendar",
            modulo="assenze",
            url="/assenze/",
        )
        Permesso.objects.create(
            ruolo_id=2,
            modulo="assenze",
            azione="gestione_assenze",
            can_view=0,
            consentito=0,
        )
        UserPermissionOverride.objects.create(
            legacy_user_id=self.target_legacy.id,
            modulo="assenze",
            azione="gestione_assenze",
            can_view=True,
        )
        nav_item = NavigationItem.objects.create(
            code="assenze-diag",
            label="Assenze",
            section="topbar",
            route_name="coming_assenze",
            order=10,
            is_visible=True,
            is_enabled=True,
        )
        NavigationRoleAccess.objects.create(item=nav_item, legacy_role_id=2, can_view=True)
        LegacyRedirect.objects.create(
            legacy_path="/admin/vecchie-assenze",
            target_url_path="/assenze/",
            is_enabled=True,
        )
        bump_legacy_cache_version()

    def _post_diag(self, data: dict):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            return self.client.post(reverse("admin_portale:acl_diagnostica"), data)

    def test_acl_diagnostica_returns_structured_reason_and_context(self):
        response = self._post_diag(
            {
                "path": "/assenze/",
                "legacy_user_id": str(self.target_legacy.id),
            }
        )

        self.assertEqual(response.status_code, 200)
        diag = response.context["diag"]
        self.assertTrue(diag["allowed"])
        self.assertEqual(diag["reason_code"], "user_override_allow")
        self.assertEqual(diag["decision_source"], "user_override")
        self.assertEqual(diag["pulsante"]["modulo"], "assenze")
        self.assertTrue(diag["registry_matches"])
        self.assertTrue(diag["redirect_matches"]["outbound"])
        self.assertIn("LEGACY_OVERRIDE", diag["badges"])
        self.assertIn("LEGACY_FALLBACK", diag["badges"])
        self.assertIn("legacy", diag["human_summary"]["title"].lower())
        self.assertEqual(diag["final_decision_source"], "legacy_fallback")

    def test_acl_diagnostica_allows_role_simulation(self):
        response = self._post_diag(
            {
                "path": "/assenze/",
                "legacy_user_id": str(self.target_legacy.id),
                "legacy_role_id": "3",
            }
        )

        self.assertEqual(response.status_code, 200)
        diag = response.context["diag"]
        self.assertEqual(diag["forced_role_id"], 3)
        self.assertEqual(diag["effective_role_id"], 3)

    def test_acl_diagnostica_human_summary_is_canonical_when_binding_exists(self):
        PermissionDefinition.objects.create(
            code="assenze.dashboard.view",
            label="Assenze dashboard",
            module="assenze",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="",
            path_pattern="/assenze",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            permission_id="assenze.dashboard.view",
            source_app="assenze",
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=2,
            permission_id="assenze.dashboard.view",
            enabled=False,
        )

        response = self._post_diag(
            {
                "path": "/assenze/",
                "legacy_user_id": str(self.target_legacy.id),
            }
        )

        self.assertEqual(response.status_code, 200)
        diag = response.context["diag"]
        self.assertEqual(diag["final_decision_source"], "canonical")
        self.assertIn("route bindata", diag["human_summary"]["title"].lower())


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
    NAVIGATION_REGISTRY_ENABLED=True,
    NAVIGATION_LEGACY_FALLBACK_ENABLED=True,
)
class AdminPortalePermissionNavigationMapTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        _ensure_ruoli_table()
        _ensure_pulsanti_table()
        _ensure_permessi_table()
        _clear_acl_navigation_seed_tables()

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-map",
            email="admin.map@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Map",
            email="admin.map@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_legacy = UtenteLegacy.objects.create(
            nome="Target Map",
            email="target.map@test.local",
            password="*AD_MANAGED*",
            ruolo="operatore",
            ruolo_id=2,
            attivo=True,
            deve_cambiare_password=False,
        )

        Ruolo.objects.create(id=1, nome="admin")
        Ruolo.objects.create(id=2, nome="operatore")
        Pulsante.objects.create(
            codice="gestione_assenze",
            nome_visibile="Gestione Assenze",
            icona="calendar",
            modulo="assenze",
            url="/assenze/",
        )
        Permesso.objects.create(
            ruolo_id=2,
            modulo="assenze",
            azione="gestione_assenze",
            can_view=1,
            consentito=1,
        )
        UserPermissionOverride.objects.create(
            legacy_user_id=self.target_legacy.id,
            modulo="assenze",
            azione="gestione_assenze",
            can_view=False,
        )
        nav_item = NavigationItem.objects.create(
            code="assenze-map",
            label="Assenze",
            section="topbar",
            route_name="coming_assenze",
            order=20,
            is_visible=True,
            is_enabled=True,
        )
        NavigationRoleAccess.objects.create(item=nav_item, legacy_role_id=2, can_view=True)
        LegacyRedirect.objects.create(
            legacy_path="/admin/old-assenze",
            target_url_path="/assenze/",
            is_enabled=True,
        )
        PermissionDefinition.objects.create(
            code="assets.work_orders.manage",
            label="Gestione Work Orders",
            module="assets",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="",
            path_pattern="/assenze",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="assets.work_orders.manage",
            source_app="assets",
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=2,
            permission_id="assets.work_orders.manage",
            enabled=True,
        )
        bump_legacy_cache_version()

    def test_map_page_shows_badges_for_registry_legacy_override_and_redirect(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(reverse("admin_portale:mappa_permessi_navigazione"))

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        target_row = next((row for row in rows if row["path"] == "/assenze"), None)
        self.assertIsNotNone(target_row)
        assert target_row is not None
        self.assertIn("REGISTRY", target_row["badges"])
        self.assertIn("LEGACY", target_row["badges"])
        self.assertIn("OVERRIDE", target_row["badges"])
        self.assertIn("ADMIN BYPASS", target_row["badges"])
        self.assertIn("REDIRECT", target_row["badges"])

    def test_map_page_exposes_workflow_detail_and_live_toggle_with_role_filter(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(
                reverse("admin_portale:mappa_permessi_navigazione"),
                {"legacy_role_id": "2"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workflow Decisionale", html=False)
        self.assertContains(response, "Modifica Live (Canonico + Legacy)", html=False)
        self.assertContains(response, "Canonico v2 (prioritario)", html=False)
        self.assertContains(response, "api/permessi/toggle", html=False)
        self.assertContains(response, "api/acl-v2/role-grant-toggle", html=False)

        rows = response.context["rows"]
        target_row = next((row for row in rows if row["path"] == "/assenze"), None)
        self.assertIsNotNone(target_row)
        assert target_row is not None
        self.assertTrue(target_row["selected_role_visible"])
        self.assertTrue(target_row["legacy_buttons"])
        self.assertTrue(target_row["legacy_buttons"][0]["selected_role_allowed"])
        self.assertTrue(target_row["canonical_permissions"])
        self.assertEqual(target_row["canonical_permissions"][0]["permission_code"], "assets.work_orders.manage")
        self.assertTrue(target_row["canonical_permissions"][0]["selected_role_grant_exists"])
        self.assertTrue(target_row["canonical_permissions"][0]["selected_role_grant_enabled"])

    def test_map_page_keeps_legacy_rows_for_disabled_role_to_allow_live_enable(self):
        Ruolo.objects.create(id=3, nome="qa")
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(
                reverse("admin_portale:mappa_permessi_navigazione"),
                {"legacy_role_id": "3"},
            )

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        target_row = next((row for row in rows if row["path"] == "/assenze"), None)
        self.assertIsNotNone(target_row)
        assert target_row is not None
        self.assertFalse(target_row["selected_role_visible"])
        self.assertTrue(target_row["legacy_buttons"])
        self.assertFalse(bool(target_row["legacy_buttons"][0]["selected_role_allowed"]))

    def test_api_acl_v2_role_grant_toggle_updates_existing_grant(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:api_acl_v2_role_grant_toggle"),
                data=json.dumps(
                    {
                        "ruolo_id": 2,
                        "permission_code": "assets.work_orders.manage",
                        "value": False,
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["permission_code"], "assets.work_orders.manage")
        self.assertFalse(payload["enabled"])
        self.assertTrue(
            RolePermissionGrant.objects.filter(
                legacy_role_id=2,
                permission_id="assets.work_orders.manage",
                enabled=False,
            ).exists()
        )

    def test_api_acl_v2_role_grant_toggle_creates_missing_grant(self):
        Ruolo.objects.create(id=3, nome="qa")
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:api_acl_v2_role_grant_toggle"),
                data=json.dumps(
                    {
                        "ruolo_id": 3,
                        "permission_code": "assets.work_orders.manage",
                        "value": True,
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["created"])
        self.assertTrue(payload["enabled"])
        self.assertTrue(
            RolePermissionGrant.objects.filter(
                legacy_role_id=3,
                permission_id="assets.work_orders.manage",
                enabled=True,
            ).exists()
        )


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
)
class AdminPortaleSimpleAccessTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        _ensure_ruoli_table()
        _ensure_pulsanti_table()
        _ensure_permessi_table()
        _clear_acl_navigation_seed_tables()

        self.admin_user = User.objects.create_superuser(
            username="admin-portale-simple-access",
            email="admin.simple.access@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Simple Access",
            email="admin.simple.access@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        Ruolo.objects.create(id=1, nome="admin")
        Ruolo.objects.create(id=2, nome="operatore")

        Pulsante.objects.create(
            codice="dashboard_home",
            nome_visibile="Dashboard",
            icona="home",
            modulo="dashboard",
            url="/dashboard",
        )
        PermissionDefinition.objects.create(
            code="dashboard.home.view",
            label="Dashboard Home",
            module="dashboard",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            permission_id="dashboard.home.view",
            route_name="dashboard_home",
            path_pattern="/dashboard",
            source_app="dashboard",
            is_active=True,
        )
        self.nav_item = NavigationItem.objects.create(
            code="dashboard-simple",
            label="Dashboard",
            section="topbar",
            route_name="dashboard_home",
            order=10,
            is_visible=True,
            is_enabled=True,
        )

    def _as_admin_get(self, url, params=None):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            return self.client.get(url, params or {})

    def _as_admin_post(self, url, data):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            return self.client.post(url, data)

    def test_accessi_route_points_to_simple_page(self):
        response = self._as_admin_get(
            reverse("admin_portale:accessi"),
            {"ruolo_id": "2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Accessi Semplificati", html=False)
        self.assertContains(response, "grant canonici", html=False)
        self.assertContains(response, 'name="simple_modules"', html=False)

    def test_accessi_semplice_post_enables_canonical_grants_only(self):
        response = self._as_admin_post(
            reverse("admin_portale:accessi"),
            {
                "ruolo_id": "2",
                "simple_modules": ["dashboard"],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Permesso.objects.filter(ruolo_id=2, modulo="dashboard").exists())
        self.assertTrue(
            RolePermissionGrant.objects.filter(
                legacy_role_id=2,
                permission_id="dashboard.home.view",
                enabled=True,
            ).exists()
        )
        self.assertFalse(NavigationRoleAccess.objects.filter(item=self.nav_item, legacy_role_id=2).exists())

    def test_accessi_semplice_post_can_disable_canonical_grants_without_touching_legacy(self):
        RolePermissionGrant.objects.create(
            legacy_role_id=2,
            permission_id="dashboard.home.view",
            enabled=True,
        )

        response = self._as_admin_post(
            reverse("admin_portale:accessi"),
            {
                "ruolo_id": "2",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            RolePermissionGrant.objects.filter(
                legacy_role_id=2,
                permission_id="dashboard.home.view",
                enabled=False,
            ).exists()
        )
        self.assertFalse(Permesso.objects.filter(ruolo_id=2, modulo="dashboard").exists())

    def test_permessi_bulk_accepts_wizard_rows_payload(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:api_permessi_bulk"),
                data=json.dumps(
                    {
                        "ruolo_id": 2,
                        "mode": "update",
                        "rows": [
                            {
                                "modulo": "dashboard",
                                "azione": "dashboard_home",
                                "field": "can_view",
                                "value": 1,
                                "can_view": 1,
                            }
                        ],
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        perm = Permesso.objects.get(ruolo_id=2, modulo="dashboard", azione="dashboard_home")
        self.assertEqual(perm.can_view, 1)
        self.assertEqual(perm.consentito, 1)

    def test_nav_user_override_toggle_is_hide_only(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                reverse("admin_portale:api_nav_user_override_toggle", args=[704]),
                data=json.dumps({"item_id": self.nav_item.id, "state": "show"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])


class AdminPortaleFormSecurityTests(TestCase):
    """Testa la validazione di sicurezza nei form admin."""

    def test_pulsante_url_blocks_javascript_scheme(self):
        form = PulsanteForm({"codice": "test", "modulo": "test", "url": "javascript:alert(1)"})
        self.assertFalse(form.is_valid())
        self.assertIn("url", form.errors)

    def test_pulsante_url_blocks_data_scheme(self):
        form = PulsanteForm({"codice": "test", "modulo": "test", "url": "data:text/html,<h1>xss</h1>"})
        self.assertFalse(form.is_valid())
        self.assertIn("url", form.errors)

    def test_pulsante_url_blocks_vbscript_scheme(self):
        form = PulsanteForm({"codice": "test", "modulo": "test", "url": "VBScript:msgbox(1)"})
        self.assertFalse(form.is_valid())
        self.assertIn("url", form.errors)

    def test_pulsante_url_allows_route_prefix(self):
        form = PulsanteForm({"codice": "test", "modulo": "test", "url": "route:dashboard_home"})
        self.assertTrue(form.is_valid())

    def test_pulsante_url_allows_local_path(self):
        form = PulsanteForm({"codice": "test", "modulo": "test", "url": "/assenze/"})
        self.assertTrue(form.is_valid())


    def test_pulsante_url_prepends_slash_to_bare_path(self):
        form = PulsanteForm({"codice": "test", "modulo": "test", "url": "assenze"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["url"], "/assenze")

    def test_utente_create_form_rejects_short_password(self):
        form = UtenteCreateForm({
            "nome": "Mario Rossi",
            "ad_managed": False,
            "password_iniziale": "short",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("password_iniziale", form.errors)

    def test_utente_create_form_accepts_long_enough_password(self):
        form = UtenteCreateForm({
            "nome": "Mario Rossi",
            "ad_managed": False,
            "password_iniziale": "sicurissima123",
        })
        self.assertTrue(form.is_valid())

    def test_utente_create_form_ad_managed_skips_password_validation(self):
        form = UtenteCreateForm({
            "nome": "Mario Rossi",
            "ad_managed": True,
            "password_iniziale": "",
        })
        self.assertTrue(form.is_valid())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleDecoratorJsonResponseTests(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")

        self.user = User.objects.create_user(
            username="admin-portale-json-check",
            email="json.check@test.local",
            password="pass12345",
        )
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.non_admin_legacy = UtenteLegacy.objects.create(
            nome="Operatore JSON",
            email="json.check@test.local",
            password="*AD_MANAGED*",
            ruolo="operatore",
            ruolo_id=2,
            attivo=True,
            deve_cambiare_password=False,
        )

    def test_api_returns_json_for_unauthenticated_requests(self):
        response = self.client.post(
            reverse("admin_portale:api_ruolo_create"),
            {"nome": "Ruolo Test"},
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "unauthenticated")
        self.assertIn(reverse("login"), payload["login_url"])

    def test_api_returns_json_for_forbidden_non_admin_requests(self):
        self.client.force_login(self.user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.non_admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=False,
        ):
            response = self.client.post(
                reverse("admin_portale:api_ruolo_create"),
                {"nome": "Ruolo Test"},
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "forbidden")
        self.assertEqual(payload["error"], "Permessi insufficienti.")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleUtentiListLayoutTests(TestCase):
    def setUp(self):
        _ensure_ruoli_table()
        _ensure_utenti_table()
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute("DELETE FROM utenti")
            cursor.execute("DELETE FROM ruoli")

        _legacy_upsert_by_id("ruoli", 1, {"nome": "admin"})
        _legacy_upsert_by_id("ruoli", 6, {"nome": "utente"})

        self.admin_user = User.objects.create_superuser(
            username="admin-users-layout",
            email="admin.users.layout@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Users Layout",
            email="admin.users.layout@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_legacy = UtenteLegacy.objects.create(
            nome="Target Layout",
            email="target.layout@test.local",
            password="*AD_MANAGED*",
            ruolo="utente",
            ruolo_id=6,
            attivo=True,
            deve_cambiare_password=False,
        )

    def test_utenti_list_renders_fullpage_workspace(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(reverse("admin_portale:utenti_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin-users-fullpage", html=False)
        self.assertContains(response, 'class="users-fullpage-shell"', html=False)
        self.assertContains(response, 'class="users-create-panel"', html=False)
        self.assertContains(response, 'class="users-table-scroll"', html=False)
        self.assertContains(response, "Target Layout", html=False)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleOpenRedirectTests(TestCase):
    """Testa che i parametri next/HTTP_REFERER non permettano redirect verso domini esterni."""

    def setUp(self):
        _ensure_utenti_table()
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-redirect-sec",
            email="admin.redirect@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Redirect",
            email="admin.redirect@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_legacy = UtenteLegacy.objects.create(
            nome="Target Utente",
            email="target.redirect@test.local",
            password="*AD_MANAGED*",
            ruolo="utente",
            ruolo_id=6,
            attivo=True,
            deve_cambiare_password=False,
        )

    def _do_post(self, url, data):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin", return_value=True
        ):
            return self.client.post(url, data)

    def test_toggle_active_rejects_external_next(self):
        response = self._do_post(
            reverse("admin_portale:utente_toggle_active", args=[self.target_legacy.id]),
            {"next": "https://evil.example.com/steal"},
        )
        self.assertEqual(response.status_code, 302)
        # deve redirect a utenti_list, NON a evil.example.com
        self.assertNotIn("evil.example.com", response["Location"])

    def test_toggle_active_accepts_local_next(self):
        response = self._do_post(
            reverse("admin_portale:utente_toggle_active", args=[self.target_legacy.id]),
            {"next": reverse("admin_portale:utenti_list")},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin-portale/utenti/", response["Location"])

    def test_force_change_password_rejects_external_next(self):
        response = self._do_post(
            reverse("admin_portale:utente_force_change_password", args=[self.target_legacy.id]),
            {"next": "http://attacker.net/phishing"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("attacker.net", response["Location"])

    def test_quick_role_rejects_external_next(self):
        response = self._do_post(
            reverse("admin_portale:utente_quick_role", args=[self.target_legacy.id]),
            {
                f"quick_ruolo_id_{self.target_legacy.id}": "6",
                "next": "//evil.com/path",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.com", response["Location"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleAuditLogTests(TestCase):
    """Testa che le operazioni critiche vengano registrate nell'audit log."""

    def setUp(self):
        _ensure_utenti_table()
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-audit-sec",
            email="admin.audit@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Audit",
            email="admin.audit@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.target_legacy = UtenteLegacy.objects.create(
            nome="Target Audit",
            email="target.audit@test.local",
            password="*AD_MANAGED*",
            ruolo="utente",
            ruolo_id=6,
            attivo=True,
            deve_cambiare_password=False,
        )

    def _do_post(self, url, data, content_type=None):
        self.client.force_login(self.admin_user)
        kwargs = {}
        if content_type:
            kwargs["content_type"] = content_type
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin", return_value=True
        ):
            if content_type:
                return self.client.post(url, data, content_type=content_type)
            return self.client.post(url, data)

    def test_utente_toggle_active_is_audited(self):
        from core.models import AuditLog

        count_before = AuditLog.objects.filter(azione="utente_toggle_active").count()
        self._do_post(
            reverse("admin_portale:utente_toggle_active", args=[self.target_legacy.id]),
            {"next": reverse("admin_portale:utenti_list")},
        )
        self.assertEqual(
            AuditLog.objects.filter(azione="utente_toggle_active").count(),
            count_before + 1,
        )

    def test_utenti_bulk_activate_is_audited(self):
        from core.models import AuditLog

        count_before = AuditLog.objects.filter(azione="utenti_bulk_activate").count()
        self._do_post(
            reverse("admin_portale:utenti_bulk_action"),
            {"user_ids": [str(self.target_legacy.id)], "bulk_mode": "activate"},
        )
        self.assertEqual(
            AuditLog.objects.filter(azione="utenti_bulk_activate").count(),
            count_before + 1,
        )

    def test_utenti_bulk_deactivate_is_audited(self):
        from core.models import AuditLog

        count_before = AuditLog.objects.filter(azione="utenti_bulk_deactivate").count()
        self._do_post(
            reverse("admin_portale:utenti_bulk_action"),
            {"user_ids": [str(self.target_legacy.id)], "bulk_mode": "deactivate"},
        )
        self.assertEqual(
            AuditLog.objects.filter(azione="utenti_bulk_deactivate").count(),
            count_before + 1,
        )

    def test_utenti_bulk_force_pwd_is_audited(self):
        from core.models import AuditLog

        count_before = AuditLog.objects.filter(azione="utenti_bulk_force_pwd").count()
        self._do_post(
            reverse("admin_portale:utenti_bulk_action"),
            {"user_ids": [str(self.target_legacy.id)], "bulk_mode": "force_pwd"},
        )
        self.assertEqual(
            AuditLog.objects.filter(azione="utenti_bulk_force_pwd").count(),
            count_before + 1,
        )

    def test_utente_delete_is_audited(self):
        from core.models import AuditLog

        tid = self.target_legacy.id
        count_before = AuditLog.objects.filter(azione="utente_delete").count()
        self._do_post(
            reverse("admin_portale:utente_delete", args=[tid]),
            {"next": reverse("admin_portale:utenti_list")},
        )
        self.assertEqual(
            AuditLog.objects.filter(azione="utente_delete").count(),
            count_before + 1,
        )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleAclCanonicoTests(TestCase):
    def setUp(self):
        _ensure_ruoli_table()
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")
            cursor.execute("DELETE FROM ruoli")
        _legacy_upsert_by_id("ruoli", 1, {"nome": "admin"})
        _legacy_upsert_by_id("ruoli", 6, {"nome": "utente"})

        self.admin_user = User.objects.create_superuser(
            username="admin-acl-canonico",
            email="admin.acl.canonico@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin ACL Canonico",
            email="admin.acl.canonico@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        self.url = reverse("admin_portale:acl_canonico")

    def test_can_create_permission_definition_from_acl_canonico_page(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                self.url,
                {
                    "action": "permission_upsert",
                    "code": "core.profilo.view",
                    "label": "Profilo",
                    "module": "core",
                    "description": "Permesso test",
                    "is_active": "1",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(PermissionDefinition.objects.filter(code="core.profilo.view").exists())

    def test_can_save_role_grants_and_user_override(self):
        PermissionDefinition.objects.create(
            code="core.profilo.view",
            label="Profilo",
            module="core",
            is_active=True,
        )
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            grant_response = self.client.post(
                self.url,
                {
                    "action": "role_grants_save",
                    "role_id": "6",
                    "grants": ["core.profilo.view"],
                },
                follow=True,
            )
            override_response = self.client.post(
                self.url,
                {
                    "action": "user_override_upsert",
                    "legacy_user_id": "999",
                    "permission_code": "core.profilo.view",
                    "enabled": "0",
                    "note": "Test deny",
                },
                follow=True,
            )

        self.assertEqual(grant_response.status_code, 200)
        self.assertEqual(override_response.status_code, 200)
        self.assertTrue(
            RolePermissionGrant.objects.filter(legacy_role_id=6, permission_id="core.profilo.view", enabled=True).exists()
        )
        self.assertTrue(
            UserPermissionGrant.objects.filter(legacy_user_id=999, permission_id="core.profilo.view", enabled=False).exists()
        )

    def test_can_create_binding_from_acl_canonico_page(self):
        PermissionDefinition.objects.create(
            code="core.profilo.view",
            label="Profilo",
            module="core",
            is_active=True,
        )
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                self.url,
                {
                    "action": "binding_upsert",
                    "permission_code": "core.profilo.view",
                    "route_name": "profilo",
                    "path_pattern": "",
                    "match_strategy": "exact",
                    "source_app": "core",
                    "priority": "100",
                    "is_active": "1",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        binding = RoutePermissionBinding.objects.get(route_name="profilo", path_pattern="")
        self.assertEqual(binding.permission_id, "core.profilo.view")

    def test_rejects_invalid_permission_code_format(self):
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.post(
                self.url,
                {
                    "action": "permission_upsert",
                    "code": "INVALID-CODE",
                    "label": "Test",
                    "module": "core",
                    "is_active": "1",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PermissionDefinition.objects.filter(code__icontains="invalid-code").exists())
        self.assertContains(response, "Formato richiesto", html=False)

    def test_shows_warning_for_binding_without_any_enabled_role_grant(self):
        PermissionDefinition.objects.create(
            code="core.diagnostica.view",
            label="Diagnostica",
            module="core",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="admin_portale:acl_diagnostica",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="core.diagnostica.view",
            source_app="admin_portale",
            is_active=True,
        )
        self.client.force_login(self.admin_user)

        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url, {"tab": "bindings", "role_id": "6"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NO ROLE GRANT", html=False)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleAclRouteCoverageTests(TestCase):
    def setUp(self):
        _ensure_ruoli_table()
        _ensure_utenti_table()
        _ensure_pulsanti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")
            cursor.execute("DELETE FROM ruoli")
            cursor.execute("DELETE FROM pulsanti")
        _legacy_upsert_by_id("ruoli", 1, {"nome": "admin"})
        _legacy_upsert_by_id("ruoli", 6, {"nome": "utente"})

        self.admin_user = User.objects.create_superuser(
            username="admin-acl-route-coverage",
            email="admin.acl.route.coverage@test.local",
            password="pass12345",
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin ACL Coverage",
            email="admin.acl.route.coverage@test.local",
            password="*AD_MANAGED*",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )
        PermissionDefinition.objects.create(
            code="admin_portale.acl_diagnostica.view",
            label="ACL diagnostica",
            module="admin_portale",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="admin_portale:acl_diagnostica",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="admin_portale.acl_diagnostica.view",
            source_app="admin_portale",
            is_active=True,
        )
        Pulsante.objects.create(
            codice="legacy_map",
            nome_visibile="Mappa legacy",
            icona="map",
            modulo="admin_portale",
            url="route:admin_portale:mappa_permessi_navigazione",
        )
        LegacyRedirect.objects.create(
            legacy_path="/legacy/schema-dati",
            target_route_name="admin_portale:schema_dati",
            is_enabled=True,
        )
        self.url = reverse("admin_portale:acl_route_coverage")

    def test_route_coverage_page_classifies_canonical_legacy_and_redirect(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        by_route = {row["route_name"]: row for row in rows}
        self.assertEqual(by_route["admin_portale:acl_diagnostica"]["status"], "CANONICAL_BOUND")
        self.assertEqual(by_route["admin_portale:mappa_permessi_navigazione"]["status"], "LEGACY_FALLBACK")
        self.assertEqual(by_route["admin_portale:schema_dati"]["status"], "REDIRECT_ONLY")

    def test_route_coverage_supports_csv_export(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url, {"export": "csv", "status": "ALL"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment; filename=\"acl_route_coverage.csv\"", response["Content-Disposition"])

    def test_route_coverage_flags_ambiguous_canonical_bindings(self):
        PermissionDefinition.objects.create(
            code="admin_portale.acl.diagnostica.duplicate",
            label="ACL duplicate",
            module="admin_portale",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="admin_portale:acl_diagnostica",
            path_pattern="/admin-portale/acl-diagnostica/duplicato",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="admin_portale.acl.diagnostica.duplicate",
            source_app="admin_portale",
            is_active=True,
        )
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url, {"q": "admin_portale:acl_diagnostica"})

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        row = next(item for item in rows if item["route_name"] == "admin_portale:acl_diagnostica")
        self.assertIn("AMBIGUOUS_CANONICAL_BINDING", row["warnings"])

    def test_route_coverage_uses_effective_binding_for_permission_and_missing_grant(self):
        PermissionDefinition.objects.create(
            code="automazioni.regole.view",
            label="Automazioni regole",
            module="automazioni",
            is_active=True,
        )
        PermissionDefinition.objects.create(
            code="automazioni.converti_power_automate.view",
            label="Automazioni converti power automate",
            module="automazioni",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="",
            path_pattern="/admin-portale/automazioni/regole",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            permission_id="automazioni.regole.view",
            source_app="automazioni",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="",
            path_pattern="/admin-portale/automazioni/regole/converti-power-automate",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            permission_id="automazioni.converti_power_automate.view",
            source_app="automazioni",
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=1,
            permission_id="automazioni.converti_power_automate.view",
            enabled=True,
        )
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url, {"q": "admin_portale:automazioni_rule_power_automate_convert"})

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        row = next(item for item in rows if item["route_name"] == "admin_portale:automazioni_rule_power_automate_convert")
        self.assertEqual(row["status"], "CANONICAL_BOUND")
        self.assertEqual(row["canonical_permissions"], ["automazioni.converti_power_automate.view"])
        self.assertEqual(row["canonical_binding_count"], 1)
        self.assertNotIn("BINDING_WITHOUT_ENABLED_ROLE_GRANT", row["warnings"])

    def test_route_coverage_marks_admin_bypass_routes_without_missing_grant_warning(self):
        PermissionDefinition.objects.create(
            code="automazioni.converti_power_automate.admin_only",
            label="Automazioni converti power automate admin only",
            module="automazioni",
            is_active=True,
        )
        RoutePermissionBinding.objects.filter(
            route_name="automazioni:automazioni_rule_power_automate_convert",
        ).delete()
        RoutePermissionBinding.objects.create(
            route_name="automazioni:automazioni_rule_power_automate_convert",
            path_pattern="/automazioni/regole/converti-power-automate",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="automazioni.converti_power_automate.admin_only",
            source_app="automazioni",
            is_active=True,
        )
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url, {"q": "automazioni:automazioni_rule_power_automate_convert"})

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        row = next(item for item in rows if item["route_name"] == "automazioni:automazioni_rule_power_automate_convert")
        self.assertEqual(row["status"], "CANONICAL_BOUND")
        self.assertTrue(row["admin_bypass"])
        self.assertFalse(row["canonical_missing_grant"])
        self.assertNotIn("BINDING_WITHOUT_ENABLED_ROLE_GRANT", row["warnings"])

    def test_route_coverage_marks_acl_shared_profile_route_as_excluded(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url, {"q": "profilo"})

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        row = next(item for item in rows if item["route_name"] == "profilo")
        self.assertEqual(row["status"], "COMING_SOON_EXCLUDED")
        self.assertEqual(row["excluded_reason"], "AUTH_SHARED_PATH")

    def test_route_coverage_marks_monitoring_problem_report_exempt_without_trailing_slash(self):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url, {"q": "monitoring:report_problem"})

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        row = next(item for item in rows if item["route_name"] == "monitoring:report_problem")
        self.assertEqual(row["status"], "COMING_SOON_EXCLUDED")
        self.assertEqual(row["excluded_reason"], "EXEMPT_MIDDLEWARE_PATH")

    def test_route_coverage_uses_gate_target_path_for_anomalie_api_routes(self):
        PermissionDefinition.objects.create(
            code="anomalie.gestione.view",
            label="Anomalie gestione",
            module="anomalie",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="",
            path_pattern="/gestione-anomalie",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            permission_id="anomalie.gestione.view",
            source_app="anomalie",
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=1,
            permission_id="anomalie.gestione.view",
            enabled=True,
        )
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin",
            return_value=True,
        ):
            response = self.client.get(self.url, {"q": "api_anomalie_db_ordini"})

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        row = next(item for item in rows if item["route_name"] == "api_anomalie_db_ordini")
        self.assertEqual(row["status"], "CANONICAL_BOUND")
        self.assertEqual(row["canonical_permissions"], ["anomalie.gestione.view"])
        self.assertEqual(row["canonical_binding_count"], 1)
        self.assertFalse(row["canonical_missing_grant"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GuestPortalSsoHardeningTests(TestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser(
            username="guestportal-admin",
            email="guestportal-admin@example.com",
            password="secret123",
        )
        self.admin_legacy = SimpleNamespace(id=1, ruolo="admin", ruolo_id=1)

    def test_guestportal_view_is_manual_only_and_does_not_expose_password_context(self):
        self.client.force_login(self.admin_user)
        with (
            patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy),
            patch("admin_portale.decorators.is_legacy_admin", return_value=True),
            patch(
                "admin_portale.views._read_guestportal_config",
                return_value={
                    "url": "https://guest.example/login",
                    "field_username": "username",
                    "field_password": "password",
                    "username_format": "alias",
                },
            ),
            patch("admin_portale.views._build_guestportal_username", return_value="guest.user"),
        ):
            response = self.client.get(reverse("admin_portale:guestportal_sso"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("gp_password", response.context)
        self.assertNotIn("gp_autosubmit", response.context)
        self.assertNotContains(response, "gp-auto-form")


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminPortalePermessiRedirectTests(TestCase):
    """Fase 3: la vecchia UI permessi legacy reindirizza alla schermata canonica."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="perm-redirect-admin", email="rdr@test.local", password="pass12345",
        )
        self.client.force_login(self.admin)

    def test_permessi_redirects_to_acl_canonico_by_default(self):
        resp = self.client.get(reverse("admin_portale:permessi"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("admin_portale:acl_canonico"), resp.url)

    def test_permessi_preserves_role_and_user_params(self):
        resp = self.client.get(
            reverse("admin_portale:permessi"), {"ruolo_id": "6", "user_id": "143"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("role_id=6", resp.url)
        self.assertIn("selected_user_id=143", resp.url)

    @override_settings(ACL_LEGACY_PERMESSI_UI_ENABLED=True)
    def test_legacy_ui_still_reachable_when_flag_enabled(self):
        _ensure_pulsanti_table()
        _ensure_permessi_table()
        resp = self.client.get(reverse("admin_portale:permessi"))
        self.assertEqual(resp.status_code, 200)


class AdminPortaleLegacyWriteGuardTests(TestCase):
    """Gli endpoint di scrittura permessi LEGACY devono rifiutare i moduli canonici."""

    def setUp(self):
        _ensure_pulsanti_table()
        _ensure_permessi_table()
        _clear_acl_navigation_seed_tables()

        self.admin = User.objects.create_superuser(
            username="acl-guard-admin", email="guard@test.local", password="pass12345",
        )
        self.client.force_login(self.admin)

        # Modulo canonico: ha un RoutePermissionBinding attivo con source_app="tickets".
        self.perm = PermissionDefinition.objects.create(
            code="legacy.tickets.tickets_dashboard", label="Tickets dashboard",
            module="tickets", is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="", path_pattern="/tickets",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            permission_id=self.perm.code, source_app="tickets",
            priority=100, is_active=True,
        )
        # Pulsante legacy del modulo canonico (per il modulo-set).
        Pulsante.objects.create(
            codice="tickets_dashboard", nome_visibile="Dashboard ticket",
            modulo="tickets", url="/tickets",
        )
        # Modulo NON canonico (nessun binding): scrittura legacy ancora consentita.
        Pulsante.objects.create(
            codice="legacy_only_action", nome_visibile="Azione legacy",
            modulo="moduolegacy", url="/moduolegacy",
        )

    def test_modulo_set_blocked_on_canonical_module(self):
        resp = self.client.post(
            reverse("admin_portale:api_permessi_modulo_set"),
            data=json.dumps({"ruolo_id": 6, "modulo": "tickets", "can_view": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.json().get("ok"))
        # Nessun permesso legacy scritto per il modulo canonico.
        self.assertFalse(Permesso.objects.filter(modulo__iexact="tickets").exists())

    def test_toggle_blocked_on_canonical_module(self):
        resp = self.client.post(
            reverse("admin_portale:api_permessi_toggle"),
            data=json.dumps({
                "ruolo_id": 6, "modulo": "tickets",
                "azione": "tickets_dashboard", "field": "can_view", "value": 1,
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 409)

    def test_modulo_set_allowed_on_non_canonical_module(self):
        resp = self.client.post(
            reverse("admin_portale:api_permessi_modulo_set"),
            data=json.dumps({"ruolo_id": 6, "modulo": "moduolegacy", "can_view": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        self.assertTrue(Permesso.objects.filter(modulo__iexact="moduolegacy").exists())

    def test_bulk_set_all_skips_canonical_modules(self):
        resp = self.client.post(
            reverse("admin_portale:api_permessi_bulk"),
            data=json.dumps({
                "ruolo_id": 6, "mode": "set_all", "field": "can_view", "value": 1,
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("ok"))
        self.assertGreaterEqual(body.get("skipped_canonical", 0), 1)
        # Il modulo canonico non riceve permessi legacy; quello legacy sì.
        self.assertFalse(Permesso.objects.filter(modulo__iexact="tickets").exists())
        self.assertTrue(Permesso.objects.filter(modulo__iexact="moduolegacy").exists())

    def test_sync_legacy_grants_creates_grant_from_legacy_permission(self):
        """Il comando travasa un permesso legacy in un grant canonico anche per route già bindate."""
        from django.core.management import call_command
        from io import StringIO

        # Ruolo 6 ha il permesso legacy su tickets_dashboard, ma NESSUN grant canonico.
        Permesso.objects.create(
            modulo="tickets", azione="tickets_dashboard", ruolo_id=6,
            can_view=1, consentito=1,
        )
        self.assertFalse(
            RolePermissionGrant.objects.filter(
                legacy_role_id=6, permission_id=self.perm.code
            ).exists()
        )
        out = StringIO()
        call_command("acl_sync_legacy_grants", "--apply", stdout=out)
        grant = RolePermissionGrant.objects.filter(
            legacy_role_id=6, permission_id=self.perm.code
        ).first()
        self.assertIsNotNone(grant)
        self.assertTrue(grant.enabled)

