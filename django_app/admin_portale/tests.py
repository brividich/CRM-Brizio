from __future__ import annotations

import configparser
import json
import tempfile
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from admin_portale.forms import PulsanteForm, UtenteCreateForm
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import (
    AnagraficaRisposta,
    AnagraficaVoce,
    ChecklistEsecuzione,
    EmployeeBoardConfig,
    Notifica,
    OptioneConfig,
    Profile,
    UserDashboardConfig,
    UserDashboardLayout,
    UserExtraInfo,
    UserModuleVisibility,
    UserPermissionOverride,
)

User = get_user_model()


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

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.ini"
            config_path.write_text("[ACTIVE_DIRECTORY]\nserver = ldap://old.local\nenabled = false\n", encoding="utf-8")

            with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
                "admin_portale.decorators.is_legacy_admin",
                return_value=True,
            ), patch("admin_portale.views._config_ini_path", return_value=config_path):
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

            parser = configparser.ConfigParser()
            parser.read(config_path, encoding="utf-8")

            self.assertEqual(parser.get("ACTIVE_DIRECTORY", "enabled"), "true")
            self.assertEqual(parser.get("ACTIVE_DIRECTORY", "server"), "ldap://dc1.example.local")
            self.assertEqual(parser.get("ACTIVE_DIRECTORY", "domain"), "EXAMPLE")
            self.assertEqual(parser.get("ACTIVE_DIRECTORY", "upn_suffix"), "@example.local")
            self.assertEqual(parser.get("ACTIVE_DIRECTORY", "timeout"), "8")
            self.assertEqual(parser.get("ACTIVE_DIRECTORY", "base_dn"), "DC=EXAMPLE,DC=LOCAL")
            self.assertEqual(parser.get("ACTIVE_DIRECTORY", "user_filter"), "(&(objectCategory=person)(objectClass=user))")
            self.assertEqual(parser.get("ACTIVE_DIRECTORY", "group_allowlist"), "EMPLOYEES,ADMINS")
            self.assertEqual(parser.get("ACTIVE_DIRECTORY", "sync_page_size"), "750")


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


# ─────────────────────────────────────────────────────────────────────────────
# Security tests
# ─────────────────────────────────────────────────────────────────────────────


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
