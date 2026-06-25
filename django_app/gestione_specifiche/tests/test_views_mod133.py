"""Test F3 — flusso MOD.133 da UI (creazione/revisione, formset, claim, approvazione)."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from gestione_specifiche import constants as C
from gestione_specifiche.models import MOD133, RigaMOD133, Specifica
from gestione_specifiche.views import _incrementa_revisione

User = get_user_model()


def _formset_data(rows, total=None, initial=0):
    total = len(rows) if total is None else total
    data = {
        "righe-TOTAL_FORMS": str(total),
        "righe-INITIAL_FORMS": str(initial),
        "righe-MIN_NUM_FORMS": "0",
        "righe-MAX_NUM_FORMS": "1000",
    }
    for i, row in enumerate(rows):
        data[f"righe-{i}-id"] = row.get("id", "")
        data[f"righe-{i}-ordine"] = row.get("ordine", str(i + 1))
        for k, v in row.items():
            if k in ("id", "ordine"):
                continue
            data[f"righe-{i}-{k}"] = v
    return data


class IncrementoRevisioneTests(TestCase):
    def test_incrementi(self):
        self.assertEqual(_incrementa_revisione("0"), "1")
        self.assertEqual(_incrementa_revisione("1"), "2")
        self.assertEqual(_incrementa_revisione(""), "1")
        self.assertEqual(_incrementa_revisione("Rev2"), "Rev3")
        self.assertEqual(_incrementa_revisione("A"), "A.1")


class FlussoUITests(TestCase):
    def setUp(self):
        self.comp = User.objects.create_superuser("comp_ui", "c@x.it", "x")
        self.appr = User.objects.create_superuser("appr_ui", "a@x.it", "x")
        self.client.force_login(self.comp)

    def test_login_required(self):
        self.client.logout()
        r = self.client.get(reverse("gestione_specifiche:lista"))
        self.assertEqual(r.status_code, 302)

    def test_crea_specifica(self):
        r = self.client.post(reverse("gestione_specifiche:nuova"), {
            "codice": "SP-UI-1", "titolo": "Trattamento", "tipo": C.TIPO_SPECIFICA,
            "fonte": C.FONTE_CLIENTE, "revisione": "0",
        })
        self.assertEqual(r.status_code, 302)
        spec = Specifica.objects.get(codice="SP-UI-1")
        self.assertEqual(spec.stato, C.STATO_BOZZA)

    def test_nuova_revisione_eredita_e_incrementa(self):
        prev = Specifica.objects.create(codice="SP-UI-2", revisione="0", titolo="T", cliente="ACME")
        r = self.client.post(reverse("gestione_specifiche:nuova") + f"?da={prev.pk}", {
            "codice": "SP-UI-2", "titolo": "T", "tipo": C.TIPO_SPECIFICA,
            "fonte": C.FONTE_CLIENTE, "revisione": "1", "cliente": "ACME", "da": prev.pk,
        })
        self.assertEqual(r.status_code, 302)
        new = Specifica.objects.get(codice="SP-UI-2", revisione="1")
        self.assertEqual(new.revisione_precedente_id, prev.pk)

    def _crea_e_avvia(self, codice="SP-UI-FLOW"):
        spec = Specifica.objects.create(codice=codice, titolo="T")
        self.client.post(reverse("gestione_specifiche:avvia_flow_down", args=[spec.pk]))
        return Specifica.objects.get(pk=spec.pk)

    def test_avvia_flow_down_crea_mod133(self):
        spec = self._crea_e_avvia()
        self.assertEqual(spec.stato, C.STATO_FLOW_DOWN)
        self.assertTrue(MOD133.objects.filter(specifica=spec).exists())

    def test_compila_salva_righe(self):
        spec = self._crea_e_avvia("SP-UI-C")
        r = self.client.post(reverse("gestione_specifiche:mod133_compila", args=[spec.pk]),
                             _formset_data([
                                 {"ordine": "1", "argomento": "Tolleranze"},
                                 {"ordine": "2", "argomento": "Materiale"},
                             ]))
        self.assertEqual(r.status_code, 302)
        mod = MOD133.objects.get(specifica=spec)
        self.assertEqual(mod.righe.count(), 2)
        self.assertEqual(mod.compilatore_id, self.comp.id)  # claim implicito

    def test_compila_riga_senza_ordine(self):
        """La UI ridisegnata non mostra il campo 'ordine': una riga inviata
        senza ordine deve salvarsi (coerciato a 0), non fallire la validazione."""
        spec = self._crea_e_avvia("SP-UI-NOORD")
        r = self.client.post(reverse("gestione_specifiche:mod133_compila", args=[spec.pk]),
                             _formset_data([{"ordine": "", "argomento": "Senza ordine"}]))
        self.assertEqual(r.status_code, 302)
        riga = MOD133.objects.get(specifica=spec).righe.get()
        self.assertEqual(riga.argomento, "Senza ordine")
        self.assertEqual(riga.ordine, 0)

    def test_obbligatorieta_condizionale_documenti(self):
        spec = self._crea_e_avvia("SP-UI-COND")
        r = self.client.post(reverse("gestione_specifiche:mod133_compila", args=[spec.pk]),
                             _formset_data([
                                 {"ordine": "1", "argomento": "X", "impatto_documenti": "on"},
                             ]))
        self.assertEqual(r.status_code, 200)  # re-render con errori
        self.assertEqual(RigaMOD133.objects.filter(mod133__specifica=spec).count(), 0)
        self.assertContains(r, "Obbligatorio quando")

    def test_riga_add_htmx(self):
        spec = self._crea_e_avvia("SP-UI-ADD")
        r = self.client.get(reverse("gestione_specifiche:mod133_riga_add", args=[spec.pk]) + "?i=3")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "righe-3-argomento")

    def test_flusso_completo_s1_s2_s3(self):
        spec = self._crea_e_avvia("SP-UI-FULL")
        # compila (compilatore = comp)
        self.client.post(reverse("gestione_specifiche:mod133_compila", args=[spec.pk]),
                         _formset_data([{"ordine": "1", "argomento": "Req"}]))
        # chiudi compilazione
        self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[spec.pk]))
        mod = MOD133.objects.get(specifica=spec)
        self.assertIsNotNone(mod.data_chiusura_compilazione)
        self.assertEqual(mod.compilatore_id, self.comp.id)
        # approva come utente diverso
        self.client.force_login(self.appr)
        self.client.post(reverse("gestione_specifiche:mod133_approva", args=[spec.pk]),
                         {"esito": C.ESITO_APPROVATO})
        spec = Specifica.objects.get(pk=spec.pk)
        self.assertEqual(spec.stato, C.STATO_IN_VALIDITA)
        self.assertIsNotNone(spec.data_verifica)

    def test_approva_stesso_utente_fallisce(self):
        spec = self._crea_e_avvia("SP-UI-GUARD")
        self.client.post(reverse("gestione_specifiche:mod133_compila", args=[spec.pk]),
                         _formset_data([{"ordine": "1", "argomento": "Req"}]))
        self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[spec.pk]))
        # stesso utente (comp) prova ad approvare -> guardia fallisce, resta in FLOW_DOWN
        self.client.post(reverse("gestione_specifiche:mod133_approva", args=[spec.pk]),
                         {"esito": C.ESITO_APPROVATO})
        spec = Specifica.objects.get(pk=spec.pk)
        self.assertEqual(spec.stato, C.STATO_FLOW_DOWN)

    def test_respingi_va_in_s8(self):
        spec = self._crea_e_avvia("SP-UI-REJ")
        self.client.post(reverse("gestione_specifiche:mod133_compila", args=[spec.pk]),
                         _formset_data([{"ordine": "1", "argomento": "Req"}]))
        self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[spec.pk]))
        self.client.force_login(self.appr)
        self.client.post(reverse("gestione_specifiche:mod133_approva", args=[spec.pk]),
                         {"esito": C.ESITO_RESPINTO, "note": "fuori standard"})
        spec = Specifica.objects.get(pk=spec.pk)
        self.assertEqual(spec.stato, C.STATO_RESPINTO)


class TemplateRenderTests(TestCase):
    """Render GET dei template F3 (intercetta errori di template)."""

    def setUp(self):
        self.u = User.objects.create_superuser("render_u", "r@x.it", "x")
        self.client.force_login(self.u)

    def test_lista(self):
        self.assertEqual(self.client.get(reverse("gestione_specifiche:lista")).status_code, 200)

    def test_nuova_get(self):
        r = self.client.get(reverse("gestione_specifiche:nuova"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Nuova specifica")

    def test_dettaglio_get(self):
        spec = Specifica.objects.create(codice="SP-R", titolo="T")
        r = self.client.get(reverse("gestione_specifiche:dettaglio", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SP-R")

    def test_modifica_get(self):
        spec = Specifica.objects.create(codice="SP-RM", titolo="T")
        self.assertEqual(
            self.client.get(reverse("gestione_specifiche:modifica", args=[spec.pk])).status_code, 200)

    def test_approva_get(self):
        spec = Specifica.objects.create(codice="SP-RA", titolo="T")
        spec.avvia_flow_down()
        spec.save()
        r = self.client.get(reverse("gestione_specifiche:mod133_approva", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Approvazione MOD.133")

    def test_compila_get(self):
        spec = Specifica.objects.create(codice="SP-RC", titolo="T")
        spec.avvia_flow_down()
        spec.save()
        r = self.client.get(reverse("gestione_specifiche:mod133_compila", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Aggiungi riga")
