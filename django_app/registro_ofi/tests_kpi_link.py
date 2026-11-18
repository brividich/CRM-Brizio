"""Tessere KPI del Registro OFI: portano all'elenco che conta lo stesso numero. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from gestione_specifiche import registro_ofi as R
from gestione_specifiche.models import RegistroOFI


def _voce(**kw):
    dati = {"numero": R.prossimo_numero(), "data_apertura": timezone.localdate()}
    dati.update(kw)
    return RegistroOFI.objects.create(**dati)


class KpiLinkTests(TestCase):
    def setUp(self):
        u = get_user_model().objects.create_user("kpi_ofi", password="x", is_superuser=True)
        UserOnboarding.objects.create(user=u, completed=True)
        self.client.force_login(u)
        oggi = timezone.localdate()
        _voce(fase="PLAN", data_richiesta=oggi - timedelta(days=3))
        _voce(fase="DO", tipo="NC")
        _voce(fase="CHECK", modulo_origine="sistema_gestione")
        _voce(fase="ACT")
        _voce(fase="CHIUSO", data_chiusura=oggi - timedelta(days=20), data_richiesta=oggi - timedelta(days=30))
        _voce(fase="CHIUSO", data_chiusura=oggi - timedelta(days=400))

    def _n(self, query):
        return len(self.client.get(reverse("registro_ofi:lista") + query).context["voci"])

    def test_contatori_pdca_e_scaduti_della_lista(self):
        r = self.client.get(reverse("registro_ofi:lista"))
        c = r.context["counters"]
        lista = reverse("registro_ofi:lista")
        self.assertContains(r, f'href="{lista}?fase_almeno=DO"')
        self.assertEqual(self._n(""), c["p"])
        self.assertEqual(self._n("?fase_almeno=DO"), c["d"])
        self.assertEqual(self._n("?fase_almeno=CHECK"), c["c"])
        self.assertEqual(self._n("?fase_almeno=ACT"), c["a"])
        self.assertEqual(self._n("?scaduti=1"), r.context["n_scaduti"])
        self.assertEqual((c["d"], c["c"], c["a"]), (5, 4, 3))

    def test_contatori_rispettano_il_modulo(self):
        r = self.client.get(reverse("registro_ofi:lista") + "?modulo=sistema_gestione")
        self.assertContains(r, "fase_almeno=CHECK&amp;modulo=sistema_gestione")
        self.assertEqual(self._n("?fase_almeno=CHECK&modulo=sistema_gestione"), r.context["counters"]["c"])

    def test_dashboard_chiuse_12_mesi_e_voci_aperte(self):
        r = self.client.get(reverse("registro_ofi:home"))
        lista = reverse("registro_ofi:lista")
        self.assertContains(r, f'href="{lista}?chiuse_12m=1"')
        self.assertEqual(self._n("?chiuse_12m=1"), r.context["c"]["chiuse_anno"])
        self.assertEqual(r.context["c"]["chiuse_anno"], 1)
        self.assertEqual(self._n("?aperte=1"), r.context["c"]["aperte"])
        for riga in r.context["c"]["per_fase"]:
            with self.subTest(fase=riga["chiave"]):
                self.assertEqual(self._n(f"?fase={riga['chiave']}&aperte=1"), riga["n"])

    def test_filtro_non_valido_ignorato(self):
        self.assertEqual(self._n("?fase_almeno=BOH"), RegistroOFI.objects.count())
