"""Motore piani: la serie segue l'applicazione valida oggi, non si blocca su date occupate. Dati sintetici."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    AssetGroup,
    AssetGroupMembership,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    WorkOrder,
)
from assets.services import maintenance_domain as domain
from assets.services.workorder_close import CloseData, RequestIdentity, close_workorder

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class MotoreScadenzeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="motore", password="x", email="m@example.com")
        self.cat = AssetCategory.objects.create(code="mot-cat", label="Presse")
        self.asset = Asset.objects.create(asset_tag="MOT01", name="Pressa", asset_category=self.cat,
                                          status=Asset.STATUS_IN_USE)
        self.group = AssetGroup.objects.create(code="mot-g", label="PRESSE")
        self.membership = AssetGroupMembership.objects.create(group=self.group, asset=self.asset)
        self.plan = MaintenanceInterventionTemplate.objects.create(code="mot-olio", label="Olio")
        self.assignment = MaintenancePlanAssignment.objects.create(
            plan=self.plan, target_type="GROUP", asset_group=self.group, frequency="DAYS", interval=30,
        )
        self.today = timezone.localdate()

    def _open(self, due=None, assignment=None):
        return MaintenanceOccurrence.objects.create(
            plan=self.plan, assignment=assignment or self.assignment, asset=self.asset,
            due_date=due or self.today,
        )

    def test_chiusura_crea_la_successiva(self):
        nxt = domain.complete_occurrence(self._open(), completed_on=self.today, user=self.user)
        self.assertEqual(nxt.due_date, self.today + timedelta(days=30))

    def test_asset_uscito_dal_gruppo_non_genera_la_successiva(self):
        occ = self._open()
        self.membership.delete()
        self.assertIsNone(domain.complete_occurrence(occ, completed_on=self.today, user=self.user))

    def test_piano_spento_non_genera_la_successiva(self):
        occ = self._open()
        MaintenanceInterventionTemplate.objects.filter(pk=self.plan.pk).update(is_active=False)
        occ.refresh_from_db()
        self.assertIsNone(domain.complete_occurrence(occ, completed_on=self.today, user=self.user))

    def test_asset_dismesso_non_genera_la_successiva(self):
        occ = self._open()
        Asset.objects.filter(pk=self.asset.pk).update(status=Asset.STATUS_RETIRED)
        occ.refresh_from_db()
        self.assertIsNone(domain.complete_occurrence(occ, completed_on=self.today, user=self.user))

    def test_personalizzazione_asset_decide_la_periodicita(self):
        occ = self._open()
        personal = MaintenancePlanAssignment.objects.create(
            plan=self.plan, target_type="ASSET", asset=self.asset, frequency="DAYS", interval=10,
        )
        nxt = domain.complete_occurrence(occ, completed_on=self.today, user=self.user)
        self.assertEqual(nxt.assignment_id, personal.pk)
        self.assertEqual(nxt.due_date, self.today + timedelta(days=10))

    def test_data_occupata_da_annullata_avanza_di_un_periodo(self):
        MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=self.today + timedelta(days=30),
            status=MaintenanceOccurrence.STATUS_CANCELED,
        )
        nxt = domain.complete_occurrence(self._open(), completed_on=self.today, user=self.user)
        self.assertEqual(nxt.status, MaintenanceOccurrence.STATUS_OPEN)
        self.assertEqual(nxt.due_date, self.today + timedelta(days=60))

    def test_generazione_non_si_blocca_su_annullata(self):
        first = self.today + timedelta(days=5)
        MaintenancePlanAssignment.objects.filter(pk=self.assignment.pk).update(first_due_date=first)
        MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=first, status=MaintenanceOccurrence.STATUS_CANCELED,
        )
        result = domain.generate_occurrences(today=self.today, horizon_days=60)
        self.assertEqual(result["created"], 1)
        aperta = MaintenanceOccurrence.objects.get(plan=self.plan, status=MaintenanceOccurrence.STATUS_OPEN)
        self.assertEqual(aperta.due_date, first + timedelta(days=30))

    def test_doppia_registrazione_rifiutata(self):
        occ = self._open()
        stale = MaintenanceOccurrence.objects.get(pk=occ.pk)
        domain.complete_occurrence(occ, completed_on=self.today, user=self.user, notes="prima")
        with self.assertRaises(domain.OccurrenceCompletionError):
            domain.complete_occurrence(stale, completed_on=self.today, user=self.user, notes="seconda")
        occ.refresh_from_db()
        self.assertEqual(occ.completion_notes, "prima")

    def test_odl_chiuso_sgancia_le_manutenzioni_non_registrate(self):
        wo = WorkOrder.objects.create(asset=self.asset, title="Giro presse")
        occ = self._open()
        MaintenanceOccurrence.objects.filter(pk=occ.pk).update(work_order=wo)
        result = close_workorder(
            wo.pk,
            data=CloseData(status=WorkOrder.STATUS_CANCELED, pending_occurrences_count=1),
            user=self.user,
            request_identity=RequestIdentity(),
        )
        occ.refresh_from_db()
        self.assertIsNone(occ.work_order_id)
        self.assertEqual(occ.status, MaintenanceOccurrence.STATUS_OPEN)
        self.assertTrue(any("da pianificare" in w for w in result.warnings))

    def test_aperte_di_asset_dismessi_fuori_dagli_elenchi(self):
        from assets.views_maintenance import _base_occurrence_queryset

        occ = self._open()
        Asset.objects.filter(pk=self.asset.pk).update(status=Asset.STATUS_RETIRED)
        self.assertFalse(_base_occurrence_queryset().filter(pk=occ.pk).exists())
        done = MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=self.today - timedelta(days=40),
            status=MaintenanceOccurrence.STATUS_DONE, completed_on=self.today - timedelta(days=40),
        )
        # Lo storico resta.
        self.assertTrue(_base_occurrence_queryset().filter(pk=done.pk).exists())

    def test_due_gruppi_a_contatore_con_intervalli_diversi_sono_in_conflitto(self):
        other = AssetGroup.objects.create(code="mot-g2", label="PRESSE 2")
        AssetGroupMembership.objects.create(group=other, asset=self.asset)
        MaintenancePlanAssignment.objects.filter(pk=self.assignment.pk).update(
            trigger_type="METER", meter_type="HOURS", meter_interval=Decimal("500"),
        )
        MaintenancePlanAssignment.objects.create(
            plan=self.plan, target_type="GROUP", asset_group=other, frequency="DAYS", interval=30,
            trigger_type="METER", meter_type="HOURS", meter_interval=Decimal("1000"),
        )
        resolution = domain.resolve_plan_for_asset(plan_id=self.plan.pk, asset=self.asset)
        self.assertTrue(resolution.is_conflict)


class MigrazioneSganciaTests(TestCase):
    def test_funzione_sgancia_libera_le_aperte_di_odl_chiusi(self):
        import importlib

        from django.apps import apps

        modulo = importlib.import_module("assets.migrations.0170_sgancia_scadenze_da_odl_chiusi")
        asset = Asset.objects.create(asset_tag="MOT-M", name="M")
        plan = MaintenanceInterventionTemplate.objects.create(code="mot-m", label="M")
        wo = WorkOrder.objects.create(asset=asset, title="Chiuso")
        WorkOrder.objects.filter(pk=wo.pk).update(status=WorkOrder.STATUS_DONE)
        occ = MaintenanceOccurrence.objects.create(plan=plan, asset=asset, due_date=date(2026, 1, 1), work_order=wo)
        modulo.sgancia(apps, None)
        occ.refresh_from_db()
        self.assertIsNone(occ.work_order_id)
