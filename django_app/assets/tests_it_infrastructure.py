from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from assets import views
from assets.models import Asset, AssetCategory, AssetDetailField, AssetITDetails, WorkMachine
from assets.services.it_monitoring import can_view_monitoring, monitoring_for_asset
from assets.services.it_presentation import it_context
from contatori.models import DispositivoSNMP, LetturaMensileContatori, Macchina, RilevazioneSNMP
from security.models import SecurityAsset


class InfrastructureProfilesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("infra-demo", "infra@example.test", "synthetic-only")
        self.client.force_login(self.user)

    def asset(self, kind):
        return Asset.objects.create(asset_tag=f"DEMO-{kind}", name=f"Demo {kind}", asset_type=kind)

    def page(self, asset):
        return self.client.get(reverse("assets:asset_view", args=[asset.pk]))

    def test_server_and_vm_do_not_infer_technical_owner(self):
        for kind in ("SERVER", "VM"):
            with self.subTest(kind=kind):
                asset = self.asset(kind)
                asset.assignment_to = "Assegnatario demo"
                asset.save()
                response = self.page(asset)
                self.assertContains(response, "Assegnazione censita")
                self.assertContains(response, "Referente tecnico, servizio e criticità non sono ancora censiti")
                self.assertContains(response, "Dispositivo non collegato al SOC")
                self.assertNotContains(response, "Salute batteria")

    def test_vm_has_no_physical_bios_declaration(self):
        vm = self.asset("VM")
        AssetITDetails.objects.create(asset=vm, bios_pwd_set=True, cpu="4 vCPU")
        response = self.page(vm)
        self.assertContains(response, "Host di virtualizzazione non collegato")
        self.assertNotContains(response, "Password BIOS impostata")
        self.assertContains(response, "4 vCPU")

    def test_printer_hides_untouched_pc_defaults_but_keeps_custom_fields(self):
        asset = self.asset("STAMPANTE")
        views._seed_default_asset_detail_fields()
        AssetITDetails.objects.create(asset=asset, cpu="CPU-LEGACY", ram="RAM-LEGACY", os="OS-LEGACY", disco="DISK-LEGACY", edr_enabled=True)
        AssetDetailField.objects.create(code="printer-firmware", label="Firmware dichiarato", section="SPECS", source_ref="it:os")
        response = self.page(asset)
        self.assertContains(response, "Firmware dichiarato")
        self.assertContains(response, "OS-LEGACY")
        self.assertNotContains(response, "CPU-LEGACY")
        self.assertNotContains(response, "RAM-LEGACY")
        self.assertNotContains(response, "EDR abilitato")
        self.assertNotContains(response, "Dispositivo non collegato al SOC")
        self.assertContains(response, "Nessun monitoraggio collegato consultabile")

    def test_printer_still_shows_soc_when_explicitly_linked(self):
        asset = self.asset("STAMPANTE")
        SecurityAsset.objects.create(hostname="PRINTER-DEMO", hub_asset=asset)
        self.assertContains(self.page(asset), 'id="asset-security-section"')

    def test_industrial_extension_wins_for_all_new_profiles(self):
        for kind in ("SERVER", "VM", "STAMPANTE"):
            asset = self.asset(kind)
            WorkMachine.objects.create(asset=asset, source_key=f"demo-industrial-{kind}")
            asset.refresh_from_db()
            self.assertIsNone(it_context(asset))

    def test_server_computed_fields_do_not_use_capacity_or_creation(self):
        asset = self.asset("SERVER")
        details = AssetITDetails.objects.create(asset=asset, disco="1 TB")
        for source in ("computed:storage_free", "computed:purchase_date"):
            value = views._resolve_asset_detail_source_value(source_ref=source, asset=asset, it_details=details, work_machine=None, extra={}, custom_fields_by_code={}, sync_text="")
            self.assertEqual(value, "")

    def test_legacy_other_printer_category_activates_inline_profile_without_reclassification(self):
        category = AssetCategory.objects.create(code="demo-printers", label="Stampanti", base_asset_type="OTHER")
        asset = self.asset("OTHER")
        asset.asset_category = category
        asset.save()
        response = self.page(asset)
        self.assertContains(response, "Stampante, consumabili e contatori")
        self.assertContains(response, "Stampante / MFC · da categoria")
        asset.refresh_from_db()
        self.assertEqual(asset.asset_type, "OTHER")

    def test_category_base_type_and_parent_but_not_device_name_are_used(self):
        parent = AssetCategory.objects.create(code="demo-vms", label="Virtualizzazione", base_asset_type="VM")
        child = AssetCategory.objects.create(code="demo-vm-child", label="Ambiente demo", parent=parent)
        asset = self.asset("OTHER")
        asset.asset_category = child
        self.assertEqual(it_context(asset)["profile"], "vm")
        asset.asset_type = "CNC"
        self.assertIsNone(it_context(asset))
        asset.asset_type = "OTHER"
        asset.asset_category = None
        asset.name = "Server stampante demo"
        self.assertIsNone(it_context(asset))


class ITMonitoringTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("monitor-demo", "monitor@example.test", "synthetic-only")
        self.request = SimpleNamespace(user=self.user)
        self.asset = Asset.objects.create(asset_tag="PR-DEMO", name="Stampante demo", asset_type="STAMPANTE")
        self.device = DispositivoSNMP.objects.create(nome="Stampante SNMP demo", categoria="STAMPANTE", host="192.0.2.44", asset=self.asset, snmp_stato="OK", snmp_ultimo_controllo=timezone.now() - timedelta(days=15))

    def snapshot(self, **kwargs):
        return RilevazioneSNMP.objects.create(dispositivo=self.device, stato=kwargs.pop("stato", "OK"), **kwargs)

    def test_no_permission_means_no_queries_or_content(self):
        with patch("assets.services.it_monitoring.acl_allows_path", return_value=False), self.assertNumQueries(0):
            self.assertIsNone(monitoring_for_asset(self.request, self.asset))
        self.client.force_login(self.user)
        with patch("assets.services.it_monitoring.acl_allows_path", return_value=False):
            response = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertNotContains(response, "Stampante SNMP demo")
        self.assertNotContains(response, "192.0.2.44")
        self.assertNotContains(response, 'id="asset-it-monitoring"')

    def test_detail_permission_checked_beyond_central(self):
        central = reverse("contatori:snmp_centrale")
        with patch("assets.services.it_monitoring.acl_allows_path", side_effect=lambda path, **kw: path == central):
            result = monitoring_for_asset(self.request, self.asset)
        self.assertEqual(result["devices"], [])

    def test_permission_database_error_fails_closed(self):
        with patch("assets.services.it_monitoring.acl_allows_path", side_effect=DatabaseError("synthetic")):
            self.assertFalse(can_view_monitoring(self.request, "/contatori/"))

    def test_zero_unknown_and_partial_payload_remain_distinct(self):
        self.snapshot(dati_stampante={"consumabili": [{"nome": "Nero", "pct": 0}, {"nome": "Ciano", "pct": None}, {"nome": "Magenta", "pct": -3}], "contatori": [{"indice": "1", "valore": 0, "unita": "fogli"}], "errori": {"lettura": "PRIVATE-ERROR"}})
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertContains(response, "0%")
        self.assertContains(response, "Quantità non comunicata")
        self.assertContains(response, "Rilevazione parziale")
        self.assertNotContains(response, "-3%")
        self.assertNotContains(response, "PRIVATE-ERROR")
        self.assertNotContains(response, "Operativo")
        self.assertContains(response, "non la disponibilità attuale")

    def test_failed_latest_snapshot_does_not_reuse_old_consumables(self):
        self.snapshot(rilevata_il=timezone.now() - timedelta(days=1), dati_stampante={"consumabili": [{"nome": "Old", "pct": 99}]})
        latest = self.snapshot(stato="ERROR", dati_stampante={})
        row = monitoring_for_asset(self.request, self.asset)["devices"][0]
        self.assertEqual(row["snapshot"]["id"], latest.pk)
        self.assertEqual(row["supplies"], [])

    def test_mfc_and_printer_counters_not_combined_and_queries_bounded(self):
        self.snapshot(dati_stampante={"contatori": [{"valore": 100, "unita": "fogli"}]})
        machine = Macchina.objects.create(reparto="Demo MFC", matricola="DEMO-SERIAL", asset=self.asset)
        reading = LetturaMensileContatori.objects.create(macchina=machine, mese=timezone.localdate().replace(day=1), a4_bn=300, a3_bn=5, a4_col=10, a3_col=2)
        with patch("assets.services.it_monitoring.can_view_monitoring", return_value=True), self.assertNumQueries(4):
            data = monitoring_for_asset(self.request, self.asset)
        self.assertEqual(data["devices"][0]["counters"][0]["valore"], 100)
        self.assertEqual(data["machines"][0]["reading"]["id"], reading.pk)
        self.assertEqual(data["machines"][0]["reading"]["a4_bn"], 300)

    def test_projection_never_polls_or_exposes_credentials(self):
        self.device.community = "SYNTHETIC-COMMUNITY"
        self.device.save()
        with patch("contatori.snmp.leggi_consumabili", side_effect=AssertionError("must not poll")):
            data = monitoring_for_asset(self.request, self.asset)
        self.assertNotIn("SYNTHETIC-COMMUNITY", str(data))
        self.assertNotIn("community", data["devices"][0])

    def test_disabled_monitoring_and_missing_snapshots_are_explicit(self):
        self.device.attivo = False
        self.device.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertContains(response, "Monitoraggio disattivato")
        self.assertContains(response, "Contatori non disponibili nell'ultima rilevazione")

    def test_inline_mfc_action_respects_own_permission_and_never_polls_on_page_get(self):
        machine = Macchina.objects.create(reparto="Demo", matricola="INLINE-DEMO", host="192.0.2.70", asset=self.asset)
        action = reverse("contatori:macchina_consumabili", args=[machine.pk])
        with patch("assets.services.it_monitoring.can_view_monitoring", side_effect=lambda request, path: path != action):
            self.assertEqual(monitoring_for_asset(self.request, self.asset)["machines"][0]["supplies_url"], "")
        self.client.force_login(self.user)
        with patch("contatori.views._leggi_consumabili_cfg", side_effect=AssertionError("no automatic polling")):
            response = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertContains(response, "Leggi consumabili qui")
        self.assertContains(response, "192.0.2.70")

    def test_inline_mfc_consumables_post_renders_levels_and_sanitizes_errors(self):
        machine = Macchina.objects.create(reparto="Demo", matricola="INLINE-POST", host="192.0.2.71", asset=self.asset)
        action = reverse("contatori:macchina_consumabili", args=[machine.pk])
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(action).status_code, 405)
        with patch("contatori.views._leggi_consumabili_cfg", return_value=([{"nome": "Nero demo", "pct": 0}, {"nome": "Ciano demo", "pct": None}], None)):
            response = self.client.post(action, {"asset_inline": "1"})
        self.assertContains(response, "0%")
        self.assertContains(response, "Quantità non comunicata")
        with patch("contatori.views._leggi_consumabili_cfg", return_value=(None, "PRIVATE-NETWORK-ERROR")):
            response = self.client.post(action, {"asset_inline": "1"})
        self.assertContains(response, "Lettura non riuscita")
        self.assertNotContains(response, "PRIVATE-NETWORK-ERROR")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        csrf_client.cookies["csrftoken"] = "a" * 32
        with patch("contatori.views._leggi_consumabili_cfg") as poll:
            self.assertEqual(csrf_client.post(action, {"asset_inline": "1"}).status_code, 403)
            poll.assert_not_called()
