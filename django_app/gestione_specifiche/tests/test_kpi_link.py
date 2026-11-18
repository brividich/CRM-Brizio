"""Tessere KPI di cruscotto e dashboard direzionale: link all'elenco filtrato con lo stesso numero."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gestione_specifiche import constants as C
from gestione_specifiche.models import MOD133, AzioneOFI, RigaMOD133, Specifica

User = get_user_model()


class SpecificheKpiLinkTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("gs_kpi", "k@x.it", "x"))
        oggi = timezone.localdate()

        def spec(codice, stato, verifica_giorni=None):
            s = Specifica.objects.create(codice=codice, titolo="T")
            campi = {"stato": stato}
            if verifica_giorni is not None:
                campi["data_verifica"] = oggi + timedelta(days=verifica_giorni)
            Specifica.objects.filter(pk=s.pk).update(**campi)
            return s

        spec("SP-K1", C.STATO_IN_VALIDITA, -5)    # scaduta
        spec("SP-K2", C.STATO_IN_VALIDITA, 10)    # entro 30
        spec("SP-K3", C.STATO_IN_VALIDITA, 45)    # 31-60
        spec("SP-K4", C.STATO_IN_VALIDITA, 75)    # 61-90
        spec("SP-K5", C.STATO_FLOW_DOWN)
        spec("SP-K6", C.STATO_SUPERATO, -50)      # non attiva: mai contata
        con_ofi = spec("SP-K7", C.STATO_FLOW_DOWN)
        mod = MOD133.objects.create(specifica=con_ofi)
        riga = RigaMOD133.objects.create(mod133=mod, ordine=1, argomento="Tolleranze")
        AzioneOFI.objects.create(riga_mod133=riga, stato=C.AZIONE_OFI_BOZZA, modo_approvazione=C.APPROV_MOD133)
        AzioneOFI.objects.create(riga_mod133=riga, stato=C.AZIONE_OFI_IN_APPROVAZIONE, modo_approvazione=C.APPROV_MOD133)
        AzioneOFI.objects.create(riga_mod133=riga, stato=C.AZIONE_OFI_APPROVATA, modo_approvazione=C.APPROV_MOD133)
        self.lista = reverse("gestione_specifiche:lista")

    def _tot(self, params):
        r = self.client.get(self.lista, params)
        self.assertEqual(r.status_code, 200)
        return r.context["tot"]

    def test_dashboard_kpi_href_e_conteggi(self):
        r = self.client.get(reverse("gestione_specifiche:kpi"))
        kpi, verifiche = r.context["kpi"], r.context["verifiche"]
        html = r.content.decode()
        self.assertIn(f'href="{self.lista}?vista=elenco"', html)
        self.assertEqual(self._tot({"vista": "elenco"}), kpi["attive"])
        self.assertIn(f'href="{self.lista}?verifica=scaduta"', html)
        self.assertEqual(self._tot({"verifica": "scaduta"}), kpi["ritardo_n"])
        self.assertEqual(kpi["ritardo_n"], 1)
        self.assertIn(f'href="{self.lista}?ofi=aperti"', html)
        r_ofi = self.client.get(self.lista, {"ofi": "aperti"})
        self.assertEqual(r_ofi.context["n_ofi_aperti_filtro"], kpi["ofi_aperti"])
        self.assertEqual(kpi["ofi_aperti"], 2)
        for fascia in ("f30", "f60", "f90"):
            self.assertIn(f'href="{self.lista}?verifica={fascia}"', html)
            self.assertEqual(self._tot({"verifica": fascia}), verifiche[fascia], fascia)
        self.assertEqual((verifiche["f30"], verifiche["f60"], verifiche["f90"]), (2, 1, 1))

    def test_cruscotto_verifica_in_scadenza_porta_al_sottoinsieme(self):
        r = self.client.get(self.lista)
        self.assertContains(r, f'href="{self.lista}?verifica=in_scadenza"')
        self.assertEqual(self._tot({"verifica": "in_scadenza"}), r.context["kpi"]["verifica_scad"])
        self.assertEqual(r.context["kpi"]["verifica_scad"], 2)
