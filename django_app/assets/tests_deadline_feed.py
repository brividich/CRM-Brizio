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


class ScadenzeAmministrativeSeparateTests(DeadlineFeedTestCase):
    """Le ``AssetAdministrativeDeadline`` sono un registro separato dai piani: si
    leggono tutte; le loro copie migrate in un piano amministrativo non contano."""

    def setUp(self):
        super().setUp()
        from assets.models import AssetAdministrativeDeadline

        # Scadenza di cui ``occ_adm`` e' la copia: stesso asset, piano con il suo titolo.
        self.scadenza = AssetAdministrativeDeadline.objects.create(
            asset=self.carroponte, title="Revisione feed", due_date=self.occ_adm.due_date
        )
        self.altra = AssetAdministrativeDeadline.objects.create(
            asset=self.firewall, title="Certificato CE feed", due_date=self.today + timedelta(days=4)
        )

    def test_feed_legge_le_scadenze_e_salta_le_copie(self):
        keys = {
            row.key
            for row in feed.collect(
                start=self.today - timedelta(days=30), end=self.today + timedelta(days=30), today=self.today
            )
        }
        self.assertIn(f"dl-{self.scadenza.id}", keys)
        self.assertIn(f"dl-{self.altra.id}", keys)
        self.assertNotIn(f"occ-{self.occ_adm.id}", keys)

    def test_administrative_dues_conta_una_volta(self):
        dues = feed.administrative_dues(due_to=self.today + timedelta(days=30))
        self.assertEqual(
            sorted((due.source, due.id) for due in dues),
            sorted([("legacy", self.scadenza.id), ("legacy", self.altra.id)]),
        )

    def test_copia_fuori_da_da_fare_e_scadenzario(self):
        response = self.client.get(
            reverse("assets:maintenance_scadenze"), {"window": "", "plan_type": "administrative"}
        )
        self.assertEqual(response.context["rows"], [])
        keys = {row.key for row in response.context["renewals"]}
        self.assertEqual(keys, {f"dl-{self.scadenza.id}", f"dl-{self.altra.id}"})

    def test_comando_prova_a_vuoto_non_scrive(self):
        import io
        from django.core.management import call_command

        out = io.StringIO()
        call_command("separate_admin_deadlines", stdout=out)
        self.occ_adm.refresh_from_db()
        self.assertEqual(self.occ_adm.status, MaintenanceOccurrence.STATUS_OPEN)
        self.assertIn("PROVA A VUOTO", out.getvalue())
        self.assertIn(f"#{self.occ_adm.id}", out.getvalue())

    def test_comando_riattiva_annulla_le_copie_e_riporta_le_esecuzioni(self):
        import io
        from django.core.management import call_command

        from assets.models import AssetAdministrativeDeadlineCompletion
        from core.models import AuditLog

        # Stato lasciato da close_migrated_admin_deadlines: originale spenta con nota.
        self.scadenza.is_active = False
        self.scadenza.notes = (
            "Nota vera.\n[23/09/2026] Chiusa: la scadenza vive nell'occorrenza "
            f"#{self.occ_adm.id} del piano amministrativo. Si gestisce da Manutenzione > Scadenzario."
        )
        self.scadenza.save()
        # Un'esecuzione registrata sulla copia (non migrata dallo storico).
        eseguita = MaintenanceOccurrence.objects.create(
            plan=self.occ_adm.plan, asset=self.carroponte, due_date=self.today - timedelta(days=400),
            status=MaintenanceOccurrence.STATUS_DONE, completed_on=self.today - timedelta(days=2),
            completion_notes="Fatta dal piano",
        )

        call_command("separate_admin_deadlines", apply=True, stdout=io.StringIO())

        self.scadenza.refresh_from_db()
        self.occ_adm.refresh_from_db()
        self.assertTrue(self.scadenza.is_active)
        self.assertEqual(self.scadenza.notes, "Nota vera.")
        self.assertEqual(self.occ_adm.status, MaintenanceOccurrence.STATUS_CANCELED)
        self.assertTrue(
            AssetAdministrativeDeadlineCompletion.objects.filter(
                deadline=self.scadenza, completed_on=eseguita.completed_on
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                azione="ASSET_SCADENZA_AMMINISTRATIVA_SEPARATA_DAI_PIANI", oggetto_id=str(self.scadenza.id)
            ).exists()
        )
        # Ripetibile: la seconda esecuzione non trova piu' niente.
        out = io.StringIO()
        call_command("separate_admin_deadlines", apply=True, stdout=out)
        self.assertIn("Fatto: 0 riattivate, 0 esecuzioni riportate, 0 occorrenze annullate", out.getvalue())

    def test_dashboard_asset_e_hub_contano_senza_doppioni(self):
        from django.test import RequestFactory

        from assets.services import dashboard_kpi
        from dashboard.scadenze_providers import ScadenzeContext, collect_asset

        overview = dashboard_kpi.get_cose_da_fare_overview(today=self.today)
        self.assertEqual(overview["deadlines_overdue"], 1)  # la scadenza, non anche la copia
        self.assertEqual(overview["deadlines_30"], 1)  # l'altra

        request = RequestFactory().get(reverse("assets:maintenance_scadenze"))
        request.user = self.admin
        titoli = [item.titolo for item in collect_asset(ScadenzeContext.build(request))]
        self.assertEqual(titoli.count("Revisione feed"), 1)
        self.assertIn("Certificato CE feed", titoli)
        self.assertIn("Total Security feed", " ".join(titoli))

    def test_nuovo_piano_non_puo_essere_amministrativo(self):
        from assets.forms_maintenance import MaintenancePlanForm

        form = MaintenancePlanForm()
        values = {value for value, _label in form.fields["maintenance_type"].choices}
        self.assertNotIn(MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE, values)
        # Un piano amministrativo gia' esistente conserva il suo tipo.
        form = MaintenancePlanForm(instance=self.occ_adm.plan)
        values = {value for value, _label in form.fields["maintenance_type"].choices}
        self.assertIn(MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE, values)


class PanoramicaKpiTests(DeadlineFeedTestCase):
    def test_panoramica_per_tipologia(self):
        response = self.client.get(reverse("assets:maintenance_responsabile"), {"vista": "operativo"})
        self.assertEqual(response.status_code, 200)
        types = {t["kind"]: t for t in response.context["panoramica"]["types"]}
        self.assertEqual(set(types), {"ordinary", "administrative", "license", "contract"})
        self.assertEqual(types["administrative"]["overdue"], 1)
        self.assertEqual(types["ordinary"]["due_30"], 1)
        self.assertEqual(types["license"]["next"].key, f"lic-{self.licenza.id}")
        self.assertEqual(len(response.context["panoramica"]["heat"]), 28)
        self.assertContains(response, "Prossime quattro settimane")

    def test_panoramica_filtrata_per_famiglia(self):
        response = self.client.get(
            reverse("assets:maintenance_responsabile"), {"vista": "operativo", "category": self.famiglia.id}
        )
        types = {t["kind"]: t for t in response.context["panoramica"]["types"]}
        self.assertEqual(types["license"]["due_30"], 0)
        self.assertEqual(types["contract"]["due_30"], 1)
        self.assertIn(f"category={self.famiglia.id}", response.context["panoramica"]["scadenzario_url"])

    def test_pagina_kpi(self):
        response = self.client.get(reverse("assets:maintenance_kpi"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["vista"], "sintesi")
        self.assertTrue(response.context["kpi_page"])
        conformita = response.context["conformita"]
        self.assertEqual(conformita["adempimenti_aperti"], 1)
        self.assertEqual(conformita["adempimenti_scaduti"], 1)
        self.assertEqual(conformita["rinnovi_90"], 2)
        self.assertContains(response, "Report e budget")
        self.assertContains(response, 'class="as-section-tab active"', html=False)


class PaginaScadenzeAmministrativeTests(DeadlineFeedTestCase):
    """/assets/scadenze/: schede per stato, serie raccolte in una riga, mesi."""

    def setUp(self):
        super().setUp()
        from assets.models import AssetAdministrativeDeadline

        D = AssetAdministrativeDeadline
        self.scaduta = D.objects.create(asset=self.carroponte, title="Verifica periodica", due_date=self.today - timedelta(days=5))
        # Serie: stesso asset e titolo, tre date.
        self.serie = [
            D.objects.create(asset=self.firewall, title="Controllo batterie", due_date=self.today + timedelta(days=d))
            for d in (20, 110, 200)
        ]
        self.chiusa = D.objects.create(asset=self.firewall, title="Certificato vecchio", due_date=self.today, is_active=False)
        self.url = reverse("assets:asset_administrative_deadline_list")

    def test_default_tutte_attive_con_serie_raccolte(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["status_filter"], "active")
        ids = [row["deadline"].id for row in response.context["deadline_rows"]]
        self.assertEqual(ids, [self.scaduta.id, self.serie[0].id])
        lead = response.context["deadline_rows"][1]
        self.assertEqual([r["deadline"].id for r in lead["series"]], [self.serie[1].id, self.serie[2].id])
        self.assertContains(response, "+2 date successive")
        self.assertNotContains(response, "Certificato vecchio")

    def test_schede_e_conteggi(self):
        response = self.client.get(self.url, {"status": "todo"})
        tabs = {tab["key"]: tab["count"] for tab in response.context["status_tabs"]}
        self.assertEqual(tabs, {"todo": 2, "next90": 1, "active": 4, "inactive": 1})
        self.assertEqual([row["deadline"].id for row in response.context["deadline_rows"]],
                         [self.scaduta.id, self.serie[0].id])
        response = self.client.get(self.url, {"status": "inactive"})
        self.assertContains(response, "Certificato vecchio")

    def test_filtro_mese(self):
        month = self.serie[1].due_date.strftime("%Y-%m")
        response = self.client.get(self.url, {"status": "active", "month": month})
        self.assertEqual([row["deadline"].id for row in response.context["deadline_rows"]], [self.serie[1].id])
        strip = {m["key"]: m["count"] for m in response.context["months"]}
        self.assertEqual(strip["overdue"], 1)
        self.assertEqual(len(response.context["months"]), 13)
        response = self.client.get(self.url, {"month": "overdue"})
        self.assertEqual([row["deadline"].id for row in response.context["deadline_rows"]], [self.scaduta.id])

    def test_registra_dalla_finestra_torna_alla_stessa_vista(self):
        response = self.client.post(self.url, {
            "action": "complete_administrative_deadline",
            "deadline_id": str(self.scaduta.id),
            "execution_date": self.today.isoformat(),
            "execution_next_due": (self.today + timedelta(days=365)).isoformat(),
            "filter_status": "todo",
            "filter_month": "overdue",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("status=todo", response["Location"])
        self.assertIn("month=overdue", response["Location"])
        self.scaduta.refresh_from_db()
        self.assertEqual(self.scaduta.due_date, self.today + timedelta(days=365))


class PanoramicaSelezioneTests(DeadlineFeedTestCase):
    def test_prossime_mostra_tutte_e_seleziona_tutte(self):
        extra = [
            MaintenanceOccurrence.objects.create(
                plan=self.occ_ord.plan, asset=self.firewall, due_date=self.today + timedelta(days=d)
            )
            for d in range(1, 13)
        ]
        response = self.client.get(reverse("assets:maintenance_responsabile"), {"vista": "operativo"})
        pan = response.context["panoramica"]
        ids = {row.occurrence_id for row in pan["prossime"]}
        self.assertTrue({occ.id for occ in extra} <= ids)
        self.assertGreaterEqual(pan["prossime_selectable"], 12)
        self.assertContains(response, "data-md-check-all", html=False)
        self.assertContains(response, f"Seleziona tutte ({pan['prossime_selectable']})")
