"""Test F1 — modelli, default, immutabilità audit, wiring M2M reparto."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from gestione_specifiche import constants as C
from gestione_specifiche.models import (
    AzioneOFI, Distribuzione, EventoSpecifica, MOD133, RigaMOD133, Specifica,
)


class SpecificaModelTests(TestCase):
    def test_default_state_and_str(self):
        spec = Specifica.objects.create(codice="SP-001", titolo="Trattamento X")
        self.assertEqual(spec.stato, C.STATO_BOZZA)
        self.assertTrue(spec.is_attiva)
        self.assertIn("SP-001", str(spec))

    def test_snapshot_metadati_keys(self):
        spec = Specifica.objects.create(codice="SP-002", revisione="1", titolo="Y", cliente="ACME")
        snap = spec.snapshot_metadati()
        for key in ("codice", "revisione", "titolo", "tipo", "fonte", "cliente", "stato", "data_verifica"):
            self.assertIn(key, snap)
        self.assertEqual(snap["codice"], "SP-002")
        self.assertIsNone(snap["data_verifica"])

    def test_revisione_precedente_protect(self):
        prev = Specifica.objects.create(codice="SP-003", revisione="0", titolo="Z")
        new = Specifica.objects.create(codice="SP-003", revisione="1", titolo="Z", revisione_precedente=prev)
        self.assertEqual(new.revisione_precedente_id, prev.id)
        self.assertIn(new, prev.revisioni_successive.all())


class EventoImmutabileTests(TestCase):
    def setUp(self):
        self.spec = Specifica.objects.create(codice="SP-010", titolo="Audit")

    def test_event_create_ok(self):
        evt = EventoSpecifica.objects.create(
            specifica=self.spec, stato_da="", stato_a=C.STATO_BOZZA, trigger="init",
        )
        self.assertIsNotNone(evt.pk)

    def test_event_update_blocked(self):
        evt = EventoSpecifica.objects.create(specifica=self.spec, stato_a=C.STATO_BOZZA)
        evt.trigger = "modificato"
        with self.assertRaises(ValidationError):
            evt.save()

    def test_event_delete_blocked(self):
        evt = EventoSpecifica.objects.create(specifica=self.spec, stato_a=C.STATO_BOZZA)
        with self.assertRaises(ValidationError):
            evt.delete()


class AzioneOFIDefaultTests(TestCase):
    def _build_riga(self):
        spec = Specifica.objects.create(codice="SP-020", titolo="OFI")
        mod = MOD133.objects.create(specifica=spec)
        return RigaMOD133.objects.create(mod133=mod, ordine=1, argomento="A")

    @override_settings(GESTIONE_SPECIFICHE={"APPROVAZIONE_DOC_CN_MODE": C.APPROV_RDD})
    def test_modo_approvazione_default_from_settings(self):
        riga = self._build_riga()
        az = AzioneOFI.objects.create(riga_mod133=riga, documento_cn="CN-1")
        self.assertEqual(az.modo_approvazione, C.APPROV_RDD)

    def test_modo_approvazione_explicit_preserved(self):
        riga = self._build_riga()
        az = AzioneOFI.objects.create(
            riga_mod133=riga, documento_cn="CN-2", modo_approvazione=C.APPROV_MOD133,
        )
        self.assertEqual(az.modo_approvazione, C.APPROV_MOD133)


class DistribuzioneRepartoTests(TestCase):
    def test_m2m_reparto_destinatari(self):
        from anagrafica.models import Reparto

        rep = Reparto.objects.create(nome="Produzione GS-test")
        spec = Specifica.objects.create(codice="SP-030", titolo="Distrib")
        dist = Distribuzione.objects.create(specifica=spec, canale=C.CANALE_NOTIFICA)
        dist.destinatari.add(rep)
        self.assertEqual(dist.destinatari.count(), 1)
        self.assertIn(dist, rep.distribuzioni_specifiche.all())
