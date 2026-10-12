"""Guida d'uso in-app di audit interni e Registro OFI: capitoli, collegamenti di pagina, PDF."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import get_resolver, reverse

from sistema_gestione import guida as G


def _nomi_rotte() -> set[str]:
    nomi = set()
    for ns, (_prefix, sub) in get_resolver().namespace_dict.items():
        for chiave in sub.reverse_dict.keys():
            if isinstance(chiave, str):
                nomi.add(f"{ns}:{chiave}")
    return nomi


class GuidaContenutoTests(TestCase):
    def test_ogni_rotta_punta_a_un_capitolo_esistente(self):
        rotte = _nomi_rotte()
        for rotta, (guida, ancora) in G.PAGE_HELP.items():
            self.assertIn(rotta, rotte, rotta)
            ids = {s["id"] for s in G._GUIDE[guida]["sezioni"]}
            self.assertIn(ancora, ids, f"{rotta} -> {guida}#{ancora}")

    def test_capitoli_con_id_unici(self):
        for guida in G._GUIDE.values():
            ids = [s["id"] for s in guida["sezioni"]]
            self.assertEqual(len(ids), len(set(ids)))

    def test_pdf_generato(self):
        pdf = G.render_guida_pdf(G.GUIDA_AUDIT, generato_da="Test", generato_il="12/10/2026")
        self.assertTrue(pdf.startswith(b"%PDF"))


class GuidaPagineTests(TestCase):
    def setUp(self):
        self.su = get_user_model().objects.create_superuser("su_guida", "g@x.it", "x")
        self.client.force_login(self.su)

    def test_pagina_guida_audit(self):
        resp = self.client.get(reverse("sistema_gestione:audit_guida"))
        self.assertEqual(resp.status_code, 200)
        for ancora in ("panoramica", "ruoli", "pagina-audit", "pagina-verifica", "pagina-car", "ofi-lista"):
            self.assertContains(resp, f'id="{ancora}"')
        self.assertContains(resp, "Scarica PDF")

    def test_pdf_scaricabile(self):
        resp = self.client.get(reverse("sistema_gestione:audit_guida"), {"pdf": "1"})
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_link_guida_nelle_pagine(self):
        attese = {
            reverse("sistema_gestione:audit_index"): "#pagina-indice",
            reverse("sistema_gestione:processi_catalogo"): "#pagina-catalogo",
            reverse("sistema_gestione:audit_cruscotto"): "#pagina-cruscotto",
            reverse("sistema_gestione:audit_miei_rilievi"): "#pagina-miei-rilievi",
        }
        for url, ancora in attese.items():
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, "Guida di questa pagina")
            self.assertContains(resp, ancora)

    def test_binding_acl(self):
        from sistema_gestione import acl_bootstrap as B
        self.assertEqual(B._ROUTE_BINDINGS["sistema_gestione:audit_guida"], B.PERM_AUDIT_MIEI)
