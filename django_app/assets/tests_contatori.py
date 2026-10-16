"""Blocco C1: letture dei contatori con freschezza, ingest dai collector, piani a
contatore. Dati sintetici."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetMeter,
    AssetMeterHistory,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    MeterIngestClient,
    WorkOrder,
)
from assets.services import maintenance_domain as domain
from assets.services.meters import MeterReadingOlder, MeterReadingRejected, record_meter_reading

User = get_user_model()
INGEST_URL = "/api/assets/contatori/ingest/"


def _complete_onboarding(user) -> None:
    from core.models import UserOnboarding

    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()}
    )


class _MeterFixture:
    def _asset_with_meter(self, tag="C1-CNC-1", value="1000"):
        asset = Asset.objects.create(asset_tag=tag, name=f"CNC {tag}", asset_type=Asset.TYPE_CNC, status=Asset.STATUS_IN_USE)
        meter = AssetMeter.objects.create(asset=asset, meter_type=AssetMeter.METER_HOURS, current_value=Decimal(value), unit_label="h")
        return asset, meter


# ---------------------------------------------------------------------------
# C1.1 — letture
# ---------------------------------------------------------------------------


class MeterReadingServiceTests(_MeterFixture, TestCase):
    def setUp(self):
        self.asset, self.meter = self._asset_with_meter()

    def test_lettura_valida_aggiorna_valore_momento_e_provenienza(self):
        read_at = timezone.now() - timedelta(hours=2)
        history = record_meter_reading(self.meter, "1050,5", read_at=read_at, source=AssetMeter.SOURCE_OPCUA)
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("1050.50"))
        self.assertEqual(self.meter.source, AssetMeter.SOURCE_OPCUA)
        self.assertEqual(self.meter.read_at, read_at)
        self.assertEqual((history.old_value, history.new_value), (Decimal("1000.00"), Decimal("1050.50")))
        self.assertEqual(self.meter.freshness_label, "aggiornato 2 ore fa")
        self.assertFalse(self.meter.is_stale)

    def test_valore_in_calo_rifiutato(self):
        with self.assertRaises(MeterReadingRejected):
            record_meter_reading(self.meter, "900", read_at=timezone.now(), source=AssetMeter.SOURCE_MANUAL)
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("1000.00"))

    def test_azzeramento_richiede_la_nota(self):
        with self.assertRaises(MeterReadingRejected):
            record_meter_reading(self.meter, "0", read_at=timezone.now(), source=AssetMeter.SOURCE_MANUAL, is_reset=True)
        history = record_meter_reading(
            self.meter, "0", read_at=timezone.now(), source=AssetMeter.SOURCE_MANUAL, is_reset=True,
            note="Contatore sostituito con la scheda",
        )
        self.assertTrue(history.is_reset)
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("0.00"))

    def test_lettura_piu_vecchia_ignorata(self):
        now = timezone.now()
        record_meter_reading(self.meter, "1100", read_at=now, source=AssetMeter.SOURCE_OPCUA)
        with self.assertRaises(MeterReadingOlder):
            record_meter_reading(self.meter, "1200", read_at=now - timedelta(minutes=5), source=AssetMeter.SOURCE_OPCUA)
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("1100.00"))

    def test_freschezza_lettura_vecchia(self):
        AssetMeter.objects.filter(pk=self.meter.pk).update(read_at=timezone.now() - timedelta(days=9))
        self.meter.refresh_from_db()
        self.assertTrue(self.meter.is_stale)
        self.assertEqual(self.meter.freshness_label, "lettura vecchia: 9 giorni")
        self.assertEqual(self.meter.freshness_tone, "muted")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeterManualViewTests(_MeterFixture, TestCase):
    def setUp(self):
        self.asset, self.meter = self._asset_with_meter(tag="C1-MAN-1")

    def test_senza_permesso_esecuzione_403(self):
        user = User.objects.create_user(username="c1-op", password="x", email="c1op@example.com")
        _complete_onboarding(user)
        self.client.force_login(user)
        response = self.client.post(
            reverse("assets:asset_meter_update", args=[self.asset.pk]), {"meter_id": self.meter.pk, "new_value": "1200"}
        )
        self.assertEqual(response.status_code, 403)
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("1000.00"))

    def test_valore_in_calo_mostra_errore(self):
        admin = User.objects.create_superuser(username="c1-admin", password="x", email="c1a@example.com")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_meter_update", args=[self.asset.pk]), {"meter_id": self.meter.pk, "new_value": "10"}
        )
        self.assertContains(response, "non puo&#x27; scendere")
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("1000.00"))

    def test_landing_qr_mostra_freschezza(self):
        admin = User.objects.create_superuser(username="c1-admin2", password="x", email="c1b@example.com")
        self.client.force_login(admin)
        record_meter_reading(self.meter, "1010", read_at=timezone.now(), source=AssetMeter.SOURCE_MANUAL)
        response = self.client.get(reverse("assets:asset_qr_landing", kwargs={"asset_tag": self.asset.asset_tag}))
        self.assertContains(response, 'id="contatori"', html=False)
        self.assertContains(response, "aggiornato meno di un&#x27;ora fa")
        self.assertContains(response, "Registra una lettura")


# ---------------------------------------------------------------------------
# C1.2 — ingest
# ---------------------------------------------------------------------------


@override_settings(ASSETS_METER_INGEST_ALLOWED_IPS=["127.0.0.1"])
class MeterIngestTests(_MeterFixture, TestCase):
    def setUp(self):
        self.asset, self.meter = self._asset_with_meter(tag="C1-ING-1", value="500")
        self.other, self.other_meter = self._asset_with_meter(tag="C1-ING-2", value="10")
        self.token = MeterIngestClient.issue_token()
        self.collector = MeterIngestClient(name="OPC UA officina (test)")
        self.collector.set_token(self.token)
        self.collector.save()
        self.collector.allowed_assets.add(self.asset)

    def _post(self, readings, token=None, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token if token is not None else self.token}"}
        headers.update(extra)
        return self.client.post(INGEST_URL, data=json.dumps({"readings": readings}), content_type="application/json", **headers)

    def _reading(self, tag="C1-ING-1", value=510, minutes_ago=1):
        return {
            "asset_tag": tag,
            "meter_type": "HOURS",
            "value": value,
            "read_at": (timezone.now() - timedelta(minutes=minutes_ago)).isoformat(),
        }

    def test_lettura_accettata(self):
        response = self._post([self._reading()])
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["accepted"], 1)
        self.assertEqual(body["results"][0]["status"], "accepted")
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("510.00"))
        self.assertEqual(self.meter.source, AssetMeter.SOURCE_OPCUA)
        self.collector.refresh_from_db()
        self.assertIsNotNone(self.collector.last_seen_at)

    def test_token_errato_401_json(self):
        response = self._post([self._reading()], token="sbagliato")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"].split(";")[0], "application/json")
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("500.00"))

    def test_senza_token_401(self):
        response = self.client.post(INGEST_URL, data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_collector_disattivato_401(self):
        MeterIngestClient.objects.filter(pk=self.collector.pk).update(is_active=False)
        self.assertEqual(self._post([self._reading()]).status_code, 401)

    def test_rete_non_ammessa_403(self):
        response = self._post([self._reading()], REMOTE_ADDR="203.0.113.7")
        self.assertEqual(response.status_code, 403)

    def test_asset_non_consentito_rigetta_la_riga(self):
        response = self._post([self._reading(tag="C1-ING-2", value=20)])
        result = response.json()["results"][0]
        self.assertEqual(result["status"], "rejected")
        self.assertIn("non consentito", result["reason"])
        self.other_meter.refresh_from_db()
        self.assertEqual(self.other_meter.current_value, Decimal("10.00"))

    def test_lettura_piu_vecchia_ignorata(self):
        self._post([self._reading(value=520, minutes_ago=1)])
        response = self._post([self._reading(value=530, minutes_ago=10)])
        self.assertEqual(response.json()["results"][0]["status"], "ignored_older")
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("520.00"))

    def test_lotto_oltre_500_413(self):
        response = self._post([self._reading()] * 501)
        self.assertEqual(response.status_code, 413)

    def test_valore_in_calo_e_fuso_mancante_rigettati(self):
        response = self._post([
            self._reading(value=100),
            {"asset_tag": "C1-ING-1", "meter_type": "HOURS", "value": 600, "read_at": "2026-10-16T10:00:00"},
        ])
        statuses = [r["status"] for r in response.json()["results"]]
        self.assertEqual(statuses, ["rejected", "rejected"])

    def test_get_non_risponde_200(self):
        response = self.client.get(INGEST_URL, HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertNotEqual(response.status_code, 200)

    def test_comando_crea_collector_e_stampa_il_token(self):
        from io import StringIO

        out = StringIO()
        call_command("meter_ingest_client", "Collector comando", "--asset", "C1-ING-1", stdout=out)
        token = out.getvalue().strip().splitlines()[-1]
        client = MeterIngestClient.objects.get(name="Collector comando")
        self.assertEqual(client.token_hash, MeterIngestClient.hash_token(token))
        self.assertNotIn(token, client.token_hash)


# ---------------------------------------------------------------------------
# C1.3 — piani a contatore
# ---------------------------------------------------------------------------


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeterPlanTests(_MeterFixture, TestCase):
    def setUp(self):
        self.asset, self.meter = self._asset_with_meter(tag="C1-PLAN-1", value="1000")
        self.plan = MaintenanceInterventionTemplate.objects.create(code="c1-tagliando", label="Tagliando 500 h")
        self.assignment = MaintenancePlanAssignment.objects.create(
            plan=self.plan,
            target_type=MaintenancePlanAssignment.TARGET_ASSET,
            asset=self.asset,
            trigger_type=MaintenancePlanAssignment.TRIGGER_METER,
            meter_type=AssetMeter.METER_HOURS,
            meter_interval=Decimal("500"),
            meter_baseline=Decimal("1000"),
        )
        self.admin = User.objects.create_superuser(username="c1-plan-admin", password="x", email="c1p@example.com")

    def _set_meter(self, value, *, days_ago=0):
        AssetMeter.objects.filter(pk=self.meter.pk).update(
            current_value=Decimal(value), read_at=timezone.now() - timedelta(days=days_ago)
        )
        self.meter.refresh_from_db()

    def _generate(self):
        return domain.generate_occurrences(asset_queryset=Asset.objects.filter(pk=self.asset.pk))

    def _open(self):
        return MaintenanceOccurrence.objects.filter(plan=self.plan, asset=self.asset, status=MaintenanceOccurrence.STATUS_OPEN)

    def test_clean_non_chiede_il_calendario(self):
        self.assignment.full_clean()
        bad = MaintenancePlanAssignment(
            plan=self.plan, target_type=MaintenancePlanAssignment.TARGET_ASSET, asset=self.asset,
            trigger_type=MaintenancePlanAssignment.TRIGGER_METER, meter_type=AssetMeter.METER_HOURS,
            meter_interval=Decimal("0"),
        )
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_soglia_non_raggiunta(self):
        self._set_meter("1400")  # traguardo 1500, preavviso 50 -> nasce da 1450
        self.assertEqual(self._generate()["created"], 0)
        self.assertFalse(self._open().exists())

    def test_finestra_di_preavviso(self):
        self._set_meter("1460")
        self.assertEqual(self._generate()["created"], 1)
        occ = self._open().get()
        self.assertTrue(occ.is_meter_based)
        self.assertEqual(occ.due_meter_value, Decimal("1500.00"))

    def test_soglia_superata_e_idempotenza(self):
        self._set_meter("1600")
        self.assertEqual(self._generate()["created"], 1)
        again = self._generate()
        self.assertEqual(again["created"], 0)
        self.assertEqual(self._open().count(), 1)

    def test_contatore_vecchio_data_non_stimata(self):
        self._set_meter("1480", days_ago=20)
        self._generate()
        occ = self._open().get()
        self.assertFalse(occ.meter_due_estimated)
        self.assertEqual(occ.due_date, timezone.localdate())

    def test_data_stimata_dal_consumo(self):
        now = timezone.now()
        AssetMeterHistory.objects.create(meter=self.meter, old_value=Decimal("1400"), new_value=Decimal("1400"), read_at=now - timedelta(days=10))
        AssetMeterHistory.objects.create(meter=self.meter, old_value=Decimal("1400"), new_value=Decimal("1460"), read_at=now - timedelta(minutes=5))
        self._set_meter("1460")  # 6 h/giorno, mancano 40 h -> 7 giorni
        self._generate()
        occ = self._open().get()
        self.assertTrue(occ.meter_due_estimated)
        self.assertEqual(occ.due_date, timezone.localdate() + timedelta(days=7))

    def test_completamento_richiede_il_valore_e_la_prossima_parte_da_li(self):
        self._set_meter("1500")
        self._generate()
        occ = self._open().get()
        with self.assertRaises(domain.OccurrenceCompletionError):
            domain.complete_occurrence(occ, user=self.admin)
        occ.refresh_from_db()
        self.assertEqual(occ.status, MaintenanceOccurrence.STATUS_OPEN)
        domain.complete_occurrence(occ, user=self.admin, meter_value="1510")
        occ.refresh_from_db()
        self.assertEqual(occ.meter_value_at_completion, Decimal("1510.00"))
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_value, Decimal("1510.00"))  # registrata anche come lettura
        # prossimo traguardo: 1510 + 500 = 2010, preavviso da 1960
        self._set_meter("1950")
        self.assertEqual(self._generate()["created"], 0)
        self._set_meter("1970")
        self._generate()
        self.assertEqual(self._open().get().due_meter_value, Decimal("2010.00"))

    def test_completamento_con_valore_in_calo_rifiutato(self):
        self._set_meter("1500")
        self._generate()
        occ = self._open().get()
        with self.assertRaises(domain.OccurrenceCompletionError):
            domain.complete_occurrence(occ, user=self.admin, meter_value="1200")

    def test_fatta_oggi_non_ammessa_a_contatore(self):
        self._set_meter("1500")
        self._generate()
        occ = self._open().get()
        self.assertFalse(occ.quick_complete_allowed)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("assets:occurrence_quick_complete", args=[occ.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 409)

    def test_form_registra_chiede_il_valore(self):
        self._set_meter("1500")
        self._generate()
        occ = self._open().get()
        self.client.force_login(self.admin)
        page = self.client.get(reverse("assets:occurrence_complete", args=[occ.pk]))
        self.assertContains(page, 'name="meter_value"', html=False)
        response = self.client.post(
            reverse("assets:occurrence_complete", args=[occ.pk]),
            {"completed_on": timezone.localdate().isoformat(), "meter_value": "1505"},
        )
        self.assertEqual(response.status_code, 302)
        occ.refresh_from_db()
        self.assertEqual(occ.status, MaintenanceOccurrence.STATUS_DONE)

    def test_riga_da_fare_mostra_il_traguardo(self):
        self._set_meter("1480", days_ago=20)
        self._generate()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assets:maintenance_da_fare"), {"mio": "0"})
        self.assertContains(response, "a 1500 h (ora 1480")
        self.assertContains(response, "data stimata non disponibile")

    def test_chiusura_odl_registra_le_ore(self):
        from assets.services.workorder_close import CloseData, RequestIdentity, close_workorder

        wo = WorkOrder.objects.create(asset=self.asset, kind=WorkOrder.KIND_CORRECTIVE, title="Guasto mandrino C1")
        close_workorder(
            wo.pk,
            data=CloseData(status=WorkOrder.STATUS_DONE, esito=WorkOrder.OUTCOME_RESOLVED, resolution="Fatto",
                           closed_at=timezone.now() - timedelta(minutes=1)),
            user=self.admin,
            request_identity=RequestIdentity(),
        )
        wo.refresh_from_db()
        self.assertEqual(wo.meter_value_at_close, Decimal("1000.00"))

    def test_form_assegnazione_a_contatore(self):
        other = Asset.objects.create(asset_tag="C1-PLAN-2", name="CNC 2", asset_type=Asset.TYPE_CNC)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("assets:maintenance_assignment_create", args=[self.plan.pk]),
            {
                "target_type": MaintenancePlanAssignment.TARGET_ASSET,
                "asset": other.pk,
                "trigger_type": MaintenancePlanAssignment.TRIGGER_METER,
                "meter_type": AssetMeter.METER_HOURS,
                "meter_interval": "250",
                "warning_days": 0,
                "auto_generate": "on",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302, response.content[:600])
        created = MaintenancePlanAssignment.objects.get(plan=self.plan, asset=other)
        self.assertEqual(created.trigger_type, MaintenancePlanAssignment.TRIGGER_METER)
        self.assertEqual(created.meter_interval, Decimal("250.00"))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeterPanelCollectorHistoryTests(_MeterFixture, TestCase):
    def test_pannello_con_letture_senza_utente(self):
        """Le letture del collector non hanno utente: il pannello non deve rispondere 500."""
        asset, meter = self._asset_with_meter(tag="C1-PAN-1")
        record_meter_reading(meter, "1100", read_at=timezone.now(), source=AssetMeter.SOURCE_OPCUA, user=None)
        admin = User.objects.create_superuser(username="c1-pan", password="x", email="c1pan@example.com")
        self.client.force_login(admin)
        response = self.client.get(reverse("assets:asset_meter_update", args=[asset.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OPC UA")
