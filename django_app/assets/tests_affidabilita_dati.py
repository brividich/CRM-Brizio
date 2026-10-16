"""Blocco A (affidabilita' dati): login sulle viste manutenzione, query per riga
sugli allegati, KPI della lista asset, badge di stato unico, ticket <-> intervento
e chiusura OdL atomica. Dati sintetici."""

from __future__ import annotations

import importlib
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenanceOccurrenceAttachment,
    WorkOrder,
    WorkOrderExecutionDay,
    WorkOrderLog,
)
from assets.services import maintenance_domain as domain
from assets.services.workorder_close import (
    CloseData,
    RequestIdentity,
    WorkOrderAlreadyClosed,
    close_workorder,
)

User = get_user_model()

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _pdf(name="rapporto.pdf"):
    return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")


def _complete_onboarding(user) -> None:
    from core.models import UserOnboarding

    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()}
    )


class _PrivateRootMixin:
    """Allegati scritti in una cartella temporanea, mai nello storage reale."""

    @classmethod
    def setUpClass(cls):
        cls._tmp_root = tempfile.mkdtemp(prefix="assets-blocco-a-")
        cls._override = override_settings(ASSETS_PRIVATE_ROOT=cls._tmp_root, MEDIA_ROOT=cls._tmp_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._tmp_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# A1 — login sulle viste del dominio manutenzione
# ---------------------------------------------------------------------------


def _iter_patterns(patterns, namespace=""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            ns = entry.namespace or namespace
            yield from _iter_patterns(entry.url_patterns, ns)
        elif isinstance(entry, URLPattern):
            yield namespace, entry


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MaintenanceViewsLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.asset = Asset.objects.create(asset_tag="A1-1", name="Pressa A1")
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="a1-plan", label="Ingrassaggio A1")
        cls.occurrence = MaintenanceOccurrence.objects.create(
            plan=cls.plan, asset=cls.asset, due_date=timezone.localdate(), warning_days=10
        )

    def test_occurrence_complete_anonimo_va_al_login(self):
        response = self.client.get(reverse("assets:occurrence_complete", args=[self.occurrence.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_safe_back_url_con_anonimo_ritorna_una_stringa(self):
        from assets.views_maintenance import _safe_back_url

        request = RequestFactory().get("/x/", {"next": "/assets/"})
        request.user = AnonymousUser()
        result = _safe_back_url(request, "/fallback/")
        self.assertIsInstance(result, str)
        self.assertEqual(result, "/assets/")

    def test_ogni_vista_di_views_maintenance_richiede_il_login(self):
        """Chiamata diretta alla vista (senza middleware): un anonimo va sempre al login."""
        factory = RequestFactory()
        checked = 0
        for namespace, pattern in _iter_patterns(get_resolver().url_patterns):
            callback = pattern.callback
            module = getattr(callback, "__module__", "")
            if namespace != "assets" or module != "assets.views_maintenance":
                continue
            kwargs = {name: 1 for name in pattern.pattern.regex.groupindex}
            for method in ("get", "post"):
                request = getattr(factory, method)("/assets/x/")
                request.user = AnonymousUser()
                request._dont_enforce_csrf_checks = True
                response = callback(request, **kwargs)
                self.assertNotEqual(response.status_code, 200, f"{pattern.name} ({method}) risponde 200 a un anonimo")
                if response.status_code != 405:
                    self.assertEqual(response.status_code, 302, f"{pattern.name} ({method})")
                    self.assertIn("login", response["Location"], pattern.name)
            checked += 1
        self.assertGreater(checked, 20)


# ---------------------------------------------------------------------------
# A2 — niente query per riga sugli allegati
# ---------------------------------------------------------------------------


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AttachmentQueriesTests(_PrivateRootMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="a2-admin", password="x", email="a2@example.com")
        cls.category = AssetCategory.objects.create(code="a2-cat", label="A2")
        cls.plan = MaintenanceInterventionTemplate.objects.create(
            code="a2-plan", label="Verifica A2", attachment_required=True
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def _seed(self, count: int, prefix: str):
        today = timezone.localdate()
        for index in range(count):
            asset = Asset.objects.create(
                asset_tag=f"{prefix}-{index}", name=f"Macchina {prefix} {index}", asset_category=self.category
            )
            MaintenanceOccurrence.objects.create(
                plan=self.plan, asset=asset, due_date=today + timedelta(days=index % 5), warning_days=30
            )
            done = MaintenanceOccurrence.objects.create(
                plan=self.plan,
                asset=asset,
                due_date=today - timedelta(days=20 + index),
                warning_days=30,
                status=MaintenanceOccurrence.STATUS_DONE,
                completed_on=today - timedelta(days=1),
            )
            if index % 2:
                MaintenanceOccurrenceAttachment.objects.create(occurrence=done, file=_pdf(), uploaded_by=self.admin)

    def _count(self, url_name, params=None):
        self.client.get(reverse(url_name), params or {})  # cache / sessione calde
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse(url_name), params or {})
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_da_fare_stesso_numero_di_query_con_3_e_30_occorrenze(self):
        self._seed(3, "S")
        small = self._count("assets:maintenance_da_fare")
        self._seed(27, "L")
        large = self._count("assets:maintenance_da_fare")
        self.assertEqual(small, large)

    def test_scadenzario_stesso_numero_di_query_con_3_e_30_occorrenze(self):
        self._seed(3, "S")
        small = self._count("assets:maintenance_scadenze", {"window": ""})
        self._seed(27, "L")
        large = self._count("assets:maintenance_scadenze", {"window": ""})
        self.assertEqual(small, large)

    def test_has_attachment_usa_il_prefetch(self):
        self._seed(2, "P")
        rows = list(MaintenanceOccurrence.objects.filter(status=MaintenanceOccurrence.STATUS_DONE).prefetch_related("attachments"))
        with self.assertNumQueries(0):
            flags = [occ.has_attachment for occ in rows]
        self.assertEqual(sorted(flags), [False, True])


# ---------------------------------------------------------------------------
# A3 / A4 — KPI della lista asset e badge di stato
# ---------------------------------------------------------------------------


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetListKpiAndBadgeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="a3-admin", password="x", email="a3@example.com")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_kpi_reali_con_dati_sintetici(self):
        assets = [
            Asset.objects.create(asset_tag=f"K-{i}", name=f"Asset {i}", status=Asset.STATUS_IN_USE) for i in range(9)
        ]
        Asset.objects.create(asset_tag="K-R", name="Asset rotto", status=Asset.STATUS_IN_REPAIR)
        # 4 OdL aperti, 1 oltre la soglia di ritardo (default 7 giorni).
        for index, asset in enumerate(assets[:4]):
            WorkOrder.objects.create(
                asset=asset,
                title=f"Intervento {index}",
                opened_at=timezone.now() - timedelta(days=60 if index == 0 else 1),
            )
        response = self.client.get(reverse("assets:asset_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["health_percent"], 90.0)
        self.assertEqual(response.context["health_label"], "Buona")
        self.assertEqual(response.context["due_percent"], 25.0)
        self.assertContains(response, 'title="1 su 4 interventi aperti"')
        self.assertContains(response, "width:25.0%")
        self.assertNotContains(response, "Ottimale")

    def test_soglie_salute(self):
        for i in range(7):
            Asset.objects.create(asset_tag=f"H-{i}", name=f"Ok {i}", status=Asset.STATUS_IN_USE)
        for i in range(3):
            Asset.objects.create(asset_tag=f"HR-{i}", name=f"Rotto {i}", status=Asset.STATUS_IN_REPAIR)
        response = self.client.get(reverse("assets:asset_list"))
        self.assertEqual(response.context["health_label"], "Da monitorare")
        Asset.objects.create(asset_tag="HR-X", name="Rotto X", status=Asset.STATUS_IN_REPAIR)
        response = self.client.get(reverse("assets:asset_list"))
        self.assertEqual(response.context["health_label"], "Critica")

    def test_zero_asset_nessuna_divisione_per_zero(self):
        response = self.client.get(reverse("assets:asset_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["due_percent"], 0.0)
        self.assertEqual(response.context["health_label"], "Nessun asset")

    def test_badge_in_riparazione_non_critico(self):
        Asset.objects.create(asset_tag="B-R", name="Fresa in officina", status=Asset.STATUS_IN_REPAIR)
        Asset.objects.create(asset_tag="B-S", name="Tornio a magazzino", status=Asset.STATUS_IN_STOCK)
        response = self.client.get(reverse("assets:asset_list"))
        self.assertContains(response, 'data-asset-status="IN_REPAIR">In riparazione</span>')
        self.assertContains(response, 'as-badge as-badge--danger')
        self.assertContains(response, 'data-asset-status="IN_STOCK">In magazzino</span>')
        self.assertNotContains(response, ">Critico<")
        self.assertNotContains(response, ">Inattivo<")

    def test_badge_uguale_su_scheda_e_qr(self):
        asset = Asset.objects.create(asset_tag="B-D", name="Pressa", status=Asset.STATUS_IN_REPAIR)
        expected = '<span class="as-badge as-badge--danger" data-asset-status="IN_REPAIR">In riparazione</span>'
        detail = self.client.get(reverse("assets:asset_view", args=[asset.pk]))
        self.assertContains(detail, expected, html=False)
        landing = self.client.get(reverse("assets:asset_qr_landing", kwargs={"asset_tag": asset.asset_tag}))
        self.assertContains(landing, expected, html=False)


# ---------------------------------------------------------------------------
# A5 — ticket <-> intervento
# ---------------------------------------------------------------------------


class _TicketFixtureMixin:
    def _make_manager(self, username="a5-man-manager"):
        from tickets.models import TicketImpostazioni

        user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x",
                                        first_name="Mario", last_name="Gestore")
        _complete_onboarding(user)
        TicketImpostazioni.objects.update_or_create(tipo="MAN", defaults={"acl_gestione": [username]})
        return user

    def _make_ticket(self, asset, **kwargs):
        from tickets.models import Ticket

        defaults = dict(
            tipo="MAN", titolo="Perdita olio", descrizione="Perdita dal circuito", categoria="MECCANICA",
            priorita="MEDIA", asset=asset, richiedente_nome="Richiedente", richiedente_email="r@example.com",
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketWorkorderLinkTests(_TicketFixtureMixin, TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="T-1", name="CNC T", status=Asset.STATUS_IN_USE)
        self.manager = self._make_manager()
        self.ticket = self._make_ticket(self.asset)

    def _post_json(self, url_name, payload):
        import json

        return self.client.post(reverse(url_name), data=json.dumps(payload), content_type="application/json")

    def test_odl_da_ticket_aperto_ha_origine_ticket_e_prende_in_carico(self):
        from tickets.models import StatoTicket, TicketStatoLog

        self.client.force_login(self.manager)
        response = self._post_json("tickets:api_crea_workorder", {"ticket_id": self.ticket.pk})
        self.assertEqual(response.status_code, 200, response.content[:300])
        wo = WorkOrder.objects.get(ticket=self.ticket)
        self.assertEqual(wo.origin, WorkOrder.ORIGIN_TICKET)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, StatoTicket.IN_CARICO)
        self.assertIsNotNone(self.ticket.data_presa_in_carico)
        log = TicketStatoLog.objects.get(ticket=self.ticket)
        self.assertEqual((log.da_stato, log.a_stato), ("APERTA", "IN_CARICO"))
        self.assertEqual(log.nota, f"Creato intervento #{wo.pk}")

    def test_odl_da_ticket_gia_in_carico_non_cambia_stato(self):
        from tickets.models import TicketStatoLog

        self.ticket.stato = "IN_ATTESA"
        self.ticket.save(update_fields=["stato"])
        self.client.force_login(self.manager)
        self._post_json("tickets:api_crea_workorder", {"ticket_id": self.ticket.pk})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, "IN_ATTESA")
        self.assertFalse(TicketStatoLog.objects.filter(ticket=self.ticket).exists())

    def test_api_stato_fa_quello_che_faceva(self):
        from tickets.models import TicketCommento, TicketStatoLog

        self.client.force_login(self.manager)
        with mock.patch("tickets.views._update_ticket_sharepoint") as sync, self.captureOnCommitCallbacks(execute=True):
            response = self._post_json(
                "tickets:api_stato",
                {"ticket_id": self.ticket.pk, "stato": "in_attesa", "nota": "Attendo ricambio",
                 "data_prevista": "2030-01-15"},
            )
        self.assertEqual(response.json(), {"ok": True, "stato": "IN_ATTESA", "label": "In attesa"})
        self.ticket.refresh_from_db()
        self.assertEqual(str(self.ticket.data_prevista_risoluzione), "2030-01-15")
        self.assertIsNone(self.ticket.closed_at)
        self.assertEqual(sync.call_count, 1)
        log = TicketStatoLog.objects.get(ticket=self.ticket)
        self.assertEqual(log.nota, "Attendo ricambio")
        commento = TicketCommento.objects.get(ticket=self.ticket)
        self.assertTrue(commento.is_interno)
        self.assertEqual(commento.testo, "Stato aggiornato: Aperta → In attesa\nAttendo ricambio")

        with mock.patch("tickets.views._update_ticket_sharepoint"):
            self._post_json("tickets:api_stato", {"ticket_id": self.ticket.pk, "stato": "RISOLTO"})
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.closed_at)
        # Firma come le API ticket (nominativo nel formato del portale).
        self.assertEqual(self.ticket.risolto_da_nome.upper(), "MARIO GESTORE")
        bad = self._post_json("tickets:api_stato", {"ticket_id": self.ticket.pk, "stato": "BOH"})
        self.assertEqual(bad.status_code, 400)

    def test_backfill_origine_idempotente(self):
        manual = WorkOrder.objects.create(asset=self.asset, ticket=self.ticket, title="Vecchio OdL da ticket")
        plain = WorkOrder.objects.create(asset=self.asset, title="OdL manuale")
        periodic = WorkOrder.objects.create(
            asset=self.asset, ticket=self.ticket, title="Periodico", origin=WorkOrder.ORIGIN_PERIODIC
        )
        migration = importlib.import_module("assets.migrations.0134_workorder_origin_ticket_backfill")
        migration.forwards(django_apps, None)
        migration.forwards(django_apps, None)
        manual.refresh_from_db()
        plain.refresh_from_db()
        periodic.refresh_from_db()
        self.assertEqual(manual.origin, WorkOrder.ORIGIN_TICKET)
        self.assertEqual(plain.origin, WorkOrder.ORIGIN_MANUAL)
        self.assertEqual(periodic.origin, WorkOrder.ORIGIN_PERIODIC)


def _close_payload(**overrides):
    payload = {
        "status": WorkOrder.STATUS_DONE,
        "esito": WorkOrder.OUTCOME_RESOLVED,
        "closed_at": timezone.localtime(timezone.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
        "resolution": "Sostituita guarnizione",
        "execution_days": "",
    }
    payload.update(overrides)
    return payload


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class WorkorderCloseTicketTests(_TicketFixtureMixin, TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="C-1", name="CNC C", status=Asset.STATUS_IN_USE)
        self.manager = self._make_manager()
        self.ticket = self._make_ticket(self.asset, stato="IN_CARICO")
        self.wo = WorkOrder.objects.create(
            asset=self.asset, ticket=self.ticket, kind=WorkOrder.KIND_CORRECTIVE,
            origin=WorkOrder.ORIGIN_TICKET, title="Perdita olio",
        )
        self.url = reverse("assets:wo_close", args=[self.wo.pk])

    def test_checkbox_visibile_al_gestore_del_ticket(self):
        self.client.force_login(self.manager)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Segna anche la segnalazione {self.ticket.numero_ticket} come Risolta")

    def test_chiusura_risolta_con_checkbox_risolve_il_ticket(self):
        from tickets.models import TicketStatoLog

        self.client.force_login(self.manager)
        with mock.patch("tickets.views._update_ticket_sharepoint"):
            response = self.client.post(self.url, _close_payload(resolve_ticket="on"))
        self.assertEqual(response.status_code, 302)
        self.wo.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_DONE)
        self.assertEqual(self.ticket.stato, "RISOLTO")
        self.assertIsNotNone(self.ticket.closed_at)
        log = TicketStatoLog.objects.get(ticket=self.ticket)
        self.assertEqual((log.da_stato, log.a_stato), ("IN_CARICO", "RISOLTO"))
        self.assertIn("Risolta", WorkOrderLog.objects.filter(work_order=self.wo).latest("id").note)

    def test_chiusura_risolta_senza_checkbox_lascia_il_ticket(self):
        self.client.force_login(self.manager)
        self.client.post(self.url, _close_payload())
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, "IN_CARICO")

    def test_risolto_temporaneamente_non_tocca_il_ticket(self):
        from tickets.models import TicketStatoLog

        self.client.force_login(self.manager)
        response = self.client.post(
            self.url,
            _close_payload(
                esito=WorkOrder.OUTCOME_RESOLVED_TEMP,
                follow_up_date=(timezone.localdate() + timedelta(days=7)).isoformat(),
                resolve_ticket="on",
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, "IN_CARICO")
        self.assertFalse(TicketStatoLog.objects.filter(ticket=self.ticket).exists())
        note = WorkOrderLog.objects.filter(work_order=self.wo).latest("id").note
        self.assertIn(f"Segnalazione {self.ticket.numero_ticket} invariata", note)

    def test_non_risolto_non_tocca_il_ticket_e_resta_aperto(self):
        self.client.force_login(self.manager)
        self.client.post(self.url, _close_payload(esito=WorkOrder.OUTCOME_NOT_RESOLVED, resolve_ticket="on"))
        self.wo.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_OPEN)
        self.assertEqual(self.wo.outcome, WorkOrder.OUTCOME_NOT_RESOLVED)
        self.assertEqual(self.ticket.stato, "IN_CARICO")

    def test_senza_gestione_ticket_niente_checkbox_e_ticket_invariato(self):
        other = User.objects.create_user(username="a5-solo-assets", password="x", email="solo@example.com")
        _complete_onboarding(other)
        self.client.force_login(other)
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Segna anche la segnalazione")
        self.assertNotContains(page, 'name="resolve_ticket"')
        self.client.post(self.url, _close_payload(resolve_ticket="on"))
        self.wo.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_DONE)
        self.assertEqual(self.ticket.stato, "IN_CARICO")

    def test_fermo_precompilato_dal_ticket(self):
        self.ticket.ore_fermo_macchina = Decimal("1.5")
        self.ticket.save(update_fields=["ore_fermo_macchina"])
        self.client.force_login(self.manager)
        response = self.client.get(self.url)
        form = response.context["form"]
        self.assertEqual(form.initial["downtime_minutes"], 90)
        self.assertEqual(form.initial["downtime_hours"], 1)
        self.assertEqual(form.initial["downtime_remainder"], 30)
        self.assertContains(response, "Precompilato dal fermo indicato nella segnalazione")

    def test_fermo_gia_compilato_sull_odl_prevale(self):
        self.ticket.ore_fermo_macchina = Decimal("3")
        self.ticket.save(update_fields=["ore_fermo_macchina"])
        self.wo.downtime_minutes = 20
        self.wo.save(update_fields=["downtime_minutes"])
        self.client.force_login(self.manager)
        response = self.client.get(self.url)
        self.assertEqual(response.context["form"].initial["downtime_minutes"], 20)


# ---------------------------------------------------------------------------
# A6 — chiusura OdL atomica
# ---------------------------------------------------------------------------


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class WorkorderCloseAtomicTests(_TicketFixtureMixin, _PrivateRootMixin, TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="a6-admin", password="x", email="a6@example.com")
        self.asset = Asset.objects.create(asset_tag="X-1", name="CNC X", status=Asset.STATUS_IN_USE)
        self.ticket = self._make_ticket(self.asset, stato="IN_CARICO")
        self.wo = WorkOrder.objects.create(
            asset=self.asset, ticket=self.ticket, kind=WorkOrder.KIND_CORRECTIVE, title="Guasto mandrino"
        )
        WorkOrderExecutionDay.objects.create(work_order=self.wo, execution_date=timezone.localdate() - timedelta(days=2))

    def _data(self, **overrides):
        values = dict(
            status=WorkOrder.STATUS_DONE,
            esito=WorkOrder.OUTCOME_RESOLVED_TEMP,
            closed_at=timezone.now() - timedelta(minutes=1),
            resolution="Fissato provvisoriamente",
            follow_up_date=timezone.localdate() + timedelta(days=5),
            execution_days=(timezone.localdate(),),
            resolve_ticket=True,
        )
        values.update(overrides)
        return CloseData(**values)

    def test_follow_up_che_fallisce_annulla_tutto(self):
        logs_before = WorkOrderLog.objects.count()
        with mock.patch(
            "assets.services.workorder_close.WorkOrder.objects.create", side_effect=RuntimeError("DB giu'")
        ):
            with self.assertRaises(RuntimeError):
                close_workorder(
                    self.wo.pk,
                    data=self._data(),
                    user=self.admin,
                    request_identity=RequestIdentity(name="Admin", can_manage_ticket=True),
                )
        self.wo.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_OPEN)
        self.assertIsNone(self.wo.closed_at)
        self.assertEqual(self.wo.outcome, "")
        self.assertEqual(
            list(self.wo.execution_days.values_list("execution_date", flat=True)),
            [timezone.localdate() - timedelta(days=2)],
        )
        self.assertEqual(WorkOrderLog.objects.count(), logs_before)
        self.assertEqual(self.ticket.stato, "IN_CARICO")

    def test_allegati_di_chiusura_non_restano_orfani_se_fallisce(self):
        before = self._stored_files()
        upload = _pdf("verbale.pdf")
        with mock.patch(
            "assets.services.workorder_close.WorkOrderLog.objects.create", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                close_workorder(
                    self.wo.pk,
                    data=self._data(esito=WorkOrder.OUTCOME_RESOLVED, follow_up_date=None, uploads=(upload,)),
                    user=self.admin,
                    request_identity=RequestIdentity(),
                )
        self.assertFalse(self.wo.attachments.exists())
        self.assertEqual(self._stored_files() - before, set())

    def test_doppia_chiusura_la_seconda_e_rifiutata(self):
        data = self._data(esito=WorkOrder.OUTCOME_RESOLVED, follow_up_date=None, resolve_ticket=False)
        close_workorder(self.wo.pk, data=data, user=self.admin, request_identity=RequestIdentity())
        logs = WorkOrderLog.objects.filter(work_order=self.wo).count()
        with self.assertRaises(WorkOrderAlreadyClosed):
            close_workorder(self.wo.pk, data=data, user=self.admin, request_identity=RequestIdentity())
        self.assertEqual(WorkOrderLog.objects.filter(work_order=self.wo).count(), logs)

    def test_doppio_invio_dalla_vista(self):
        self.client.force_login(self.admin)
        url = reverse("assets:wo_close", args=[self.wo.pk])
        first = self.client.post(url, _close_payload())
        self.assertEqual(first.status_code, 302)
        # Il secondo invio parte dalla stessa pagina gia' aperta: il service lo ferma.
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_DONE)
        second = self.client.post(url, _close_payload(), follow=True)
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "risulta gia")
        self.assertEqual(WorkOrderLog.objects.filter(work_order=self.wo, note__startswith="Intervento chiuso").count(), 1)

    def test_close_rifiuta_lo_stato_open(self):
        with self.assertRaises(ValueError):
            self.wo.close(status=WorkOrder.STATUS_OPEN)
        self.wo.record_outcome_keep_open(resolution="Non risolto", downtime=15)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_OPEN)
        self.assertIsNone(self.wo.closed_at)
        self.assertEqual(self.wo.downtime_minutes, 15)

    def _stored_files(self):
        import os

        return {os.path.join(root, name) for root, _, files in os.walk(self._tmp_root) for name in files}

    def test_occorrenza_con_completamento_fallito_non_lascia_allegati(self):
        before = self._stored_files()
        plan = MaintenanceInterventionTemplate.objects.create(code="a6-plan", label="Controllo A6")
        occurrence = MaintenanceOccurrence.objects.create(
            plan=plan, asset=self.asset, due_date=timezone.localdate(), warning_days=10
        )
        self.client.force_login(self.admin)
        with mock.patch(
            "assets.views_maintenance.domain.complete_occurrence",
            side_effect=domain.OccurrenceCompletionError("rifiutata"),
        ):
            response = self.client.post(
                reverse("assets:occurrence_complete", args=[occurrence.pk]),
                {"completed_on": timezone.localdate().isoformat(), "attachment": _pdf()},
            )
        self.assertIn(response.status_code, (200, 302))
        self.assertFalse(MaintenanceOccurrenceAttachment.objects.filter(occurrence=occurrence).exists())
        self.assertEqual(self._stored_files() - before, set())
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, MaintenanceOccurrence.STATUS_OPEN)

    def test_occorrenza_completata_con_allegato(self):
        plan = MaintenanceInterventionTemplate.objects.create(
            code="a6-plan-ok", label="Controllo A6 ok", attachment_required=True
        )
        occurrence = MaintenanceOccurrence.objects.create(
            plan=plan, asset=self.asset, due_date=timezone.localdate(), warning_days=10
        )
        self.client.force_login(self.admin)
        self.client.post(
            reverse("assets:occurrence_complete", args=[occurrence.pk]),
            {"completed_on": timezone.localdate().isoformat(), "attachment": _pdf()},
        )
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, MaintenanceOccurrence.STATUS_DONE)
        self.assertEqual(occurrence.attachments.count(), 1)
