"""Servizio unico delle scadenze (``services.deadline_feed``), Calendario e Scadenzario.

Calendario ed elenco leggono la stessa fonte: occorrenze (ordinarie e
amministrative), licenze software e contratti di assistenza. Licenze e contratti
seguono l'ACL delle loro pagine.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore
from assets.models import (
    Asset,
    AssetCategory,
    AssistanceContract,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    SoftwareLicense,
)
from assets.services import deadline_feed as feed

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class DeadlineFeedTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.admin = User.objects.create_superuser(username="feed-admin", password="x", email="f@b.c")
        cls.famiglia = AssetCategory.objects.create(code="feed-soll", label="Sollevamento feed")
        cls.sotto = AssetCategory.objects.create(code="feed-crp", label="Carroponte feed", parent=cls.famiglia)
        cls.altra = AssetCategory.objects.create(code="feed-it", label="IT feed")
        cls.carroponte = Asset.objects.create(
            asset_tag="CRP-F1", name="Carroponte 10 t", asset_category=cls.sotto, reparto="Officina"
        )
        cls.firewall = Asset.objects.create(asset_tag="FW-F1", name="Firewall", asset_category=cls.altra, reparto="IT")
        ordinaria = MaintenanceInterventionTemplate.objects.create(code="feed-lubr", label="Lubrificazione feed")
        amministrativa = MaintenanceInterventionTemplate.objects.create(
            code="feed-rev",
            label="Revisione feed",
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
        )
        cls.occ_ord = MaintenanceOccurrence.objects.create(
            plan=ordinaria, asset=cls.carroponte, due_date=cls.today + timedelta(days=3), warning_days=30
        )
        cls.occ_adm = MaintenanceOccurrence.objects.create(
            plan=amministrativa, asset=cls.carroponte, due_date=cls.today - timedelta(days=2), warning_days=30
        )
        cls.licenza = SoftwareLicense.objects.create(
            product_name="Total Security feed", vendor="WatchGuard", asset=cls.firewall,
            expiry_date=cls.today + timedelta(days=10),
        )
        fornitore = Fornitore.objects.create(ragione_sociale="Assistenza Gru feed")
        cls.contratto = AssistanceContract.objects.create(
            supplier=fornitore, title="Full service carroponti feed", asset_category=cls.famiglia,
            end_date=cls.today + timedelta(days=20),
        )

    def setUp(self):
        self.client.force_login(self.admin)


class CollectTests(DeadlineFeedTestCase):
    def _keys(self, **filters):
        rows = feed.collect(
            start=self.today - timedelta(days=30),
            end=self.today + timedelta(days=60),
            filters=feed.FeedFilters(**filters),
            today=self.today,
        )
        return {row.key for row in rows}, rows

    def test_quattro_tipologie_nella_stessa_forma(self):
        keys, rows = self._keys()
        self.assertEqual(
            keys,
            {f"occ-{self.occ_ord.id}", f"occ-{self.occ_adm.id}", f"lic-{self.licenza.id}", f"con-{self.contratto.id}"},
        )
        by_key = {row.key: row for row in rows}
        self.assertEqual(by_key[f"occ-{self.occ_ord.id}"].kind, feed.KIND_ORDINARY)
        self.assertEqual(by_key[f"occ-{self.occ_adm.id}"].kind, feed.KIND_ADMINISTRATIVE)
        self.assertEqual(by_key[f"occ-{self.occ_adm.id}"].state, feed.STATE_OVERDUE)
        self.assertEqual(by_key[f"lic-{self.licenza.id}"].state, feed.STATE_DUE_SOON)
        # Ordinate per data: la scaduta per prima.
        self.assertEqual(rows[0].key, f"occ-{self.occ_adm.id}")

    def test_famiglia_comprende_sottocategorie_e_contratti_di_categoria(self):
        from assets.forms_maintenance import category_with_descendants

        keys, _ = self._keys(category_ids=frozenset(category_with_descendants(self.famiglia.id)))
        self.assertEqual(
            keys, {f"occ-{self.occ_ord.id}", f"occ-{self.occ_adm.id}", f"con-{self.contratto.id}"}
        )

    def test_filtro_tipologia_e_reparto(self):
        keys, _ = self._keys(kinds=frozenset({feed.KIND_LICENSE}))
        self.assertEqual(keys, {f"lic-{self.licenza.id}"})
        keys, _ = self._keys(reparto="IT")
        self.assertEqual(keys, {f"lic-{self.licenza.id}"})

    def test_esecuzione_esclude_licenze_e_contratti(self):
        keys, _ = self._keys(execution_mode="INTERNAL")
        self.assertFalse(any(key.startswith(("lic-", "con-")) for key in keys))

    def test_concluse_solo_su_richiesta(self):
        MaintenanceOccurrence.objects.filter(pk=self.occ_ord.pk).update(
            status=MaintenanceOccurrence.STATUS_DONE, completed_on=self.today
        )
        keys, _ = self._keys()
        self.assertNotIn(f"occ-{self.occ_ord.id}", keys)
        keys, rows = self._keys(include_done=True)
        self.assertIn(f"occ-{self.occ_ord.id}", keys)

    def test_parse_kinds(self):
        allowed = frozenset(feed.ALL_KINDS)
        self.assertEqual(feed.parse_kinds([], allowed), allowed)
        self.assertEqual(feed.parse_kinds(["none"], allowed), frozenset())
        self.assertEqual(feed.parse_kinds(["machine_work"], allowed), frozenset())
        self.assertEqual(feed.parse_kinds(["license"], frozenset({"ordinary"})), frozenset())


class CalendarioTests(DeadlineFeedTestCase):
    def _json(self, **params):
        params.setdefault("start", (self.today - timedelta(days=30)).isoformat() + "T00:00:00+02:00")
        params.setdefault("end", (self.today + timedelta(days=60)).isoformat() + "T00:00:00+02:00")
        response = self.client.get(reverse("assets:calendario_asset_json"), params)
        self.assertEqual(response.status_code, 200)
        return {event["id"]: event for event in response.json()["events"]}

    def test_pagina_rende_con_filtri_e_viste(self):
        response = self.client.get(reverse("assets:calendario_asset"))
        self.assertEqual(response.status_code, 200)
        for text in ("Ordinaria", "Amministrativa", "Licenza", "Contratto", "Famiglia", "Elenco", "Per asset"):
            self.assertContains(response, text)
        self.assertContains(response, 'class="as-section-tab active"', html=False)

    def test_json_tutte_le_tipologie_e_filtri(self):
        events = self._json()
        self.assertIn(f"occ-{self.occ_adm.id}", events)
        self.assertIn(f"lic-{self.licenza.id}", events)
        self.assertIn(f"con-{self.contratto.id}", events)
        adm = events[f"occ-{self.occ_adm.id}"]
        self.assertEqual(adm["kind"], "administrative")
        self.assertEqual(adm["state"], "overdue")
        self.assertEqual(adm["asset_tag"], "CRP-F1")
        self.assertTrue(any(a["url"].endswith(f"/registra/") for a in adm["actions"]))

        only_lic = self._json(kinds="license")
        self.assertEqual(set(only_lic), {f"lic-{self.licenza.id}"})
        self.assertEqual(self._json(kinds="none"), {})
        by_family = self._json(category=self.famiglia.id)
        self.assertNotIn(f"lic-{self.licenza.id}", by_family)

    def test_periodo_rispettato_e_limitato(self):
        events = self._json(
            start=(self.today + timedelta(days=15)).isoformat(),
            end=(self.today + timedelta(days=25)).isoformat(),
        )
        self.assertEqual(set(events), {f"con-{self.contratto.id}"})
        # Parametri rotti: nessun 500, si ripiega sul periodo di default.
        self.assertIsInstance(self._json(start="non-una-data", end="x"), dict)

    def test_licenze_e_contratti_seguono_l_acl_delle_loro_pagine(self):
        with mock.patch("core.middleware.acl_allows_path", return_value=False):
            events = self._json()
            page = self.client.get(reverse("assets:calendario_asset"))
        self.assertIn(f"occ-{self.occ_ord.id}", events)
        self.assertFalse(any(key.startswith(("lic-", "con-")) for key in events))
        self.assertNotContains(page, 'class="cm-chip" data-kind="license"', html=False)
        self.assertContains(page, 'class="cm-chip" data-kind="ordinary"', html=False)


class ScadenzarioRinnoviTests(DeadlineFeedTestCase):
    def test_licenze_e_contratti_compaiono_nell_elenco(self):
        response = self.client.get(reverse("assets:maintenance_scadenze"), {"window": "30"})
        self.assertEqual(response.status_code, 200)
        keys = {row.key for row in response.context["renewals"]}
        self.assertEqual(keys, {f"lic-{self.licenza.id}", f"con-{self.contratto.id}"})
        self.assertContains(response, "Total Security feed")

    def test_scheda_licenze_e_contratti_nasconde_le_occorrenze(self):
        response = self.client.get(reverse("assets:maintenance_scadenze"), {"window": "", "plan_type": "renewals"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"], [])
        self.assertEqual(len(response.context["renewals"]), 2)

    def test_scadute_e_filtri_non_applicabili(self):
        response = self.client.get(reverse("assets:maintenance_scadenze"), {"window": "overdue"})
        self.assertEqual(response.context["renewals"], [])
        # Un filtro che su licenze e contratti non ha senso li esclude invece di ignorarlo.
        response = self.client.get(
            reverse("assets:maintenance_scadenze"), {"window": "30", "execution_mode": "EXTERNAL"}
        )
        self.assertEqual(response.context["renewals"], [])

    def test_amministrative_non_mostra_rinnovi(self):
        response = self.client.get(
            reverse("assets:maintenance_scadenze"), {"window": "", "plan_type": "administrative"}
        )
        self.assertEqual(response.context["renewals"], [])
        self.assertEqual({r["occurrence"].id for r in response.context["rows"]}, {self.occ_adm.id})
