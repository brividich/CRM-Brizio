"""Test F5 — generazione OFI su conferma, idempotenza, 3 modi di approvazione."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from gestione_specifiche import constants as C
from gestione_specifiche.models import AzioneOFI, MOD133, RigaMOD133, Specifica
from gestione_specifiche.ofi import approva_azione_ofi, crea_ofi_da_riga

User = get_user_model()


class OFIBase(TestCase):
    def setUp(self):
        self.dm = User.objects.create_user("dm_ofi", password="x")
        self.comp = User.objects.create_user("comp_ofi", password="x")
        self.appr = User.objects.create_user("appr_ofi", password="x")
        self.altro = User.objects.create_user("altro_ofi", password="x")

    def _riga(self, *, genera=True, codice="SP-OFI", doc="CN-100"):
        spec = Specifica.objects.create(codice=codice, titolo="T")
        spec.avvia_flow_down(attore=self.dm)
        spec.save()
        mod = spec.mod133
        mod.compilatore = self.comp
        mod.approvatore = self.appr
        mod.save()
        riga = RigaMOD133.objects.create(
            mod133=mod, ordine=1, argomento="A", genera_ofi=genera, rif_doc_cn=doc,
        )
        return spec, mod, riga


class ApprovazioneOFIStatoTests(OFIBase):
    def test_azione_gia_decisa_non_ribaltabile(self):
        # M7: una volta approvata/respinta, l'azione OFI non e' piu' modificabile.
        spec, mod, riga = self._riga()
        az = crea_ofi_da_riga(riga, attore=self.dm)
        approva_azione_ofi(az, approvatore=self.appr, esito=C.AZIONE_OFI_APPROVATA)
        with self.assertRaises(ValidationError):
            approva_azione_ofi(az, approvatore=self.appr, esito=C.AZIONE_OFI_RESPINTA)


class CreazioneOFITests(OFIBase):
    def test_crea_su_conferma(self):
        spec, mod, riga = self._riga()
        az = crea_ofi_da_riga(riga, attore=self.dm)
        self.assertIsNotNone(az.ofi)
        riga.refresh_from_db()
        self.assertEqual(riga.ofi, az.ofi)
        self.assertEqual(az.documento_cn, "CN-100")
        self.assertEqual(az.stato, C.AZIONE_OFI_BOZZA)
        self.assertTrue(spec.eventi.filter(trigger="ofi_creato").exists())

    def test_idempotenza(self):
        spec, mod, riga = self._riga()
        az1 = crea_ofi_da_riga(riga, attore=self.dm)
        az2 = crea_ofi_da_riga(riga, attore=self.dm)
        self.assertEqual(az1.pk, az2.pk)
        self.assertEqual(AzioneOFI.objects.filter(riga_mod133=riga).count(), 1)

    def test_richiede_genera_ofi(self):
        spec, mod, riga = self._riga(genera=False)
        with self.assertRaises(ValidationError):
            crea_ofi_da_riga(riga, attore=self.dm)

    @override_settings(GESTIONE_SPECIFICHE={"APPROVAZIONE_DOC_CN_MODE": C.APPROV_RDD})
    def test_modo_default_da_settings(self):
        spec, mod, riga = self._riga()
        az = crea_ofi_da_riga(riga, attore=self.dm)
        self.assertEqual(az.modo_approvazione, C.APPROV_RDD)


class ApprovazioneModiTests(OFIBase):
    def _azione(self, modo, codice):
        spec, mod, riga = self._riga(codice=codice)
        az = crea_ofi_da_riga(riga, attore=self.dm)
        az.modo_approvazione = modo
        az.save(update_fields=["modo_approvazione"])
        return spec, mod, az

    def test_mod133_approver_solo_approvatore_mod133(self):
        spec, mod, az = self._azione(C.APPROV_MOD133, "SP-M1")
        # un utente diverso dall'approvatore MOD.133 non può approvare
        with self.assertRaises(ValidationError):
            approva_azione_ofi(az, approvatore=self.altro)
        # l'approvatore del MOD.133 può
        approva_azione_ofi(az, approvatore=self.appr)
        az.refresh_from_db()
        self.assertEqual(az.stato, C.AZIONE_OFI_APPROVATA)
        self.assertEqual(az.approvatore_id, self.appr.id)

    def test_car_flow_approvatore_generico(self):
        spec, mod, az = self._azione(C.APPROV_CAR_FLOW, "SP-M2")
        approva_azione_ofi(az, approvatore=self.altro)
        az.refresh_from_db()
        self.assertEqual(az.stato, C.AZIONE_OFI_APPROVATA)

    def test_rdd_dedicato_approvatore_dedicato(self):
        spec, mod, az = self._azione(C.APPROV_RDD, "SP-M3")
        approva_azione_ofi(az, approvatore=self.altro)
        az.refresh_from_db()
        self.assertEqual(az.stato, C.AZIONE_OFI_APPROVATA)

    def test_respingi(self):
        spec, mod, az = self._azione(C.APPROV_CAR_FLOW, "SP-M4")
        approva_azione_ofi(az, approvatore=self.altro, esito=C.AZIONE_OFI_RESPINTA)
        az.refresh_from_db()
        self.assertEqual(az.stato, C.AZIONE_OFI_RESPINTA)
        self.assertTrue(spec.eventi.filter(trigger="azione_ofi_approvata").exists())


class OFIViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su_ofi", "s@x.it", "x")
        self.client.force_login(self.su)

    def test_genera_ofi_e_approva_da_view(self):
        altro = User.objects.create_user("altro_vofi", password="x")
        spec = Specifica.objects.create(codice="SP-VOFI", titolo="T")
        spec.avvia_flow_down(attore=self.su)
        spec.save()
        riga = RigaMOD133.objects.create(
            mod133=spec.mod133, ordine=1, argomento="A", genera_ofi=True, rif_doc_cn="CN-9",
        )
        # OFI generabile solo in validita' (S3): porta la specifica in S3.
        mod = spec.mod133
        mod.compilatore = altro
        mod.approvatore = self.su
        mod.esito = C.ESITO_APPROVATO
        mod.save()
        spec.approva_flow_down(attore=self.su)
        spec.save()
        r = self.client.post(reverse("gestione_specifiche:riga_genera_ofi", args=[spec.pk, riga.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AzioneOFI.objects.filter(riga_mod133=riga).exists())
        # dettaglio mostra la sezione Azioni OFI
        r2 = self.client.get(reverse("gestione_specifiche:dettaglio", args=[spec.pk]))
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, "Azioni OFI")
        # approvazione via view (car_flow default)
        az = AzioneOFI.objects.get(riga_mod133=riga)
        r3 = self.client.post(reverse("gestione_specifiche:azione_ofi_approva", args=[az.pk]),
                              {"esito": C.AZIONE_OFI_APPROVATA})
        self.assertEqual(r3.status_code, 302)
        az.refresh_from_db()
        self.assertEqual(az.stato, C.AZIONE_OFI_APPROVATA)
