"""Regole sui dati della manutenzione: indici (migrazione 0171) e normalizzazioni in save(). Dati sintetici."""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from assets.models import (
    Asset,
    AssetAdministrativeDeadline,
    MaintenanceInterventionTemplate,
    WorkOrder,
)


class VincoliDbTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="VDB01", name="Pressa")
        self.plan = MaintenanceInterventionTemplate.objects.create(code="vdb-p", label="Polizza")

    def test_riattivare_scadenza_spostata_toglie_il_piano(self):
        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset, title="Polizza", due_date=date(2026, 1, 1), is_active=False, moved_to_plan=self.plan,
        )
        deadline.is_active = True
        deadline.save(update_fields=["is_active", "updated_at"])
        deadline.refresh_from_db()
        self.assertTrue(deadline.is_active)
        self.assertIsNone(deadline.moved_to_plan_id)

    def test_scadenza_spostata_resta_spenta_e_collegata(self):
        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset, title="Polizza", due_date=date(2026, 1, 1), is_active=False, moved_to_plan=self.plan,
        )
        deadline.save()
        deadline.refresh_from_db()
        self.assertEqual(deadline.moved_to_plan_id, self.plan.pk)

    def test_indici_dichiarati(self):
        nomi_asset = {index.name for index in Asset._meta.indexes}
        self.assertTrue({"idx_asset_status", "idx_asset_reparto", "idx_asset_type"} <= nomi_asset)
        self.assertIn("idx_wo_status_opened", {index.name for index in WorkOrder._meta.indexes})
