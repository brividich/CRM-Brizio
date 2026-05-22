from __future__ import annotations

import tempfile
from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from core.legacy_anagrafica import cleanup_duplicate_anagrafica_rows, ensure_anagrafica_schema
from assets.models import Asset, AssetCategory, SoftwareLicense
from .models import DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile, SaldoCedolino

User = get_user_model()

VALID_GIF_1X1 = (
    b"GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
    b"\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


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
class AnagraficaRateiExportTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, reparto, attivo)
                VALUES
                    (%s, %s, %s, %s, %s)
                """,
                ["m.rossi", "Mario", "Rossi", "AMMINISTRAZIONE", 1],
            )
            cursor.execute(
                """
                SELECT id
                FROM anagrafica_dipendenti
                WHERE aliasusername = %s
                """,
                ["m.rossi"],
            )
            self.legacy_id = int(cursor.fetchone()[0])

        self.user = User.objects.create_superuser(
            username="ratei-export",
            email="ratei-export@example.com",
            password="pass12345",
        )

    def test_ratei_export_with_reparto_filter_returns_valid_xlsx(self):
        SaldoCedolino.objects.create(
            tax_code="RSSMRA80A01H501U",
            legacy_anagrafica_id=self.legacy_id,
            data_competenza=date(2026, 5, 31),
            anzianita_anni=3,
            anzianita_mesi=4,
            ferie_anni_prec="1.50",
            ferie_maturati="8.00",
            ferie_goduti="2.00",
            ferie_residui="7.50",
            rol_anni_prec="0.00",
            rol_maturati="4.00",
            rol_goduti="1.00",
            rol_residui="3.00",
            ex_fest_anni_prec="0.00",
            ex_fest_maturati="2.00",
            ex_fest_goduti="0.00",
            ex_fest_residui="2.00",
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("anagrafica:ratei_export"),
            {"periodo": "2026-05-31", "reparto": "AMMINISTRAZIONE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        wb = load_workbook(BytesIO(response.content), data_only=True)
        ws = wb["Ratei Ferie"]
        self.assertEqual(ws["A1"].value, "Dipendente")
        self.assertEqual(ws["E1"].value, "Ferie")
        self.assertEqual(ws["E2"].value, "Anni Prec.")
        self.assertEqual(ws["A3"].value, "Rossi Mario")
        self.assertEqual(ws["B3"].value, "AMMINISTRAZIONE")


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
            reverse("anagrafica:dipendente_create"),
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
            reverse("anagrafica:dipendente_create"),
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
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(html.count(">Aksoy Derya<"), 1)
        self.assertNotIn(">AKSOY DERYA<", html)

    def test_ex_dipendenti_are_separated_from_active_list(self):
        """Un dipendente con data_cessazione non compare nella lista in forza
        ma compare nella vista dedicata agli ex dipendenti."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo)
                VALUES (%s, %s, %s, %s)
                """,
                ["m.attivo", "Marco", "Attivo", 1],
            )
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo)
                VALUES (%s, %s, %s, %s)
                """,
                ["e.cessato", "Elia", "Cessato", 0],
            )
            cursor.execute(
                "SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s",
                ["e.cessato"],
            )
            ex_legacy_id = int(cursor.fetchone()[0])

        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=ex_legacy_id,
            data_cessazione=date(2025, 12, 31),
        )

        self.client.force_login(self.user)

        list_html = self.client.get(reverse("anagrafica:dipendenti_list")).content.decode()
        self.assertIn(">Attivo Marco<", list_html)
        self.assertNotIn(">Cessato Elia<", list_html)

        ex_response = self.client.get(reverse("anagrafica:ex_dipendenti_list"))
        ex_html = ex_response.content.decode()
        self.assertEqual(ex_response.status_code, 200)
        self.assertIn(">Cessato Elia<", ex_html)
        self.assertNotIn(">Attivo Marco<", ex_html)
        self.assertEqual(ex_response.context["page_obj"].paginator.count, 1)

    def test_list_orders_employees_by_surname_and_name_on_first_load(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, reparto, attivo)
                VALUES
                    (%s, %s, %s, %s, %s)
                """,
                ["z.zeta", "Zoe", "Zeta", "Produzione", 1],
            )
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, reparto, attivo)
                VALUES
                    (%s, %s, %s, %s, %s)
                """,
                ["a.alfa", "Anna", "Alfa", "Produzione", 1],
            )

        self.client.force_login(self.user)
        response = self.client.get(reverse("anagrafica:dipendenti_list"))

        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertLess(html.index("Alfa Anna"), html.index("Zeta Zoe"))

    def test_list_uses_employee_photo_or_gray_avatar_fallback(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, reparto, attivo)
                VALUES
                    (%s, %s, %s, %s, %s)
                """,
                ["a.alfa", "Anna", "Alfa", "Produzione", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["a.alfa"])
            photo_legacy_id = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, reparto, attivo)
                VALUES
                    (%s, %s, %s, %s, %s)
                """,
                ["b.beta", "Bruno", "Beta", "Produzione", 1],
            )

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            civile = DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=photo_legacy_id)
            civile.foto.save("profilo.gif", ContentFile(VALID_GIF_1X1), save=True)

            self.client.force_login(self.user)
            response = self.client.get(reverse("anagrafica:dipendenti_list"))

            html = response.content.decode()
            self.assertEqual(response.status_code, 200)
            self.assertIn(f"/media/anagrafica/dipendenti/{photo_legacy_id}/foto/", html)
            self.assertIn("ana-avatar-img", html)
            self.assertIn("ana-avatar-fallback", html)

    def test_civil_form_can_upload_employee_photo(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, reparto, attivo)
                VALUES
                    (%s, %s, %s, %s, %s)
                """,
                ["a.alfa", "Anna", "Alfa", "Produzione", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["a.alfa"])
            legacy_id = int(cursor.fetchone()[0])

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_login(self.user)
            response = self.client.post(
                reverse("anagrafica:dipendente_civile_save", args=[legacy_id]),
                {
                    "foto": SimpleUploadedFile(
                        "profilo.gif",
                        VALID_GIF_1X1,
                        content_type="image/gif",
                    )
                },
            )

            self.assertEqual(response.status_code, 302)
            civile = DipendenteAnagraficaCivile.objects.get(legacy_anagrafica_id=legacy_id)
            self.assertTrue(civile.foto.name.startswith(f"anagrafica/dipendenti/{legacy_id}/foto/"))

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


# ===========================================================================
# Visite mediche / Documenti dipendente / Servizi DPI ingresso
# ===========================================================================

from datetime import timedelta

from .models import (
    AnagraficaVisiteMedichePermission,
    DipendenteRuoloOperativo,
    DocumentoDipendente,
    RuoloOperativo,
    TipoVisitaMedica,
    VisitaMedica,
)
from .services.visite import (
    STATO_IN_SCADENZA,
    STATO_MANCANTE,
    STATO_SCADUTA,
    STATO_VALIDA,
    stato_visite,
    tipi_visita_richiesti_per_dipendente,
)


class VisitaMedicaScadenzaTests(TestCase):
    def setUp(self):
        self.tipo_12 = TipoVisitaMedica.objects.create(nome="Tipo 12 mesi", durata_mesi=12)
        self.tipo_24 = TipoVisitaMedica.objects.create(nome="Tipo 24 mesi", durata_mesi=24)
        self.tipo_0 = TipoVisitaMedica.objects.create(nome="Senza scadenza", durata_mesi=0)

    def test_scadenza_calcolata_12_mesi(self):
        v = VisitaMedica.objects.create(
            legacy_anagrafica_id=1,
            tipo=self.tipo_12,
            data_svolgimento=date(2026, 1, 15),
        )
        self.assertEqual(v.data_scadenza, date(2027, 1, 15))

    def test_scadenza_calcolata_24_mesi(self):
        v = VisitaMedica.objects.create(
            legacy_anagrafica_id=1,
            tipo=self.tipo_24,
            data_svolgimento=date(2026, 5, 1),
        )
        self.assertEqual(v.data_scadenza, date(2028, 5, 1))

    def test_scadenza_durata_zero_non_imposta_data(self):
        v = VisitaMedica.objects.create(
            legacy_anagrafica_id=1,
            tipo=self.tipo_0,
            data_svolgimento=date(2026, 5, 1),
        )
        self.assertIsNone(v.data_scadenza)

    def test_is_scaduta_e_in_scadenza(self):
        from django.utils import timezone
        oggi = timezone.localdate()
        v_scaduta = VisitaMedica.objects.create(
            legacy_anagrafica_id=1,
            tipo=self.tipo_12,
            data_svolgimento=oggi - timedelta(days=400),
        )
        self.assertTrue(v_scaduta.is_scaduta)

        v_in_scad = VisitaMedica.objects.create(
            legacy_anagrafica_id=2,
            tipo=self.tipo_12,
            data_svolgimento=oggi - timedelta(days=340),  # scadenza tra ~25g
        )
        self.assertFalse(v_in_scad.is_scaduta)
        self.assertTrue(v_in_scad.in_scadenza)


class StatoVisiteServiceTests(TestCase):
    def setUp(self):
        self.ruolo = RuoloOperativo.objects.create(nome="Saldatore")
        self.tipo = TipoVisitaMedica.objects.create(
            nome="Visita saldatori", durata_mesi=12, obbligatoria=True,
        )
        self.tipo.ruoli_operativi.add(self.ruolo)
        self.tipo_non_obb = TipoVisitaMedica.objects.create(
            nome="Visita facoltativa", durata_mesi=12, obbligatoria=False,
        )
        self.tipo_non_obb.ruoli_operativi.add(self.ruolo)

    def test_dipendente_senza_ruoli_non_ha_visite_richieste(self):
        self.assertEqual(tipi_visita_richiesti_per_dipendente(999), [])

    def test_dipendente_con_ruolo_vede_solo_obbligatorie(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=10, ruolo=self.ruolo)
        tipi = tipi_visita_richiesti_per_dipendente(10)
        nomi = {t.nome for t in tipi}
        self.assertIn("Visita saldatori", nomi)
        self.assertNotIn("Visita facoltativa", nomi)

    def test_stato_visite_mancante(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=11, ruolo=self.ruolo)
        out = stato_visite(11)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["stato"], STATO_MANCANTE)

    def test_stato_visite_valida_e_scaduta(self):
        from django.utils import timezone
        oggi = timezone.localdate()
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=12, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=12, tipo=self.tipo, data_svolgimento=oggi - timedelta(days=30),
        )
        out = stato_visite(12)
        self.assertEqual(out[0]["stato"], STATO_VALIDA)

        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=13, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=13, tipo=self.tipo, data_svolgimento=oggi - timedelta(days=400),
        )
        out = stato_visite(13)
        self.assertEqual(out[0]["stato"], STATO_SCADUTA)


class DPIPDFRenderTests(TestCase):
    def test_render_modulo_consegna_dpi_produce_pdf_bytes(self):
        from dpi.models import (
            CategoriaDPI, ConsegnaDPI, RichiestaDPI, StatoRichiesta,
        )
        from dpi.pdf import render_modulo_consegna_dpi

        cat = CategoriaDPI.objects.create(nome="Elmetto", vita_utile_giorni=365)
        richiesta = RichiestaDPI.objects.create(
            categoria=cat,
            quantita=1,
            stato=StatoRichiesta.APPROVATA,
            richiedente_legacy_id=99,
            richiedente_nome="Test Dipendente",
        )
        consegna = ConsegnaDPI.objects.create(
            richiesta=richiesta,
            data_consegna=date(2026, 5, 21),
            consegnato_da_nome="HR",
            firma_immagine="",
        )
        pdf_bytes = render_modulo_consegna_dpi(consegna)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 1000)


class VisiteMedichePermissionTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su", email="su@test.local", password="x"
        )
        self.user_plain = User.objects.create_user(
            username="plain", email="plain@test.local", password="x"
        )

    def test_superuser_sempre_autorizzato(self):
        from .views import _can_view_visite_mediche
        class FakeReq:
            user = self.user_super
        # Lo helper accetta `request`-like con `.user`. Funziona anche con questo stub.
        self.assertTrue(_can_view_visite_mediche(FakeReq()))

    def test_default_admin_blocca_utente_normale(self):
        from .views import _can_view_visite_mediche
        AnagraficaVisiteMedichePermission.objects.all().delete()
        # default get_instance crea ACCESSO_ADMIN
        class FakeReq:
            user = self.user_plain
        self.assertFalse(_can_view_visite_mediche(FakeReq()))


class DocumentoDipendenteDownloadACLTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su2", email="su2@test.local", password="x"
        )
        self.user_plain = User.objects.create_user(
            username="plain2", email="plain2@test.local", password="x"
        )
        # Forziamo ACCESSO_ADMIN per le visite (default)
        perm = AnagraficaVisiteMedichePermission.get_instance()
        perm.accesso = AnagraficaVisiteMedichePermission.ACCESSO_ADMIN
        perm.save()

        self.doc_referto = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=1,
            tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
            nome_originale="referto.pdf",
        )
        # Salviamo un file vuoto per evitare 404 prima del 403
        self.doc_referto.file.save("referto.pdf", ContentFile(b"%PDF-1.4 stub"), save=True)

    def test_referto_403_per_utente_normale(self):
        # Bypassa eventuali middleware globali (SetupWizard, NotizieMandatory)
        # chiamando direttamente la view: il test interessa la sola ACL.
        from django.test import RequestFactory
        from .views import documento_dipendente_download

        rf = RequestFactory()
        request = rf.get(f"/anagrafica/documenti/{self.doc_referto.id}/download")
        request.user = self.user_plain
        resp = documento_dipendente_download(request, self.doc_referto.id)
        self.assertEqual(resp.status_code, 403)

    def test_referto_autorizzato_per_superuser(self):
        from django.test import RequestFactory
        from .views import documento_dipendente_download

        rf = RequestFactory()
        request = rf.get(f"/anagrafica/documenti/{self.doc_referto.id}/download")
        request.user = self.user_super
        resp = documento_dipendente_download(request, self.doc_referto.id)
        # FileResponse o HttpResponse 200/404 (in test il file dovrebbe esserci)
        self.assertNotEqual(resp.status_code, 403)


class DocumentoDipendenteListTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, reparto, attivo)
                VALUES
                    (%s, %s, %s, %s, %s)
                """,
                ["l.bianchi", "Luca", "Bianchi", "HR", 1],
            )
            cursor.execute(
                """
                SELECT id
                FROM anagrafica_dipendenti
                WHERE aliasusername = %s
                """,
                ["l.bianchi"],
            )
            self.legacy_id = int(cursor.fetchone()[0])

        self.user_super = User.objects.create_superuser(
            username="docs-admin", email="docs-admin@test.local", password="x"
        )
        self.doc = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=self.legacy_id,
            tipo=DocumentoDipendente.Tipo.MANUALE,
            nome_originale="contratto.pdf",
            descrizione="Documento contratto",
            created_by=self.user_super,
            created_by_display="Admin Docs",
        )

    def test_documenti_list_renderizza_nome_dipendente(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        from django.test import RequestFactory
        from .views import documenti_list

        rf = RequestFactory()
        request = rf.get("/anagrafica/documenti/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)

        resp = documenti_list(request)

        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8", errors="ignore")
        self.assertIn("Bianchi Luca", body)
        self.assertIn("contratto.pdf", body)


class DocumentoDipendenteUploadTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="docs-upload-admin",
            email="docs-upload-admin@test.local",
            password="x",
        )

    def test_documento_upload_salva_pdf_manuale(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        from django.test import RequestFactory
        from .views import documento_dipendente_upload

        with tempfile.TemporaryDirectory() as private_root, override_settings(
            ANAGRAFICA_PRIVATE_ROOT=private_root
        ):
            uploaded = SimpleUploadedFile(
                "contratto.pdf",
                b"%PDF-1.4\n% test pdf\n",
                content_type="application/pdf",
            )
            request = RequestFactory().post(
                "/anagrafica/dipendenti/277/documenti/upload",
                data={"file": uploaded, "descrizione": "Contratto firmato"},
            )
            request.user = self.user_super
            request.session = SessionStore()
            request._messages = FallbackStorage(request)

            resp = documento_dipendente_upload(request, 277)

            self.assertEqual(resp.status_code, 302)
            doc = DocumentoDipendente.objects.get(legacy_anagrafica_id=277)
            self.assertEqual(doc.tipo, DocumentoDipendente.Tipo.MANUALE)
            self.assertEqual(doc.nome_originale, "contratto.pdf")
            self.assertEqual(doc.tipo_mime, "application/pdf")
            self.assertEqual(doc.descrizione, "Contratto firmato")
            self.assertTrue(doc.file.name.endswith(".pdf"))


class ImpostazioniRedirectTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="settings-admin", email="settings-admin@test.local", password="x"
        )

    def _post_request(self, path: str, data: dict):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        from django.test import RequestFactory

        request = RequestFactory().post(path, data=data)
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return request

    def test_cartella_documento_create_redirects_to_documenti_tab(self):
        from .models import CartellaDocumentoDipendente
        from .views import cartella_documento_create

        request = self._post_request(
            "/anagrafica/cartelle-documenti/nuovo",
            {"nome": "Contratti", "descrizione": "Archivio contratti", "ordine": "10"},
        )

        resp = cartella_documento_create(request)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], f"{reverse('anagrafica:impostazioni')}?tab=documenti#tab-documenti")
        self.assertTrue(CartellaDocumentoDipendente.objects.filter(nome="Contratti").exists())

    def test_subnav_categoria_create_redirects_to_navigazione_tab(self):
        from .models import SubnavCategoriaAnagrafica
        from .views import subnav_categoria_create

        request = self._post_request(
            "/anagrafica/subnav/categoria/nuovo",
            {"nome": "Custom", "icona": "", "ordine": "5"},
        )

        resp = subnav_categoria_create(request)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], f"{reverse('anagrafica:impostazioni')}?tab=navigazione#tab-navigazione")
        self.assertTrue(SubnavCategoriaAnagrafica.objects.filter(nome="Custom").exists())


class VisiteMedicheDashboardTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su3", email="su3@test.local", password="x"
        )
        self.user_plain = User.objects.create_user(
            username="plain3", email="plain3@test.local", password="x"
        )

    def test_dashboard_403_per_utente_normale(self):
        from django.test import RequestFactory
        from .views import visite_mediche_dashboard

        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/")
        request.user = self.user_plain
        # _check_session_setup richiede session+messages middleware: usiamo middleware factories
        from django.contrib.messages.storage.fallback import FallbackStorage
        request.session = {}
        request._messages = FallbackStorage(request)
        resp = visite_mediche_dashboard(request)
        # Redirect verso anagrafica:index (302)
        self.assertEqual(resp.status_code, 302)

    def test_dashboard_render_superuser(self):
        # Smoke test: la view ritorna 200 e prepara il context senza errori.
        # Usiamo RequestFactory + chiamiamo la view; per evitare l'accesso
        # ai context processor (es. legacy_nav che richiede session), il
        # template usa solo variabili nostre. La risposta NON renderizza
        # context processors quando si chiama direttamente la view: il
        # rendering avviene comunque, quindi forniamo una session vuota.
        ruolo = RuoloOperativo.objects.create(nome="Operatore")
        tipo = TipoVisitaMedica.objects.create(
            nome="Visita test", durata_mesi=12, obbligatoria=True
        )
        tipo.ruoli_operativi.add(ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=77, ruolo=ruolo)

        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        from django.test import RequestFactory
        from .views import visite_mediche_dashboard

        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_dashboard(request)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8", errors="ignore")
        self.assertIn("Visite mediche", body)
        self.assertIn("Copertura per tipologia", body)


class DPIIngressoServiceTests(TestCase):
    def test_crea_consegne_iniziali_crea_richiesta_e_consegna(self):
        from dpi.models import CategoriaDPI, ConsegnaDPI, RichiestaDPI, StatoRichiesta
        from .services.dpi_ingresso import RigaConsegnaIniziale, crea_consegne_iniziali

        cat = CategoriaDPI.objects.create(
            nome="Guanti", vita_utile_giorni=180, obbligatoria_mansionario=True,
        )
        civile = DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=42)
        user = User.objects.create_user(username="hr", email="hr@x.local", password="x")

        consegne = crea_consegne_iniziali(
            civile, None, [RigaConsegnaIniziale(categoria_id=cat.id, quantita=2)], user,
        )
        self.assertEqual(len(consegne), 1)
        consegna = consegne[0]
        self.assertIsInstance(consegna, ConsegnaDPI)
        self.assertEqual(consegna.richiesta.stato, StatoRichiesta.CONSEGNATA)
        self.assertEqual(consegna.richiesta.quantita, 2)
        self.assertEqual(consegna.richiesta.richiedente_legacy_id, 42)
        # scadenza stimata calcolata dalla vita utile della categoria
        from django.utils import timezone
        self.assertEqual(
            consegna.data_scadenza_stimata,
            timezone.localdate() + timedelta(days=180),
        )
