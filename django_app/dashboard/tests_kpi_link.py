"""Riquadri numerici della scheda dipendente: ogni numero apre l'elenco che conta le stesse righe."""
from __future__ import annotations

from datetime import timedelta

from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from dashboard import views as dashboard_views
from tasks.models import Task, TaskStatus
from tasks.tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions


class SchedaDipendenteKpiLinkTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="eb-kpi", legacy_user_id=761, role_id=2, role_name="tasks")
        self.altro = _create_user_with_legacy(username="eb-altro", legacy_user_id=762, role_id=2, role_name="tasks")
        oggi = timezone.localdate()
        Task.objects.create(title="Mia scaduta", created_by=self.altro, assigned_to=self.user,
                            status=TaskStatus.TODO, due_date=oggi - timedelta(days=1))
        Task.objects.create(title="Mia in corso", created_by=self.altro, assigned_to=self.user,
                            status=TaskStatus.IN_PROGRESS)
        Task.objects.create(title="Mia chiusa", created_by=self.altro, assigned_to=self.user, status=TaskStatus.DONE)
        # Creata da me ma assegnata ad altri: «le mie» la mostrerebbe, il riquadro no.
        Task.objects.create(title="Creata da me", created_by=self.user, assigned_to=self.altro, status=TaskStatus.TODO)
        self.client.force_login(self.user)

    def test_riquadri_attivita_e_elenco_contano_lo_stesso(self):
        dati = dashboard_views._board_data_tasks(761, {"max_items": 5})
        self.assertEqual(dati["user_id"], self.user.pk)
        html = render_to_string("dashboard/partials/widget_body.html",
                                {"w": {"id": "tasks_stats"}, "widget_data": {"tasks_stats": dati}})
        base = f"{reverse('tasks:list')}?mine=0&assigned_to={self.user.pk}"
        for filtro, chiave in (("&status=TODO", "todo"), ("&status=IN_PROGRESS", "in_progress"),
                               ("&status=DONE", "done"), ("&overdue=on", "overdue")):
            self.assertIn(f'href="{(base + filtro).replace("&", "&amp;")}"', html)
            elenco = self.client.get(base + filtro)
            self.assertEqual(elenco.status_code, 200)
            self.assertEqual(len(elenco.context["tasks"]), dati["stats"][chiave], filtro)

    def test_panoramica_task_aperti_apre_le_assegnate_aperte(self):
        dati = dashboard_views._board_data_module_overview(self.user, None, 761, {})
        card = next(c for c in dati["cards"] if c["label"] == "Task aperti")
        elenco = self.client.get(card["url"])
        self.assertEqual(len(elenco.context["tasks"]), card["value"])
        self.assertEqual(card["value"], 2)

    def test_riquadri_letture_portano_ai_filtri_di_le_mie_letture(self):
        html = render_to_string("dashboard/partials/widget_body.html", {
            "w": {"id": "procedure_da_leggere"},
            "widget_data": {"procedure_da_leggere": {"items": [], "stats": {"pending": 2, "overdue": 1, "confirmed": 3}}},
        })
        u = reverse("procedure_refresh:my_assignments")
        for stato in ("pending", "overdue", "read_confirmed"):
            self.assertIn(f'href="{u}?status={stato}"', html)


# ── Tessere della home e della hub preview ──────────────────────────────────────

from datetime import date, datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import RequestFactory, TestCase, override_settings  # noqa: E402

from core.models import SiteConfig, UserOnboarding  # noqa: E402
from dashboard import views_home_portale as home  # noqa: E402


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class HomeTileKpiLinkTests(TestCase):
    """Ogni numero della home con un link: l'elenco di destinazione conta lo stesso numero."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="home-kpi", email="home-kpi@example.com", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True, completed_at=timezone.now())
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()

    def _tile(self) -> dict:
        request = RequestFactory().get("/")
        request.user = self.admin
        request.legacy_user = None
        return home._tile_kpi_counts(None, True, request_user=self.admin, request=request)

    def _apri(self, url: str):
        risposta = self.client.get(url)
        self.assertEqual(risposta.status_code, 200, url)
        return risposta

    def test_ticket_attivi_come_elenco_ticket(self):
        from tickets.models import PrioritaTicket, StatoTicket, Ticket, TipoTicket

        base = {"tipo": TipoTicket.IT, "priorita": PrioritaTicket.MEDIA, "richiedente_nome": "Persona Prova",
                "richiedente_email": "persona.prova@example.com"}
        for stato in (StatoTicket.APERTA, StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA,
                      StatoTicket.CHIUSO):
            Ticket.objects.create(titolo=f"Ticket {stato}", stato=stato, **base)
        kpi = self._tile()["ticket"][0]
        self.assertEqual(kpi["value"], 3)
        self.assertEqual(kpi["url"], f"{reverse('tickets:elenco')}?attivi=1")
        self.assertEqual(self._apri(kpi["url"]).context["tickets"].count(), kpi["value"])

    def test_incidenti_in_analisi_e_anno_come_elenco(self):
        from rilevazione_incidenti.models import RilevazioneIncidente, TipoEventoSicurezza
        from rilevazione_incidenti.services import get_safety_kpis

        tz_loc = timezone.get_current_timezone()
        quest_anno = timezone.make_aware(datetime(self.oggi.year, 1, 1, 0, 30), tz_loc)
        anno_scorso = timezone.make_aware(datetime(self.oggi.year - 1, 12, 31, 23, 30), tz_loc)
        for nome, quando, chiusa in (("Persona Uno", quest_anno, False), ("Persona Due", quest_anno, True),
                                     ("Persona Tre", anno_scorso, False), ("Persona Quattro", anno_scorso, True)):
            RilevazioneIncidente.objects.create(
                nominativo=nome, tipologia_scheda="Near Miss", tipo_evento=TipoEventoSicurezza.NEAR_MISS,
                reparto="CNC", data_segnalazione=quando, chiusura_rspp=chiusa)
        in_analisi, anno = self._tile()["incidenti"]
        self.assertEqual((in_analisi["value"], anno["value"]), (2, 2))
        lista = reverse("rilevazione_incidenti:lista")
        self.assertEqual(in_analisi["url"], f"{lista}?stato=IN_ANALISI#sic-elenco")
        self.assertEqual(anno["url"], f"{lista}?anno={self.oggi.year}#sic-elenco")
        self.assertEqual(len(self._apri(in_analisi["url"]).context["items"]), in_analisi["value"])
        self.assertEqual(len(self._apri(anno["url"]).context["items"]), anno["value"])
        # KPI sicurezza della hub preview: near miss dell'anno = elenco con tipo evento + anno.
        near = self._apri(f"{lista}?tipo_evento=near_miss&anno={self.oggi.year}")
        self.assertEqual(len(near.context["items"]), get_safety_kpis()["near_miss"])
        # Anno non valido: ignorato.
        self.assertEqual(len(self._apri(f"{lista}?anno=abcd").context["items"]), 4)

    def test_incidenti_senza_link_con_elenco_sharepoint(self):
        from rilevazione_incidenti.models import SicurezzaImpostazioni

        cfg, _ = SicurezzaImpostazioni.objects.get_or_create(pk=1)
        cfg.sharepoint_site_id, cfg.sharepoint_list_id = "sito-finto", "lista-finta"
        cfg.save()
        for kpi in self._tile()["incidenti"]:
            self.assertNotIn("url", kpi)

    def test_asset_per_stato_come_inventario(self):
        from assets.models import Asset

        for tag, stato in (("HK-1", Asset.STATUS_IN_USE), ("HK-2", Asset.STATUS_IN_USE),
                           ("HK-3", Asset.STATUS_IN_REPAIR), ("HK-4", Asset.STATUS_RETIRED)):
            Asset.objects.create(asset_tag=tag, name=f"Bene {tag}", status=stato)
        in_uso, in_riparazione = self._tile()["asset"]
        self.assertEqual((in_uso["value"], in_riparazione["value"]), (2, 1))
        for kpi in (in_uso, in_riparazione):
            self.assertEqual(self._apri(kpi["url"]).context["visible_count"], kpi["value"])

    def test_numeri_personali_senza_elenco_restano_senza_link(self):
        from assets.models import Asset

        Asset.objects.create(asset_tag="HK-9", name="Bene mio", status=Asset.STATUS_IN_USE, assigned_legacy_user_id=77)
        utente = get_user_model().objects.create_user(username="home-kpi-op", password="x")
        tile = home._tile_kpi_counts(SimpleNamespace(id=77, ruolo="", nome="", email=""), False, request_user=utente)
        self.assertEqual(tile["asset"][0]["value"], 1)
        for kpi in tile["asset"]:
            self.assertNotIn("url", kpi)
        # Anche i ticket di chi non vede tutta l'azienda restano senza link.
        self.assertNotIn("url", tile["ticket"][0])

    def test_procedure_in_attesa_e_scadute_come_report(self):
        from procedure_refresh.models import (
            AssignmentStatus,
            CampaignStatus,
            ProcedureAssignment,
            ProcedureCampaign,
            ProcedureCampaignDocument,
            ProcedureDocument,
            ProcedureRevision,
            SourceType,
        )

        doc = ProcedureDocument.objects.create(code="MT-HK-1", title="Doc", document_type="MT", is_active=True)
        rev = ProcedureRevision.objects.create(
            document=doc, revision_code="Rev.01", revision_date=date(2026, 1, 1), effective_date=date(2026, 1, 2),
            source_type=SourceType.SHAREPOINT, source_url="https://example.invalid/doc.pdf", file_name="d.pdf",
            is_current=True, published_by=self.admin)
        camp = ProcedureCampaign.objects.create(
            name="Sessione home", status=CampaignStatus.PUBLISHED, start_date=self.oggi - timedelta(days=30),
            due_date=self.oggi + timedelta(days=30), created_by=self.admin)
        ProcedureCampaignDocument.objects.create(campaign=camp, revision=rev)
        ProcedureCampaign.objects.create(name="Bozza home", status=CampaignStatus.DRAFT, start_date=self.oggi,
                                         due_date=self.oggi, created_by=self.admin)
        stati = (
            (AssignmentStatus.READ_CONFIRMED, 5), (AssignmentStatus.ASSIGNED, 3), (AssignmentStatus.OPENED, 4),
            (AssignmentStatus.ASSIGNED, -1), (AssignmentStatus.OVERDUE, -9), (AssignmentStatus.CANCELLED, 5),
        )
        for i, (stato, giorni) in enumerate(stati):
            utente = get_user_model().objects.create_user(username=f"home-kpi-u{i}", password="x")
            ProcedureAssignment.objects.create(campaign=camp, revision=rev, user=utente, assigned_by=self.admin,
                                               due_date=self.oggi + timedelta(days=giorni), status=stato)
        in_attesa, scadute, campagne = self._tile()["procedure"]
        self.assertEqual((in_attesa["value"], scadute["value"], campagne["value"]), (2, 2, 1))
        for kpi in (in_attesa, scadute):
            self.assertEqual(len(self._apri(kpi["url"]).context["assignments"]), kpi["value"])
        self.assertEqual(self._apri(campagne["url"]).context["campaigns"].count(), campagne["value"])

    def test_diario_ultimi_giorni_come_registro(self):
        from diario_preposto.models import SegnalazionePreposto

        adesso = timezone.now()
        for giorni in (0, 3, 7, 12, 45):
            SegnalazionePreposto.objects.create(
                titolo=f"Fatto {giorni}", data_segnalazione=adesso - timedelta(days=giorni), descrizione="x",
                preposto="Preposto Prova", chi_segnala="Preposto Prova", creato_da=self.admin)
        sette, trenta, oggi = self._tile()["diario"]
        # Sette giorni compreso oggi: la segnalazione di 7 giorni fa è fuori (prima era dentro).
        self.assertEqual((sette["value"], trenta["value"], oggi["value"]), (2, 4, 1))
        self.assertNotIn("url", oggi)
        for kpi in (sette, trenta):
            self.assertEqual(self._apri(kpi["url"]).context["totale"], kpi["value"])

    def test_fornitori_attivi_come_elenco(self):
        from anagrafica.models import Fornitore

        Fornitore.objects.create(ragione_sociale="Fornitore Uno Srl", is_active=True)
        Fornitore.objects.create(ragione_sociale="Fornitore Due Srl", is_active=False)
        kpi = self._tile()["fornitori"][0]
        self.assertEqual(kpi["value"], 1)
        self.assertEqual(kpi["url"], f"{reverse('fornitori:fornitori_list')}?attivi=1")


class HomeTaskScadutiLinkTests(TasksBaseTestCase):
    """«In corso» e «scaduti» della tessera Task: stessi insiemi dei filtri dell'elenco attività."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="home-task", legacy_user_id=771, role_id=2, role_name="tasks")
        altro = _create_user_with_legacy(username="home-task-altro", legacy_user_id=772, role_id=2, role_name="tasks")
        oggi = timezone.localdate()
        Task.objects.create(title="Scaduta", created_by=altro, assigned_to=self.user, status=TaskStatus.TODO,
                            due_date=oggi - timedelta(days=1))
        Task.objects.create(title="In corso", created_by=altro, assigned_to=self.user, status=TaskStatus.IN_PROGRESS)
        Task.objects.create(title="Chiusa scaduta", created_by=altro, assigned_to=self.user, status=TaskStatus.DONE,
                            due_date=oggi - timedelta(days=3))
        Task.objects.create(title="Di un altro", created_by=self.user, assigned_to=altro, status=TaskStatus.TODO,
                            due_date=oggi - timedelta(days=1))
        self.client.force_login(self.user)

    def test_in_corso_e_scaduti_come_elenco(self):
        tile = home._tile_kpi_counts(SimpleNamespace(id=771, ruolo="", nome="", email=""), False,
                                     request_user=self.user)
        in_corso, scaduti = tile["task"]
        self.assertEqual((in_corso["value"], scaduti["value"]), (2, 1))
        for kpi in (in_corso, scaduti):
            elenco = self.client.get(kpi["url"])
            self.assertEqual(elenco.status_code, 200)
            self.assertEqual(len(elenco.context["tasks"]), kpi["value"], kpi["unit"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class HubPreviewKpiLinkTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="hub-kpi", email="hub-kpi@example.com", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True, completed_at=timezone.now())
        self.request = RequestFactory().get("/hub-preview/")
        self.request.user = self.admin
        self.request.legacy_user = None
        self.tile = {
            "ticket": [{"value": 4, "unit": "attivi", "tone": "warning", "url": "/tickets/elenco/?attivi=1"}],
            "asset": [{"value": 2, "unit": "assegnati", "tone": "info"}],
        }

    def _cards(self):
        with (
            patch("dashboard.views_home_portale._tile_kpi_counts", return_value=self.tile),
            patch("dashboard.views_home_portale.moduli_visibili", return_value={"ticket", "asset"}),
        ):
            return {c["kpi_key"]: c for c in dashboard_views._hub_kpi_cards({}, self.request)}

    def test_card_porta_il_link_della_tessera_della_home(self):
        cards = self._cards()
        self.assertEqual(cards["ticket"]["url"], "/tickets/elenco/?attivi=1")
        self.assertIsNone(cards["asset"]["url"])
        # Somma di due registri: nessun elenco la riproduce, resta senza link.
        self.assertNotIn("url", cards["scadenze"])

    def test_personalizzazioni_siteconfig_applicate(self):
        """I campi sono chiave/valore: con key/value l'errore era inghiottito e niente veniva applicato."""
        SiteConfig.objects.create(chiave="hub_kpi_ticket_label", valore="Richieste IT")
        SiteConfig.objects.create(chiave="hub_kpi_ticket_bg_color", valore="#123456")
        SiteConfig.objects.create(chiave="hub_kpi_asset_disabled", valore="1")
        cards = self._cards()
        self.assertEqual(cards["ticket"]["label"], "Richieste IT")
        self.assertEqual(cards["ticket"]["custom_bg"], "#123456")
        self.assertNotIn("asset", cards)

    def test_procedure_da_confermare_come_le_mie_letture(self):
        from procedure_refresh.models import (
            AssignmentStatus,
            CampaignStatus,
            ProcedureAssignment,
            ProcedureCampaign,
            ProcedureCampaignDocument,
            ProcedureDocument,
            ProcedureRevision,
            SourceType,
        )

        oggi = timezone.localdate()
        camp = ProcedureCampaign.objects.create(
            name="Sessione hub", status=CampaignStatus.PUBLISHED, start_date=oggi - timedelta(days=30),
            due_date=oggi + timedelta(days=30), created_by=self.admin)
        for i, stato in enumerate((AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED, AssignmentStatus.OVERDUE,
                                   AssignmentStatus.READ_CONFIRMED)):
            doc = ProcedureDocument.objects.create(code=f"MT-HUB-{i}", title="Doc", document_type="MT", is_active=True)
            rev = ProcedureRevision.objects.create(
                document=doc, revision_code="Rev.01", revision_date=date(2026, 1, 1),
                effective_date=date(2026, 1, 2), source_type=SourceType.SHAREPOINT,
                source_url="https://example.invalid/doc.pdf", file_name="d.pdf", is_current=True,
                published_by=self.admin)
            ProcedureCampaignDocument.objects.create(campaign=camp, revision=rev)
            ProcedureAssignment.objects.create(campaign=camp, revision=rev, user=self.admin, assigned_by=self.admin,
                                               due_date=oggi + timedelta(days=5), status=stato)
        card = self._cards()["procedure"]
        self.assertEqual(card["value"], 3)
        self.client.force_login(self.admin)
        risposta = self.client.get(card["url"])
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.context["pr_stats"]["filtered"], card["value"])

    def test_pagina_branding_stato_reale_e_link(self):
        SiteConfig.objects.create(chiave="hub_hero_title", valore="Titolo di prova")
        self.client.force_login(self.admin)
        with patch("monitoring.views.failed_today_job_ids", return_value={1, 2}):
            risposta = self.client.get(reverse("dashboard_hub_preview"))
        self.assertEqual(risposta.status_code, 200)
        html = risposta.content.decode()
        self.assertIn("Titolo di prova", html)
        stato = {v["label"]: v for v in risposta.context["hub_status_items"]}
        self.assertEqual(stato["Job falliti oggi"]["value"], "2")
        self.assertFalse(stato["Job falliti oggi"]["ok"])
        self.assertIn("failed_today=1", stato["Job falliti oggi"]["url"])
        # Niente più valori fissi né link a «#» nella striscia e nei pannelli laterali.
        for fisso in ("Sincronizzazioni", ">Operativo<", ">Disponibile<"):
            self.assertNotIn(fisso, html)
        self.assertNotIn('<a href="#" class="hd-side-link"', html)
        self.assertNotIn('<a href="#" class="hd-approve-link"', html)
        u = reverse("assenze_gestione")
        self.assertIn(f'href="{u}?stato=all#mie-richieste" class="hd-side-link"', html)

    def test_striscia_di_stato_solo_per_gli_admin(self):
        self.assertEqual(dashboard_views._hub_status_items(False), [])
