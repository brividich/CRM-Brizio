"""Rischio sulla scheda dell'asset e sistema fuori supporto in Dispositivi. Dati sintetici."""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from security.models import SecurityAsset, SecurityAssetSignal, SecurityCveImpact, SecurityCveRecord, SecuritySource, SoftwareInstallation
from security.services import pc_copertura, rischio_asset as ra

OGGI = date(2026, 11, 6)


def _sw(host, product, version, hub=None):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{product}|{version}", source_kind="watchguard", fonti=["watchguard"], host=host, host_display=host, hub_asset=hub, vendor="microsoft",
        vendor_raw="Microsoft", product=product, product_raw=product, version_raw=version, still_detected=True, seen_at=now, last_seen_at=now,
    )


class SistemaTests(TestCase):
    def stato(self, product, version):
        return ra.stato_sistema([SoftwareInstallation(product=product, version_raw=version)], OGGI)

    def test_pro_24h2_fuori_supporto(self):
        s = self.stato("windows 11 pro 64 bits version 24h2", "10.0.26100.1000")
        self.assertEqual((s["fuori"], s["fine"]), (True, date(2026, 10, 13)))

    def test_pro_25h2_supportata(self):
        s = self.stato("windows 11 pro 64 bits version 25h2", "10.0.26200.1000")
        self.assertEqual((s["fuori"], s["in_scadenza"], s["fine"]), (False, False, date(2027, 10, 12)))

    def test_ltsc_usa_la_data_lunga(self):
        s = self.stato("windows 10 enterprise ltsc 2021 64 bits version 21h2", "10.0.19044.1000")
        self.assertEqual(s["fine"], date(2027, 1, 12))
        self.assertTrue(s["in_scadenza"])

    def test_edizione_ignota_usa_la_data_lunga_ma_vale_la_piu_vicina(self):
        generica = SoftwareInstallation(product="windows 11", version_raw="10.0.26100.1000")
        pro = SoftwareInstallation(product="windows 11 pro", version_raw="10.0.26100.1000")
        self.assertFalse(ra.stato_sistema([generica], OGGI)["fuori"])
        self.assertTrue(ra.stato_sistema([generica, pro], OGGI)["fuori"])

    def test_non_windows(self):
        self.assertIsNone(self.stato("demo tool", "1.0"))


class ValutaTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="PC-1", name="PC demo", asset_type=Asset.TYPE_PC, reparto="Demo")

    def test_niente_dati_niente_scheda(self):
        self.assertIsNone(ra.valuta(self.asset, OGGI))

    def test_sistema_fuori_supporto_e_alto(self):
        _sw("pc1", "windows 11 pro", "10.0.26100.1", hub=self.asset)
        v = ra.valuta(self.asset, OGGI)
        self.assertEqual(v["livello"], ra.ALTO)
        self.assertIn("fuori supporto dal 13/10/2026", v["alti"][0])

    def test_tutto_a_posto_ma_dice_cosa_non_controlla(self):
        _sw("pc1", "windows 11 pro", "10.0.26200.1", hub=self.asset)
        v = ra.valuta(self.asset, OGGI)
        self.assertEqual((v["livello"], v["etichetta"]), (ra.NESSUNO, "Nessun problema noto"))
        self.assertIn("non controllati", v["note"][0])

    def test_cve_grave_e_media(self):
        inst = _sw("pc1", "demo", "1.0", hub=self.asset)
        now = timezone.now()
        cve = SecurityCveRecord.objects.create(cve_id="CVE-2099-0002", cvss=5.0, severity="medium")
        SecurityCveImpact.objects.create(cve=cve, host="pc1", installation=inst, hub_asset=self.asset, outcome=SecurityCveImpact.IMPACTS, computed_at=now)
        self.assertEqual(ra.valuta(self.asset, OGGI)["livello"], ra.MEDIO)
        SecurityCveRecord.objects.filter(pk=cve.pk).update(cvss=9.8, severity="critical")
        self.assertEqual(ra.valuta(self.asset, OGGI)["livello"], ra.ALTO)

    def _backup(self, status, giorni_fa=0):
        source = SecuritySource.objects.create(name="Backup demo", vendor="Demo", source_type="email")
        device = SecurityAsset.objects.create(hostname="pc1", hub_asset=self.asset, source=source)
        SecurityAssetSignal.objects.create(asset=device, source=source, kind=SecurityAssetSignal.KIND_BACKUP, status=status, title="Job",
                                           occurred_at=timezone.now() - timedelta(days=giorni_fa))

    def test_backup_fallito_e_medio(self):
        _sw("pc1", "demo", "1.0", hub=self.asset)
        self._backup("failed")
        v = ra.valuta(self.asset)
        self.assertEqual((v["livello"], v["backup"]), (ra.MEDIO, "ko"))

    def test_backup_vecchio(self):
        _sw("pc1", "demo", "1.0", hub=self.asset)
        self._backup("completed", 60)
        self.assertEqual(ra.valuta(self.asset)["backup"], "vecchio")

    def test_server_senza_backup_e_medio_pc_no(self):
        _sw("pc1", "demo", "1.0", hub=self.asset)
        self.assertEqual(ra.valuta(self.asset, OGGI)["livello"], ra.NESSUNO)
        Asset.objects.filter(pk=self.asset.pk).update(asset_type=Asset.TYPE_SERVER)
        self.asset.refresh_from_db()
        self.assertEqual(ra.valuta(self.asset, OGGI)["livello"], ra.MEDIO)


class PagineTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("ris-demo", "ris@example.test", "x")
        self.client.force_login(self.user)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        self.asset = Asset.objects.create(asset_tag="PC-1", name="PC demo", asset_type=Asset.TYPE_PC, reparto="Reparto demo")
        _sw("pc-demo", "windows 11 pro", "10.0.26100.1", hub=self.asset)

    def _card(self, user=None):
        request = RequestFactory().get("/")
        request.user = user or self.user
        return Template("{% load security_asset %}{% security_asset_rischio asset %}").render(Context({"request": request, "asset": self.asset}))

    def test_card_nella_scheda(self):
        html = self._card()
        self.assertIn("Rischio alto", html)
        self.assertIn("Reparto demo", html)
        self.assertNotIn("{#", html)

    def test_card_solo_a_chi_vede_il_soc(self):
        with patch("security.templatetags.security_asset.can_view_security_center", return_value=False):
            self.assertNotIn("Rischio alto", self._card())

    def test_filtro_in_dispositivi(self):
        _sw("pc-nuovo", "windows 11 pro", "10.0.26200.1")
        righe = pc_copertura.righe(proposte=False)
        self.assertEqual([r["nome"] for r in pc_copertura.filtra(righe, "sistema_fuori")], ["pc-demo"])
        r = self.client.get(reverse("security:pc_copertura"), {"f": "sistema_fuori"})
        self.assertContains(r, "Sistema fuori supporto")
        self.assertContains(r, "fuori supporto")
