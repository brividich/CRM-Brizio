"""Panoramica manutenzione (giorni cliccabili, multiselezione, sezioni chiudibili,
azioni sugli OdL selezionati) e ricerca in tutto il modulo."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetAdministrativeDeadline,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    WorkOrder,
    WorkOrderLog,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class PanoramicaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.admin = User.objects.create_superuser(username="pn-admin", password="x", email="p@n.a")
        cls.tecnico = User.objects.create_user(username="pn-tecnico", password="x", first_name="Mario", last_name="Rossi")
        cls.asset = Asset.objects.create(asset_tag="PN-01", name="Pressa sintetica", status=Asset.STATUS_IN_USE)
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="pn-lub", label="Lubrificazione guide")

    def setUp(self):
        self.client.force_login(self.admin)
        self.occ = MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=self.today + timedelta(days=2), warning_days=10
        )

    def test_giorni_cliccabili_con_elenco_del_giorno_e_link_al_calendario(self):
        response = self.client.get(reverse("assets:maintenance_responsabile"))
        day = (self.today + timedelta(days=2)).isoformat()
        self.assertContains(response, f'data-pn-day="{day}"')
        self.assertContains(response, f'data-pn-dayview="{day}"')
        self.assertContains(response, f"data={day}")
        # La manutenzione del giorno si seleziona anche da li' (e da Prossime scadenze).
        self.assertContains(response, f'value="{self.occ.id}" form="md-bulk-form"', count=3)

    def test_sezioni_chiudibili_e_odl_selezionabili(self):
        wo = WorkOrder.objects.create(asset=self.asset, title="Intervento sintetico")
        response = self.client.get(reverse("assets:maintenance_responsabile"))
        for section in ("non-pianificate", "odl-attivi", "carico-manutentori", "odl-anziani",
                        "rapporti-mancanti", "follow-up"):
            self.assertContains(response, f'id="{section}" open data-md-collapsible')
        self.assertContains(response, f'value="{wo.pk}" form="wo-bulk-form"')
        self.assertContains(response, 'id="wo-bulk-form"')
        self.assertContains(response, "__mdMultiSelect")
        self.assertNotContains(response, "{#")

    def test_assegnazione_massiva_degli_odl(self):
        wo1 = WorkOrder.objects.create(asset=self.asset, title="Uno")
        wo2 = WorkOrder.objects.create(asset=self.asset, title="Due")
        response = self.client.post(
            reverse("assets:workorder_bulk_action"),
            {"workorder_ids": [wo1.pk, wo2.pk], "action": "assign", "wob-assigned_to": self.tecnico.pk,
             "next": reverse("assets:maintenance_responsabile")},
        )
        self.assertRedirects(response, reverse("assets:maintenance_responsabile"), fetch_redirect_response=False)
        wo1.refresh_from_db()
        wo2.refresh_from_db()
        self.assertEqual(wo1.assigned_to, self.tecnico)
        self.assertEqual(wo2.assigned_to, self.tecnico)
        self.assertEqual(WorkOrderLog.objects.filter(work_order__in=[wo1, wo2]).count(), 2)

    def test_chiudi_i_completati_lascia_aperti_gli_altri(self):
        completo = WorkOrder.objects.create(asset=self.asset, title="Completo")
        MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=self.today - timedelta(days=30), warning_days=10,
            status=MaintenanceOccurrence.STATUS_DONE, completed_on=self.today - timedelta(days=1), work_order=completo,
        )
        aperto = WorkOrder.objects.create(asset=self.asset, title="Da finire")
        self.occ.work_order = aperto
        self.occ.save(update_fields=["work_order"])
        self.client.post(
            reverse("assets:workorder_bulk_action"),
            {"workorder_ids": [completo.pk, aperto.pk], "action": "close_complete"},
        )
        completo.refresh_from_db()
        aperto.refresh_from_db()
        self.assertEqual(completo.status, WorkOrder.STATUS_DONE)
        self.assertEqual(aperto.status, WorkOrder.STATUS_OPEN)

    def test_next_esterno_non_viene_seguito(self):
        wo = WorkOrder.objects.create(asset=self.asset, title="Uno")
        response = self.client.post(
            reverse("assets:workorder_bulk_action"),
            {"workorder_ids": [wo.pk], "action": "assign", "wob-assigned_to": self.tecnico.pk,
             "next": "https://evil.example/"},
        )
        self.assertEqual(response["Location"], reverse("assets:maintenance_responsabile"))

    def test_senza_permesso_di_pianificare_nessuna_azione(self):
        wo = WorkOrder.objects.create(asset=self.asset, title="Uno")
        self.client.force_login(self.tecnico)
        self.client.post(
            reverse("assets:workorder_bulk_action"),
            {"workorder_ids": [wo.pk], "action": "assign", "wob-assigned_to": self.tecnico.pk},
        )
        wo.refresh_from_db()
        self.assertIsNone(wo.assigned_to)


@override_settings(LEGACY_AUTH_ENABLED=False)
class RicercaModuloTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.admin = User.objects.create_superuser(username="cerca-admin", password="x", email="c@e.r")
        cls.asset = Asset.objects.create(asset_tag="ZETA-9", name="Compressore zeta", status=Asset.STATUS_IN_USE)
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="zeta-filtri", label="Cambio filtri zeta")
        cls.admin_plan = MaintenanceInterventionTemplate.objects.create(
            code="zeta-ver", label="Verifica biennale zeta",
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
        )
        MaintenanceOccurrence.objects.create(plan=cls.plan, asset=cls.asset, due_date=cls.today, warning_days=10)
        MaintenanceOccurrence.objects.create(plan=cls.admin_plan, asset=cls.asset, due_date=cls.today, warning_days=10)
        MaintenanceOccurrence.objects.create(
            plan=cls.plan, asset=cls.asset, due_date=cls.today - timedelta(days=90), warning_days=10,
            status=MaintenanceOccurrence.STATUS_DONE, completed_on=cls.today - timedelta(days=90),
        )
        AssetAdministrativeDeadline.objects.create(asset=cls.asset, title="Certificato zeta", due_date=cls.today)
        cls.wo = WorkOrder.objects.create(asset=cls.asset, title="Perdita olio zeta")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_la_ricerca_copre_tutte_le_categorie(self):
        response = self.client.get(reverse("assets:module_search"), {"q": "zeta"})
        self.assertEqual(response.status_code, 200)
        keys = {group.key for group in response.context["groups"]}
        self.assertTrue({"asset", "plans", "deadlines", "admin", "workorders", "history"} <= keys, keys)
        self.assertContains(response, "Certificato zeta")
        self.assertContains(response, "Verifica biennale zeta")
        self.assertContains(response, "Perdita olio zeta")

    def test_numero_odl(self):
        data = self.client.get(reverse("assets:module_search"), {"q": f"#{self.wo.pk}", "format": "json"}).json()
        odl = [g for g in data["groups"] if g["key"] == "workorders"]
        self.assertTrue(odl and any(h["url"].endswith(f"/{self.wo.pk}/") for h in odl[0]["hits"]))

    def test_json_per_i_suggerimenti_e_termine_corto(self):
        data = self.client.get(reverse("assets:module_search"), {"q": "zeta", "format": "json"}).json()
        self.assertTrue(data["groups"])
        self.assertIn("page_url", data)
        corto = self.client.get(reverse("assets:module_search"), {"q": "z", "format": "json"}).json()
        self.assertEqual(corto["groups"], [])

    def test_il_campo_in_testa_punta_alla_ricerca_del_modulo(self):
        response = self.client.get(reverse("assets:maintenance_responsabile"))
        self.assertContains(response, f'action="{reverse("assets:module_search")}"')
