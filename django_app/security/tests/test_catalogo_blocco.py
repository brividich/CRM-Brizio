"""Catalogo software: classificazione in blocco e regole per produttore. Dati sintetici."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import SoftwareCatalogEntry as E, SoftwareProduttoreConsentito as R
from assets.views_software import catalog_rows
from core.models import AuditLog
from security.models import SoftwareInstallation


def _sw(host, vendor, vendor_raw, product, version="1.0"):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{vendor}|{product}|{version}", source_kind="watchguard", host=host, host_display=host,
        vendor=vendor, vendor_raw=vendor_raw, product=product, product_raw=product, version_raw=version,
        still_detected=True, seen_at=now, last_seen_at=now,
    )


class _Base(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("blocco-demo", "blocco@example.test", "x")
        self.client.force_login(self.user)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        self.url = reverse("assets:software_catalog")
        _sw("pc1", "microsoft", "Microsoft Corporation", "demo word")
        _sw("pc2", "microsoft", "Microsoft Corporation", "demo excel")
        _sw("pc1", "acme", "Acme Srl", "acme tool")

    def stato(self):
        return {r["key"]: r for r in catalog_rows(with_cve=False)}


class BloccoTests(_Base):
    def test_classifica_i_selezionati(self):
        r = self.client.post(self.url, {"azione": "classifica", "classification": "consentito", "licensing": "gratuito", "k": ["acme|acme tool", "microsoft|demo word"]})
        self.assertEqual(r.status_code, 302)
        stato = self.stato()
        self.assertEqual(stato["acme|acme tool"]["classification"], "consentito")
        self.assertEqual(stato["acme|acme tool"]["licensing"], "gratuito")
        self.assertEqual(stato["microsoft|demo excel"]["classification"], "da_classificare")

    def test_licenza_non_cambiare_e_non_tocca_il_resto(self):
        E.objects.create(inventory_key="acme|acme tool", licensing="a_pagamento", min_version="2.0", notes="Nota")
        self.client.post(self.url, {"azione": "classifica", "classification": "da_rimuovere", "licensing": "", "k": ["acme|acme tool"]})
        e = E.objects.get()
        self.assertEqual((e.classification, e.licensing, e.min_version, e.notes), ("da_rimuovere", "a_pagamento", "2.0", "Nota"))

    def test_chiave_inventata_ignorata(self):
        self.client.post(self.url, {"azione": "classifica", "classification": "consentito", "k": ["finto|finto"]})
        self.assertFalse(E.objects.exists())

    def test_valore_non_valido(self):
        self.client.post(self.url, {"azione": "classifica", "classification": "boh", "k": ["acme|acme tool"]})
        self.assertFalse(E.objects.exists())

    def test_una_voce_di_registro_e_un_controllo_soc(self):
        with patch("assets.views_software._run_software_policy", return_value=0) as soc:
            self.client.post(self.url, {"azione": "classifica", "classification": "non_autorizzato", "k": ["acme|acme tool", "microsoft|demo word"]})
        soc.assert_called_once()
        self.assertEqual(AuditLog.objects.filter(azione="update_software_catalog_blocco").count(), 1)

    def test_senza_permesso(self):
        with patch("assets.views_software._can_edit", return_value=False):
            pagina = self.client.get(self.url)
            self.assertNotContains(pagina, 'id="sc-blocco"')
            self.assertNotContains(pagina, "Regole per produttore")
            self.client.post(self.url, {"azione": "classifica", "classification": "consentito", "k": ["acme|acme tool"]})
            self.client.post(self.url, {"azione": "consenti_produttore", "produttore": "Acme Srl"})
        self.assertFalse(E.objects.exists() or R.objects.exists())


class RegolaTests(_Base):
    def test_consente_anche_i_nuovi_e_si_toglie(self):
        self.client.post(self.url, {"azione": "consenti_produttore", "produttore": "Microsoft Corporation"})
        _sw("pc3", "microsoft", "Microsoft Corporation", "demo nuovo")
        stato = self.stato()
        for k in ("microsoft|demo word", "microsoft|demo nuovo"):
            self.assertEqual((stato[k]["classification"], stato[k]["da_regola"]), ("consentito", True))
        self.assertEqual(stato["acme|acme tool"]["classification"], "da_classificare")
        self.assertFalse(E.objects.exists())
        self.client.post(self.url, {"azione": "togli_produttore", "regola": R.objects.get().pk})
        self.assertEqual(self.stato()["microsoft|demo word"]["classification"], "da_classificare")

    def test_la_decisione_sul_programma_vince(self):
        E.objects.create(inventory_key="microsoft|demo word", classification="non_autorizzato")
        R.objects.create(produttore="microsoft")
        riga = self.stato()["microsoft|demo word"]
        self.assertEqual((riga["classification"], riga["da_regola"]), ("non_autorizzato", False))

    def test_filtro_e_avanzamento(self):
        R.objects.create(produttore="microsoft")
        r = self.client.get(self.url, {"f": "da_classificare"})
        self.assertEqual([x["key"] for x in r.context["rows"]], ["acme|acme tool"])
        self.assertEqual(r.context["avanzamento"], {"decisi": 2, "programmi": 3, "percento_pc": 67})
        self.assertContains(r, "da regola", count=0)
        self.assertEqual([p["etichetta"] for p in r.context["produttori_proposti"]], ["Acme Srl"])

    def test_pagina_con_regole_e_dettaglio(self):
        R.objects.create(produttore="microsoft", etichetta="Microsoft Corporation")
        r = self.client.get(self.url)
        self.assertContains(r, "Microsoft Corporation")
        self.assertContains(r, "da regola")
        self.assertNotContains(r, "{#")
        d = self.client.get(reverse("assets:software_catalog_detail"), {"k": "microsoft|demo word"})
        self.assertContains(d, "regola sul produttore")
