"""Subnav «Salute e sicurezza» (prompt 03, obiettivo D): gruppi, conteggi delle scadenze, ACL, voce accesa."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

from .templatetags.anagrafica_extras import safety_subnav

User = get_user_model()

VOCI_SCADUTE = [
    {"kind": "visita", "scaduta": True},
    {"kind": "formazione", "scaduta": True},
    {"kind": "qualifica", "scaduta": True},
]


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SafetySubnavTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("safnav_admin", "safnav_admin@example.invalid", "x")

    def setUp(self):
        cache.clear()

    def _gruppi(self, path, active=""):
        request = RequestFactory().get(path)
        request.user = self.admin
        request.resolver_match = resolve(path)
        return safety_subnav({"request": request}, active)

    def _voci(self, gruppi):
        return {v["chiave"]: v for g in gruppi for v in g["voci"]}

    def test_conteggi_delle_scadenze_su_scadenzario_e_visite(self):
        with patch("anagrafica.views._build_scadenzario_voci", return_value=VOCI_SCADUTE) as build:
            voci = self._voci(self._gruppi(reverse("anagrafica:scadenzario")))
            self._gruppi(reverse("anagrafica:scadenzario"))  # seconda pagina: dalla cache
        self.assertEqual(voci["scadenzario"]["n"], 3)
        self.assertEqual(voci["visite"]["n"], 1)
        self.assertEqual(build.call_count, 1)

    def test_voce_accesa_anche_nelle_sottopagine(self):
        with patch("anagrafica.views._build_scadenzario_voci", return_value=[]):
            voci = self._voci(self._gruppi(reverse("anagrafica:visite_mediche_sessioni")))
        self.assertTrue(voci["visite"]["active"])
        self.assertFalse(voci["scadenzario"]["active"])

    def test_due_livelli_sezione_accesa_e_totale(self):
        with patch("anagrafica.views._build_scadenzario_voci", return_value=VOCI_SCADUTE):
            gruppi = self._gruppi(reverse("anagrafica:visite_mediche_sessioni"))
        accese = [g["titolo"] for g in gruppi if g["active"]]
        self.assertEqual(accese, ["Sorveglianza sanitaria"])
        sanitaria = next(g for g in gruppi if g["titolo"] == "Sorveglianza sanitaria")
        self.assertEqual(sanitaria["url"], reverse("anagrafica:visite_mediche_dashboard"))
        self.assertEqual(sanitaria["n"], 1)

    def test_pagina_non_mappata_apre_la_prima_sezione(self):
        with patch("anagrafica.views._build_scadenzario_voci", return_value=[]):
            gruppi = self._gruppi(reverse("anagrafica:index"))
        self.assertEqual([g["active"] for g in gruppi][0], True)
        self.assertEqual(sum(g["active"] for g in gruppi), 1)

    def test_voci_negate_dall_acl_non_compaiono_e_gruppo_vuoto_sparisce(self):
        sanitarie = {reverse(n) for n in ("anagrafica:visite_mediche_dashboard", "anagrafica:referti_coda",
                                          "anagrafica:libretto_sanitario_generale")}
        with patch("anagrafica.views._build_scadenzario_voci", return_value=[]), \
                patch("core.middleware.acl_allows_path", side_effect=lambda path, **kw: path not in sanitarie):
            gruppi = self._gruppi(reverse("anagrafica:scadenzario"))
        titoli = [g["titolo"] for g in gruppi]
        self.assertNotIn("Sorveglianza sanitaria", titoli)
        self.assertNotIn("visite", self._voci(gruppi))

    def test_pagine_salute_mostrano_la_subnav(self):
        self.client.force_login(self.admin)
        with patch("anagrafica.views._build_scadenzario_voci", return_value=[]):
            for nome in ("anagrafica:scadenzario", "anagrafica:visite_mediche_sessioni", "anagrafica:referti_registro"):
                with self.subTest(pagina=nome):
                    r = self.client.get(reverse(nome))
                    self.assertEqual(r.status_code, 200)
                    # Seconda riga della subnav dal DB (prima: barra «safnav» scritta nella pagina).
                    self.assertContains(r, 'class="hrnav-sub"')
