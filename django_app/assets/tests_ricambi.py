"""Blocco C3: ricambi minimi (anagrafica, movimenti, scarico su intervento, sotto scorta).
Dati sintetici."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, AssetCategory, SparePart, SparePartMovement, WorkOrder
from assets.services.spare_parts import SparePartError, register_movement, workorder_parts_cost

User = get_user_model()


def _complete_onboarding(user) -> None:
    from core.models import UserOnboarding

    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()}
    )


class SparePartMovementTests(TestCase):
    def setUp(self):
        self.part = SparePart.objects.create(code="CUSC-6204", description="Cuscinetto 6204", stock_qty=Decimal("5"),
                                             min_qty=Decimal("2"), unit_cost_eur=Decimal("7.50"))

    def test_carico_scarico_rettifica_coerenti(self):
        register_movement(self.part, SparePartMovement.KIND_IN, "10")
        register_movement(self.part, SparePartMovement.KIND_OUT, "3")
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, Decimal("12.00"))
        movement = register_movement(self.part, SparePartMovement.KIND_ADJUST, "11", note="Inventario del 16/10")
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, Decimal("11.00"))
        self.assertEqual(movement.stock_after, Decimal("11.00"))

    def test_sotto_zero_rifiutato(self):
        with self.assertRaises(SparePartError):
            register_movement(self.part, SparePartMovement.KIND_OUT, "6")
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, Decimal("5.00"))
        self.assertFalse(SparePartMovement.objects.exists())

    def test_rettifica_senza_nota_rifiutata(self):
        with self.assertRaises(SparePartError):
            register_movement(self.part, SparePartMovement.KIND_ADJUST, "4")

    def test_scarichi_annidati_sulla_stessa_parte(self):
        """Due scarichi nella stessa transazione esterna (simulazione di concorrenza):
        il secondo vede la giacenza aggiornata dal primo e non va sotto zero."""
        with transaction.atomic():
            register_movement(self.part, SparePartMovement.KIND_OUT, "3")
            stale = SparePart.objects.get(pk=self.part.pk)
            stale.stock_qty = Decimal("5")  # copia vecchia in memoria
            with self.assertRaises(SparePartError):
                register_movement(stale, SparePartMovement.KIND_OUT, "3")
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, Decimal("2.00"))

    def test_lock_sulla_riga(self):
        with mock.patch("assets.services.spare_parts.SparePart.objects.select_for_update",
                        wraps=SparePart.objects.select_for_update) as lock:
            register_movement(self.part, SparePartMovement.KIND_IN, "1")
        self.assertTrue(lock.called)

    def test_sotto_scorta(self):
        from assets.services.spare_parts import below_min_queryset

        self.assertFalse(below_min_queryset().filter(pk=self.part.pk).exists())
        register_movement(self.part, SparePartMovement.KIND_OUT, "3")
        self.assertTrue(below_min_queryset().filter(pk=self.part.pk).exists())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SparePartViewsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="c3-admin", password="x", email="c3@example.com")
        self.category = AssetCategory.objects.create(code="c3-cnc", label="CNC C3")
        self.asset = Asset.objects.create(asset_tag="C3-CNC-1", name="CNC C3", asset_category=self.category)
        self.part = SparePart.objects.create(code="FILTRO-OLIO", description="Filtro olio", stock_qty=Decimal("4"),
                                             min_qty=Decimal("1"), unit_cost_eur=Decimal("12.00"))
        self.part.compatible_categories.add(self.category)
        self.other = SparePart.objects.create(code="CINGHIA", description="Cinghia", stock_qty=Decimal("1"), min_qty=Decimal("3"))
        self.wo = WorkOrder.objects.create(asset=self.asset, title="Cambio filtro", kind=WorkOrder.KIND_CORRECTIVE)

    def test_elenco_e_filtro_sotto_scorta(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assets:spare_part_list"))
        self.assertContains(response, "FILTRO-OLIO")
        self.assertContains(response, "1 sotto scorta")
        response = self.client.get(reverse("assets:spare_part_list"), {"sotto_scorta": "1"})
        self.assertContains(response, "CINGHIA")
        self.assertNotContains(response, "FILTRO-OLIO")

    def test_export_xlsx(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assets:spare_part_list"), {"export": "xlsx"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])

    def test_scarico_su_intervento_e_costo_materiali(self):
        self.client.force_login(self.admin)
        url = reverse("assets:workorder_spare_parts", args=[self.wo.pk])
        panel = self.client.get(url)
        self.assertContains(panel, "compatibile")
        response = self.client.post(url, {"part_id": self.part.pk, "qty": "2"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "24,00 €")
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, Decimal("2.00"))
        self.assertEqual(workorder_parts_cost(self.wo), Decimal("24.00"))
        # Chiusura senza costo materiali a mano: lo prendono i ricambi.
        self.client.post(reverse("assets:wo_close", args=[self.wo.pk]), {
            "status": WorkOrder.STATUS_DONE, "esito": WorkOrder.OUTCOME_RESOLVED,
            "closed_at": timezone.localtime(timezone.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
            "resolution": "Filtro sostituito", "execution_days": "",
        })
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_DONE)
        self.assertEqual(self.wo.materials_cost_eur, Decimal("24.00"))

    def test_costo_materiali_a_mano_prevale(self):
        self.client.force_login(self.admin)
        register_movement(self.part, SparePartMovement.KIND_OUT, "1", work_order=self.wo, user=self.admin)
        self.client.post(reverse("assets:wo_close", args=[self.wo.pk]), {
            "status": WorkOrder.STATUS_DONE, "esito": WorkOrder.OUTCOME_RESOLVED,
            "closed_at": timezone.localtime(timezone.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
            "resolution": "Fatto", "execution_days": "", "materials_cost_eur": "30",
        })
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.materials_cost_eur, Decimal("30.00"))
        panel = self.client.get(reverse("assets:workorder_spare_parts", args=[self.wo.pk]))
        self.assertContains(panel, "differenza 18,00 €")

    def test_scarico_oltre_giacenza_mostra_errore(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("assets:workorder_spare_parts", args=[self.wo.pk]),
                                    {"part_id": self.part.pk, "qty": "9"})
        self.assertContains(response, "Giacenza insufficiente")
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, Decimal("4.00"))

    def test_senza_permesso_esecuzione_403(self):
        user = User.objects.create_user(username="c3-op", password="x", email="c3op@example.com")
        _complete_onboarding(user)
        self.client.force_login(user)
        response = self.client.post(reverse("assets:workorder_spare_parts", args=[self.wo.pk]),
                                    {"part_id": self.part.pk, "qty": "1"})
        self.assertEqual(response.status_code, 403)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, Decimal("4.00"))

    def test_anagrafica_e_rettifiche_solo_admin(self):
        user = User.objects.create_user(username="c3-op2", password="x", email="c3op2@example.com")
        _complete_onboarding(user)
        self.client.force_login(user)
        response = self.client.post(reverse("assets:spare_part_create"), {"code": "X", "description": "Furtivo", "unit": "pz", "min_qty": "0"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SparePart.objects.filter(code="X").exists())
        self.client.post(reverse("assets:spare_part_detail", args=[self.part.pk]), {"kind": "ADJUST", "qty": "99", "note": "x"})
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, Decimal("4.00"))

    def test_admin_crea_e_carica(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("assets:spare_part_create"), {
            "code": "OLIO-ISO46", "description": "Olio idraulico ISO 46", "unit": "l", "min_qty": "20", "is_active": "on",
        })
        part = SparePart.objects.get(code="OLIO-ISO46")
        self.assertRedirects(response, reverse("assets:spare_part_detail", args=[part.pk]), fetch_redirect_response=False)
        self.client.post(reverse("assets:spare_part_detail", args=[part.pk]), {"kind": "IN", "qty": "40", "unit_cost_eur": "3,20"})
        part.refresh_from_db()
        self.assertEqual(part.stock_qty, Decimal("40.00"))
        self.assertEqual(part.movements.get().unit_cost_eur, Decimal("3.20"))

    def test_panoramica_e_promemoria_sotto_scorta(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assets:maintenance_responsabile"))
        self.assertEqual(response.context["kpi"]["spare_below_min"], 1)
        self.assertContains(response, "Ricambi sotto scorta")
        out = StringIO()
        call_command("send_maintenance_reminders", "--dry-run", "--recipients", "test@example.com", stdout=out)
        self.assertIn("RICAMBI SOTTO SCORTA (1)", out.getvalue())
        self.assertIn("CINGHIA", out.getvalue())
