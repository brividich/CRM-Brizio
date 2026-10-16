"""Blocco C2: codici guasto (problema / causa / rimedio) e Pareto. Dati sintetici."""

from __future__ import annotations

import importlib
from datetime import timedelta

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, AssetCategory, FailureCode, WorkOrder
from assets.services.failure_codes import codes_for_category

User = get_user_model()


class _Fixture:
    def _tree(self):
        self.root = AssetCategory.objects.create(code="c2-macchine", label="Macchine C2")
        self.child = AssetCategory.objects.create(code="c2-cnc", label="CNC C2", parent=self.root)
        self.other = AssetCategory.objects.create(code="c2-it", label="IT C2")
        self.global_code = FailureCode.objects.create(kind=FailureCode.KIND_PROBLEM, code="perdita-olio", label="Perdita olio")
        self.root_code = FailureCode.objects.create(kind=FailureCode.KIND_PROBLEM, code="vibrazioni", label="Vibrazioni", asset_category=self.root)
        self.child_code = FailureCode.objects.create(kind=FailureCode.KIND_PROBLEM, code="mandrino", label="Mandrino rumoroso", asset_category=self.child)
        self.other_code = FailureCode.objects.create(kind=FailureCode.KIND_PROBLEM, code="schermo", label="Schermo nero", asset_category=self.other)


class FailureCodeFilterTests(_Fixture, TestCase):
    def setUp(self):
        self._tree()

    def test_categoria_figlia_vede_globali_propri_e_antenati(self):
        labels = set(codes_for_category(FailureCode.KIND_PROBLEM, self.child).values_list("label", flat=True))
        self.assertEqual(labels, {"Perdita olio", "Vibrazioni", "Mandrino rumoroso"})

    def test_categoria_radice_non_vede_i_figli(self):
        labels = set(codes_for_category(FailureCode.KIND_PROBLEM, self.root).values_list("label", flat=True))
        self.assertEqual(labels, {"Perdita olio", "Vibrazioni"})

    def test_senza_categoria_solo_globali_e_niente_disattivati(self):
        FailureCode.objects.create(kind=FailureCode.KIND_PROBLEM, code="vecchio", label="Vecchio", is_active=False)
        labels = set(codes_for_category(FailureCode.KIND_PROBLEM, None).values_list("label", flat=True))
        self.assertEqual(labels, {"Perdita olio"})

    def test_codice_usato_e_protetto(self):
        asset = Asset.objects.create(asset_tag="C2-1", name="CNC 1", asset_category=self.child)
        WorkOrder.objects.create(asset=asset, title="Guasto", kind=WorkOrder.KIND_CORRECTIVE, failure_problem=self.child_code)
        with self.assertRaises(ProtectedError):
            self.child_code.delete()


class FailureCodeMigrationTests(TestCase):
    def test_cause_storiche_idempotenti(self):
        asset = Asset.objects.create(asset_tag="C2-MIG", name="Pressa")
        wo = WorkOrder.objects.create(asset=asset, title="Storico", kind=WorkOrder.KIND_CORRECTIVE, failure_cause="MECHANICAL")
        migration = importlib.import_module("assets.migrations.0140_codici_guasto_cause_storiche")
        migration.forwards(django_apps, None)
        migration.forwards(django_apps, None)
        self.assertEqual(FailureCode.objects.filter(kind=FailureCode.KIND_CAUSE, asset_category__isnull=True).count(), 6)
        wo.refresh_from_db()
        self.assertEqual(wo.failure_cause_code.code, "mechanical")
        migration.backwards(django_apps, None)
        wo.refresh_from_db()
        self.assertIsNone(wo.failure_cause_code_id)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FailureCodeCloseAndAdminTests(_Fixture, TestCase):
    def setUp(self):
        self._tree()
        self.admin = User.objects.create_superuser(username="c2-admin", password="x", email="c2@example.com")
        self.client.force_login(self.admin)
        self.asset = Asset.objects.create(asset_tag="C2-CNC", name="CNC C2", asset_category=self.child)
        # La causa "mechanical" e' gia' seminata dalla migrazione 0139.
        self.cause, _ = FailureCode.objects.get_or_create(
            kind=FailureCode.KIND_CAUSE, code="mechanical", asset_category=None, defaults={"label": "Meccanica"}
        )
        self.remedy = FailureCode.objects.create(kind=FailureCode.KIND_REMEDY, code="sostituzione", label="Sostituzione pezzo")

    def test_form_di_chiusura_filtra_e_salva_i_codici(self):
        wo = WorkOrder.objects.create(asset=self.asset, title="Guasto C2", kind=WorkOrder.KIND_CORRECTIVE)
        url = reverse("assets:wo_close", args=[wo.pk])
        page = self.client.get(url)
        self.assertContains(page, "Mandrino rumoroso")
        self.assertNotContains(page, "Schermo nero")
        response = self.client.post(url, {
            "status": WorkOrder.STATUS_DONE,
            "esito": WorkOrder.OUTCOME_RESOLVED,
            "closed_at": timezone.localtime(timezone.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
            "resolution": "Sostituito cuscinetto",
            "execution_days": "",
            "failure_problem": self.child_code.pk,
            "failure_cause_code": self.cause.pk,
            "failure_remedy": self.remedy.pk,
        })
        self.assertEqual(response.status_code, 302)
        wo.refresh_from_db()
        self.assertEqual((wo.failure_problem_id, wo.failure_cause_code_id, wo.failure_remedy_id),
                         (self.child_code.pk, self.cause.pk, self.remedy.pk))
        # La causa coincide con un valore storico: il campo legacy resta allineato.
        self.assertEqual(wo.failure_cause, "MECHANICAL")

    def test_codice_di_altra_categoria_rifiutato(self):
        wo = WorkOrder.objects.create(asset=self.asset, title="Guasto C2b", kind=WorkOrder.KIND_CORRECTIVE)
        response = self.client.post(reverse("assets:wo_close", args=[wo.pk]), {
            "status": WorkOrder.STATUS_DONE, "esito": WorkOrder.OUTCOME_RESOLVED,
            "closed_at": timezone.localtime(timezone.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
            "resolution": "x", "execution_days": "", "failure_problem": self.other_code.pk,
        })
        self.assertEqual(response.status_code, 200)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrder.STATUS_OPEN)

    def test_tab_codici_guasto_crea_e_disattiva(self):
        target = reverse("assets:gestione_admin") + "?tab=guasti"
        page = self.client.get(target)
        self.assertContains(page, 'id="codici-guasto"', html=False)
        response = self.client.post(reverse("assets:gestione_admin"), {
            "action": "failure_code_create", "kind": "REMEDY", "label": "Regolazione", "asset_category": "",
        })
        self.assertRedirects(response, target, fetch_redirect_response=False)
        code = FailureCode.objects.get(label="Regolazione")
        self.assertEqual(code.code, "regolazione")
        self.client.post(reverse("assets:gestione_admin"), {
            "action": "failure_code_update", "code_id": code.pk, "label": "Regolazione", "sort_order": "5",
        })
        code.refresh_from_db()
        self.assertFalse(code.is_active)

    def test_eliminare_un_codice_usato_e_negato(self):
        WorkOrder.objects.create(asset=self.asset, title="Usa", kind=WorkOrder.KIND_CORRECTIVE, failure_remedy=self.remedy)
        self.client.post(reverse("assets:gestione_admin"), {"action": "failure_code_delete", "code_id": self.remedy.pk})
        self.assertTrue(FailureCode.objects.filter(pk=self.remedy.pk).exists())

    def test_operatore_non_admin_non_crea(self):
        user = User.objects.create_user(username="c2-op", password="x", email="op2@example.com")
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "completed_at": timezone.now()})
        self.client.force_login(user)
        self.client.post(reverse("assets:gestione_admin"), {"action": "failure_code_create", "kind": "PROBLEM", "label": "Furtivo"})
        self.assertFalse(FailureCode.objects.filter(label="Furtivo").exists())

    def test_pareto_con_dati_sintetici(self):
        now = timezone.now()
        for index in range(3):
            WorkOrder.objects.create(
                asset=self.asset, title=f"Olio {index}", kind=WorkOrder.KIND_CORRECTIVE, status=WorkOrder.STATUS_DONE,
                closed_at=now - timedelta(days=5), failure_problem=self.global_code, downtime_minutes=60 if index == 0 else 0,
            )
        WorkOrder.objects.create(
            asset=self.asset, title="Vibra", kind=WorkOrder.KIND_CORRECTIVE, status=WorkOrder.STATUS_DONE,
            closed_at=now - timedelta(days=5), failure_problem=self.root_code, downtime_minutes=30,
        )
        WorkOrder.objects.create(
            asset=self.asset, title="Vecchio", kind=WorkOrder.KIND_CORRECTIVE, status=WorkOrder.STATUS_DONE,
            closed_at=now - timedelta(days=200), failure_problem=self.root_code,
        )
        response = self.client.get(reverse("assets:maintenance_responsabile"))
        pareto = response.context["pareto"]
        self.assertEqual([(r["failure_problem__label"], r["total"]) for r in pareto["rows"]],
                         [("Perdita olio", 3), ("Vibrazioni", 1)])
        self.assertEqual((pareto["with_downtime"], pareto["total"]), (2, 4))
        self.assertContains(response, "Fermo indicato in 2 interventi su 4")
        filtered = self.client.get(reverse("assets:maintenance_responsabile"), {"pareto_cat": self.other.pk})
        self.assertEqual(filtered.context["pareto"]["rows"], [])
