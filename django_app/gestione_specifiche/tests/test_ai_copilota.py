"""Test F9 — copilota AI: l'output è sempre 'proposto', mai applicato senza umano."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from gestione_specifiche import constants as C
from gestione_specifiche.ai_copilota import (
    cambiamenti_tra_revisioni, proponi_righe_da_diff, proponi_righe_mod133,
    proponi_tag, ricerca_semantica,
)
from gestione_specifiche.models import RigaMOD133, Specifica

User = get_user_model()


def _ai(content):
    return SimpleNamespace(content=content)


class ProponiRigheTests(TestCase):
    def setUp(self):
        self.spec = Specifica.objects.create(codice="SP-AI", titolo="Trattamento")

    def test_ai_offline_proposta_vuota_nessuna_scrittura(self):
        with patch("ai_assistant.services.chat_with_ollama", side_effect=Exception("down")):
            res = proponi_righe_mod133(self.spec)
        self.assertTrue(res["proposto"])
        self.assertFalse(res["ai_disponibile"])
        self.assertEqual(res["righe"], [])
        self.assertEqual(RigaMOD133.objects.count(), 0)  # nulla salvato

    def test_ai_propone_ma_non_salva(self):
        canned = _ai('[{"argomento":"Tolleranze","tag_processo":"meccanica","impatto_documenti": true}]')
        with patch("ai_assistant.services.chat_with_ollama", return_value=canned):
            res = proponi_righe_mod133(self.spec)
        self.assertTrue(res["proposto"])
        self.assertEqual(len(res["righe"]), 1)
        self.assertEqual(res["righe"][0]["argomento"], "Tolleranze")
        self.assertTrue(res["righe"][0]["impatto_documenti"])
        # INVARIANTE: nessuna riga creata nel DB
        self.assertEqual(RigaMOD133.objects.count(), 0)


class ProponiDaDiffTests(TestCase):
    """F5: diff rev. precedente ↔ nuova → righe MOD.133 (proposta, mai salvata)."""

    def test_cambiamenti_deterministici(self):
        prec = "Par 1. Requisito A tolleranza 0.1\n\nPar 2. Materiale acciaio"
        nuovo = ("Par 1. Requisito A tolleranza 0.05\n\nPar 2. Materiale acciaio\n\n"
                 "Par 3. Nuovo requisito tracciabilita lotti")
        camb = cambiamenti_tra_revisioni(prec, nuovo)
        tipi = {c["tipo"] for c in camb}
        self.assertIn("aggiunto", tipi)     # Par 3
        self.assertIn("modificato", tipi)   # Par 1 cambiato
        self.assertTrue(any("tracciabilita" in c["testo"] for c in camb if c["tipo"] == "aggiunto"))

    def test_nessun_cambiamento(self):
        camb = cambiamenti_tra_revisioni("uguale testo", "uguale testo")
        self.assertEqual(camb, [])

    def test_senza_revisione_precedente(self):
        spec = Specifica.objects.create(codice="SP-D0", titolo="T")
        res = proponi_righe_da_diff(spec)
        self.assertTrue(res["proposto"])
        self.assertFalse(res["ai_disponibile"])
        self.assertEqual(res["righe"], [])
        self.assertIn("Nessuna revisione precedente", res["nota"])

    def _coppia(self):
        prev = Specifica.objects.create(codice="SP-D", revisione="A", titolo="T")
        nuova = Specifica.objects.create(codice="SP-D", revisione="B", titolo="T",
                                         revisione_precedente=prev)
        return prev, nuova

    def test_diff_propone_ma_non_salva(self):
        prev, nuova = self._coppia()
        testi = {"A": "Requisito vecchio tol 0.1", "B": "Requisito nuovo tol 0.05\n\nAggiunta tracciabilita"}
        canned = _ai('[{"argomento":"Tracciabilita lotti","impatto_operativo": true}]')
        with patch("gestione_specifiche.ai_copilota._estrai_testo_specifica",
                   side_effect=lambda s: testi[s.revisione]), \
             patch("ai_assistant.services.chat_with_ollama", return_value=canned):
            res = proponi_righe_da_diff(nuova)
        self.assertTrue(res["proposto"])
        self.assertEqual(res["fonte"], "ai_diff")
        self.assertTrue(res["ai_disponibile"])
        self.assertEqual(len(res["righe"]), 1)
        self.assertEqual(res["righe"][0]["argomento"], "Tracciabilita lotti")
        self.assertTrue(res["cambiamenti"])           # diff deterministico presente
        self.assertEqual(RigaMOD133.objects.count(), 0)  # INVARIANTE: nulla salvato

    def test_ai_offline_ma_diff_presente(self):
        prev, nuova = self._coppia()
        testi = {"A": "Requisito vecchio", "B": "Requisito nuovo diverso"}
        with patch("gestione_specifiche.ai_copilota._estrai_testo_specifica",
                   side_effect=lambda s: testi[s.revisione]), \
             patch("ai_assistant.services.chat_with_ollama", side_effect=Exception("down")):
            res = proponi_righe_da_diff(nuova)
        self.assertTrue(res["proposto"])
        self.assertFalse(res["ai_disponibile"])
        self.assertEqual(res["righe"], [])
        self.assertTrue(res["cambiamenti"])  # il diff resta utile anche senza AI


class ProponiTagTests(TestCase):
    def test_proposta_tag_non_modifica_spec(self):
        spec = Specifica.objects.create(codice="SP-TAG", titolo="Calibrazione strumenti")
        canned = _ai("Metrologia / Calibrazione")
        with patch("ai_assistant.services.chat_with_ollama", return_value=canned):
            res = proponi_tag(f"{spec.titolo}")
        self.assertTrue(res["proposto"])
        self.assertEqual(res["tag"], "metrologia")  # normalizzato snake_case, primo token
        spec = Specifica.objects.get(pk=spec.pk)  # re-fetch (FSMField protected)
        self.assertEqual(spec.tag, "")  # INVARIANTE: non applicato

    def test_offline_tag_vuoto(self):
        with patch("ai_assistant.services.chat_with_ollama", side_effect=Exception("down")):
            res = proponi_tag("qualcosa")
        self.assertTrue(res["proposto"])
        self.assertEqual(res["tag"], "")
        self.assertFalse(res["ai_disponibile"])


@override_settings(OLLAMA_EMBED_ENABLED=False)  # forza il fallback lessicale: deterministico, no endpoint live
class RicercaSemanticaTests(TestCase):
    def test_ranking_lessicale_read_only(self):
        Specifica.objects.create(codice="SP-TT", titolo="Trattamento termico tolleranze lega")
        Specifica.objects.create(codice="SP-IM", titolo="Imballo e logistica spedizioni")
        risultati = ricerca_semantica("trattamento termico")
        codici = [r["codice"] for r in risultati]
        self.assertIn("SP-TT", codici)
        self.assertNotIn("SP-IM", codici)  # nessun overlap → score 0 → escluso
        self.assertTrue(all("score" in r for r in risultati))

    def test_query_vuota(self):
        self.assertEqual(ricerca_semantica(""), [])


class CopilotaViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("ai_su", "a@x.it", "x")
        self.client.force_login(self.su)

    def test_endpoint_precompila_non_salva(self):
        spec = Specifica.objects.create(codice="SP-EP", titolo="T")
        canned = _ai('[{"argomento":"X"}]')
        with patch("ai_assistant.services.chat_with_ollama", return_value=canned):
            r = self.client.get(reverse("gestione_specifiche:ai_precompila_mod133", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["proposto"])
        self.assertEqual(RigaMOD133.objects.count(), 0)  # INVARIANTE

    def test_endpoint_proponi_tag_non_salva(self):
        spec = Specifica.objects.create(codice="SP-ET", titolo="T")
        with patch("ai_assistant.services.chat_with_ollama", return_value=_ai("saldatura")):
            r = self.client.get(reverse("gestione_specifiche:ai_proponi_tag", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tag"], "saldatura")
        spec = Specifica.objects.get(pk=spec.pk)  # re-fetch (FSMField protected)
        self.assertEqual(spec.tag, "")  # INVARIANTE

    def test_endpoint_diff_non_salva(self):
        prev = Specifica.objects.create(codice="SP-DV", revisione="A", titolo="T")
        spec = Specifica.objects.create(codice="SP-DV", revisione="B", titolo="T",
                                        revisione_precedente=prev)
        testi = {"A": "vecchio requisito", "B": "nuovo requisito diverso aggiunto"}
        with patch("gestione_specifiche.ai_copilota._estrai_testo_specifica",
                   side_effect=lambda s: testi[s.revisione]), \
             patch("ai_assistant.services.chat_with_ollama", return_value=_ai('[{"argomento":"X"}]')):
            r = self.client.get(reverse("gestione_specifiche:ai_diff_mod133", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["proposto"])
        self.assertEqual(data["fonte"], "ai_diff")
        self.assertEqual(RigaMOD133.objects.count(), 0)  # INVARIANTE

    def test_pagina_compila_ha_pulsante_diff(self):
        # La pagina di compilazione MOD.133 mostra il pulsante «Confronta con revisione precedente».
        spec = Specifica.objects.create(codice="SP-CMP", titolo="T")
        spec.avvia_flow_down(attore=self.su)  # S1->S2, crea il MOD.133
        spec.save()
        r = self.client.get(reverse("gestione_specifiche:mod133_compila", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Confronta con revisione precedente")
        self.assertContains(r, "gsAiDiff")

    def test_pagina_ricerca(self):
        Specifica.objects.create(codice="SP-RIC", titolo="Trattamento superficiale")
        r = self.client.get(reverse("gestione_specifiche:ricerca"), {"q": "trattamento"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SP-RIC")

    def test_nessuna_transizione_automatica(self):
        # Le funzioni copilota non cambiano mai lo stato.
        spec = Specifica.objects.create(codice="SP-NT", titolo="T")
        with patch("ai_assistant.services.chat_with_ollama", return_value=_ai('[{"argomento":"X"}]')):
            proponi_righe_mod133(spec)
            proponi_tag("x")
        spec = Specifica.objects.get(pk=spec.pk)  # re-fetch (FSMField protected)
        self.assertEqual(spec.stato, C.STATO_BOZZA)
