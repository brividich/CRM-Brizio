from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
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
