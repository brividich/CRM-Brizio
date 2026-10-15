"""Mansionario fase 3: competenze per mansione, livello calcolato, esito, lacune. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from core.legacy_models import AnagraficaDipendente

from .models import (
    AbilitazioneMacchinaStorico, CompetenzaSkm, DipendenteQualifica, SkillMatrixConfig, TipoQualifica,
    VoceMacchinaCatalogo,
)
from .services import mansionario_competenze as comp
from .services import mansionario_struttura as svc
from .tests import _ensure_anagrafica_table

User = get_user_model()


class LivelloCalcolatoTests(TestCase):
    def _v(self, bloccante=False):
        return VoceMacchinaCatalogo(codice="x", nome="x", bloccante=bloccante)

    def test_media_con_tetto_sulla_bloccante(self):
        regola = SkillMatrixConfig.REGOLA_MEDIA_TETTO
        # O(4)+O(4)+L(2) = 10/3 → 3 (U); bloccante a L fa da tetto → L
        self.assertEqual(comp.livello_calcolato([(self._v(), "O"), (self._v(), "O"), (self._v(True), "L")], regola), "L")
        self.assertEqual(comp.livello_calcolato([(self._v(), "O"), (self._v(), "O"), (self._v(), "L")], regola), "U")

    def test_altre_regole(self):
        coppie = [(self._v(), "O"), (self._v(True), "U"), (self._v(), "I")]
        self.assertEqual(comp.livello_calcolato(coppie, SkillMatrixConfig.REGOLA_MIN), "I")
        self.assertEqual(comp.livello_calcolato(coppie, SkillMatrixConfig.REGOLA_MEDIA), "L")
        self.assertEqual(comp.livello_calcolato(coppie, SkillMatrixConfig.REGOLA_BLOCCANTI), "U")

    def test_competenza_senza_livello_vale_zero(self):
        self.assertEqual(comp.livello_calcolato([(self._v(), ""), (self._v(), "L")], SkillMatrixConfig.REGOLA_MEDIA_TETTO), "I")


@override_settings(LEGACY_AUTH_ENABLED=False)
class ValutazioneTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("mnc_admin", "mnc@example.invalid", "x")
        asset = Asset.objects.create(name="Tornio sintetico C3", reparto="TORNI")
        self.mansione = CompetenzaSkm.objects.create(competenza_key="C3-TC", display="Tornio C3",
                                                     tipo=CompetenzaSkm.TIPO_MACCHINA, asset=asset)
        self.carrello = TipoQualifica.objects.create(nome="Carrellista sintetico")
        self.p = AnagraficaDipendente.objects.create(nome="UNO", cognome="ESEMPIO", aliasusername="esempio.uno.c3")
        self.setup_voce = comp.salva_competenza(self.mansione, nome="Set-up", livello_minimo="U", bloccante=True)
        self.prog = comp.salva_competenza(self.mansione, nome="Programmazione", livello_minimo="L")
        self.ab = svc.assegna(self.mansione, legacy_anagrafica_id=self.p.pk, livello="I")

    def test_abilitato_quando_tutto_a_posto_e_livello_riscritto(self):
        val = comp.registra_livelli(self.ab, {self.setup_voce.pk: "O", self.prog.pk: "U"})
        self.ab.refresh_from_db()
        # O(4) + U(3) → media 3,5 arrotondata per difetto = U; il tetto bloccante (O) non abbassa.
        self.assertEqual((val.esito, self.ab.livello), (comp.ABILITATO, "U"))

    def test_bloccante_sotto_minimo_non_abilitato(self):
        val = comp.registra_livelli(self.ab, {self.setup_voce.pk: "L", self.prog.pk: "O"})
        self.assertEqual(val.esito, comp.NON_ABILITATO)
        self.assertIn("Set-up: L, richiesto U", val.mancanze)

    def test_non_bloccante_sotto_minimo_in_addestramento(self):
        val = comp.registra_livelli(self.ab, {self.setup_voce.pk: "O", self.prog.pk: "I"})
        self.assertEqual(val.esito, comp.IN_ADDESTRAMENTO)

    def test_requisito_formale_mancante(self):
        comp.salva_competenza(self.mansione, voce=self.prog, nome="Programmazione", livello_minimo="L",
                              qualifica_id=self.carrello.pk)
        val = comp.registra_livelli(self.ab, {self.setup_voce.pk: "O", self.prog.pk: "O"})
        self.assertEqual(val.esito, comp.NON_ABILITATO)
        self.assertIn("qualifica «Carrellista sintetico»", " ".join(val.mancanze))
        # Non abilitato = sotto soglia anche nella skill matrix (O,O con requisito mancante → I, media 3 → tetto L).
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "L")
        self.assertFalse(self.ab.is_operativa(SkillMatrixConfig.get_instance().soglia_operativa_ordinale))
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p.pk, tipo=self.carrello,
                                           data_scadenza=timezone.localdate() + timedelta(days=100))
        self.assertEqual(comp.valuta(self.ab).esito, comp.ABILITATO)

    def test_storico_e_lacune(self):
        comp.registra_livelli(self.ab, {self.setup_voce.pk: "L"})
        self.assertTrue(AbilitazioneMacchinaStorico.objects.filter(competenza=self.mansione,
                                                                   note__startswith="Mansionario: valutazione").exists())
        lacune = comp.lacune()
        self.assertEqual([(r["legacy_id"], r["valutazione"].esito) for r in lacune], [(self.p.pk, comp.NON_ABILITATO)])

    def test_competenza_doppia_rifiutata(self):
        with self.assertRaises(ValueError):
            comp.salva_competenza(self.mansione, nome="set-up", livello_minimo="L")

    def test_mansione_senza_competenze_usa_il_livello_a_mano(self):
        altra = CompetenzaSkm.objects.create(competenza_key="P-X", display="Processo X", tipo=CompetenzaSkm.TIPO_PROCESSO)
        ab = svc.assegna(altra, legacy_anagrafica_id=self.p.pk, livello="U")
        self.assertEqual(comp.valuta(ab).esito, comp.ABILITATO)

    def test_pagine(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("anagrafica:mansionario_mansione", args=[self.mansione.pk]))
        self.assertContains(r, "Competenze richieste")
        self.assertContains(r, reverse("anagrafica:mansionario_valuta", args=[self.mansione.pk, self.ab.pk]))
        r = self.client.post(reverse("anagrafica:mansionario_valuta", args=[self.mansione.pk, self.ab.pk]),
                             {f"livello_{self.setup_voce.pk}": "U", f"livello_{self.prog.pk}": "U"})
        self.assertEqual(r.status_code, 302)
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "U")
        for url in (reverse("anagrafica:mansionario"), reverse("anagrafica:mansionario_lacune"),
                    reverse("anagrafica:mansionario_persona", args=[self.p.pk]),
                    reverse("anagrafica:mansionario_valuta", args=[self.mansione.pk, self.ab.pk])):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        csv = self.client.get(reverse("anagrafica:mansionario_lacune") + "?formato=csv")
        self.assertEqual(csv["Content-Type"].split(";")[0], "text/csv")

    def test_aggiungi_e_togli_competenza_dalla_pagina(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("anagrafica:mansionario_competenza_salva", args=[self.mansione.pk]),
                         {"nome": "Controllo dimensionale", "livello_minimo": "U", "bloccante": "on"})
        voce = VoceMacchinaCatalogo.objects.get(mansione=self.mansione, nome="Controllo dimensionale")
        self.assertTrue(voce.bloccante)
        self.client.post(reverse("anagrafica:mansionario_competenza_disattiva", args=[self.mansione.pk, voce.pk]))
        voce.refresh_from_db()
        self.assertFalse(voce.attiva)

    def test_utente_senza_permessi_non_valuta(self):
        semplice = User.objects.create_user("mnc_semplice", "s@example.invalid", "x")
        self.client.force_login(semplice)
        self.client.post(reverse("anagrafica:mansionario_valuta", args=[self.mansione.pk, self.ab.pk]),
                         {f"livello_{self.setup_voce.pk}": "O"})
        self.assertFalse(self.ab.voci.exists())
