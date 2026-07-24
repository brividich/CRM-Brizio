"""Test 4.2 — Registro OFI centralizzato (PDCA, allineato MOD.174).

Registro trasversale delle Opportunità di Miglioramento / Non Conformità con
ciclo PLAN-DO-CHECK-ACT, priorità, proprietario/owner di processo, scadenza e
reminder. Le righe MOD.133 con impatto confluiscono creando la voce di registro;
le azioni OFI vi si collegano via FK. Nessun dato reale.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gestione_specifiche.models import (
    AzioneOFI,
    RegistroOFI,
    RigaMOD133,
    Specifica,
)
from gestione_specifiche.ofi import crea_ofi_da_riga
from gestione_specifiche import registro_ofi as R


class RegistroBase(TestCase):
    def setUp(self):
        self.dm = get_user_model().objects.create_user("dm_reg", password="x")

    def _riga(self, *, doc="CN-100", genera=True, tag="Trattamenti"):
        spec = Specifica.objects.create(codice=f"SP-REG-{doc}", titolo="T")
        spec.avvia_flow_down(attore=self.dm)
        spec.save()
        riga = RigaMOD133.objects.create(
            mod133=spec.mod133, ordine=1, argomento="A", genera_ofi=genera,
            impatto_documenti=True, rif_doc_cn=doc, tag_processo=tag,
            descrizione_impatto="Serve aggiornare la procedura X.",
        )
        return spec, riga


class RegistroModelTests(RegistroBase):
    def test_scaduto_se_richiesta_passata_e_non_chiuso(self):
        v = RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=timezone.localdate(),
            data_richiesta=timezone.localdate() - timedelta(days=1))
        self.assertTrue(v.is_scaduto)
        self.assertFalse(v.is_chiuso)

    def test_non_scaduto_se_chiuso(self):
        v = RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=timezone.localdate(),
            data_richiesta=timezone.localdate() - timedelta(days=1),
            fase=RegistroOFI.FASE_CHIUSO, data_chiusura=timezone.localdate())
        self.assertFalse(v.is_scaduto)
        self.assertTrue(v.is_chiuso)


class NumerazioneTests(RegistroBase):
    def test_numeri_progressivi_senza_collisione(self):
        n1 = R.prossimo_numero()
        RegistroOFI.objects.create(numero=n1, data_apertura=timezone.localdate())
        n2 = R.prossimo_numero()
        self.assertEqual(n2, n1 + 1)


class CreazioneDaRigaTests(RegistroBase):
    def test_registro_da_riga_crea_voce(self):
        spec, riga = self._riga(tag="Trattamenti termici")
        voce = R.registro_da_riga(riga)
        self.assertEqual(voce.processo, "Trattamenti termici")
        self.assertIn("procedura X", voce.opportunita)
        self.assertEqual(voce.fase, RegistroOFI.FASE_PLAN)
        # origine tracciata verso la riga
        self.assertEqual(voce.object_id, riga.id)

    def test_registro_da_riga_idempotente(self):
        spec, riga = self._riga()
        v1 = R.registro_da_riga(riga)
        v2 = R.registro_da_riga(riga)
        self.assertEqual(v1.pk, v2.pk)


class IntegrazioneOFITests(RegistroBase):
    def test_genera_ofi_collega_registro(self):
        spec, riga = self._riga(doc="CN-1")
        az = crea_ofi_da_riga(riga, attore=self.dm)
        az.refresh_from_db()
        self.assertIsNotNone(az.registro_id)
        self.assertEqual(az.registro.numero, az.ofi)

    def test_registro_condiviso_tra_azioni_stessa_riga(self):
        from gestione_specifiche.models import RigaMOD133Documento
        spec, riga = self._riga(doc="CN-1")
        RigaMOD133Documento.objects.create(riga=riga, codice_documento="CN-2")
        crea_ofi_da_riga(riga, attore=self.dm)
        registri = set(AzioneOFI.objects.filter(riga_mod133=riga).values_list("registro_id", flat=True))
        self.assertEqual(len(registri), 1)  # unica voce di registro per la riga


class ContatoriPDCATests(RegistroBase):
    def test_conta_pdca(self):
        oggi = timezone.localdate()
        for fase in (RegistroOFI.FASE_PLAN, RegistroOFI.FASE_PLAN,
                     RegistroOFI.FASE_DO, RegistroOFI.FASE_CHIUSO):
            RegistroOFI.objects.create(numero=R.prossimo_numero(), data_apertura=oggi, fase=fase)
        c = R.conta_pdca()
        self.assertEqual(c["plan"], 2)
        self.assertEqual(c["do"], 1)
        self.assertEqual(c["chiuso"], 1)
        self.assertEqual(c["tot"], 4)


class ReminderTests(RegistroBase):
    def test_voci_da_sollecitare(self):
        oggi = timezone.localdate()
        # scaduta, aperta, reminder attivo, non inviato → da sollecitare
        v1 = RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=oggi,
            data_richiesta=oggi - timedelta(days=2))
        # chiusa → esclusa
        RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=oggi,
            data_richiesta=oggi - timedelta(days=2), fase=RegistroOFI.FASE_CHIUSO,
            data_chiusura=oggi)
        # reminder disattivato → esclusa
        RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=oggi,
            data_richiesta=oggi - timedelta(days=2), reminder_attivo=False)
        # senza data_richiesta → esclusa
        RegistroOFI.objects.create(numero=R.prossimo_numero(), data_apertura=oggi)
        da = R.voci_da_sollecitare(oggi=oggi)
        self.assertEqual([v.pk for v in da], [v1.pk])

    def test_invio_dry_run_non_marca(self):
        oggi = timezone.localdate()
        v = RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=oggi,
            data_richiesta=oggi - timedelta(days=1))
        res = R.invia_reminder_ofi(oggi=oggi, dry_run=True)
        self.assertEqual(res["candidate"], 1)
        self.assertEqual(res["inviati"], 0)
        v.refresh_from_db()
        self.assertFalse(v.reminder_inviato)

    def test_invio_marca_inviato(self):
        oggi = timezone.localdate()
        v = RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=oggi,
            data_richiesta=oggi - timedelta(days=1))
        res = R.invia_reminder_ofi(oggi=oggi)
        self.assertEqual(res["inviati"], 1)
        v.refresh_from_db()
        self.assertTrue(v.reminder_inviato)
        # seconda esecuzione: nulla da sollecitare (già inviato)
        self.assertEqual(R.invia_reminder_ofi(oggi=oggi)["candidate"], 0)


class RegistroViewTests(RegistroBase):
    def setUp(self):
        super().setUp()
        self.su = get_user_model().objects.create_superuser("su_reg", "sr@x.it", "x")
        self.client.force_login(self.su)

    def test_render_registro(self):
        RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=timezone.localdate(),
            processo="Trattamenti", opportunita="Migliorare X")
        resp = self.client.get(reverse("gestione_specifiche:ofi_registro"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Registro OFI")
        self.assertContains(resp, "Trattamenti")

    def test_filtro_per_modulo(self):
        oggi = timezone.localdate()
        RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=oggi,
            modulo_origine="gestione_specifiche", processo="Da MOD.133")
        RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=oggi,
            modulo_origine="altro_modulo", processo="Da altrove")
        # registro unico: entrambe
        r_all = self.client.get(reverse("gestione_specifiche:ofi_registro"))
        self.assertContains(r_all, "Da MOD.133")
        self.assertContains(r_all, "Da altrove")
        # registro del modulo: solo la sua
        r_mod = self.client.get(
            reverse("gestione_specifiche:ofi_registro"), {"modulo": "gestione_specifiche"})
        self.assertContains(r_mod, "Da MOD.133")
        self.assertNotContains(r_mod, "Da altrove")
