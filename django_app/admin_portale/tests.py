from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import ANY, MagicMock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from admin_portale.forms import PulsanteForm, UtenteCreateForm
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import AnagraficaDipendente, Permesso, Pulsante, Ruolo, UtenteLegacy
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
    UserDashboardConfig,
    UserDashboardLayout,
    UserExtraInfo,
    UserModuleVisibility,
    UserOnboarding,
    UserPermissionGrant,
    UserPermissionOverride,
)

User = get_user_model()


def _make_workspace_tempdir(prefix: str) -> Path:
    root = Path.cwd() / ".tmp_tests"
    root.mkdir(exist_ok=True)
    target = root / f"{prefix}{uuid4().hex}"
    target.mkdir(parents=True, exist_ok=False)
    return target


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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AdminPortaleCaporepartoRoleSyncTests(TestCase):
    def setUp(self):
        _ensure_ruoli_table()
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")
            cursor.execute("DELETE FROM ruoli")
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (1, 'admin')")
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (2, 'caporeparto')")
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (6, 'utente')")

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
        self.assertIn("OVERRIDE", diag["badges"])
        self.assertIn("LEGACY", diag["badges"])
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
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (1, 'admin')")
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (6, 'utente')")

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
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (1, 'admin')")
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (6, 'utente')")

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
            code="admin_portale.acl.prefix.view",
            label="ACL prefix",
            module="admin_portale",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="",
            path_pattern="/admin-portale/acl-diagnostica",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            permission_id="admin_portale.acl.prefix.view",
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

