"""Scheda della verifica periodica: statistiche (stato dei punti, ricorrenze, andamento) e schede."""

from __future__ import annotations

import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import (
    Asset,
    PeriodicCheckItem,
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
    WorkOrder,
)
from assets.services import periodic_checks as checks
from assets.services import periodic_stats
from assets.tests_periodic_layout import TITLE_BLOCK, synthetic_plan

User = get_user_model()
NF, BA = "Non funzionante", "Bassa autonomia"


@override_settings(LEGACY_AUTH_ENABLED=False)
class StatistichePlanimetriaTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        override = override_settings(ASSETS_PRIVATE_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._tmp.cleanup)
        self.admin = User.objects.create_superuser(username="ps-admin", password="x", email="ps@y.z")
        self.asset = Asset.objects.create(asset_tag="QG-9", name="Quadro luci")
        system = PeriodicCheckSystem.objects.create(name="Impianto elettrico", asset=self.asset)
        self.check_type = PeriodicCheckType.objects.create(
            system=system, name="Verifica illuminazione di emergenza", frequency_months=4,
            method=PeriodicCheckType.METHOD_LAYOUT,
        )
        self.layout = checks.create_layout(self.check_type, synthetic_plan(), name="plan.pdf", exclude_areas=[TITLE_BLOCK])
        self.points = {p.code: p for p in self.layout.points.all()}

    def _session(self, day: date, defects: dict[str, str]) -> PeriodicCheckSession:
        session = checks.register_session(checks.SessionInput(
            self.check_type, day, PeriodicCheckSession.OUTCOME_OK,
            results=[
                checks.ResultInput(f"Punto {code}", kind=PeriodicCheckResult.KIND_POINT, result=PeriodicCheckResult.RESULT_KO,
                                   point=self.points[code], category=category)
                for code, category in defects.items()
            ],
        ))
        session.layout = self.layout
        session.save(update_fields=["layout"])
        return session

    def test_stato_attuale_ricorrenze_e_andamento(self):
        # storico importato: conta per le date, non per i punti
        checks.register_session(checks.SessionInput(self.check_type, date(2025, 5, 1), PeriodicCheckSession.OUTCOME_ARCHIVE))
        self._session(date(2025, 9, 1), {"5": NF, "9": BA})
        self._session(date(2026, 1, 10), {"5": NF})
        last = self._session(date(2026, 5, 20), {"5": NF, "11": BA})
        result_11 = last.results.get(point__code="11")
        work_order = checks.create_work_order(result_11, asset=self.asset)
        work_order.status = WorkOrder.STATUS_DONE
        work_order.save(update_fields=["status"])

        stats = periodic_stats.type_stats(self.check_type, today=date(2026, 6, 1))
        by_code = {p.code: p for p in stats.points}
        self.assertEqual((by_code["5"].state, by_code["5"].streak, by_code["5"].since), ("cat0", 3, date(2025, 9, 1)))
        self.assertEqual(by_code["11"].state, "fixed")
        self.assertEqual(by_code["9"].state, "ok")
        self.assertEqual([p.code for p in stats.defective], ["5"])
        self.assertEqual(stats.efficiency_pct, round(100 * 11 / 12))
        self.assertEqual([(p.code, p.recent_count) for p in stats.recurring], [("5", 3)])
        self.assertEqual((stats.confirmed, stats.with_results), (4, 3))
        self.assertEqual([row["total"] for row in stats.trend], [2, 1, 2])
        self.assertEqual([s["key"] for s in stats.trend_series], [NF, BA])
        # 1/9 dopo 1/5 (+4 mesi = 1/9) nei tempi; 10/1 oltre 1/1; 20/5 oltre 10/5
        self.assertEqual((stats.on_time, stats.on_time_total), (1, 3))

    def test_nessun_esito_niente_mappa_colorata(self):
        stats = periodic_stats.type_stats(self.check_type)
        self.assertEqual({p.state for p in stats.points}, {"unknown"})
        self.assertIsNone(stats.efficiency_pct)

    def test_schede_della_pagina(self):
        self._session(date(2026, 5, 20), {"5": NF})
        self.client.force_login(self.admin)
        url = reverse("assets:periodic_check_type_detail", args=[self.check_type.id])
        for tab, expected in (
            ("panoramica", "Stato attuale"),
            ("storico", "Storico verifiche"),
            ("odl", "Ordini di lavoro dai rilievi"),
            ("documenti", "Documenti"),
            ("impostazioni", "Planimetria e foglio per il tecnico"),
        ):
            with self.subTest(tab=tab):
                response = self.client.get(url, {"tab": tab})
                self.assertContains(response, expected)
                self.assertNotContains(response, "{#")
        page = self.client.get(url)
        self.assertContains(page, 'id="punto-5"')
        self.assertContains(page, "Andamento dei rilievi")
        image = self.client.get(reverse("assets:periodic_check_layout_image", args=[self.layout.id]))
        self.assertEqual((image.status_code, image["Content-Type"]), (200, "image/png"))

    def test_mappa_proporzioni_e_segnalazioni_cliccabili(self):
        last = self._session(date(2026, 5, 20), {"5": NF, "9": BA})
        self.client.force_login(self.admin)
        page = self.client.get(reverse("assets:periodic_check_type_detail", args=[self.check_type.id]))
        html = page.content.decode()
        # proporzioni con aspect-ratio: padding-top in % stirava la planimetria
        self.assertIn("aspect-ratio:", html)
        self.assertNotIn('class="pc-map" style="padding-top', html)
        session_url = reverse("assets:periodic_check_session_detail", args=[last.id])
        self.assertContains(page, 'data-pc-point="5"')
        self.assertContains(page, f'data-session-url="{session_url}"')
        self.assertContains(page, 'data-pc-focus="9"')
        self.assertContains(page, "Segnalazioni attive")
        self.assertContains(page, "is-cat0 is-open")
        self.assertEqual(page.context["map"]["counts"]["cat0"], 1)
        self.assertEqual(page.context["map"]["counts"]["cat1"], 1)


@override_settings(LEGACY_AUTH_ENABLED=False)
class StatisticheChecklistTests(TestCase):
    def test_voci_piu_spesso_non_ok(self):
        system = PeriodicCheckSystem.objects.create(name="Impianto elettrico")
        check_type = PeriodicCheckType.objects.create(system=system, name="Verifica quadri elettrici", frequency_months=6,
                                                      method=PeriodicCheckType.METHOD_CHECKLIST)
        vista = PeriodicCheckItem.objects.create(check_type=check_type, label="Esame a vista")
        temp = PeriodicCheckItem.objects.create(check_type=check_type, label="Controllo temperature")
        for day, ko in ((date(2025, 7, 1), [temp]), (date(2026, 1, 1), [temp, vista]), (date(2026, 7, 1), [])):
            checks.register_session(checks.SessionInput(check_type, day, "OK", results=[
                checks.ResultInput(i.label, item=i, result="KO" if i in ko else "OK") for i in (vista, temp)
            ]))
        stats = periodic_stats.type_stats(check_type, today=date(2026, 8, 1))
        self.assertEqual([(f["label"], f["ko"], f["of"]) for f in stats.item_failures],
                         [("Controllo temperature", 2, 3), ("Esame a vista", 1, 3)])
        self.assertEqual([row["total"] for row in stats.trend], [1, 2, 0])
