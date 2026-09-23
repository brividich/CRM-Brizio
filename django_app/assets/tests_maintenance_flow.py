"""Flusso della manutenzione dall'inizio alla fine: applicare un piano, vedere le
scadenze, registrare e tornare dove si era. Dall'audit dei link del 23/09/2026."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class FlussoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.admin = User.objects.create_superuser(username="flow-admin", password="x", email="f@l.w")
        cls.category = AssetCategory.objects.create(code="flow-cat", label="Flow")
        cls.asset = Asset.objects.create(asset_tag="FLOW-1", name="Pressa", asset_category=cls.category,
                                         status=Asset.STATUS_IN_USE)
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="flow-plan", label="Ingrassaggio flow")

    def setUp(self):
        self.client.force_login(self.admin)

    def _apply(self, first_due):
        return self.client.post(
            reverse("assets:maintenance_assignment_create", args=[self.plan.id]),
            {
                "target_type": MaintenancePlanAssignment.TARGET_CATEGORY,
                "asset_category": self.category.id,
                "frequency": MaintenancePlanAssignment.FREQ_DAYS,
                "interval": 30,
                "warning_days": 15,
                "first_due_date": first_due.isoformat(),
                "schedule_anchor": MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR,
                "auto_generate": "on",
                "is_active": "on",
            },
            follow=True,
        )

    def test_applicare_un_piano_crea_subito_le_scadenze_in_preavviso(self):
        response = self._apply(self.today + timedelta(days=5))
        self.assertTrue(MaintenancePlanAssignment.objects.filter(plan=self.plan).exists(), response.content[:500])
        self.assertTrue(MaintenanceOccurrence.objects.filter(plan=self.plan, asset=self.asset).exists())
        self.assertContains(response, "1 scadenza creata ora")

    def test_scadenza_lontana_compare_come_prevista_nel_calendario(self):
        self._apply(self.today + timedelta(days=60))
        self.assertFalse(MaintenanceOccurrence.objects.filter(plan=self.plan).exists())
        events = self.client.get(
            reverse("assets:calendario_asset_json"),
            {"start": self.today.isoformat(), "end": (self.today + timedelta(days=130)).isoformat()},
        ).json()["events"]
        forecasts = [e for e in events if e["state"] == "forecast" and e["title"] == "Ingrassaggio flow"]
        # La serie continua: 60, 90, 120 giorni.
        self.assertGreaterEqual(len(forecasts), 3)
        self.assertFalse(any(e.get("movable") or e.get("plannable") for e in forecasts))
        spente = self.client.get(
            reverse("assets:calendario_asset_json"),
            {"start": self.today.isoformat(), "end": (self.today + timedelta(days=130)).isoformat(), "forecast": "0"},
        ).json()["events"]
        self.assertFalse(any(e["state"] == "forecast" for e in spente))

    def test_registrare_riporta_alla_pagina_di_partenza(self):
        occ = MaintenanceOccurrence.objects.create(plan=self.plan, asset=self.asset, due_date=self.today, warning_days=10)
        partenza = reverse("assets:calendario_asset") + "?kinds=ordinary"
        page = self.client.get(reverse("assets:occurrence_complete", args=[occ.id]), HTTP_REFERER="http://testserver" + partenza)
        self.assertContains(page, f'value="http://testserver{partenza}"', html=False)
        response = self.client.post(
            reverse("assets:occurrence_complete", args=[occ.id]),
            {"completed_on": self.today.isoformat(), "next": partenza},
        )
        self.assertRedirects(response, partenza, fetch_redirect_response=False)
        # Un "next" esterno non viene mai seguito.
        occ2 = MaintenanceOccurrence.objects.create(plan=self.plan, asset=self.asset, due_date=self.today + timedelta(days=1), warning_days=10)
        response = self.client.post(
            reverse("assets:occurrence_complete", args=[occ2.id]),
            {"completed_on": self.today.isoformat(), "next": "https://evil.example/"},
        )
        self.assertEqual(response["Location"], reverse("assets:maintenance_da_fare"))

    def test_link_della_scheda_asset_vanno_alle_pagine_nuove(self):
        from assets.views import _asset_maintenance_rule_list_page_url, _maintenance_schedule_page_url

        self.assertEqual(
            _maintenance_schedule_page_url(asset_id=self.asset.id, status="due"),
            f"{reverse('assets:maintenance_scadenze')}?asset={self.asset.id}&window=30",
        )
        self.assertEqual(
            _asset_maintenance_rule_list_page_url(self.asset.id),
            reverse("assets:asset_maintenance_plans", args=[self.asset.id]),
        )


    def test_registrare_propone_ultima_volta_e_altre_scadenze_della_macchina(self):
        MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=self.today - timedelta(days=40), warning_days=10,
            status=MaintenanceOccurrence.STATUS_DONE, completed_on=self.today - timedelta(days=41),
            downtime_minutes=45,
        )
        occ = MaintenanceOccurrence.objects.create(plan=self.plan, asset=self.asset, due_date=self.today, warning_days=10)
        altro = MaintenanceInterventionTemplate.objects.create(code="flow-plan-2", label="Controllo cinghie")
        MaintenanceOccurrence.objects.create(plan=altro, asset=self.asset, due_date=self.today + timedelta(days=7), warning_days=10)
        response = self.client.get(reverse("assets:occurrence_complete", args=[occ.id]))
        self.assertContains(response, "Usa lo stesso fermo")
        self.assertContains(response, "Controllo cinghie")

    def test_applicare_propone_la_famiglia_degli_asset_scoperti(self):
        Asset.objects.create(asset_tag="FLOW-2", name="Pressa 2", asset_category=self.category, status=Asset.STATUS_IN_USE)
        MaintenancePlanAssignment.objects.create(
            plan=self.plan, target_type=MaintenancePlanAssignment.TARGET_ASSET, asset=self.asset,
            frequency=MaintenancePlanAssignment.FREQ_DAYS, interval=30, warning_days=15,
            first_due_date=self.today + timedelta(days=60),
            schedule_anchor=MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR,
        )
        response = self.client.get(reverse("assets:maintenance_assignment_create", args=[self.plan.id]))
        self.assertContains(response, "FLOW-2")
        self.assertContains(response, "Usa la famiglia")

    def test_scheda_piano_permette_la_multiselezione(self):
        occ = MaintenanceOccurrence.objects.create(plan=self.plan, asset=self.asset, due_date=self.today, warning_days=10)
        response = self.client.get(reverse("assets:maintenance_plan_detail", args=[self.plan.id]))
        self.assertContains(response, f'value="{occ.id}" form="md-bulk-form"')
        self.assertContains(response, 'id="md-bulk-form"')


@override_settings(LEGACY_AUTH_ENABLED=False)
class OdlPerAssetTests(TestCase):
    """Selezione multipla -> un OdL per asset e giorno, numerati X-1, X-2 (WorkOrder.mark_batch)."""

    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.admin = User.objects.create_superuser(username="batch-admin", password="x", email="b@a.t")
        cls.a1 = Asset.objects.create(asset_tag="B-01", name="Tornio", status=Asset.STATUS_IN_USE)
        cls.a2 = Asset.objects.create(asset_tag="B-02", name="Fresa", status=Asset.STATUS_IN_USE)
        cls.p1 = MaintenanceInterventionTemplate.objects.create(code="b-lub", label="Lubrificazione")
        cls.p2 = MaintenanceInterventionTemplate.objects.create(code="b-fil", label="Filtri")

    def setUp(self):
        self.client.force_login(self.admin)
        d = self.today + timedelta(days=3)
        self.o1 = MaintenanceOccurrence.objects.create(plan=self.p1, asset=self.a1, due_date=d, warning_days=10)
        self.o2 = MaintenanceOccurrence.objects.create(plan=self.p2, asset=self.a1, due_date=d, warning_days=10)
        self.o3 = MaintenanceOccurrence.objects.create(plan=self.p1, asset=self.a2, due_date=d, warning_days=10)
        self.o4 = MaintenanceOccurrence.objects.create(plan=self.p2, asset=self.a2, due_date=d + timedelta(days=5), warning_days=10)

    def _create(self, ids, **extra):
        data = {"occurrence_ids": ids, **extra}
        return self.client.post(reverse("assets:occurrence_create_workorder"), data)

    def test_un_odl_per_asset_e_giorno_numerati_come_gruppo(self):
        response = self._create([self.o1.id, self.o2.id, self.o3.id, self.o4.id], split_by_asset="on")
        for occ in (self.o1, self.o2, self.o3, self.o4):
            occ.refresh_from_db()
        # Stesso asset, stesso giorno -> stesso OdL.
        self.assertEqual(self.o1.work_order_id, self.o2.work_order_id)
        # Asset diverso, o stesso asset in un altro giorno -> OdL diversi.
        wo_ids = {self.o1.work_order_id, self.o3.work_order_id, self.o4.work_order_id}
        self.assertEqual(len(wo_ids), 3)
        from assets.models import WorkOrder

        wos = list(WorkOrder.objects.filter(pk__in=wo_ids).order_by("id"))
        leader = wos[0].id
        self.assertEqual([wo.display_number for wo in wos], [f"{leader}-1", f"{leader}-2", f"{leader}-3"])
        self.assertRedirects(response, reverse("assets:wo_view", args=[leader]), fetch_redirect_response=False)
        page = self.client.get(reverse("assets:wo_view", args=[wos[1].id]))
        self.assertContains(page, f"Gruppo {leader}")
        self.assertContains(page, f"#{leader}-3")

    def test_senza_la_casella_resta_un_unico_odl(self):
        self._create([self.o1.id, self.o3.id])
        self.o1.refresh_from_db()
        self.o3.refresh_from_db()
        self.assertEqual(self.o1.work_order_id, self.o3.work_order_id)

    def test_la_scheda_suggerisce_le_altre_scadenze_dello_stesso_asset(self):
        self._create([self.o3.id], split_by_asset="on")
        self.o3.refresh_from_db()
        page = self.client.get(reverse("assets:wo_view", args=[self.o3.work_order_id]))
        self.assertContains(page, "Suggerimenti")
        self.assertIn(self.o4, page.context["suggested_occurrences"])
        self.assertContains(page, "Nessun manutentore e nessuna ditta")

    def test_registrare_tutte_le_manutenzioni_chiude_l_odl_e_va_nello_storico(self):
        from assets.models import WorkOrder

        self._create([self.o1.id, self.o2.id], split_by_asset="on")
        wo = WorkOrder.objects.get(occurrences=self.o1)
        oggi = self.today.isoformat()
        self.client.post(reverse("assets:occurrence_complete", args=[self.o1.id]), {"completed_on": oggi})
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrder.STATUS_OPEN)  # ne manca una
        response = self.client.post(
            reverse("assets:occurrence_complete", args=[self.o2.id]), {"completed_on": oggi}, follow=True
        )
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrder.STATUS_DONE)
        self.assertEqual(wo.executed_by, self.admin)
        self.assertContains(response, "compare fra i chiusi")
        storico = self.client.get(reverse("assets:maintenance_history"))
        self.assertContains(storico, wo.title)

    def test_storico_mostra_le_manutenzioni_registrate_senza_odl(self):
        self.client.post(
            reverse("assets:occurrence_complete", args=[self.o3.id]), {"completed_on": self.today.isoformat()}
        )
        storico = self.client.get(reverse("assets:maintenance_history"), {"source": "maintenance"})
        self.assertContains(storico, "Registrata senza OdL")
        self.assertContains(storico, "B-02")

    def test_scheda_di_lavoro_stampabile(self):
        from assets.models import MaintenanceChecklistStep, WorkOrder

        MaintenanceChecklistStep.objects.create(intervention_template=self.p1, step_number=10, description="Ingrassare guide")
        self._create([self.o1.id, self.o3.id], split_by_asset="")
        wo = WorkOrder.objects.get(occurrences=self.o1)
        response = self.client.get(reverse("assets:workorder_worksheet", args=[wo.id]))
        self.assertContains(response, "Scheda di lavoro")
        self.assertContains(response, "Ingrassare guide")
        self.assertContains(response, "B-01")
        self.assertContains(response, "B-02")
        detail = self.client.get(reverse("assets:wo_view", kwargs={"id": wo.id}))
        self.assertContains(detail, reverse("assets:workorder_worksheet", args=[wo.id]))
        singola = self.client.get(reverse("assets:occurrence_worksheet", args=[self.o4.id]))
        self.assertContains(singola, "Manutenzione senza ordine di lavoro")
