"""Manutenzione, round 2 di UI/UX (docs/manutenzione/CHECKLIST_UX_2026-09.md)."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    WorkOrder,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class Ux2TestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.admin = User.objects.create_superuser(username="ux2-admin", password="x", email="u@b.c")
        cls.altro = User.objects.create_user(username="ux2-altro", password="x")
        cls.category = AssetCategory.objects.create(code="ux2-cnc", label="CNC ux2")
        cls.asset = Asset.objects.create(asset_tag="UX2-01", name="Tornio", asset_category=cls.category)
        cls.asset2 = Asset.objects.create(asset_tag="UX2-02", name="Fresa", asset_category=cls.category)
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="ux2-lub", label="Lubrificazione ux2")
        due = cls.today + timedelta(days=2)
        cls.libera = MaintenanceOccurrence.objects.create(plan=cls.plan, asset=cls.asset, due_date=due, warning_days=30)
        cls.di_altri = MaintenanceOccurrence.objects.create(plan=cls.plan, asset=cls.asset2, due_date=due, warning_days=30)
        wo = WorkOrder.objects.create(asset=cls.asset2, title="OdL di un altro", assigned_to=cls.altro)
        MaintenanceOccurrence.objects.filter(pk=cls.di_altri.pk).update(work_order=wo)

    def setUp(self):
        self.client.force_login(self.admin)


class DaFareManutentoreTests(Ux2TestCase):
    def _ids(self, response):
        return {row["occurrence"].id for block in response.context["blocks"] for row in block["rows"]}

    def test_chi_pianifica_vede_tutto_di_default(self):
        response = self.client.get(reverse("assets:maintenance_da_fare"))
        self.assertFalse(response.context["only_mine"])
        self.assertEqual(self._ids(response), {self.libera.id, self.di_altri.id})

    def test_il_mio_lavoro_esclude_quello_assegnato_ad_altri(self):
        response = self.client.get(reverse("assets:maintenance_da_fare"), {"mio": "1"})
        self.assertTrue(response.context["only_mine"])
        self.assertEqual(self._ids(response), {self.libera.id})
        self.assertContains(response, "Il mio lavoro")

    def test_chi_esegue_senza_pianificare_apre_sul_suo_lavoro(self):
        with mock.patch("assets.views_maintenance.can_plan_maintenance", return_value=False), \
                mock.patch("assets.views_maintenance.can_execute_maintenance", return_value=True):
            response = self.client.get(reverse("assets:maintenance_da_fare"))
            self.assertTrue(response.context["only_mine"])
            tutto = self.client.get(reverse("assets:maintenance_da_fare"), {"mio": "0"})
            self.assertFalse(tutto.context["only_mine"])


class CalendarioOdlTests(Ux2TestCase):
    def test_json_segnala_cosa_si_puo_pianificare(self):
        response = self.client.get(
            reverse("assets:calendario_asset_json"),
            {"start": (self.today - timedelta(days=5)).isoformat(), "end": (self.today + timedelta(days=10)).isoformat()},
        )
        events = {e["id"]: e for e in response.json()["events"]}
        libera = events[f"occ-{self.libera.id}"]
        self.assertTrue(libera["plannable"])
        self.assertEqual(libera["occurrence_id"], self.libera.id)
        self.assertFalse(events[f"occ-{self.di_altri.id}"]["plannable"])  # ha gia' un OdL

    def test_vassoio_solo_per_chi_pianifica_e_crea_l_odl(self):
        page = self.client.get(reverse("assets:calendario_asset"))
        self.assertContains(page, 'id="cm-tray"', html=False)
        response = self.client.post(
            reverse("assets:occurrence_create_workorder"),
            {"occurrence_ids": [self.libera.id], "next": reverse("assets:calendario_asset")},
        )
        self.libera.refresh_from_db()
        self.assertIsNotNone(self.libera.work_order_id)
        self.assertRedirects(response, reverse("assets:wo_view", args=[self.libera.work_order_id]), fetch_redirect_response=False)
        with mock.patch("assets.views_maintenance.can_plan_maintenance", return_value=False):
            self.assertNotContains(self.client.get(reverse("assets:calendario_asset")), 'id="cm-tray"', html=False)


class ScadenzarioExportTests(Ux2TestCase):
    def test_excel_con_gli_stessi_filtri(self):
        import io

        from openpyxl import load_workbook

        response = self.client.get(reverse("assets:maintenance_scadenze"), {"window": "30", "q": "UX2-01", "format": "xlsx"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("scadenzario_manutenzione_", response["Content-Disposition"])
        sheet = load_workbook(io.BytesIO(response.content)).active
        valori = [str(cell.value or "") for row in sheet.iter_rows() for cell in row]
        self.assertIn("UX2-01", valori)
        self.assertNotIn("UX2-02", valori)  # filtrato fuori dalla ricerca

    def test_pdf_e_pulsanti_in_testata(self):
        response = self.client.get(reverse("assets:maintenance_scadenze"), {"window": "30", "format": "pdf"})
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        page = self.client.get(reverse("assets:maintenance_scadenze"), {"window": "30"})
        self.assertContains(page, "format=xlsx")
        self.assertContains(page, "format=pdf")


class SchedaAssetScadenzeTests(Ux2TestCase):
    def test_la_scheda_asset_mostra_tutte_le_sue_scadenze(self):
        from anagrafica.models import Fornitore
        from assets.models import AssistanceContract, SoftwareLicense

        SoftwareLicense.objects.create(product_name="Licenza CAM ux2", asset=self.asset, expiry_date=self.today + timedelta(days=20))
        fornitore = Fornitore.objects.create(ragione_sociale="Service ux2")
        AssistanceContract.objects.create(
            supplier=fornitore, title="Contratto categoria ux2", asset_category=self.category,
            end_date=self.today + timedelta(days=40),
        )
        response = self.client.get(reverse("assets:asset_view", args=[self.asset.id]))
        self.assertEqual(response.status_code, 200)
        titoli = [row.title for row in response.context["asset_deadline_rows"]]
        self.assertIn("Lubrificazione ux2", titoli)
        self.assertIn("Licenza CAM ux2", titoli)
        self.assertIn("Contratto categoria ux2", titoli)  # contratto sulla categoria dell'asset
        self.assertContains(response, "Scadenze di questo asset")

    def test_scadenzario_filtrato_per_asset_include_licenze(self):
        from assets.models import SoftwareLicense

        SoftwareLicense.objects.create(product_name="Licenza CAM ux2", asset=self.asset, expiry_date=self.today + timedelta(days=20))
        response = self.client.get(reverse("assets:maintenance_scadenze"), {"window": "", "asset": self.asset.id})
        self.assertEqual([r.title for r in response.context["renewals"]], ["Licenza CAM ux2"])
        self.assertEqual({r["occurrence"].id for r in response.context["rows"]}, {self.libera.id})


class ImpostaManutenzioneTests(Ux2TestCase):
    def test_percorso_legge_i_dati_veri(self):
        from assets.models import MaintenancePlanAssignment

        response = self.client.get(reverse("assets:maintenance_setup"))
        self.assertEqual(response.status_code, 200)
        steps = {s["key"]: s for s in response.context["steps"]}
        self.assertEqual(steps["piani"]["status"], "done")
        # Il piano di prova non e' applicato a niente: il passo 2 lo elenca.
        self.assertEqual(steps["applicazioni"]["status"], "todo")
        self.assertIn("Lubrificazione ux2", [label for label, _url in steps["applicazioni"]["items"]])
        self.assertEqual(steps["gruppi"]["status"], "optional")
        self.assertContains(response, "Imposta la manutenzione")

        MaintenancePlanAssignment.objects.create(
            plan=self.plan, target_type=MaintenancePlanAssignment.TARGET_CATEGORY, asset_category=self.category,
            frequency=MaintenancePlanAssignment.FREQ_DAYS, interval=30, auto_generate=False,
        )
        steps = {s["key"]: s for s in self.client.get(reverse("assets:maintenance_setup")).context["steps"]}
        self.assertEqual(steps["applicazioni"]["status"], "done")
        self.assertEqual(steps["generazione"]["status"], "todo")  # periodicita' da confermare

    def test_voce_di_menu_in_configurazione(self):
        response = self.client.get(reverse("assets:maintenance_setup"))
        self.assertContains(response, 'aria-label="Configurazione"', html=False)
        self.assertContains(response, 'aria-current="page">Imposta</a>', html=False)


class GruppiFacoltativiTests(Ux2TestCase):
    def test_filtro_gruppo_solo_se_esistono_gruppi(self):
        from assets.forms_maintenance import OccurrenceFilterForm
        from assets.models import AssetGroup

        self.assertNotIn("group", OccurrenceFilterForm({}).fields)
        AssetGroup.objects.create(code="linea-3", label="Linea 3")
        self.assertIn("group", OccurrenceFilterForm({}).fields)
        page = self.client.get(reverse("assets:asset_group_list"))
        self.assertContains(page, "Famiglia o gruppo?")


class BadgeDaFareTests(Ux2TestCase):
    def test_badge_con_le_scadute(self):
        MaintenanceOccurrence.objects.create(plan=self.plan, asset=self.asset, due_date=self.today - timedelta(days=3), warning_days=30)
        response = self.client.get(reverse("assets:maintenance_scadenze"))
        self.assertContains(response, 'class="as-nav-badge"', html=False)
