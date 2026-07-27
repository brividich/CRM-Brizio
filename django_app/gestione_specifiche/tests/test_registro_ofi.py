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
        resp = self.client.get(reverse("registro_ofi:lista"))
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
        r_all = self.client.get(reverse("registro_ofi:lista"))
        self.assertContains(r_all, "Da MOD.133")
        self.assertContains(r_all, "Da altrove")
        # registro del modulo: solo la sua
        r_mod = self.client.get(
            reverse("registro_ofi:lista"), {"modulo": "gestione_specifiche"})
        self.assertContains(r_mod, "Da MOD.133")
        self.assertNotContains(r_mod, "Da altrove")


class TopLevelUrlTests(TestCase):
    def test_lista_e_montata_al_top_level(self):
        """La rotta OFI è /ofi-registro/, non /gestione-specifiche/ofi-registro/."""
        self.assertEqual(reverse("registro_ofi:lista"), "/ofi-registro/")
        self.assertEqual(reverse("registro_ofi:nuovo"), "/ofi-registro/nuovo/")


class ReplicaMOD174Tests(RegistroBase):
    """La lista replica ESATTAMENTE il MOD.174 (intestazione, colonne, KPI)."""

    def setUp(self):
        super().setUp()
        self.su = get_user_model().objects.create_superuser("su_174", "s@x.it", "x")
        self.client.force_login(self.su)

    def test_intestazione_e_colonne_mod174(self):
        oggi = timezone.localdate()
        RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=oggi,
            processo="Trattamenti", opportunita="Migliorare X",
            norma_en9100=True, rif_norma="8.5.1")
        resp = self.client.get(reverse("registro_ofi:lista"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "MOD.174")
        # colonne fedeli all'Excel
        for col in ("REF", "OFI", "NC", "REF NORMA", "PROCESSO", "OPPORTUNITY",
                    "PLAN", "DO", "CHECK", "ACT", "OWNER", "TOT"):
            self.assertContains(resp, col)

    def test_kpi_over90(self):
        oggi = timezone.localdate()
        # 10 voci, 9 in ACT → A/P = 90% → ">90%"
        for _ in range(9):
            RegistroOFI.objects.create(numero=R.prossimo_numero(), data_apertura=oggi,
                                       fase=RegistroOFI.FASE_ACT)
        RegistroOFI.objects.create(numero=R.prossimo_numero(), data_apertura=oggi,
                                   fase=RegistroOFI.FASE_PLAN)
        resp = self.client.get(reverse("registro_ofi:lista"))
        self.assertContains(resp, "90%")


class ContatoriCumulativiTests(RegistroBase):
    def test_conta_pdca_cumulativo(self):
        oggi = timezone.localdate()
        for fase in (RegistroOFI.FASE_PLAN, RegistroOFI.FASE_DO,
                     RegistroOFI.FASE_CHECK, RegistroOFI.FASE_ACT):
            RegistroOFI.objects.create(numero=R.prossimo_numero(), data_apertura=oggi, fase=fase)
        c = R.conta_pdca_cumulativo()
        # P = tutte (raggiunte almeno PLAN), D = raggiunte almeno DO, ...
        self.assertEqual(c["p"], 4)
        self.assertEqual(c["d"], 3)
        self.assertEqual(c["c"], 2)
        self.assertEqual(c["a"], 1)
        self.assertEqual(c["tot"], 4)
        self.assertEqual(c["pct"], 25)  # 1/4


class InserimentoOFITests(RegistroBase):
    def setUp(self):
        super().setUp()
        self.su = get_user_model().objects.create_superuser("su_ins", "i@x.it", "x")
        self.client.force_login(self.su)

    def test_form_render_campi_mod174(self):
        resp = self.client.get(reverse("registro_ofi:nuovo"))
        self.assertEqual(resp.status_code, 200)
        # campi del MOD.174 presenti nel form
        for name in ("tipo", "data_apertura", "rif_norma", "processo",
                     "opportunita", "plan", "do", "verifica", "act",
                     "allegato_link", "owner_processo", "fase"):
            self.assertContains(resp, f'name="{name}"')

    def test_post_crea_voce_con_numero_automatico(self):
        atteso = R.prossimo_numero()
        resp = self.client.post(reverse("registro_ofi:nuovo"), {
            "tipo": RegistroOFI.TIPO_OFI,
            "data_apertura": timezone.localdate().isoformat(),
            "processo": "Collaudo",
            "opportunita": "Ridurre gli scarti",
            "fase": RegistroOFI.FASE_PLAN,
            "priorita": RegistroOFI.PRIORITA_MEDIA,
            "norma_en9100": "on",
            "rif_norma": "8.7",
            "owner_processo": "Rossi",
        })
        self.assertEqual(resp.status_code, 302)
        v = RegistroOFI.objects.get(numero=atteso)
        self.assertEqual(v.processo, "Collaudo")
        self.assertTrue(v.norma_en9100)

    def test_form_ha_campo_modulo_con_datalist(self):
        resp = self.client.get(reverse("registro_ofi:nuovo"))
        self.assertContains(resp, 'name="modulo_origine"')
        self.assertContains(resp, 'list="ofi-moduli"')
        self.assertContains(resp, '<datalist id="ofi-moduli"')

    def test_datalist_propone_moduli_esistenti(self):
        RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=timezone.localdate(),
            modulo_origine="gestione_specifiche")
        resp = self.client.get(reverse("registro_ofi:nuovo"))
        # l'etichetta leggibile è proposta nel datalist
        self.assertContains(resp, 'value="gestione_specifiche"')
        self.assertContains(resp, "Specifiche / MOD.133")

    def test_post_con_modulo_libero(self):
        atteso = R.prossimo_numero()
        resp = self.client.post(reverse("registro_ofi:nuovo"), {
            "tipo": RegistroOFI.TIPO_OFI,
            "data_apertura": timezone.localdate().isoformat(),
            "processo": "Verniciatura",
            "opportunita": "x",
            "fase": RegistroOFI.FASE_PLAN,
            "priorita": RegistroOFI.PRIORITA_MEDIA,
            "modulo_origine": "produzione",
        })
        self.assertEqual(resp.status_code, 302)
        v = RegistroOFI.objects.get(numero=atteso)
        self.assertEqual(v.modulo_origine, "produzione")

    def test_dettaglio_render(self):
        v = RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=timezone.localdate(),
            processo="Saldatura", opportunita="Rivedere il WPS",
            fase=RegistroOFI.FASE_CHECK)
        resp = self.client.get(reverse("registro_ofi:dettaglio", args=[v.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Saldatura")
        self.assertContains(resp, "MOD.174")

    def test_post_modifica_aggiorna(self):
        v = RegistroOFI.objects.create(
            numero=R.prossimo_numero(), data_apertura=timezone.localdate(),
            processo="Vecchio", fase=RegistroOFI.FASE_PLAN)
        resp = self.client.post(reverse("registro_ofi:modifica", args=[v.pk]), {
            "tipo": RegistroOFI.TIPO_OFI,
            "data_apertura": timezone.localdate().isoformat(),
            "processo": "Nuovo",
            "opportunita": "x",
            "fase": RegistroOFI.FASE_DO,
            "priorita": RegistroOFI.PRIORITA_ALTA,
        })
        self.assertEqual(resp.status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.processo, "Nuovo")
        self.assertEqual(v.fase, RegistroOFI.FASE_DO)


class AclBindingTests(TestCase):
    def test_rotte_ofi_hanno_binding_canonico(self):
        from gestione_specifiche import acl_bootstrap as B
        self.assertEqual(B._ROUTE_BINDINGS["registro_ofi:lista"], B.PERM_VIEW)
        self.assertEqual(B._ROUTE_BINDINGS["registro_ofi:nuovo"], B.PERM_OFI_ADD)
        self.assertEqual(B._ROUTE_BINDINGS["registro_ofi:modifica"], B.PERM_OFI_ADD)
