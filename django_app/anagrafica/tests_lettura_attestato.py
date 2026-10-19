"""«Leggi un attestato»: proposta dei campi e registrazione (dati sintetici)."""
from __future__ import annotations

import tempfile
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafica.models import DipendenteAnagraficaCivile
from anagrafica.models_formazione import (
    TrainingCertificate,
    TrainingCourse,
    TrainingEmployeeRecord,
    TrainingPlan,
    TrainingProvider,
)
from anagrafica.services.lettura_attestato import proponi
from core.lettura_documenti import Lettura
from core.test_lettura_documenti import pdf_con_testo

RIGHE_DIP = [
    {"id": 501, "nome": "Anna", "cognome": "Sintetica", "reparto": "OFFICINA"},
    {"id": 502, "nome": "Marco", "cognome": "Esempio", "reparto": "MAGAZZINO"},
]
CF_ANNA = "SNTNNA80A41H501U"

TESTO_ATTESTATO = f"""
ENTE SINTETICO FORMAZIONE SRL
ATTESTATO DI FREQUENZA N. AT-2026/0042
Si attesta che SINTETICA ANNA, C.F. {CF_ANNA}
ha frequentato il corso SIC-GEN Formazione generale sicurezza lavoratori
della durata di 4 ore, svolto in data 12/03/2026.
Validità quinquennale, scadenza 12/03/2031. Rilasciato il 15/03/2026.
"""


def _patch_anagrafica():
    return patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=RIGHE_DIP)


class PropostaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        piano = TrainingPlan.objects.create(codice="PLA", nome="Piano sintetico")
        cls.corso = TrainingCourse.objects.create(
            piano=piano, codice="SIC-GEN", titolo="Formazione generale sicurezza lavoratori",
            durata_ore_teorica=4, validita_mesi=60, stato="ATTIVO",
        )
        TrainingCourse.objects.create(piano=piano, codice="CARR", titolo="Carrellisti", durata_ore_teorica=12, stato="ATTIVO")
        TrainingProvider.objects.create(nome="Ente Sintetico Formazione Srl")
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=501, codice_fiscale=CF_ANNA)

    def test_proposta_completa(self):
        with _patch_anagrafica():
            p = proponi(Lettura(TESTO_ATTESTATO, pagine=1))
        self.assertEqual([d["legacy_id"] for d in p["dipendenti"]], [501])
        self.assertEqual(p["dipendenti"][0]["motivo"], "codice fiscale")
        self.assertEqual(p["corsi"][0]["id"], self.corso.id)
        self.assertEqual(p["corsi"][0]["motivo"], "codice del corso")
        self.assertEqual(p["data_completamento"], "2026-03-12")
        self.assertEqual(p["data_rilascio"], "2026-03-15")
        self.assertEqual(p["data_scadenza_letta"], "2031-03-12")
        self.assertEqual(p["ore"], "4")
        self.assertEqual(p["ente"], "Ente Sintetico Formazione Srl")
        self.assertEqual(p["numero"], "AT-2026/0042")
        self.assertNotIn(CF_ANNA, p["testo"])  # il codice fiscale non torna alla pagina

    def test_senza_codice_fiscale_riconosce_il_nome_e_il_titolo(self):
        testo = "Si attesta che Marco Esempio ha frequentato FORMAZIONE GENERALE SULLA SICUREZZA DEI LAVORATORI il 02/02/2026"
        with _patch_anagrafica():
            p = proponi(Lettura(testo))
        self.assertEqual([d["legacy_id"] for d in p["dipendenti"]], [502])
        self.assertEqual(p["corsi"][0]["motivo"], "titolo del corso")
        self.assertEqual(p["data_completamento"], "2026-02-02")

    def test_niente_riconosciuto_avvisa(self):
        with _patch_anagrafica():
            p = proponi(Lettura("Documento qualsiasi senza dati utili"))
        self.assertEqual(p["dipendenti"], [])
        self.assertEqual(p["corsi"], [])
        self.assertTrue(any("dipendente" in a for a in p["avvisi"]))

    def test_cessato_escluso(self):
        from anagrafica.models import DipendenteAnagraficaAziendale

        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=501, data_cessazione=date(2025, 1, 1))
        with _patch_anagrafica():
            p = proponi(Lettura(TESTO_ATTESTATO))
        self.assertEqual(p["dipendenti"], [])


class PaginaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        piano = TrainingPlan.objects.create(codice="PLB", nome="Piano sintetico B")
        cls.corso = TrainingCourse.objects.create(
            piano=piano, codice="SIC-GEN", titolo="Formazione generale sicurezza lavoratori",
            durata_ore_teorica=4, validita_mesi=60, stato="ATTIVO",
        )

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("la_admin", "la@example.invalid", "x")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:formazione_dashboard")

    def _pdf(self):
        return SimpleUploadedFile("attestato.pdf", pdf_con_testo(TESTO_ATTESTATO.strip().splitlines()), "application/pdf")

    def test_pagina_si_apre_dalla_dashboard(self):
        with _patch_anagrafica():
            resp = self.client.get(self.url + "?vista=leggi-attestato")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Leggi un attestato")
        self.assertContains(resp, "SINTETICA")  # COGNOME NOME, come nel resto dell'anagrafica

    def test_leggi_risponde_json_con_la_proposta(self):
        with _patch_anagrafica():
            resp = self.client.post(self.url, {"azione": "leggi_attestato", "file": self._pdf()})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["corsi"][0]["id"], self.corso.id)
        self.assertEqual(data["data_completamento"], "2026-03-12")
        self.assertFalse(TrainingEmployeeRecord.objects.exists())  # leggere non registra niente

    def test_file_non_ammesso(self):
        falso = SimpleUploadedFile("attestato.pdf", b"<html>non un pdf</html>", "application/pdf")
        resp = self.client.post(self.url, {"azione": "leggi_attestato", "file": falso})
        self.assertEqual(resp.status_code, 400)

    def test_registra_crea_completamento_certificato_e_archivia(self):
        dati = {"azione": "registra_attestato", "dipendente": "501", "corso": str(self.corso.pk),
                "data_completamento": "2026-03-12", "data_rilascio": "2026-03-15", "ore": "4",
                "ente": "Ente Sintetico", "numero": "AT-2026/0042", "idoneo": "1"}
        with tempfile.TemporaryDirectory() as root, override_settings(ANAGRAFICA_PRIVATE_ROOT=root), _patch_anagrafica():
            resp = self.client.post(self.url, {**dati, "file": self._pdf()}, follow=True)
            self.assertContains(resp, "Attestato registrato")
            record = TrainingEmployeeRecord.objects.get(legacy_anagrafica_id=501, corso=self.corso)
            self.assertEqual(record.data_completamento, date(2026, 3, 12))
            self.assertEqual(record.data_scadenza, date(2031, 3, 12))  # dalla validità del corso
            cert = TrainingCertificate.objects.get(record=record)
            self.assertEqual(cert.numero_attestato, "AT-2026/0042")
            self.assertIsNotNone(cert.file_attestato_id)
            # Stesso attestato una seconda volta: niente doppione a libretto.
            resp = self.client.post(self.url, {**dati, "file": self._pdf()}, follow=True)
            self.assertContains(resp, "era già")
        self.assertEqual(TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=501).count(), 1)

    def test_dipendente_non_in_forza_rifiutato(self):
        with _patch_anagrafica():
            resp = self.client.post(self.url, {
                "azione": "registra_attestato", "dipendente": "999", "corso": str(self.corso.pk),
                "data_completamento": "2026-03-12", "file": self._pdf(),
            }, follow=True)
        self.assertContains(resp, "non è tra quelli in forza")
        self.assertFalse(TrainingEmployeeRecord.objects.exists())

    def test_senza_permesso_di_modifica(self):
        with patch("anagrafica.views._can_edit_formazione", return_value=False), _patch_anagrafica():
            resp = self.client.post(self.url, {"azione": "leggi_attestato", "file": self._pdf()})
        self.assertEqual(resp.status_code, 403)
