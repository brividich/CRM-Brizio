"""Modulo Registro OFI / NC: dashboard, «Le mie voci», permessi e collegamenti con i processi.

Nessun dato reale: utenti, processi e voci sintetici.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from gestione_specifiche import registro_ofi as R
from gestione_specifiche.forms import RegistroOFIForm
from gestione_specifiche.models import RegistroOFI
from sistema_gestione.models import Processo

from . import collegamenti


def _voce(**kw):
    dati = {"numero": R.prossimo_numero(), "data_apertura": timezone.localdate()}
    dati.update(kw)
    return RegistroOFI.objects.create(**dati)


def _permessi(*codici):
    """Patch del controllo permessi delle viste: concessi solo i codici indicati."""
    return patch("registro_ofi.views.request_has_permission_code",
                 side_effect=lambda request, code: code in codici)


class ProcessoDaTestoTests(TestCase):
    def setUp(self):
        self.prd = Processo.objects.create(codice="PRC-07", nome="Produzione")
        self.acq = Processo.objects.create(codice="PRC-08", nome="Acquisti")

    def test_codice_nome_e_codice_in_testa(self):
        for testo in ("PRC-07", "prc-07", "Produzione", "PRC-07 - Produzione", "PRC-07 · reparto CNC"):
            self.assertEqual(R.processo_da_testo(testo), self.prd, testo)

    def test_testo_ambiguo_o_libero_resta_scollegato(self):
        for testo in ("", "Produzione, Acquisti", "Officina", "PRC-0"):
            self.assertIsNone(R.processo_da_testo(testo), testo)

    def test_la_voce_si_collega_da_sola(self):
        v = _voce(processo="PRC-08 - Acquisti")
        self.assertEqual(v.processo_sgi, self.acq)
        v = _voce(processo_sgi=self.prd)
        self.assertEqual(v.processo, "PRC-07 - Produzione")
        v = _voce(processo="Officina")
        self.assertIsNone(v.processo_sgi_id)

    def test_save_con_update_fields_salva_anche_il_collegamento(self):
        v = _voce(processo="Officina")
        v.processo = "Produzione"
        v.save(update_fields=["processo"])
        v.refresh_from_db()
        self.assertEqual(v.processo_sgi, self.prd)


class FormProcessoTests(TestCase):
    def setUp(self):
        self.resp = get_user_model().objects.create_user("resp_proc", password="x")
        self.processo = Processo.objects.create(codice="PRC-09", nome="Collaudo", responsabile=self.resp)

    def _dati(self, **kw):
        dati = {"tipo": "OFI", "data_apertura": timezone.localdate().isoformat(), "fase": "PLAN",
                "priorita": "MEDIA", "processo_sgi": self.processo.pk}
        dati.update(kw)
        return dati

    def test_scelto_il_processo_si_compilano_testo_e_responsabile(self):
        form = RegistroOFIForm(self._dati())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["processo"], "PRC-09 - Collaudo")
        self.assertEqual(form.cleaned_data["responsabile"], self.resp)

    def test_responsabile_scelto_resta(self):
        altro = get_user_model().objects.create_user("altro_proc", password="x")
        form = RegistroOFIForm(self._dati(responsabile=altro.pk))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["responsabile"], altro)


class VisteModuloTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.qualita = User.objects.create_user("ofi_qualita", password="x")
        self.resp = User.objects.create_user("ofi_resp", password="x", first_name="Rita", last_name="Prova")
        self.altro = User.objects.create_user("ofi_altro", password="x")
        for u in (self.qualita, self.resp, self.altro):
            UserOnboarding.objects.create(user=u, completed=True)
        self.processo = Processo.objects.create(codice="PRC-10", nome="Manutenzione", responsabile=self.resp)
        oggi = timezone.localdate()
        self.mia = _voce(responsabile=self.resp, processo_sgi=self.processo, tipo=RegistroOFI.TIPO_NC,
                         data_richiesta=oggi - timedelta(days=2), opportunita="Registrazioni mancanti")
        # Voce senza responsabile e senza processo: la dashboard non deve rompersi.
        self.orfana = _voce(processo="Officina", data_richiesta=oggi + timedelta(days=10))
        acl = patch("core.middleware.resolve_acl_access", return_value={"allowed": True})
        acl.start()
        self.addCleanup(acl.stop)

    def test_dashboard_completa_per_chi_consulta_il_registro(self):
        from .acl_bootstrap import PERM_OFI_VIEW
        self.client.force_login(self.qualita)
        with _permessi(PERM_OFI_VIEW):
            r = self.client.get(reverse("registro_ofi:home"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Da dove arrivano le voci")
        self.assertContains(r, "senza responsabile")
        self.assertContains(r, reverse("sistema_gestione:processo_dettaglio", args=[self.processo.pk]) + "#ofi")
        self.assertContains(r, reverse("registro_ofi:dettaglio", args=[self.orfana.pk]))
        self.assertNotContains(r, "{#")

    def test_dashboard_del_responsabile_mostra_solo_il_suo_lavoro(self):
        self.client.force_login(self.resp)
        with _permessi():
            r = self.client.get(reverse("registro_ofi:home"))
        self.assertContains(r, f"NC {self.mia.numero}")
        self.assertNotContains(r, reverse("registro_ofi:dettaglio", args=[self.orfana.pk]))
        self.assertNotContains(r, "Da dove arrivano le voci")

    def test_scheda_visibile_al_responsabile_non_agli_altri(self):
        url = reverse("registro_ofi:dettaglio", args=[self.mia.pk])
        self.client.force_login(self.resp)
        with _permessi():
            r = self.client.get(url)
        self.assertContains(r, "Collegamenti")
        self.assertContains(r, "PRC-10 - Manutenzione")
        self.client.force_login(self.altro)
        with _permessi():
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_le_mie_voci(self):
        self.client.force_login(self.resp)
        with _permessi():
            r = self.client.get(reverse("registro_ofi:mie"))
        self.assertContains(r, reverse("registro_ofi:dettaglio", args=[self.mia.pk]))
        self.assertContains(r, "inserita a mano")
        self.assertNotContains(r, reverse("registro_ofi:dettaglio", args=[self.orfana.pk]))

    def test_filtri_del_registro(self):
        from .acl_bootstrap import PERM_OFI_VIEW
        self.client.force_login(self.qualita)
        casi = {"?processo=%d" % self.processo.pk: (self.mia,), "?processo=0": (self.orfana,),
                "?senza_responsabile=1": (self.orfana,), "?in_scadenza=1": (self.orfana,),
                "?origine=manuale": (self.mia, self.orfana), "?origine=audit_interno": ()}
        for query, attese in casi.items():
            with _permessi(PERM_OFI_VIEW):
                r = self.client.get(reverse("registro_ofi:lista") + query)
            self.assertEqual([v.pk for v in r.context["voci"]], sorted([v.pk for v in attese], reverse=True), query)

    def test_nuova_voce_dalla_scheda_processo(self):
        from gestione_specifiche.acl_bootstrap import PERM_OFI_ADD
        self.client.force_login(self.qualita)
        url = reverse("registro_ofi:nuovo") + f"?processo={self.processo.pk}"
        with _permessi(PERM_OFI_ADD):
            r = self.client.get(url)
            self.assertEqual(r.context["form"].initial["processo_sgi"], self.processo.pk)
            self.assertEqual(r.context["form"].initial["responsabile"], self.resp.pk)
            r = self.client.post(url, {"tipo": "OFI", "data_apertura": timezone.localdate().isoformat(),
                                       "fase": "PLAN", "priorita": "MEDIA", "processo_sgi": self.processo.pk,
                                       "opportunita": "Ridurre i fermi"})
        voce = RegistroOFI.objects.get(opportunita="Ridurre i fermi")
        self.assertRedirects(r, reverse("registro_ofi:dettaglio", args=[voce.pk]), fetch_redirect_response=False)
        self.assertEqual((voce.processo_sgi, voce.responsabile), (self.processo, self.resp))
        self.assertIn("PRC-10", voce.eventi.get().nota)

    def test_vecchio_cruscotto_porta_alla_dashboard(self):
        self.client.force_login(self.qualita)
        r = self.client.get(reverse("registro_ofi:cruscotto") + "?modulo=x")
        self.assertRedirects(r, reverse("registro_ofi:home") + "?modulo=x", fetch_redirect_response=False)

    @patch("sistema_gestione.processi_views._has_perm", return_value=True)
    def test_scheda_processo_mostra_le_voci(self, _perm):
        self.client.force_login(self.qualita)
        r = self.client.get(reverse("sistema_gestione:processo_dettaglio", args=[self.processo.pk]))
        self.assertContains(r, 'id="tab-ofi"')
        self.assertContains(r, reverse("registro_ofi:dettaglio", args=[self.mia.pk]))
        self.assertEqual(r.context["n_ofi_nc_aperte"], 1)


class CollegamentiTests(TestCase):
    def test_origine_manuale_e_conteggi(self):
        v = _voce(processo="Officina")
        self.assertIsNone(collegamenti.origine(v))
        self.assertIsNone(collegamenti.processo(v))
        conteggi = {r["chiave"]: r["n"] for r in collegamenti.conta_per_origine([v])}
        self.assertEqual(conteggi["manuale"], 1)

    def test_rilievi_degli_enti_pesano_sul_processo_collegato(self):
        from django.contrib.contenttypes.models import ContentType

        from sistema_gestione.models import AuditEsterno
        from sistema_gestione.services.audit_automation import rilievi_esterni_per_processo

        p = Processo.objects.create(codice="PRC-11", nome="Saldatura")
        ct = ContentType.objects.get_for_model(AuditEsterno)
        # Testo libero che da solo non indica il processo: conta il processo scelto nella voce.
        voce = _voce(tipo=RegistroOFI.TIPO_NC, processo="reparto saldature", content_type=ct, object_id=1)
        voce.processo_sgi = p
        voce.save()
        self.assertEqual(rilievi_esterni_per_processo(Processo.objects.filter(pk=p.pk)), {p.pk: {"nc": 1, "altri": 0}})


class BootstrapTests(TestCase):
    def test_chi_apriva_il_registro_con_le_specifiche_lo_apre_ancora(self):
        from core.models import (
            GroupPermissionGrant, PermissionDefinition, RolePermissionGrant, UserPermissionGrant,
        )

        from . import acl_bootstrap as B

        for code in (B.PERM_GS_VIEW, B.PERM_OFI_VIEW):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": "t"})
        RolePermissionGrant.objects.create(legacy_role_id=7, permission_id=B.PERM_GS_VIEW, enabled=True)
        RolePermissionGrant.objects.create(legacy_role_id=8, permission_id=B.PERM_GS_VIEW, enabled=False)
        UserPermissionGrant.objects.create(legacy_user_id=42, permission_id=B.PERM_GS_VIEW, enabled=True)
        self.assertTrue(B._copia_grant_view(PermissionDefinition, RolePermissionGrant, UserPermissionGrant,
                                            GroupPermissionGrant))
        self.assertTrue(RolePermissionGrant.objects.filter(legacy_role_id=7, permission_id=B.PERM_OFI_VIEW,
                                                           enabled=True).exists())
        self.assertFalse(RolePermissionGrant.objects.filter(legacy_role_id=8, permission_id=B.PERM_OFI_VIEW).exists())
        self.assertTrue(UserPermissionGrant.objects.filter(legacy_user_id=42, permission_id=B.PERM_OFI_VIEW).exists())
