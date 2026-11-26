"""Colonna «Codice fiscale» in «Elenco del personale»: solo con il permesso sui dati HR riservati.

Dati sintetici: codici fiscali inventati, ``carica_dipendenti`` sostituito come negli altri test.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from anagrafica.models import DipendenteAnagraficaCivile
from anagrafica.reportistica import conversazione
from anagrafica.reportistica import sezioni as catalogo
from anagrafica.reportistica.dati import Contesto, Dipendente, Perimetro

OGGI = timezone.localdate()
CF_A = "TSTAAA80A01H501X"
CF_B = "TSTBBB85B41F205Y"


def _persone() -> list[Dipendente]:
    return [
        # Anagrafica doppia: il codice fiscale e' sulla scheda del doppione (961).
        Dipendente(id=911, nominativo="PROVA ANNA", data_assunzione=OGGI - timedelta(days=900), ids=(911, 961)),
        Dipendente(id=912, nominativo="ESEMPIO LUCA", data_assunzione=OGGI - timedelta(days=300)),
        Dipendente(id=913, nominativo="SENZA CF", data_assunzione=OGGI - timedelta(days=30)),
    ]


def _request(autenticato: bool = True):
    return SimpleNamespace(user=SimpleNamespace(is_authenticated=autenticato, is_superuser=False))


class CodiceFiscaleReportTest(TestCase):
    def setUp(self):
        super().setUp()
        p = patch("anagrafica.reportistica.dati.carica_dipendenti", side_effect=_persone)
        p.start()
        self.addCleanup(p.stop)
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=961, codice_fiscale=CF_A.lower())
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=912, codice_fiscale=CF_B)
        self.sezione = catalogo.get("personale_elenco")

    def _hr(self, consentito: bool):
        p = patch("anagrafica.views._check_hr_permission", return_value=consentito)
        p.start()
        self.addCleanup(p.stop)

    def _calcola(self, request):
        ctx = Contesto(date_from=OGGI - timedelta(days=365), date_to=OGGI,
                       perimetro=Perimetro.from_dict({}), request=request, today=OGGI)
        return self.sezione.calcola(ctx, {})

    def test_con_permesso_hr_colonna_e_valori(self):
        self._hr(True)
        req = _request()
        self.assertIn("codice_fiscale", dict(self.sezione.colonne_per(req)))
        per_nome = {r["nominativo"]: r["codice_fiscale"] for r in self._calcola(req).righe}
        self.assertEqual(per_nome, {"PROVA ANNA": CF_A, "ESEMPIO LUCA": CF_B, "SENZA CF": ""})
        self.assertEqual(self.sezione.colonne_effettive(["nominativo", "codice_fiscale"], req),
                         ["nominativo", "codice_fiscale"])

    def test_senza_permesso_niente_colonna_ne_dati(self):
        self._hr(False)
        req = _request()
        self.assertNotIn("codice_fiscale", dict(self.sezione.colonne_per(req)))
        self.assertTrue(all(r["codice_fiscale"] == "" for r in self._calcola(req).righe))
        self.assertEqual(self.sezione.colonne_effettive(["nominativo", "codice_fiscale"], req), ["nominativo"])

    def test_senza_request_fail_closed(self):
        self.assertNotIn("codice_fiscale", dict(self.sezione.colonne_per(None)))
        self.assertTrue(all(r["codice_fiscale"] == "" for r in self._calcola(None).righe))

    def test_chat_avvisa_che_la_colonna_e_riservata(self):
        self._hr(False)
        avvisi: list[str] = []
        out = conversazione._colonne(self.sezione, ["nominativo", "codice_fiscale"], avvisi, _request())
        self.assertEqual(out, ["nominativo"])
        self.assertEqual(len(avvisi), 1)
        self.assertIn("riservate ai dati HR", avvisi[0])

    def test_chat_con_permesso_accetta_la_colonna(self):
        self._hr(True)
        avvisi: list[str] = []
        out = conversazione._colonne(self.sezione, ["nominativo", "Codice fiscale"], avvisi, _request())
        self.assertEqual(out, ["nominativo", "codice_fiscale"])
        self.assertEqual(avvisi, [])
