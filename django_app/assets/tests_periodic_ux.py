"""Verifiche periodiche: categorie, «Cosa fare adesso», schede della verifica anche
sulla singola verifica, testata sotto la barra del modulo."""

from __future__ import annotations

import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    PeriodicCheckCategory,
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class VerificheUxTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        override = override_settings(ASSETS_PRIVATE_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._tmp.cleanup)
        self.client.force_login(User.objects.create_superuser(username="pux-admin", password="x", email="pux@y.z"))
        self.system = PeriodicCheckSystem.objects.create(name="Impianto elettrico")
        self.fire = PeriodicCheckCategory.objects.create(name="Antincendio", color="red")
        today = timezone.localdate()
        self.overdue = PeriodicCheckType.objects.create(
            system=self.system, name="Estintori", category=self.fire, next_due_date=today - timedelta(days=5))
        self.plain = PeriodicCheckType.objects.create(
            system=self.system, name="Terra", next_due_date=today + timedelta(days=200))

    def _list(self, **params):
        return self.client.get(reverse("assets:periodic_check_list"), params)

    def test_righe_cliccabili_verso_la_scheda(self):
        page = self._list()
        self.assertContains(page, f'data-href="{reverse("assets:periodic_check_type_detail", args=[self.plain.id])}"')

    def test_filtro_e_raggruppamento_per_categoria(self):
        page = self._list(categoria=str(self.fire.id))
        names = [row["type"].name for group in page.context["groups"] for row in group["rows"]]
        self.assertEqual(names, ["Estintori"])
        page = self._list(categoria="nessuna")
        self.assertEqual([row["type"].name for g in page.context["groups"] for row in g["rows"]], ["Terra"])
        page = self._list(raggruppa="categoria")
        self.assertEqual([g["name"] for g in page.context["groups"]], ["Antincendio", "Senza categoria"])

    def test_cosa_fare_adesso(self):
        session = PeriodicCheckSession.objects.create(
            check_type=self.plain, performed_on=timezone.localdate(), outcome=PeriodicCheckSession.OUTCOME_REMARKS)
        PeriodicCheckResult.objects.create(session=session, label="Picchetto corroso",
                                           kind=PeriodicCheckResult.KIND_REMARK, result=PeriodicCheckResult.RESULT_KO)
        todo = self._list().context["todo"]
        kinds = {(row["kind"], row["title"]) for row in todo}
        self.assertIn(("Scaduta", "Estintori"), kinds)
        self.assertIn(("Rilievi senza OdL", "Terra"), kinds)
        self.assertEqual(todo[0]["tone"], "danger")

    def test_singola_verifica_ha_le_schede_e_la_testata_sotto_la_barra(self):
        session = PeriodicCheckSession.objects.create(check_type=self.plain, performed_on=timezone.localdate())
        page = self.client.get(reverse("assets:periodic_check_session_detail", args=[session.id]))
        self.assertTrue(page.context["assets_head_below_nav"])
        self.assertEqual([t["key"] for t in page.context["type_tabs"] if t["active"]], ["storico"])
        html = page.content.decode()
        self.assertContains(page, "Sezioni della verifica")
        self.assertLess(html.index('class="as-section-nav"'), html.index('class="as-page-head"'))
        self.assertEqual([p["state"] for p in page.context["progress"]], ["done", "done", "done"])

    def test_elenco_tiene_la_testata_sopra_la_barra(self):
        html = self._list().content.decode()
        self.assertLess(html.index('class="as-page-head"'), html.index('class="as-section-nav"'))

    def test_categorie_crea_e_assegna(self):
        url = reverse("assets:periodic_check_categories")
        response = self.client.post(url, {"name": "Elettrico", "color": "blue", "sort_order": 10, "is_active": "on"})
        self.assertRedirects(response, url)
        elettrico = PeriodicCheckCategory.objects.get(name="Elettrico")
        self.client.post(url, {"action": "assign", f"type_{self.plain.id}": str(elettrico.id),
                               f"type_{self.overdue.id}": ""})
        self.plain.refresh_from_db()
        self.overdue.refresh_from_db()
        self.assertEqual((self.plain.category_id, self.overdue.category_id), (elettrico.id, None))

    def test_form_verifica_con_categoria_e_segnalazioni(self):
        page = self.client.get(reverse("assets:periodic_check_type_edit", args=[self.plain.id]))
        self.assertContains(page, 'name="category"')
        self.assertContains(page, 'name="point_categories"')
        self.assertContains(page, 'type="radio" name="method"')
