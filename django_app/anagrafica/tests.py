from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_anagrafica import cleanup_duplicate_anagrafica_rows, ensure_anagrafica_schema
from assets.models import Asset, AssetCategory, SoftwareLicense

User = get_user_model()


def _ensure_anagrafica_table() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute("DROP TABLE IF EXISTS anagrafica_dipendenti")
            cursor.execute(
                """
                CREATE TABLE anagrafica_dipendenti (
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
                IF OBJECT_ID('anagrafica_dipendenti', 'U') IS NOT NULL
                    DROP TABLE anagrafica_dipendenti
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
    ensure_anagrafica_schema()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnagraficaDipendentiViewTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
        self.user = User.objects.create_superuser(
            username="anagrafica-view",
            email="anagrafica-view@example.com",
            password="pass12345",
        )

    def test_can_create_inactive_employee_without_account(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("anagrafica:dipendenti_list"),
            {
                "nome": "Mario",
                "cognome": "Rossi",
                "aliasusername": "m.rossi",
                "matricola": "MR001",
                "reparto": "Produzione",
                "mansione": "Saldatore",
                "ruolo": "Operaio",
                "email_notifica": "m.rossi@example.com",
            },
        )

        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT nome, cognome, attivo, utente_id
                FROM anagrafica_dipendenti
                WHERE aliasusername = %s
                """,
                ["m.rossi"],
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Mario")
        self.assertEqual(row[1], "Rossi")
        self.assertEqual(int(row[2] or 0), 0)
        self.assertIsNone(row[3])

    def test_create_employee_defaults_notification_email_to_account_email(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("anagrafica:dipendenti_list"),
            {
                "nome": "Federico",
                "cognome": "Bernini",
                "aliasusername": "f.bernini",
                "email": "federicobernini3@gmail.com",
                "attivo": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT email, email_notifica
                FROM anagrafica_dipendenti
                WHERE aliasusername = %s
                """,
                ["f.bernini"],
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "federicobernini3@gmail.com")
        self.assertEqual(row[1], "federicobernini3@gmail.com")

    def test_detail_falls_back_to_account_email_when_notification_email_is_missing(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, email, email_notifica, attivo)
                VALUES
                    (%s, %s, %s, %s, %s, %s)
                """,
                ["f.bernini", "Federico", "Bernini", "federicobernini3@gmail.com", "", 1],
            )
            cursor.execute(
                """
                SELECT id
                FROM anagrafica_dipendenti
                WHERE aliasusername = %s
                """,
                ["f.bernini"],
            )
            row = cursor.fetchone()

        self.client.force_login(self.user)
        response = self.client.get(reverse("anagrafica:dipendente_detail", args=[int(row[0])]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dip"]["email_notifica"], "federicobernini3@gmail.com")
        self.assertContains(response, "federicobernini3@gmail.com")

    def test_detail_shows_assigned_software_licenses(self):
        asset_category = AssetCategory.objects.create(
            code="anagrafica-license",
            label="Categoria Licenze",
            base_asset_type=Asset.TYPE_PC,
        )
        asset = Asset.objects.create(
            name="Laptop marketing",
            asset_type=Asset.TYPE_PC,
            asset_category=asset_category,
            reparto="MKT",
            source_key="anagrafica-asset-license",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, email, email_notifica, attivo)
                VALUES
                    (%s, %s, %s, %s, %s, %s)
                """,
                ["l.gallo", "Lara", "Gallo", "l.gallo@example.com", "l.gallo@example.com", 1],
            )
            cursor.execute(
                """
                SELECT id
                FROM anagrafica_dipendenti
                WHERE aliasusername = %s
                """,
                ["l.gallo"],
            )
            row = cursor.fetchone()

        SoftwareLicense.objects.create(
            category=SoftwareLicense.CATEGORY_OFFICE,
            vendor="Microsoft",
            product_name="Office 365",
            assigned_anagrafica_id=int(row[0]),
            assigned_to_display="Gallo Lara",
            asset=asset,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("anagrafica:dipendente_detail", args=[int(row[0])]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Office 365")

    def test_list_deduplicates_uppercase_legacy_rows(self):
        with connection.cursor() as cursor:
            vendor = connection.vendor
            if vendor == "sqlite":
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, matricola, ruolo, email)
                    VALUES
                        (NULL, 'DERYA', 'AKSOY', 'INT010', 'Operatore Aggiustaggio', 'legacy@test.local')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, email)
                    VALUES
                        ('d.aksoy', 'Derya', 'Aksoy', 'd.aksoy@example.local')
                    """
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, matricola, ruolo, email)
                    VALUES
                        (NULL, 'DERYA', 'AKSOY', 'INT010', 'Operatore Aggiustaggio', 'legacy@test.local')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, email)
                    VALUES
                        ('d.aksoy', 'Derya', 'Aksoy', 'd.aksoy@example.local')
                    """
                )

        self.client.force_login(self.user)
        response = self.client.get(reverse("anagrafica:dipendenti_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aksoy Derya", count=1)
        self.assertNotContains(response, "AKSOY DERYA")

    def test_cleanup_duplicate_rows_merges_and_deletes_duplicates(self):
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, matricola, ruolo, email)
                    VALUES
                        (NULL, 'DERYA', 'AKSOY', 'INT010', 'Operatore Aggiustaggio', 'legacy@test.local')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, email)
                    VALUES
                        ('d.aksoy', 'Derya', 'Aksoy', 'd.aksoy@example.local')
                    """
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, matricola, ruolo, email)
                    VALUES
                        (NULL, 'DERYA', 'AKSOY', 'INT010', 'Operatore Aggiustaggio', 'legacy@test.local')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO anagrafica_dipendenti
                        (aliasusername, nome, cognome, email)
                    VALUES
                        ('d.aksoy', 'Derya', 'Aksoy', 'd.aksoy@example.local')
                    """
                )

        summary = cleanup_duplicate_anagrafica_rows()
        self.assertEqual(summary["groups"], 1)
        self.assertEqual(summary["rows_deleted"], 1)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT nome, cognome, aliasusername, matricola, ruolo
                FROM anagrafica_dipendenti
                """
            )
            rows = cursor.fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Derya")
        self.assertEqual(rows[0][1], "Aksoy")
        self.assertEqual(rows[0][2], "d.aksoy")
        self.assertEqual(rows[0][3], "INT010")
        self.assertEqual(rows[0][4], "Operatore Aggiustaggio")
