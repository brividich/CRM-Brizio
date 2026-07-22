"""A3 / punto 2.1 — la richiesta DPI filtra le categorie al profilo di rischio del
richiedente (mansione di rischio a vista), con override + motivazione per il fuori profilo."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafica.models import Mansione
from anagrafica.models_rischi import EsposizioneRischio, FattoreRischio
from anagrafica.tests import _ensure_anagrafica_table

from .models import CategoriaDPI, RichiestaDPI

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NuovaRichiestaProfiloRischioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.user = User.objects.create_superuser(
            username="dpi_prof", email="dpi_prof@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.user)
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, mansione, attivo) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["r.dpi", "Rita", "DPI", "Saldatore-A3", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername=%s", ["r.dpi"])
            self.legacy_id = int(cur.fetchone()[0])
        # Profilo: mansione Saldatore esposta a un fattore che richiede "Maschera".
        self.dpi_in = CategoriaDPI.objects.create(nome="Maschera saldatura A3")
        self.dpi_out = CategoriaDPI.objects.create(nome="Elmetto A3")
        fattore = FattoreRischio.objects.create(codice="SALD", nome="Fumi saldatura")
        fattore.categorie_dpi.add(self.dpi_in)
        mansione = Mansione.objects.create(nome="Saldatore-A3")
        EsposizioneRischio.objects.create(fattore=fattore, mansione=mansione)

    def _post(self, categoria_id, motivazione=""):
        with patch("dpi.views._legacy_id", return_value=self.legacy_id):
            return self.client.post(reverse("dpi:nuova"), {
                "categoria_id": str(categoria_id), "quantita": "1", "motivazione": motivazione,
            })

    def test_get_filtra_al_profilo(self):
        with patch("dpi.views._legacy_id", return_value=self.legacy_id):
            resp = self.client.get(reverse("dpi:nuova"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Profilo mansione", body)   # badge sulla categoria in profilo
        self.assertIn("fuori-profilo", body)       # l'Elmetto è nascosto (classe fuori-profilo)

    def test_in_profilo_ok_senza_motivazione(self):
        resp = self._post(self.dpi_in.pk)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(RichiestaDPI.objects.filter(categoria=self.dpi_in).count(), 1)

    def test_fuori_profilo_senza_motivazione_rifiutata(self):
        resp = self._post(self.dpi_out.pk)
        self.assertEqual(resp.status_code, 200)  # ri-render con errore, nessun redirect
        self.assertEqual(RichiestaDPI.objects.filter(categoria=self.dpi_out).count(), 0)

    def test_fuori_profilo_con_motivazione_ok_e_nota(self):
        resp = self._post(self.dpi_out.pk, motivazione="Sostituzione temporanea reparto")
        self.assertEqual(resp.status_code, 302)
        r = RichiestaDPI.objects.get(categoria=self.dpi_out)
        self.assertIn("fuori profilo", r.note_gestione.lower())
