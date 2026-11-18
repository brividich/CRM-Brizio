"""Tessere KPI di «Presenti in azienda»: ognuna apre l'elenco che conta lo stesso numero."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from . import services

_ANTINCENDIO = {"nome": "Antincendio", "colore": "#dc2626"}
_PRIMO_SOCCORSO = {"nome": "Primo soccorso", "colore": "#16a34a"}


def _stato():
    def p(cognome, incarichi):
        return {"cognome": cognome, "nome": "N", "matricola": cognome[:3], "reparto": "CNC",
                "mansione": "", "entrata": "08:00", "legacy_id": None, "incarichi": incarichi}
    return {
        "presenti": [p("Alfa", [_ANTINCENDIO]), p("Beta", [_ANTINCENDIO, _PRIMO_SOCCORSO]), p("Gamma", [])],
        "esterni": [{"cognome": "Ospite", "nome": "Uno", "matricola": "", "azienda": "Ditta"}],
        "errore": "", "configurato": True,
    }


class PresentiKpiLinkTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser("pres_kpi", password="x")
        self.client.force_login(self.admin)
        p = patch.object(services, "stato", side_effect=_stato)
        p.start()
        self.addCleanup(p.stop)

    def test_tessere_incarico_aprono_elenco_filtrato_con_lo_stesso_numero(self):
        home = reverse("presenti:home")
        r = self.client.get(home)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f'href="{home}#pres-dipendenti"')
        self.assertContains(r, f'href="{home}#pres-esterni"')
        for inc in r.context["riepilogo"]["incarichi"]:
            self.assertContains(r, f'href="{home}?incarico={inc["nome"].replace(" ", "%20")}#pres-dipendenti"')
            filtrata = self.client.get(home, {"incarico": inc["nome"]})
            self.assertEqual(len(filtrata.context["righe"]), inc["n"], inc["nome"])
        self.assertEqual(len(r.context["righe"]), r.context["riepilogo"]["totale"])
