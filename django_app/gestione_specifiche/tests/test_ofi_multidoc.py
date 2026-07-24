"""Test 4.1 — più documenti impattanti sulla stessa riga MOD.133.

Una riga può impattare più documenti CN: oltre al documento **primario**
(`rif_doc_cn`, invariato) una tabella figlia `RigaMOD133Documento` elenca i
documenti **ulteriori**. La generazione OFI crea **una azione per documento
impattato** (idempotente per documento). Il composito MOD.133 li elenca tutti.
Nessun dato reale.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from gestione_specifiche.composito import dati_mod133_da_spec
from gestione_specifiche.models import (
    AzioneOFI,
    RigaMOD133,
    RigaMOD133Documento,
    Specifica,
)
from gestione_specifiche.ofi import crea_ofi_da_riga, documenti_riga


class MultiDocBase(TestCase):
    def setUp(self):
        self.dm = get_user_model().objects.create_user("dm_md", password="x")

    def _riga(self, *, doc="CN-100", genera=True):
        spec = Specifica.objects.create(codice=f"SP-MD-{doc}", titolo="T")
        spec.avvia_flow_down(attore=self.dm)
        spec.save()
        mod = spec.mod133
        riga = RigaMOD133.objects.create(
            mod133=mod, ordine=1, argomento="A", genera_ofi=genera,
            impatto_documenti=True, rif_doc_cn=doc,
        )
        return spec, mod, riga


class DocumentiRigaTests(MultiDocBase):
    def test_solo_primario(self):
        spec, mod, riga = self._riga(doc="CN-100")
        self.assertEqual(documenti_riga(riga), ["CN-100"])

    def test_primario_piu_figli(self):
        spec, mod, riga = self._riga(doc="CN-100")
        RigaMOD133Documento.objects.create(riga=riga, codice_documento="CN-200")
        RigaMOD133Documento.objects.create(riga=riga, codice_documento="CN-300")
        self.assertEqual(documenti_riga(riga), ["CN-100", "CN-200", "CN-300"])

    def test_dedup_figlio_uguale_primario(self):
        spec, mod, riga = self._riga(doc="CN-100")
        RigaMOD133Documento.objects.create(riga=riga, codice_documento="CN-100")
        self.assertEqual(documenti_riga(riga), ["CN-100"])


class OFIMultiDocTests(MultiDocBase):
    def test_una_azione_per_documento(self):
        spec, mod, riga = self._riga(doc="CN-100")
        RigaMOD133Documento.objects.create(riga=riga, codice_documento="CN-200")
        crea_ofi_da_riga(riga, attore=None)
        docs = set(AzioneOFI.objects.filter(riga_mod133=riga).values_list("documento_cn", flat=True))
        self.assertEqual(docs, {"CN-100", "CN-200"})

    def test_stesso_numero_ofi_per_riga(self):
        spec, mod, riga = self._riga(doc="CN-100")
        RigaMOD133Documento.objects.create(riga=riga, codice_documento="CN-200")
        crea_ofi_da_riga(riga, attore=None)
        numeri = set(AzioneOFI.objects.filter(riga_mod133=riga).values_list("ofi", flat=True))
        self.assertEqual(len(numeri), 1)  # unico numero OFI per la riga

    def test_idempotente_per_documento(self):
        spec, mod, riga = self._riga(doc="CN-100")
        RigaMOD133Documento.objects.create(riga=riga, codice_documento="CN-200")
        crea_ofi_da_riga(riga, attore=None)
        crea_ofi_da_riga(riga, attore=None)
        self.assertEqual(AzioneOFI.objects.filter(riga_mod133=riga).count(), 2)

    def test_singolo_documento_compat(self):
        # comportamento storico: una riga con solo rif_doc_cn → una azione
        spec, mod, riga = self._riga(doc="CN-9")
        az = crea_ofi_da_riga(riga, attore=None)
        self.assertEqual(az.documento_cn, "CN-9")
        self.assertEqual(AzioneOFI.objects.filter(riga_mod133=riga).count(), 1)


class CompositoMultiDocTests(MultiDocBase):
    def test_composito_include_documenti_figli(self):
        spec, mod, riga = self._riga(doc="CN-100")
        RigaMOD133Documento.objects.create(riga=riga, codice_documento="CN-200")
        dati = dati_mod133_da_spec(spec)
        self.assertIn("CN-100", dati["documenti_cn_interessati"])
        self.assertIn("CN-200", dati["documenti_cn_interessati"])


class DocumentoEndpointTests(MultiDocBase):
    def setUp(self):
        # superuser per la client: bypassa l'ACL middleware come in OFIViewTests.
        self.dm = get_user_model().objects.create_superuser("dm_ep", "ep@x.it", "x")
        self.client.force_login(self.dm)

    def test_add_e_delete_documento(self):
        spec, mod, riga = self._riga(doc="CN-100")  # in flow-down (S2)
        # aggiunta
        r = self.client.post(
            reverse("gestione_specifiche:riga_documento_add", args=[spec.pk, riga.pk]),
            {"codice_documento": "CN-777", "rif_paragrafo": "§3"})
        self.assertEqual(r.status_code, 302)
        d = RigaMOD133Documento.objects.get(riga=riga, codice_documento="CN-777")
        self.assertEqual(d.rif_paragrafo, "§3")
        # rimozione
        r2 = self.client.post(
            reverse("gestione_specifiche:riga_documento_delete", args=[spec.pk, d.pk]))
        self.assertEqual(r2.status_code, 302)
        self.assertFalse(RigaMOD133Documento.objects.filter(pk=d.pk).exists())

    def test_add_codice_vuoto_non_crea(self):
        spec, mod, riga = self._riga(doc="CN-100")
        r = self.client.post(
            reverse("gestione_specifiche:riga_documento_add", args=[spec.pk, riga.pk]),
            {"codice_documento": "  "})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(riga.documenti.count(), 0)
