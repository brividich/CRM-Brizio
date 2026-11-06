"""Copertura delle CVE per programma: «non controllato» dichiarato, CPE esteso ai nomi dello stesso programma. Dati sintetici."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from assets.views_software import catalog_rows
from security.models import SecurityCveRecord, SoftwareCpeMapping as Cpe, SoftwareInstallation, SoftwareProgrammaRegola
from security.services import cpe_auto, cpe_ai, metriche, software_catalog as sc


def _sw(host, vendor, product, version="1.0", *, hub=None, raw=None):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{vendor}|{product}|{version}", source_kind="watchguard", host=host, host_display=host, hub_asset=hub,
        vendor=vendor, vendor_raw=vendor, product=product, product_raw=raw or product, version_raw=version,
        still_detected=True, seen_at=now, last_seen_at=now,
    )


class _Base(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("cve-demo", "cve@example.test", "x")
        self.client.force_login(self.user)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        _sw("pc1", "igor pavlov", "7-zip 25.01", "25.01")
        _sw("pc2", "igor pavlov", "7-zip 26.05", "26.05")
        _sw("pc3", "7-zip", "7-zip", "26.05")
        _sw("pc1", "demo", "demo tool")
        self.nomi = {("igor pavlov", "7-zip 25.01"), ("igor pavlov", "7-zip 26.05"), ("7-zip", "7-zip")}


class StatiTests(_Base):
    def test_senza_cpe_non_controllato(self):
        self.assertEqual(set(sc.stati_cve().values()), {sc.NON_CONTROLLATO})

    def test_un_nome_con_cpe_basta(self):
        Cpe.objects.create(vendor="7-zip", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)
        self.assertEqual(sc.stati_cve()[sc.chiave_canonica("7-zip|7-zip")], sc.CONTROLLATO)
        self.assertEqual(sc.stati_cve()["demo|demo tool"], sc.NON_CONTROLLATO)

    def test_non_applicabile_solo_se_lo_sono_tutti(self):
        Cpe.objects.create(vendor="7-zip", product="7-zip", not_applicable=True)
        self.assertEqual(sc.stati_cve()[sc.chiave_canonica("7-zip|7-zip")], sc.NON_CONTROLLATO)
        for v, p in self.nomi - {("7-zip", "7-zip")}:
            Cpe.objects.create(vendor=v, product=p, not_applicable=True)
        self.assertEqual(sc.stati_cve()[sc.chiave_canonica("7-zip|7-zip")], sc.NON_APPLICABILE)

    def test_metrica_e_riepilogo_coincidono_con_il_filtro(self):
        Cpe.objects.create(vendor="7-zip", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)
        m = metriche.copertura_cpe()
        self.assertEqual((m.extra["totale"], m.extra["coperti"], m.extra["non_controllati"]), (2, 1, 1))
        righe = [r for r in catalog_rows(with_cve=True) if r["cve_stato"] == sc.NON_CONTROLLATO]
        self.assertEqual(len(righe), m.extra["non_controllati"])


class PropagazioneTests(_Base):
    def test_una_conferma_copre_le_release(self):
        Cpe.objects.create(vendor="7-zip", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)
        self.assertEqual(cpe_auto.propaga_ai_programmi(), 2)
        coperti = set(Cpe.objects.filter(confirmed=True, cpe_product="7-zip").values_list("vendor", "product"))
        self.assertEqual(coperti, self.nomi)
        self.assertEqual(Cpe.objects.get(vendor="igor pavlov", product="7-zip 25.01").origin, Cpe.ORIGIN_AUTO)

    def test_due_cpe_diversi_non_si_estende(self):
        Cpe.objects.create(vendor="7-zip", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)
        Cpe.objects.create(vendor="igor pavlov", product="7-zip 26.05", cpe_vendor="igor", cpe_product="altro", confirmed=True)
        self.assertEqual(cpe_auto.propaga_ai_programmi(), 0)

    def test_rifiuto_rispettato(self):
        Cpe.objects.create(vendor="7-zip", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)
        Cpe.objects.create(vendor="igor pavlov", product="7-zip 26.05", origin=Cpe.ORIGIN_AUTO_REJECTED)
        cpe_auto.propaga_ai_programmi()
        self.assertFalse(Cpe.objects.get(vendor="igor pavlov", product="7-zip 26.05").confirmed)

    def test_unione_a_mano_non_estende_il_cpe(self):
        _sw("pc1", "microsoft", "windows 10")
        _sw("pc2", "microsoft", "windows 11")
        SoftwareProgrammaRegola.objects.create(tipo="unisci", chiave="microsoft|windows 10", chiave_altra="microsoft|windows 11")
        Cpe.objects.create(vendor="microsoft", product="windows 10", cpe_vendor="microsoft", cpe_product="windows_10", confirmed=True)
        cpe_auto.propaga_ai_programmi()
        self.assertFalse(Cpe.objects.filter(vendor="microsoft", product="windows 11").exists())

    def test_separato_non_eredita(self):
        SoftwareProgrammaRegola.objects.create(tipo="separa", chiave="igor pavlov|7-zip 25.01")
        Cpe.objects.create(vendor="7-zip", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)
        cpe_auto.propaga_ai_programmi()
        self.assertFalse(Cpe.objects.filter(vendor="igor pavlov", product="7-zip 25.01").exists())

    def test_nome_con_release_collegato_dal_nome_pulito(self):
        SoftwareInstallation.objects.filter(vendor="7-zip").delete()
        self.assertGreaterEqual(cpe_auto.auto_link({("7-zip", "7-zip")}), 1)
        self.assertTrue(Cpe.objects.filter(vendor="igor pavlov", product="7-zip 26.05", confirmed=True, cpe_product="7-zip").exists())

    def test_ai_una_domanda_per_programma(self):
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0001", configurations=[{"vendor": "seven", "product": "7-zip"}])
        casi = [c for c in cpe_ai.casi_cpe() if "7-zip" in c["product"]]
        self.assertEqual(len(casi), 1)


class PagineTests(_Base):
    def test_confermare_da_software_e_cpe_vale_per_tutti(self):
        self.client.post(reverse("security:software_mapping"), {"action": "cpe_confirm_bulk", "bulk": "7-zip|||7-zip|||7-zip:7-zip"})
        self.assertEqual(set(Cpe.objects.filter(confirmed=True).values_list("vendor", "product")), self.nomi)

    def test_software_e_cpe_una_riga_per_programma(self):
        r = self.client.get(reverse("security:software_mapping"))
        righe = r.context["page"].object_list
        self.assertEqual(len(righe), 2)
        riga = next(x for x in righe if x["nomi"] == 3)
        self.assertEqual(riga["hosts"], 3)
        self.assertContains(r, "3 nomi: la decisione vale per tutti")

    def test_software_e_cpe_cerca_anche_nei_nomi(self):
        r = self.client.get(reverse("security:software_mapping"), {"q": "26.05"})
        self.assertEqual(len(r.context["page"].object_list), 1)

    def test_catalogo_e_dettaglio_dicono_non_controllato(self):
        r = self.client.get(reverse("assets:software_catalog"))
        self.assertContains(r, ">non controllato<")
        self.assertContains(r, "CVE non controllate")
        d = self.client.get(reverse("assets:software_catalog_detail"), {"k": "demo|demo tool"})
        self.assertContains(d, "CVE non controllate per questo programma")
        self.assertNotContains(d, "nessuna nota")

    def test_dettaglio_controllato(self):
        Cpe.objects.create(vendor="demo", product="demo tool", cpe_vendor="demo", cpe_product="tool", confirmed=True)
        d = self.client.get(reverse("assets:software_catalog_detail"), {"k": "demo|demo tool"})
        self.assertContains(d, "Nessuna delle CVE note al SOC")
        self.assertContains(d, "nessuna nota")

    def test_chi_non_vede_il_soc_non_ha_lo_stato(self):
        from unittest.mock import patch

        with patch("assets.views_software._can_see_cve", return_value=False):
            r = self.client.get(reverse("assets:software_catalog"), {"f": "non_controllato"})
        self.assertNotContains(r, "CVE non controllate")
        self.assertNotContains(r, ">non controllato<")

    def test_cruscotto_e_pannello(self):
        r = self.client.get(reverse("security:vulnerabilities"))
        self.assertContains(r, "2 programmi su 2 non controllati")
        p = self.client.get(reverse("security:cve_pannello_programma"), {"k": "demo|demo tool"})
        self.assertContains(p, "Non controllato.")

    def test_copertura_del_pc(self):
        hub = Asset.objects.create(asset_tag="SW-DEMO", name="PC-DEMO")
        _sw("pc9", "demo", "demo tool", hub=hub)
        _sw("pc9", "altro", "altro tool", hub=hub)
        Cpe.objects.create(vendor="demo", product="demo tool", cpe_vendor="demo", cpe_product="tool", confirmed=True)
        self.assertEqual(sc.copertura_asset(hub), {"programmi": 2, "non_controllati": 1})
