"""KPI cliccabili in core: CAPA e componenti della home/hub preview."""
from __future__ import annotations

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ActionItem


def _kpi_href(html: str, label: str) -> str:
    for m in re.finditer(r'<a class="[^"]*kpi-link[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        if label in m.group(2):
            return m.group(1).replace("&amp;", "&")
    raise AssertionError(f"KPI cliccabile non trovato: {label}")


class CapaKpiLinkTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("kpi_capa", "kpi_capa@example.test", "x")
        self.client.force_login(self.admin)
        oggi = timezone.localdate()
        ActionItem.objects.create(titolo="aperta scaduta", stato=ActionItem.STATO_APERTA, data_scadenza=oggi - timedelta(days=2))
        ActionItem.objects.create(titolo="in corso", stato=ActionItem.STATO_IN_CORSO, data_scadenza=oggi + timedelta(days=5))
        ActionItem.objects.create(titolo="da verificare", stato=ActionItem.STATO_CHIUSA)
        ActionItem.objects.create(titolo="verificata", stato=ActionItem.STATO_VERIFICATA, data_scadenza=oggi - timedelta(days=9))

    def test_tessere_portano_alla_lista_con_lo_stesso_numero(self):
        resp = self.client.get(reverse("capa_list"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for label, key in (("Aperte", "n_aperte"), ("Scadute", "n_scadute"), ("Da verificare", "n_da_verificare")):
            lista = self.client.get(_kpi_href(html, label))
            self.assertEqual(lista.context["page_obj"].paginator.count, resp.context[key], label)
        self.assertEqual((resp.context["n_aperte"], resp.context["n_scadute"], resp.context["n_da_verificare"]), (3, 1, 1))


class HomeTileKpiLinkTests(TestCase):
    def test_kpi_del_pannello_con_url_diventa_link(self):
        mod = {
            "accessible": True, "diretto": False, "id": "ticket", "tone": "warning", "label": "Ticket",
            "sub": "Interventi", "url": "/tickets/", "kpi_value": 3,
            "kpis": [
                {"value": 3, "unit": "attivi", "tone": "warning", "url": "/tickets/?stato=aperti"},
                {"value": 1, "unit": "scaduti", "tone": "danger"},
            ],
        }
        html = render_to_string("core/components/_home_module_tile.html", {"mod": mod})
        self.assertIn('href="/tickets/?stato=aperti"', html)
        self.assertEqual(html.count("kpi-link"), 1)

    def test_hub_preview_kpi_con_url(self):
        admin = get_user_model().objects.create_superuser("kpi_hubprev", "kpi_hubprev@example.test", "x")
        self.client.force_login(admin)
        kpis = [{"label": "Ticket aperti", "value": 4, "url": "/tickets/?stato=aperti", "icon": "TKT"},
                {"label": "Asset", "value": 9, "icon": "AST"}]
        with patch("dashboard.views._hub_kpi_cards", return_value=kpis):
            resp = self.client.get(reverse("dashboard_hub_preview"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertEqual(_kpi_href(html, "Ticket aperti"), "/tickets/?stato=aperti")
        self.assertIn("Asset", html)
