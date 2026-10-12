"""Inventario software nella gestione asset: scheda del PC, licenze collegate, PC contati."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, SoftwareLicense
from security.models import SoftwareInstallation
from security.services import software_catalog


def _install(host, version, *, hub=None, still=True, product="7-zip", vendor="igor pavlov", days_ago=0):
    now = timezone.now() - timedelta(days=days_ago)
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}-{product}-{version}", source_kind="watchguard", host=host.lower(), host_display=host, hub_asset=hub,
        vendor=vendor, vendor_raw="Igor Pavlov", product=product, product_raw="7-Zip (x64)", version_raw=version,
        still_detected=still, seen_at=now, last_seen_at=now,
    )


class SoftwareCatalogTests(TestCase):
    def setUp(self):
        self.hub = Asset.objects.create(asset_tag="SW-DEMO", name="PC-DEMO-01")
        _install("PC-DEMO-01", "23.01", hub=self.hub, still=False, days_ago=40)
        _install("PC-DEMO-01", "24.08", hub=self.hub)
        _install("PC-DEMO-02", "24.08")
        self.key = software_catalog.inventory_key("igor pavlov", "7-zip")

    def test_asset_rows_group_versions_and_keep_history(self):
        data = software_catalog.software_for_hub_asset(self.hub)
        self.assertEqual(data["present"], 1)
        row = data["rows"][0]
        self.assertEqual(row["versions"], ["24.08"])
        self.assertEqual([p["version"] for p in row["previous"]], ["23.01"])
        self.assertEqual(row["first_seen"].date(), (timezone.now() - timedelta(days=40)).date())

    def test_hosts_by_key_counts_only_present_installs(self):
        self.assertEqual(software_catalog.hosts_by_key({self.key}), {self.key: 2})

    def test_license_states(self):
        today = timezone.localdate()
        valid = SoftwareLicense(product_name="7-Zip", inventory_key=self.key, expiry_date=today + timedelta(days=10))
        expired = SoftwareLicense(product_name="Altro", inventory_key="x|y", expiry_date=today - timedelta(days=1))
        self.assertEqual(software_catalog.license_states_for_keys([valid, expired]), {self.key: "coperta", "x|y": "scaduta"})

    def test_catalog_lists_product_with_pc_count(self):
        item = software_catalog.catalog()[0]
        self.assertEqual((item["key"], item["label"], item["hosts"]), (self.key, "7-Zip (x64)", 2))


class SoftwarePagesTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create(username="sw_admin", is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)
        self.hub = Asset.objects.create(asset_tag="SW-DEMO", name="PC-DEMO-01")
        _install("PC-DEMO-01", "24.08", hub=self.hub)
        _install("PC-DEMO-02", "24.08")
        self.key = software_catalog.inventory_key("igor pavlov", "7-zip")

    def test_asset_page_shows_installed_software_with_license(self):
        SoftwareLicense.objects.create(product_name="7-Zip", inventory_key=self.key, seats_total=5)
        response = self.client.get(reverse("assets:asset_view", args=[self.hub.pk]))
        self.assertContains(response, "Software installati")
        self.assertContains(response, "7-Zip (x64)")
        self.assertContains(response, "Licenza valida")

    def test_asset_without_inventory_has_no_section(self):
        other = Asset.objects.create(asset_tag="SW-ALTRO", name="ALTRO")
        self.assertNotContains(self.client.get(reverse("assets:asset_view", args=[other.pk])), "Software installati")

    def test_license_list_counts_pcs_and_flags_over_seats(self):
        SoftwareLicense.objects.create(product_name="7-Zip", inventory_key=self.key, seats_total=1)
        response = self.client.get(reverse("assets:software_license_list"))
        self.assertContains(response, "Installato su <strong>2</strong> PC su 1 posti", html=False)
        self.assertContains(response, "Più installazioni che posti")

    def test_license_form_offers_inventory_software(self):
        response = self.client.get(reverse("assets:software_license_list"))
        self.assertContains(response, 'name="inventory_key"')
        self.assertContains(response, "7-Zip (x64) · Igor Pavlov (2 PC)")
