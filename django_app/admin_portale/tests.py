from __future__ import annotations

from unittest.mock import ANY, MagicMock, patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

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
