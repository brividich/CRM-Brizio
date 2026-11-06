"""Riconciliazione IT: PC dell'inventario senza asset, PC e server senza inventario con il motivo. Dati sintetici."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, AssetSenzaInventario
from security.models import SoftwareInstallation
from security.services.software_inventory import _link_assets


def _sw(host, product="demo tool", hub=None):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{product}", source_kind="watchguard", host=host, host_display=host.upper(), hub_asset=hub,
        vendor="demo", vendor_raw="Demo", product=product, product_raw=product, version_raw="1.0",
        still_detected=True, seen_at=now, last_seen_at=now,
    )


class _Base(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("ric-demo", "ric@example.test", "x")
        self.client.force_login(self.user)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        self.url = reverse("assets:it_reconciliation")


class InventarioTests(_Base):
    def test_proposta_e_collegamento(self):
        asset = Asset.objects.create(asset_tag="PC-1", name="pc-demo-01", asset_type=Asset.TYPE_PC)
        _sw("pc-demo-01")
        _sw("pc-demo-01", "altro tool")
        r = self.client.get(self.url)
        riga = next(x for x in r.context["rows"] if x["kind"] == "inv")
        self.assertEqual((riga["label"], riga["asset"], riga["ident"]), ("pc-demo-01", asset, "2 programmi rilevati"))
        self.assertContains(r, "Inventario software")
        self.client.post(self.url, {"row": riga["key"]})
        self.assertEqual(SoftwareInstallation.objects.filter(hub_asset=asset).count(), 2)

    def test_senza_proposta_va_nella_seconda_scheda(self):
        _sw("pc-sconosciuto")
        r = self.client.get(self.url, {"vista": "senza"})
        self.assertEqual([x["label"] for x in r.context["rows"] if x["kind"] == "inv"], ["pc-sconosciuto"])
        self.assertContains(r, "1 programmi rilevati")

    def test_collegato_non_compare_e_i_programmi_nuovi_lo_seguono(self):
        asset = Asset.objects.create(asset_tag="PC-2", name="scheda-diversa", asset_type=Asset.TYPE_PC)
        _sw("pc-rinominato", hub=asset)
        self.assertFalse([x for x in self.client.get(self.url).context["rows"] if x["kind"] == "inv"])
        self.assertEqual(_link_assets("pc-rinominato")[1], asset)

    def test_senza_permesso_non_collega(self):
        asset = Asset.objects.create(asset_tag="PC-1", name="pc-demo-01", asset_type=Asset.TYPE_PC)
        riga = _sw("pc-demo-01")
        with patch("assets.views._can_edit_asset", return_value=False):
            self.client.post(self.url, {"row": f"inv:{riga.pk}:{asset.pk}"})
        riga.refresh_from_db()
        self.assertIsNone(riga.hub_asset)


class SenzaInventarioTests(_Base):
    def setUp(self):
        super().setUp()
        self.vuoto = Asset.objects.create(asset_tag="PC-V", name="PC vuoto", asset_type=Asset.TYPE_PC)
        self.pieno = Asset.objects.create(asset_tag="PC-P", name="PC pieno", asset_type=Asset.TYPE_NOTEBOOK)
        _sw("pc-pieno", hub=self.pieno)
        Asset.objects.create(asset_tag="PC-R", name="PC dismesso", asset_type=Asset.TYPE_PC, status=Asset.STATUS_RETIRED)
        Asset.objects.create(asset_tag="CNC-1", name="Macchina", asset_type=Asset.TYPE_CNC)

    def test_elenco_solo_pc_e_server_in_uso(self):
        r = self.client.get(self.url, {"vista": "inventario"})
        self.assertEqual(r.context["da_spiegare"], [self.vuoto])
        self.assertContains(r, "PC vuoto")
        self.assertContains(r, "Fuori dominio")
        self.assertNotContains(r, "{#")

    def test_motivo_e_togli(self):
        self.client.post(self.url, {"azione": "motivo", "asset": self.vuoto.pk, "motivo": "fuori_dominio", "nota": "Laboratorio"})
        r = self.client.get(self.url, {"vista": "inventario"})
        self.assertEqual(r.context["da_spiegare"], [])
        self.assertContains(r, "Già spiegati (1)")
        self.assertContains(r, "Laboratorio")
        self.client.post(self.url, {"azione": "togli_motivo", "asset": self.vuoto.pk})
        self.assertFalse(AssetSenzaInventario.objects.exists())

    def test_motivo_non_valido_o_senza_permesso(self):
        self.client.post(self.url, {"azione": "motivo", "asset": self.vuoto.pk, "motivo": "boh"})
        with patch("assets.views._can_edit_asset", return_value=False):
            self.client.post(self.url, {"azione": "motivo", "asset": self.vuoto.pk, "motivo": "altro"})
        self.assertFalse(AssetSenzaInventario.objects.exists())
