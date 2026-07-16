from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import DipendenteQualifica, QualificaSessione, TipoQualifica
from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class QualificheCruscottoTests(TestCase):
    """Smoke test del cruscotto Qualifiche e dello scadenzario dedicato (Fase 1).

    Verifica anche, implicitamente, che la migrazione dati 0064 (subnav) si
    applichi correttamente nel test DB.
    """

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, reparto, attivo) "
                "VALUES (1, 'Mario', 'Rossi', 'Produzione', 1)"
            )
        self.user = User.objects.create_superuser(
            username="qual-view", email="qual-view@example.com", password="pass12345",
        )
        self.tipo = TipoQualifica.objects.create(
            nome="Patentino carrellista",
            categoria=TipoQualifica.CAT_PROFESSIONALE,
            durata_mesi=60,
        )
        oggi = timezone.localdate()
        # Una scaduta + una in scadenza entro 60gg
        DipendenteQualifica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_conseguimento=date(2020, 1, 1), data_scadenza=oggi - timedelta(days=10),
        )
        DipendenteQualifica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_conseguimento=oggi - timedelta(days=300), data_scadenza=oggi + timedelta(days=20),
        )
        QualificaSessione.objects.create(
            tipo=self.tipo, data_conseguimento=oggi + timedelta(days=15), ente="Ente Test",
        )
        self.client.force_login(self.user)

    def test_dashboard_ok(self):
        resp = self.client.get(reverse("anagrafica:qualifiche_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["tipi_attivi"], 1)
        self.assertEqual(resp.context["tot_assegnazioni"], 2)
        self.assertEqual(resp.context["n_scadute"], 1)
        self.assertEqual(len(resp.context["timeline"]), 12)
        self.assertEqual(len(resp.context["prossime_sessioni"]), 1)

    def test_scadenzario_default(self):
        resp = self.client.get(reverse("anagrafica:qualifiche_scadenzario"))
        self.assertEqual(resp.status_code, 200)
        # Default = scadute + ≤60gg → entrambe le righe
        self.assertEqual(resp.context["totale"], 2)

    def test_scadenzario_filtra_scadute(self):
        resp = self.client.get(reverse("anagrafica:qualifiche_scadenzario"), {"stato": "scaduta"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["totale"], 1)

    def test_scadenzario_export_csv(self):
        resp = self.client.get(
            reverse("anagrafica:qualifiche_scadenzario"), {"stato": "tutte", "format": "csv"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Patentino carrellista", body)
        self.assertIn("Rossi Mario", body)
        self.assertIn("Ente", body)  # header colonna Fase 2


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class QualificheFase2Tests(TestCase):
    """Fase 2a: estremi certificato (n°/livello/ente), evidenza, verifica HR."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, reparto, attivo) "
                "VALUES (1, 'Mario', 'Rossi', 'Produzione', 1)"
            )
        self.user = User.objects.create_superuser(
            username="qual-f2", email="qual-f2@example.com", password="pass12345",
        )
        self.tipo = TipoQualifica.objects.create(
            nome="Antincendio", categoria=TipoQualifica.CAT_SICUREZZA, durata_mesi=60,
        )
        self.client.force_login(self.user)

    def test_add_con_estremi_e_evidenza(self):
        pdf = SimpleUploadedFile("cert.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        resp = self.client.post(
            reverse("anagrafica:dipendente_qualifica_add", args=[1]),
            {
                "tipo_id": self.tipo.id,
                "data_conseguimento": "2026-01-10",
                "numero": "AB-999",
                "livello": "liv. 2",
                "ente": "Vigili del Fuoco",
                "note": "",
                "documento": pdf,
            },
        )
        self.assertEqual(resp.status_code, 302)
        q = DipendenteQualifica.objects.get(legacy_anagrafica_id=1, tipo=self.tipo)
        self.assertEqual(q.numero, "AB-999")
        self.assertEqual(q.livello, "liv. 2")
        self.assertEqual(q.ente, "Vigili del Fuoco")
        self.assertTrue(q.documento)
        self.assertFalse(q.verificata)
        # Evidenza scaricabile (storage privato, view protetta)
        ev = self.client.get(reverse("anagrafica:dipendente_qualifica_evidenza", args=[1, q.id]))
        self.assertEqual(ev.status_code, 200)

    def test_add_rifiuta_formato_non_ammesso(self):
        bad = SimpleUploadedFile("malware.exe", b"MZ", content_type="application/octet-stream")
        self.client.post(
            reverse("anagrafica:dipendente_qualifica_add", args=[1]),
            {"tipo_id": self.tipo.id, "data_conseguimento": "2026-01-10", "documento": bad},
        )
        self.assertFalse(DipendenteQualifica.objects.filter(legacy_anagrafica_id=1).exists())

    def test_verifica_toggle(self):
        q = DipendenteQualifica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo, data_conseguimento=date(2026, 1, 1),
        )
        # Attiva verifica
        self.client.post(reverse("anagrafica:dipendente_qualifica_verifica", args=[1, q.id]))
        q.refresh_from_db()
        self.assertTrue(q.verificata)
        self.assertEqual(q.verificata_da_id, self.user.id)
        self.assertIsNotNone(q.verificata_il)
        # Toggle off
        self.client.post(reverse("anagrafica:dipendente_qualifica_verifica", args=[1, q.id]))
        q.refresh_from_db()
        self.assertFalse(q.verificata)
        self.assertIsNone(q.verificata_da_id)

    def test_storico_rilascio_e_rinnovo_con_dedup(self):
        url = reverse("anagrafica:dipendente_qualifica_add", args=[1])
        # Rilascio
        self.client.post(url, {"tipo_id": self.tipo.id, "data_conseguimento": "2024-01-10"})
        # Rinnovo (nuova data) → seconda riga di storico
        self.client.post(url, {"tipo_id": self.tipo.id, "data_conseguimento": "2026-01-10"})
        q = DipendenteQualifica.objects.get(legacy_anagrafica_id=1, tipo=self.tipo)
        self.assertEqual(q.storico.count(), 2)
        # Re-post identico → dedup, niente nuova riga
        self.client.post(url, {"tipo_id": self.tipo.id, "data_conseguimento": "2026-01-10"})
        self.assertEqual(q.storico.count(), 2)

    def test_storico_storicizza_evidenza(self):
        url = reverse("anagrafica:dipendente_qualifica_add", args=[1])
        pdf1 = SimpleUploadedFile("v1.pdf", b"%PDF-1.4 uno", content_type="application/pdf")
        self.client.post(url, {"tipo_id": self.tipo.id, "data_conseguimento": "2024-01-10", "documento": pdf1})
        pdf2 = SimpleUploadedFile("v2.pdf", b"%PDF-1.4 due", content_type="application/pdf")
        self.client.post(url, {"tipo_id": self.tipo.id, "data_conseguimento": "2026-01-10", "documento": pdf2})
        q = DipendenteQualifica.objects.get(legacy_anagrafica_id=1, tipo=self.tipo)
        storici = list(q.storico.order_by("id"))
        self.assertEqual(len(storici), 2)
        self.assertTrue(storici[0].documento)
        self.assertTrue(storici[1].documento)
        # Evidenza del primo rilascio preservata (path diverso dall'attuale)
        self.assertNotEqual(storici[0].documento.name, storici[1].documento.name)
        self.assertEqual(q.documento.name, storici[1].documento.name)
        # Download dell'evidenza storica del primo rilascio
        r = self.client.get(reverse(
            "anagrafica:dipendente_qualifica_storico_evidenza", args=[1, q.id, storici[0].id]))
        self.assertEqual(r.status_code, 200)

    def test_dashboard_kpi_da_verificare(self):
        pdf = SimpleUploadedFile("c.pdf", b"%PDF-1.4", content_type="application/pdf")
        q = DipendenteQualifica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo, data_conseguimento=date(2026, 1, 1),
            documento=pdf,
        )
        resp = self.client.get(reverse("anagrafica:qualifiche_dashboard"))
        self.assertEqual(resp.context["n_con_evidenza"], 1)
        self.assertEqual(resp.context["n_da_verificare"], 1)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class QualificheChipProcessiTests(TestCase):
    """Task 3 (stream 3): chip virtuale 'Processi qualificati' (MOD.128) accanto
    alle categorie reali di TipoQualifica. Pseudo-categoria non persistita sul
    modello: riusa i ProcessoQualificato già caricati in `qualifiche_list`."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.su = User.objects.create_superuser(
            username="su-ql", email="su-ql@test.local", password="x",
        )
        self.client.force_login(self.su)
        from .models_mpq import ClienteQualificante, ProcessoQualificato
        cli = ClienteQualificante.objects.create(nome="ACME")
        ProcessoQualificato.objects.create(nome="Saldatura X", cliente=cli)
        TipoQualifica.objects.create(
            nome="RSPP", categoria=TipoQualifica.CAT_SICUREZZA, durata_mesi=60,
        )

    def _get(self, **q):
        return self.client.get(reverse("anagrafica:qualifiche_list"), q)

    def test_chip_processi_presente_con_conteggio(self):
        body = self._get().content.decode()
        self.assertIn("Processi qualificati", body)
        self.assertIn("categoria=PROCESSI", body)  # href della chip

    def test_filtro_processi_mostra_solo_mod128(self):
        body = self._get(categoria="PROCESSI").content.decode()
        self.assertIn("Saldatura X", body)   # sezione MOD.128 visibile
        self.assertNotIn("RSPP", body)       # catalogo tipi nascosto

    def test_filtro_categoria_reale_nasconde_processi(self):
        body = self._get(categoria="SICUREZZA").content.decode()
        self.assertIn("RSPP", body)
        self.assertNotIn("Saldatura X", body)  # MOD.128 nascosto sotto altra categoria
