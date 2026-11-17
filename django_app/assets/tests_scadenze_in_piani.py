"""«Sposta nei piani»: le scadenze amministrative diventano piani di manutenzione, con doppioni."""

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
    MaintenancePlanAssignment,
    PeriodicCheckSystem,
    PeriodicCheckType,
)
from assets.services import deadline_feed as feed
from assets.services import scadenze_in_piani as sp

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class ScadenzeInPianiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="sp-admin", password="x", email="sp@example.local")
        cls.oggi = timezone.localdate()
        cls.a1 = Asset.objects.create(asset_tag="CP-01", name="Carroponte 1")
        cls.a2 = Asset.objects.create(asset_tag="CP-02", name="Carroponte 2")

    def setUp(self):
        self.client.force_login(self.admin)

    def _dl(self, asset, title, giorni, **kw):
        return AssetAdministrativeDeadline.objects.create(asset=asset, title=title, due_date=self.oggi + timedelta(days=giorni), **kw)

    def _proposta(self, deadline):
        return next(p for p in sp.analizza().proposte if deadline in p.righe)

    def test_stesso_titolo_su_due_asset_un_piano_due_applicazioni(self):
        d1 = self._dl(self.a1, "Verifica annuale funi", 10, recurrence_months=12)
        d2 = self._dl(self.a2, "Verifica annuale funi", 40, recurrence_months=12)
        chiavi = [self._proposta(d1).chiave, self._proposta(d2).chiave]
        esito = sp.applica(chiavi, user=self.admin)
        self.assertEqual((esito.applicazioni, esito.piani_creati), (2, 1))
        piano = MaintenanceInterventionTemplate.objects.get(label="Verifica annuale funi")
        self.assertEqual(piano.maintenance_type, MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE)
        a = MaintenancePlanAssignment.objects.get(plan=piano, asset=self.a1)
        self.assertEqual((a.frequency, a.interval, a.first_due_date), ("MONTHS", 12, d1.due_date))
        self.assertEqual(a.effective_schedule_anchor, MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR)
        d1.refresh_from_db()
        self.assertFalse(d1.is_active)
        self.assertEqual(d1.moved_to_plan, piano)
        # L'occorrenza nuova non e' una «copia» della scadenza spostata: compare nel registro unico.
        occ = MaintenanceOccurrence.objects.get(plan=piano, asset=self.a1)
        keys = [r.key for r in feed.collect(start=None, end=self.oggi + timedelta(days=60),
                                            filters=feed.FeedFilters(asset_id=self.a1.id), today=self.oggi)]
        self.assertIn(f"occ-{occ.id}", keys)
        self.assertNotIn(f"dl-{d1.id}", keys)

    def test_serie_diventa_una_applicazione_con_periodicita_dalle_date(self):
        d1 = self._dl(self.a1, "Controllo semestrale", 5)
        self._dl(self.a1, "Controllo semestrale", 5 + 182)
        p = self._proposta(d1)
        self.assertEqual((p.azione, p.mesi, len(p.righe)), (sp.AZIONE_SPOSTA, 6, 2))
        sp.applica([p.chiave], user=self.admin)
        self.assertFalse(AssetAdministrativeDeadline.objects.filter(is_active=True).exists())
        self.assertEqual(MaintenancePlanAssignment.objects.filter(asset=self.a1).count(), 1)

    def test_doppione_di_un_piano_gia_attivo(self):
        piano = MaintenanceInterventionTemplate.objects.create(code="vts", label="Verifica Termocoppia Sicurezza - VTS")
        MaintenancePlanAssignment.objects.create(
            plan=piano, asset=self.a1, target_type=MaintenancePlanAssignment.TARGET_ASSET,
            frequency=MaintenancePlanAssignment.FREQ_MONTHS, interval=12, first_due_date=self.oggi,
        )
        d = self._dl(self.a1, "Verifica VTS", 20, recurrence_months=12)
        p = self._proposta(d)
        self.assertEqual(p.azione, sp.AZIONE_DOPPIONE)
        self.assertEqual(p.piano_esistente, piano)
        esito = sp.applica([p.chiave], user=self.admin)
        self.assertEqual((esito.doppioni, esito.applicazioni), (1, 0))
        d.refresh_from_db()
        self.assertEqual((d.is_active, d.moved_to_plan), (False, piano))
        self.assertEqual(MaintenanceInterventionTemplate.objects.count(), 1)

    def test_senza_periodicita_serve_indicarla(self):
        d = self._dl(self.a1, "Certificato una tantum", 30)
        p = self._proposta(d)
        self.assertEqual(p.azione, sp.AZIONE_SENZA_PERIODO)
        esito = sp.applica([p.chiave], user=self.admin)
        self.assertTrue(esito.saltate)
        self.assertTrue(AssetAdministrativeDeadline.objects.get(pk=d.pk).is_active)
        esito = sp.applica([p.chiave], mesi={p.chiave: 24}, user=self.admin)
        self.assertEqual(esito.applicazioni, 1)
        self.assertEqual(MaintenancePlanAssignment.objects.get(asset=self.a1).interval, 24)

    def test_collegata_a_verifica_impianto_resta(self):
        d = self._dl(self.a1, "Verifica SAT", 10, recurrence_months=12)
        system = PeriodicCheckSystem.objects.create(name="Sollevamento", asset=self.a1)
        PeriodicCheckType.objects.create(system=system, name="SAT", administrative_deadline=d)
        p = self._proposta(d)
        self.assertEqual(p.azione, sp.AZIONE_RESTA)
        sp.applica([p.chiave], user=self.admin)
        self.assertTrue(AssetAdministrativeDeadline.objects.get(pk=d.pk).is_active)

    def test_ripetere_non_crea_doppioni(self):
        d = self._dl(self.a1, "Revisione biennale", 10, recurrence_months=24)
        chiave = self._proposta(d).chiave
        sp.applica([chiave], user=self.admin)
        esito = sp.applica([chiave], user=self.admin)
        self.assertEqual(esito.applicazioni, 0)
        self.assertTrue(esito.saltate)
        self.assertEqual(MaintenancePlanAssignment.objects.count(), 1)

    def test_pagina_anteprima_e_spostamento(self):
        d = self._dl(self.a1, "Revisione annuale", 10, recurrence_months=12)
        lista = self.client.get(reverse("assets:asset_administrative_deadline_list"))
        self.assertContains(lista, reverse("assets:scadenze_sposta_nei_piani"))
        page = self.client.get(reverse("assets:scadenze_sposta_nei_piani"))
        self.assertContains(page, "Revisione annuale")
        self.assertContains(page, "Diventa piano")
        chiave = self._proposta(d).chiave
        response = self.client.post(reverse("assets:scadenze_sposta_nei_piani"), {"scelta": [chiave]})
        self.assertRedirects(response, reverse("assets:scadenze_sposta_nei_piani"), fetch_redirect_response=False)
        self.assertFalse(AssetAdministrativeDeadline.objects.get(pk=d.pk).is_active)
