"""KPI cliccabili dell'area Automazioni: ogni tessera porta alla lista filtrata con lo stesso numero."""
from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from automazioni.models import AutomationRuleOperationType, AutomationRunLog, AutomationRunLogStatus


def _kpi_href(html: str, label: str) -> str:
    for m in re.finditer(r'<a class="[^"]*kpi-link[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        if label in m.group(2):
            return m.group(1).replace("&amp;", "&")
    raise AssertionError(f"KPI cliccabile non trovato: {label}")


class PianificatiKpiLinkTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("kpi_auto", "kpi_auto@example.test", "x")
        self.client.force_login(self.admin)

    def test_attivi_disattivi_filtrano_le_stesse_righe(self):
        url = reverse("admin_portale:automazioni_pianificati")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual(ctx["totale"], ctx["attivi"] + ctx["disattivi"])
        html = resp.content.decode()
        for label, key, stato in (("Attivi", "attivi", "attivi"), ("Disattivati", "disattivi", "disattivi")):
            href = _kpi_href(html, label)
            self.assertEqual(href, f"{url}?stato={stato}")
            filtered = self.client.get(href)
            shown = len(filtered.context["rows"]) + len(filtered.context["digest_rows"])
            self.assertEqual(shown, ctx[key], label)
            self.assertEqual(filtered.context["righe_mostrate"], ctx[key])

    def test_notifiche_censite_porta_all_elenco(self):
        resp = self.client.get(reverse("admin_portale:automazioni_event_notifications"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertEqual(_kpi_href(html, "Notifiche censite"), "#elenco-notifiche")
        self.assertIn('id="elenco-notifiche"', html)


class RunLogChipTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("kpi_runlog", "kpi_runlog@example.test", "x")
        self.client.force_login(self.admin)
        for status, source in ((AutomationRunLogStatus.ERROR, "assenze"), (AutomationRunLogStatus.ERROR, "tickets"),
                               (AutomationRunLogStatus.SUCCESS, "assenze")):
            AutomationRunLog.objects.create(source_code=source, operation_type=AutomationRuleOperationType.UPDATE,
                                            status=status, payload_json={})

    def test_chip_errori_conta_quello_che_mostra(self):
        url = reverse("admin_portale:automazioni_run_log_list")
        resp = self.client.get(url, {"source_code": "assenze"})
        self.assertEqual(resp.context["chip_counts"]["errors"], 1)
        html = resp.content.decode()
        m = re.search(r'<a class="auto-chip chip-errors[^"]*"\s+href="([^"]+)"', html)
        self.assertIsNotNone(m)
        href = m.group(1).replace("&amp;", "&")
        self.assertIn("status=error", href)
        self.assertIn("source_code=assenze", href)
        filtered = self.client.get(href)
        self.assertEqual(len(filtered.context["run_logs"]), resp.context["chip_counts"]["errors"])
