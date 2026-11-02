"""«Chiudi intervento»: «Stesso intervento su altri asset» (Registra insieme sugli OdL).

Checklist: docs/ai/CHECKLIST_REGISTRA_INSIEME.md (voce 5). Dati sintetici.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, WorkOrder, WorkOrderChecklist, WorkOrderLog

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class ChiudiOdlInsiemeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="odl-ins-admin", password="x", email="o@i.n")

    def setUp(self):
        self.client.force_login(self.admin)
        now = timezone.now()
        self.a1 = Asset.objects.create(asset_tag="INS-1", name="Pressa 1")
        self.a2 = Asset.objects.create(asset_tag="INS-2", name="Pressa 2")
        self.a3 = Asset.objects.create(asset_tag="INS-3", name="Pressa 3")
        self.a4 = Asset.objects.create(asset_tag="INS-4", name="Pressa 4")
        self.main = WorkOrder.objects.create(
            asset=self.a1, title="Pulizia filtri", kind=WorkOrder.KIND_PREVENTIVE, due_at=now,
        )
        self.twin = WorkOrder.objects.create(
            asset=self.a2, title="pulizia filtri", kind=WorkOrder.KIND_PREVENTIVE, due_at=now + timedelta(days=10),
        )
        self.blocked = WorkOrder.objects.create(
            asset=self.a3, title="Pulizia filtri", kind=WorkOrder.KIND_PREVENTIVE, due_at=now,
        )
        WorkOrderChecklist.objects.create(work_order=self.blocked, step_number=1, description="Foto", is_mandatory=True)
        self.far = WorkOrder.objects.create(
            asset=self.a4, title="Pulizia filtri", kind=WorkOrder.KIND_PREVENTIVE, due_at=now + timedelta(days=500),
        )
        self.other_kind = WorkOrder.objects.create(
            asset=self.a4, title="Pulizia filtri", kind=WorkOrder.KIND_CORRECTIVE, due_at=now,
        )
        self.url = reverse("assets:wo_close", args=[self.main.pk])

    def _post(self, **extra):
        data = {
            "status": WorkOrder.STATUS_DONE,
            "esito": WorkOrder.OUTCOME_RESOLVED,
            "closed_at": timezone.localtime(timezone.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
            "resolution": "Filtri puliti",
            "execution_days": "",
            "downtime_minutes": "30",
            "intervention_duration_minutes": "45",
        }
        data.update(extra)
        return self.client.post(self.url, data)

    def test_pagina_propone_gemelli_e_blocca_chi_ha_checklist(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Stesso intervento su altri asset")
        self.assertContains(page, f'name="also_close" value="{self.twin.pk}">')
        self.assertContains(page, f'name="also_close" value="{self.blocked.pk}" disabled>')
        self.assertContains(page, "checklist da completare")
        self.assertContains(page, '<li data-insieme-days="10">')
        self.assertNotContains(page, f'value="{self.far.pk}"')  # oltre un anno
        self.assertNotContains(page, f'value="{self.other_kind.pk}"')  # altro tipo
        self.assertNotContains(page, "{#")

    def test_chiude_insieme_solo_i_consentiti(self):
        response = self._post(also_close=[self.twin.pk, self.blocked.pk, self.far.pk, self.other_kind.pk])
        self.assertEqual(response.status_code, 302)
        for wo in (self.main, self.twin, self.blocked, self.far, self.other_kind):
            wo.refresh_from_db()
        self.assertEqual(self.main.status, WorkOrder.STATUS_DONE)
        self.assertEqual(self.main.downtime_minutes, 30)
        self.assertEqual(self.twin.status, WorkOrder.STATUS_DONE)
        self.assertEqual(self.twin.outcome, WorkOrder.OUTCOME_RESOLVED)
        self.assertEqual(self.twin.resolution, "Filtri puliti")
        self.assertFalse(self.twin.downtime_minutes)  # fermo solo sul principale
        self.assertFalse(self.twin.intervention_duration_minutes)
        self.assertTrue(
            WorkOrderLog.objects.filter(work_order=self.twin, note__contains=f"insieme all'intervento #{self.main.pk}").exists()
        )
        for untouched in (self.blocked, self.far, self.other_kind):
            self.assertEqual(untouched.status, WorkOrder.STATUS_OPEN)

    def test_stesso_lotto_anche_con_titolo_diverso(self):
        a5 = Asset.objects.create(asset_tag="INS-5", name="Pressa 5")
        renamed = WorkOrder.objects.create(asset=a5, title="Altro nome", kind=WorkOrder.KIND_CORRECTIVE)
        WorkOrder.mark_batch([self.main, renamed])
        page = self.client.get(self.url)
        self.assertContains(page, f'name="also_close" value="{renamed.pk}">')

    def test_senza_spunte_chiude_solo_il_principale(self):
        self._post()
        self.twin.refresh_from_db()
        self.assertEqual(self.twin.status, WorkOrder.STATUS_OPEN)
