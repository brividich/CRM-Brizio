from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from assets import views
from assets.models import Asset, AssetDetailField, AssetDetailSectionLayout, AssetEndpoint, AssetITDetails, WorkMachine
from assets.services.it_presentation import workstation_context


class WorkstationPresentationTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("it-presentation", "it@example.test", "synthetic-only")
        self.client.force_login(self.admin)
        self.asset = Asset.objects.create(asset_tag="IT-DEMO-01", name="Postazione dimostrativa", asset_type=Asset.TYPE_NOTEBOOK)

    def page(self, asset=None):
        return self.client.get(reverse("assets:asset_view", args=[(asset or self.asset).pk]))

    def test_empty_profile_and_unlinked_soc_are_explicit(self):
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dispositivo non collegato al SOC")
        self.assertContains(response, "Sistema operativo da censire")
        self.assertContains(response, "Nessuna interfaccia censita")
        self.assertNotContains(response, "Salute batteria")
        self.assertNotContains(response, "Carico medio CPU")
        self.assertContains(response, 'id="asset-security-section"', count=1)

    def test_real_specs_and_multiple_interfaces(self):
        AssetITDetails.objects.create(asset=self.asset, os="OS dimostrativo", cpu="CPU test", disco="512 GB", edr_enabled=True)
        AssetEndpoint.objects.create(asset=self.asset, endpoint_name="LAN", ip="192.0.2.10", vlan=10)
        AssetEndpoint.objects.create(asset=self.asset, endpoint_name="WLAN", ip="192.0.2.11", vlan=20)
        response = self.page()
        self.assertContains(response, "512 GB")
        self.assertContains(response, "192.0.2.10")
        self.assertContains(response, "192.0.2.11")
        self.assertContains(response, "Sì, dichiarato")
        self.assertContains(response, "No / non verificato")
        self.assertNotIn("Data acquisto", dict(response.context["spec_pairs"]))

    def test_computed_fields_do_not_invent_measurements_or_purchase(self):
        details = AssetITDetails.objects.create(asset=self.asset, disco="512 GB")
        kwargs = dict(asset=self.asset, it_details=details, work_machine=None, extra={}, custom_fields_by_code={}, sync_text="")
        for field in ("storage_free", "purchase_date"):
            self.assertEqual(views._resolve_asset_detail_source_value(source_ref=f"computed:{field}", **kwargs), "")
        kwargs["extra"] = {"storage_free": "120 GB"}
        self.assertEqual(views._resolve_asset_detail_source_value(source_ref="computed:storage_free", **kwargs), "120 GB")

    def test_custom_layout_order_fields_and_hidden_sections_survive(self):
        AssetDetailField.objects.create(code="custom-demo", label="Campo personalizzato", section="SPECS", source_ref="asset:serial_number")
        self.asset.serial_number = "SERIAL-DEMO"
        self.asset.save()
        AssetDetailSectionLayout.objects.update_or_create(code="QR", defaults={"is_visible": False})
        response = self.page()
        self.assertContains(response, "Campo personalizzato")
        self.assertContains(response, "SERIAL-DEMO")
        self.assertNotContains(response, 'id="asset-section-qr"')
        body = response.content.decode()
        positions = [body.index(f'id="asset-section-{card["code"].lower()}"') for card in response.context["detail_section_cards"]]
        self.assertEqual(positions, sorted(positions))

    def test_non_it_profiles_keep_existing_page(self):
        # Il firewall ha ora un profilo IT proprio ("network"): vedi DeviceKpiBandTests.
        for kind in (Asset.TYPE_CNC, Asset.TYPE_OTHER):
            with self.subTest(kind=kind):
                asset = Asset.objects.create(asset_tag=f"DEMO-{kind}", name=f"Demo {kind}", asset_type=kind)
                response = self.page(asset)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'id="asset-it-overview"')
                self.assertIsNone(response.context["it_presentation"])

    def test_industrial_extension_wins_over_pc_type(self):
        WorkMachine.objects.create(asset=self.asset, source_key="it-ot-demo", x_mm=100)
        self.asset.refresh_from_db()
        self.assertIsNone(workstation_context(self.asset))
        response = self.page()
        self.assertNotContains(response, 'id="asset-it-overview"')
        self.assertContains(response, "Corsa X")

    def test_soc_projection_not_called_without_permission(self):
        with patch("security.templatetags.security_asset.can_view_security_center", return_value=False), patch("security.services.asset_overview.overview_for_hub_asset") as projection:
            response = self.page()
        projection.assert_not_called()
        self.assertNotContains(response, 'id="asset-security-section"')
        self.assertNotContains(response, "Alert attivi collegati")

    def test_hidden_profile_does_not_reveal_custom_specs_in_new_section(self):
        AssetDetailField.objects.create(code="hidden-demo", label="Specifiche riservate al layout", section="SPECS", source_ref="asset:serial_number")
        AssetDetailSectionLayout.objects.update_or_create(code="PROFILE", defaults={"is_visible": False})
        self.asset.serial_number = "DEMO-SERIAL"
        self.asset.save()
        self.assertNotContains(self.page(), "Specifiche riservate al layout")

    def test_ticket_action_reuses_native_permission(self):
        with patch("tickets.views._can_open_tickets", return_value=True):
            response = self.page()
        self.assertContains(response, "Apri ticket IT")
        self.assertEqual(response.context["it_ticket_create_url"], f"{reverse('tickets:nuovo')}?tipo=IT&asset={self.asset.pk}")
        with patch("tickets.views._can_open_tickets", return_value=False):
            self.assertNotContains(self.page(), "Apri ticket IT")

    def test_disclosures_and_soc_precede_management(self):
        response = self.page()
        body = response.content.decode()
        self.assertLess(body.index('id="asset-security-section"'), body.index('id="asset-section-maintenance"'))
        self.assertContains(response, '<details class="af-card af-it-disclosure')
        self.assertContains(response, "asset-it.css")
