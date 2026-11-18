"""Tessere KPI dei Report conformità: portano all'elenco del modulo o al dettaglio del report. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from gestione_specifiche import registro_ofi as R
from gestione_specifiche.models import RegistroOFI


class KpiLinkTests(TestCase):
    def setUp(self):
        u = get_user_model().objects.create_user("kpi_rc", password="x", is_superuser=True, is_staff=True)
        UserOnboarding.objects.create(user=u, completed=True)
        self.client.force_login(u)
        oggi = timezone.localdate()
        for kw in ({"tipo": "NC", "data_richiesta": oggi - timedelta(days=2)}, {"tipo": "OFI"},
                   {"tipo": "OFI", "fase": "CHIUSO", "data_chiusura": oggi}):
            RegistroOFI.objects.create(numero=R.prossimo_numero(), data_apertura=oggi, **kw)

    def _slug_registro(self):
        from report_conformita.registry import all_reports

        return next(r.slug for r in all_reports() if r.builder.__name__ == "_registro_nc_ofi")

    def test_registro_ofi_porta_al_registro_filtrato(self):
        r = self.client.get(reverse("report_conformita:report", args=[self._slug_registro()]))
        kpis = {k.label: k for k in r.context["kpis"]}
        lista = reverse("registro_ofi:lista")
        self.assertEqual(kpis["Aperte"].url, f"{lista}?aperte=1")
        self.assertContains(r, f'href="{lista}?aperte=1&amp;tipo=NC"')
        for etichetta, query in (("Aperte", "?aperte=1"), ("di cui non conformità", "?aperte=1&tipo=NC"),
                                 ("Oltre la data di chiusura", "?scaduti=1")):
            with self.subTest(kpi=etichetta):
                voci = self.client.get(lista + query).context["voci"]
                self.assertEqual(len(voci), kpis[etichetta].value)
        # Senza una lista equivalente la tessera porta al dettaglio del report.
        self.assertEqual(kpis["Chiuse nel periodo"].url, "#rc-dettaglio")
        self.assertContains(r, 'id="rc-dettaglio"')

    def test_con_filtro_norma_niente_link_al_registro(self):
        r = self.client.get(reverse("report_conformita:report", args=[self._slug_registro()]), {"norma": "9100"})
        self.assertTrue(all(k.url == "#rc-dettaglio" for k in r.context["kpis"]))

    def test_link_non_consentito_ripiega_sul_dettaglio(self):
        with patch("report_conformita.views.allowed_links", return_value=[]):
            r = self.client.get(reverse("report_conformita:report", args=[self._slug_registro()]))
        self.assertTrue(all(k.url == "#rc-dettaglio" for k in r.context["kpis"]))

    def test_riesame_porta_ai_report(self):
        r = self.client.get(reverse("report_conformita:riesame"))
        sezione = next(s for s in r.context["sezioni"] if s["report"].slug == self._slug_registro())
        self.assertTrue(all(k.url for k in sezione["kpis"]))
        self.assertIn(f"{reverse('registro_ofi:lista')}?aperte=1", [k.url for k in sezione["kpis"]])
