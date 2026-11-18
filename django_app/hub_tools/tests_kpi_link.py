"""KPI cliccabili di Hub Tools: le tessere notifiche portano alla lista filtrata con lo stesso numero."""
from __future__ import annotations

import re
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Notifica


def _kpi_hrefs(html: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r'<a class="hn-stat kpi-link" href="([^"]+)"[^>]*>.*?hn-stat-label">([^<]+)<', html, re.S):
        out[m.group(2).strip()] = m.group(1).replace("&amp;", "&")
    return out


class NotificheKpiLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser("kpi_hub", "kpi_hub@example.test", "x")
        Notifica.objects.create(legacy_user_id=1, messaggio="nuova")  # non letta, banner in attesa
        Notifica.objects.create(legacy_user_id=1, messaggio="vista", popup_shown=True)  # non letta, banner visto
        Notifica.objects.create(legacy_user_id=2, messaggio="letta", letta=True, popup_shown=True)
        Notifica.objects.create(legacy_user_id=2, messaggio="archiviata", letta=True, archiviata=True)

    def setUp(self):
        self.client.force_login(self.user)
        legacy_admin = SimpleNamespace(id=1, ruolo="admin", ruolo_id=1)
        self.stack = ExitStack()
        for target in ("admin_portale.decorators", "core.context_processors"):
            self.stack.enter_context(patch(f"{target}.get_legacy_user", return_value=legacy_admin))
            self.stack.enter_context(patch(f"{target}.is_legacy_admin", return_value=True))
        self.addCleanup(self.stack.close)

    def test_tessere_portano_alla_lista_con_lo_stesso_numero(self):
        with patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=[]):
            resp = self.client.get(reverse("hub_tools:hub_notifiche"))
            self.assertEqual(resp.status_code, 200)
            hrefs = _kpi_hrefs(resp.content.decode())
            attesi = {"Totali": "totale", "Non lette": "non_lette", "Lette": "lette",
                      "Banner in attesa": "popup_pend", "Archiviate": "archiviate"}
            self.assertEqual(set(hrefs), set(attesi))
            for label, key in attesi.items():
                lista = self.client.get(hrefs[label])
                self.assertEqual(lista.context["page_obj"].paginator.count, resp.context[key], label)
        self.assertEqual(resp.context["popup_pend"], 1)
        self.assertIn("letta=banner", hrefs["Banner in attesa"])
