"""Copilota MOD.133 con lo storico: revisione precedente approvata, stesso cliente, apprendimento."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ai_assistant.models import AiProposta
from gestione_specifiche.ai_copilota import proponi_righe_mod133, proponi_tag
from gestione_specifiche.ai_storico import registra_esito_compilazione, registra_proposta_righe, storico_spec, storico_testo
from gestione_specifiche.models import MOD133, RigaMOD133, Specifica

CHAT = "ai_assistant.services.chat_with_ollama"


class StoricoSpecificheTests(TestCase):
    def _approvata(self, codice, revisione, righe, cliente="Cliente Demo", tag="", precedente=None):
        spec = Specifica.objects.create(codice=codice, revisione=revisione, titolo="Trattamento", cliente=cliente, tag=tag,
                                        revisione_precedente=precedente)
        mod = MOD133.objects.create(specifica=spec, data_approvazione=timezone.now())
        for i, (argomento, doc, tag_riga) in enumerate(righe):
            RigaMOD133.objects.create(mod133=mod, ordine=i, argomento=argomento, rif_doc_cn=doc, tag_processo=tag_riga)
        return spec

    def setUp(self):
        self.rev_a = self._approvata("SP-1", "A", [("Tolleranze di lavorazione", "IO-12", "meccanica"),
                                                   ("Marcatura pezzi", "IO-30", "marcatura")], tag="meccanica")
        self._approvata("SP-2", "C", [("Marcatura pezzi", "IO-30", "marcatura")], tag="marcatura")
        self._approvata("SP-3", "B", [("Marcatura pezzi", "IO-31", "marcatura")], tag="marcatura")
        self.nuova = Specifica.objects.create(codice="SP-1", revisione="B", titolo="Trattamento", cliente="Cliente Demo",
                                              revisione_precedente=self.rev_a)

    def test_storico_e_contesto(self):
        storico = storico_spec(self.nuova)
        self.assertEqual(storico["precedente"]["revisione"], "A")
        self.assertEqual([r["argomento"] for r in storico["precedente"]["righe"]], ["Tolleranze di lavorazione", "Marcatura pezzi"])
        self.assertEqual(storico["argomenti_cliente"][0]["argomento"], "Marcatura pezzi")  # SP-2 e SP-3
        self.assertEqual(storico["tag_cliente"][0], {"tag": "marcatura", "volte": 2})
        testo = storico_testo(storico)
        self.assertIn("MOD.133 APPROVATO della revisione precedente (SP-1 rev. A)", testo)

    def test_lo_storico_arriva_all_ai_nel_contesto_non_nel_prompt(self):
        with patch(CHAT, return_value=SimpleNamespace(content='[{"argomento":"Tolleranze di lavorazione"}]')) as chat:
            res = proponi_righe_mod133(self.nuova)
        self.assertEqual(res["storico"]["precedente"]["revisione"], "A")
        prompt, contesto = chat.call_args.args[0], chat.call_args.kwargs["runtime_context"]
        self.assertLess(len(prompt), 2000)  # il prompt viene tagliato a 2000: i testi lunghi stanno nel contesto
        self.assertIn("Tolleranze di lavorazione", contesto)
        with patch(CHAT, return_value=SimpleNamespace(content="marcatura")) as chat:
            self.assertEqual(proponi_tag("Marcatura laser dei pezzi", spec=self.nuova)["tag"], "marcatura")
        self.assertIn("TAG usati per le specifiche dello stesso cliente", chat.call_args.kwargs["runtime_context"])

    def test_apprende_dalla_chiusura_della_compilazione(self):
        user = get_user_model().objects.create(username="gs-ai")
        registra_proposta_righe(self.nuova, [{"argomento": "Tolleranze di lavorazione", "tag_processo": "meccanica"},
                                             {"argomento": "Marcatura pezzi", "tag_processo": "marcatura"}], user=user)
        mod = MOD133.objects.create(specifica=self.nuova)
        RigaMOD133.objects.create(mod133=mod, argomento="Tolleranze di lavorazione", tag_processo="meccanica")
        RigaMOD133.objects.create(mod133=mod, argomento="Marcatura pezzi", tag_processo="marcatura")
        registra_esito_compilazione(Specifica.objects.get(pk=self.nuova.pk), user=user)
        self.assertEqual(AiProposta.objects.get(azione="mod133_righe").esito, AiProposta.ACCETTATA)
