"""Flusso incontro KICK-OFF in due tempi: convocazione → esito.

Copre la separazione fra `project_meeting_edit` (prima dell'incontro) e
`project_meeting_minutes` (dopo), e le azioni documentali esposte dal dettaglio
incontro: invio convocazione, invio minuta, download PDF.
"""
from __future__ import annotations

from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from tasks.models import (
    KickoffMeeting,
    MeetingIssue,
    MeetingIssueStatus,
    MeetingStatus,
    Project,
)
from tasks.tests import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingTwoStepFlowTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="meeting-flow",
            legacy_user_id=311,
            role_id=2,
            role_name="tasks",
        )
        self.user.email = "pm@example.com"
        self.user.save(update_fields=["email"])
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user
        )
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            titolo="Avvio commessa",
            luogo="Sala A",
            partecipanti_email_extra="mario@example.com",
            agenda_items=[
                {"id": "a1", "titolo": "Stato avanzamento", "nota": "", "done": False},
            ],
            created_by=self.user,
        )
        self.client.force_login(self.user)

    # ── separazione dei due form ────────────────────────────────────────
    def test_convocazione_non_chiede_il_verbale(self):
        response = self.client.get(
            reverse("tasks:project_meeting_edit", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn('name="note"', body)
        self.assertNotIn('name="next_steps"', body)
        self.assertIn('name="data"', body)
        self.assertIn('name="stato"', body)

    def test_esito_chiede_solo_il_dopo_incontro(self):
        response = self.client.get(
            reverse("tasks:project_meeting_minutes", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('name="note"', body)
        self.assertIn('name="next_steps"', body)
        self.assertNotIn('name="data"', body)

    def test_salvare_la_convocazione_non_declassa_un_incontro_svolto(self):
        self.meeting.stato = MeetingStatus.SVOLTO
        self.meeting.save(update_fields=["stato"])
        response = self.client.post(
            reverse("tasks:project_meeting_edit", args=[self.project.id, self.meeting.id]),
            {
                "titolo": "Avvio commessa",
                "data": "2026-09-10",
                "ora": "",
                "luogo": "Sala B",
                "stato": MeetingStatus.SVOLTO,
                "agenda_items_raw": "[]",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.stato, MeetingStatus.SVOLTO)
        self.assertEqual(self.meeting.luogo, "Sala B")

    def test_esito_puo_essere_aggiornato_senza_riscrivere_svolto_at(self):
        url = reverse("tasks:project_meeting_minutes", args=[self.project.id, self.meeting.id])
        self.client.post(url, {"note": "primo giro", "problemi_aperti": "", "next_steps": ""})
        self.meeting.refresh_from_db()
        first_timestamp = self.meeting.svolto_at
        self.assertIsNotNone(first_timestamp)

        self.client.post(url, {"note": "secondo giro", "problemi_aperti": "", "next_steps": ""})
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.note, "secondo giro")
        self.assertEqual(self.meeting.svolto_at, first_timestamp)

    # ── azioni documentali ──────────────────────────────────────────────
    def test_invio_convocazione_raggiunge_i_partecipanti(self):
        response = self.client.post(
            reverse("tasks:project_meeting_send_invite", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("mario@example.com", mail.outbox[0].to)
        self.assertIn("Convocazione", mail.outbox[0].subject)

    def test_invio_minuta_raggiunge_i_partecipanti(self):
        self.meeting.note = "Verbale del giorno"
        self.meeting.stato = MeetingStatus.SVOLTO
        self.meeting.save(update_fields=["note", "stato"])
        response = self.client.post(
            reverse("tasks:project_meeting_send_minute", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Minuta", mail.outbox[0].subject)

    def test_invio_senza_destinatari_non_manda_nulla(self):
        self.meeting.partecipanti_email_extra = ""
        self.meeting.save(update_fields=["partecipanti_email_extra"])
        response = self.client.post(
            reverse("tasks:project_meeting_send_minute", args=[self.project.id, self.meeting.id]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(response, "non ha partecipanti")

    def test_minuta_pdf_scaricabile(self):
        response = self.client.get(
            reverse("tasks:project_meeting_minute_pdf", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    # ── pulizia calendario ──────────────────────────────────────────────
    def test_eliminare_l_incontro_rimuove_l_evento_outlook(self):
        self.meeting.sync_outlook = True
        self.meeting.outlook_event_id = "AAA-EVENT-ID"
        self.meeting.save(update_fields=["sync_outlook", "outlook_event_id"])

        with patch("tasks.meeting_outlook.sync_meeting_outlook_event", return_value=("info", "ok")) as sync:
            response = self.client.post(
                reverse("tasks:project_meeting_delete", args=[self.project.id, self.meeting.id])
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(KickoffMeeting.objects.filter(pk=self.meeting.pk).exists())
        sync.assert_called_once()
        # La cancellazione su Graph avviene proprio perche' sync_outlook e' falso.
        self.assertFalse(sync.call_args.kwargs["meeting"].sync_outlook)


class MinuteContentTests(TasksBaseTestCase):
    """La minuta deve contenere l'agenda strutturata e i problemi tracciati."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="minute-content",
            legacy_user_id=312,
            role_id=2,
            role_name="tasks",
        )
        self.project = Project.objects.create(name="", created_by=self.user)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            partecipanti_email_extra="mario@example.com",
            agenda_items=[
                {"id": "a1", "titolo": "Collaudo linea 3", "nota": "con il cliente", "done": True},
            ],
            created_by=self.user,
        )
        MeetingIssue.objects.create(
            project=self.project,
            source_meeting=self.meeting,
            title="Ritardo fornitore stampi",
            status=MeetingIssueStatus.OPEN,
            created_by=self.user,
        )

    def test_minuta_contiene_agenda_strutturata_e_problemi(self):
        from tasks.minute_email import build_minute_email

        _, body_text, body_html = build_minute_email(self.meeting)
        self.assertIn("Collaudo linea 3", body_html)
        self.assertIn("Ritardo fornitore stampi", body_html)
        self.assertIn("Collaudo linea 3", body_text)

    def test_convocazione_contiene_agenda_ma_non_i_problemi(self):
        from tasks.minute_email import build_invite_email

        _, _, body_html = build_invite_email(self.meeting)
        self.assertIn("Collaudo linea 3", body_html)
        self.assertNotIn("Ritardo fornitore stampi", body_html)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FirstMeetingOnKickoffCreateTests(TasksBaseTestCase):
    """Creare un kickoff crea anche il suo incontro 1 e ci porta sopra."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="kickoff-first",
            legacy_user_id=313,
            role_id=2,
            role_name="tasks",
        )
        self.client.force_login(self.user)

    def _create_kickoff(self, part_number: str, **extra):
        payload = {
            "client_name": "Cliente",
            "part_number": part_number,
            "revisione": "A",
            "versione": "1.0",
            "description": "",
            "control_method": "",
            "vrf_quote_number": "",
            "vrf_description": "",
            "vrf_esp": "",
            "project_manager": self.user.id,
        }
        payload.update(extra)
        return self.client.post(reverse("tasks:project_create"), payload)

    def test_kickoff_nasce_con_il_suo_primo_incontro(self):
        response = self._create_kickoff("PN-FIRST-001")
        project = Project.objects.get(part_number="PN-FIRST-001")
        meeting = project.meetings.get()

        self.assertEqual(meeting.numero, 1)
        self.assertEqual(meeting.stato, MeetingStatus.PIANIFICATO)
        self.assertRedirects(
            response, reverse("tasks:project_meeting_edit", args=[project.id, meeting.id])
        )

    def test_la_convocazione_di_arrivo_e_compilabile(self):
        self._create_kickoff("PN-FIRST-002")
        project = Project.objects.get(part_number="PN-FIRST-002")
        meeting = project.meetings.get()

        page = self.client.get(
            reverse("tasks:project_meeting_edit", args=[project.id, meeting.id])
        )
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('name="data"', body)
        self.assertIn('name="luogo"', body)

    def test_helper_idempotente_non_crea_un_secondo_incontro(self):
        from tasks.views import _create_first_meeting

        project = Project.objects.create(name="", created_by=self.user)
        first = _create_first_meeting(project, self.user)
        second = _create_first_meeting(project, self.user)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(project.meetings.count(), 1)

    def test_incontro_senza_team_resta_senza_partecipanti(self):
        from tasks.views import _create_first_meeting

        project = Project.objects.create(name="", created_by=self.user)
        meeting = _create_first_meeting(project, self.user)

        self.assertEqual(meeting.partecipanti_utenti.count(), 0)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NewMeetingDefaultParticipantsTests(TasksBaseTestCase):
    """Il form "Nuovo incontro" preseleziona PM/capocommessa/programmatore della commessa."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="pm-default", legacy_user_id=401, role_id=2, role_name="tasks")
        self.capo = _create_user_with_legacy(username="capo-default", legacy_user_id=402, role_id=2, role_name="tasks")
        self.prog = _create_user_with_legacy(username="prog-default", legacy_user_id=403, role_id=2, role_name="tasks")
        self.project = Project.objects.create(
            name="", created_by=self.pm,
            project_manager=self.pm, capo_commessa=self.capo, programmer=self.prog,
        )
        self.client.force_login(self.pm)

    def test_nuovo_incontro_preseleziona_i_tre_ruoli(self):
        response = self.client.get(reverse("tasks:project_meeting_create", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        preselected = set(response.context["form"].initial.get("partecipanti_utenti") or [])
        self.assertEqual(preselected, {self.pm.id, self.capo.id, self.prog.id})

    def test_ruoli_non_assegnati_non_rompono_il_default(self):
        project = Project.objects.create(name="", created_by=self.pm, project_manager=self.pm)
        response = self.client.get(reverse("tasks:project_meeting_create", args=[project.id]))
        self.assertEqual(response.status_code, 200)
        preselected = set(response.context["form"].initial.get("partecipanti_utenti") or [])
        self.assertEqual(preselected, {self.pm.id})


class AgendaItemResponsabileDurataTests(TasksBaseTestCase):
    """I punti agenda possono portare un responsabile e una durata stimata (opzionali)."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        self.convocato = _create_user_with_legacy(
            username="agenda-resp",
            legacy_user_id=312,
            role_id=2,
            role_name="tasks",
        )

    def test_clean_agenda_items_raw_preserva_responsabile_e_durata(self):
        import json

        from tasks.forms import KickoffMeetingForm

        form = KickoffMeetingForm(data={
            "data": "2026-09-10",
            "stato": MeetingStatus.PIANIFICATO,
            "partecipanti_utenti": [self.convocato.pk],
            "agenda_items_raw": json.dumps([{
                "id": "a1",
                "titolo": "Punto 1",
                "responsabile_id": self.convocato.pk,
                "responsabile_label": "Mario Rossi",
                "durata_minuti": 15,
            }]),
        })
        self.assertTrue(form.is_valid(), form.errors)
        item = form.cleaned_data["agenda_items_raw"][0]
        self.assertEqual(item["responsabile_id"], self.convocato.pk)
        self.assertEqual(item["responsabile_label"], "Mario Rossi")
        self.assertEqual(item["durata_minuti"], 15)

    def test_responsabile_non_convocato_viene_azzerato(self):
        """Il responsabile di un punto deve essere fra i partecipanti convocati."""
        import json

        from tasks.forms import KickoffMeetingForm

        estraneo = _create_user_with_legacy(
            username="agenda-estraneo",
            legacy_user_id=313,
            role_id=2,
            role_name="tasks",
        )
        form = KickoffMeetingForm(data={
            "data": "2026-09-10",
            "stato": MeetingStatus.PIANIFICATO,
            "partecipanti_utenti": [self.convocato.pk],
            "agenda_items_raw": json.dumps([{
                "id": "a1",
                "titolo": "Punto 1",
                "responsabile_id": estraneo.pk,
                "responsabile_label": "Estraneo",
            }]),
        })
        self.assertTrue(form.is_valid(), form.errors)
        item = form.cleaned_data["agenda_items_raw"][0]
        self.assertIsNone(item["responsabile_id"])
        self.assertEqual(item["responsabile_label"], "")

    def test_durata_fuori_range_viene_scartata(self):
        import json

        from tasks.forms import KickoffMeetingForm

        form = KickoffMeetingForm(data={
            "data": "2026-09-10",
            "stato": MeetingStatus.PIANIFICATO,
            "agenda_items_raw": json.dumps([{"id": "a1", "titolo": "Punto 1", "durata_minuti": 9999}]),
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["agenda_items_raw"][0]["durata_minuti"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingsDigestJobTests(TasksBaseTestCase):
    """Job periodico unico: "domani hai un incontro" + (il lunedi) problemi scaduti."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="reminder-user", legacy_user_id=411, role_id=2, role_name="tasks"
        )
        self.user.email = "reminder@example.com"
        self.user.save(update_fields=["email"])
        self.project = Project.objects.create(name="", created_by=self.user, project_manager=self.user)

    def test_promemoria_solo_per_incontri_di_domani_non_ancora_avvisati(self):
        from datetime import timedelta

        from django.utils import timezone

        from tasks.tasks import run_meetings_digest

        tomorrow = timezone.localdate() + timedelta(days=1)
        meeting_tomorrow = KickoffMeeting.objects.create(project=self.project, data=tomorrow, created_by=self.user)
        meeting_tomorrow.partecipanti_utenti.add(self.user)
        meeting_later = KickoffMeeting.objects.create(
            project=self.project, data=tomorrow + timedelta(days=5), created_by=self.user
        )

        run_meetings_digest()

        meeting_tomorrow.refresh_from_db()
        meeting_later.refresh_from_db()
        self.assertIsNotNone(meeting_tomorrow.reminder_sent_at)
        self.assertIsNone(meeting_later.reminder_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.email, mail.outbox[0].to)

    def test_promemoria_e_idempotente(self):
        from datetime import timedelta

        from django.utils import timezone

        from tasks.tasks import run_meetings_digest

        tomorrow = timezone.localdate() + timedelta(days=1)
        meeting = KickoffMeeting.objects.create(project=self.project, data=tomorrow, created_by=self.user)
        meeting.partecipanti_utenti.add(self.user)

        run_meetings_digest()
        run_meetings_digest()

        self.assertEqual(len(mail.outbox), 1)

    def test_incontro_annullato_non_riceve_promemoria(self):
        from datetime import timedelta

        from django.utils import timezone

        from tasks.tasks import run_meetings_digest

        tomorrow = timezone.localdate() + timedelta(days=1)
        meeting = KickoffMeeting.objects.create(
            project=self.project, data=tomorrow, created_by=self.user, stato=MeetingStatus.ANNULLATO
        )
        meeting.partecipanti_utenti.add(self.user)

        run_meetings_digest()

        meeting.refresh_from_db()
        self.assertIsNone(meeting.reminder_sent_at)

    def test_incontro_e_problema_scaduto_lo_stesso_lunedi_fanno_una_sola_email(self):
        from datetime import date, timedelta
        from unittest.mock import patch

        from tasks.models import MeetingIssue, MeetingIssueStatus
        from tasks.tasks import run_meetings_digest

        monday = date(2026, 9, 7)  # lunedi
        tomorrow = monday + timedelta(days=1)
        with patch("django.utils.timezone.localdate", return_value=monday):
            meeting = KickoffMeeting.objects.create(project=self.project, data=tomorrow, created_by=self.user)
            meeting.partecipanti_utenti.add(self.user)
            MeetingIssue.objects.create(
                project=self.project,
                title="Problema scaduto",
                status=MeetingIssueStatus.OPEN,
                assigned_to=self.user,
                due_date=monday - timedelta(days=3),
            )

            run_meetings_digest()

        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("Incontri KICK-OFF di domani", body)
        self.assertIn("Problema scaduto", body)

    def test_problema_scaduto_fuori_lunedi_non_genera_sollecito(self):
        from datetime import date, timedelta
        from unittest.mock import patch

        from tasks.models import MeetingIssue, MeetingIssueStatus
        from tasks.tasks import run_meetings_digest

        tuesday = date(2026, 9, 8)  # non lunedi
        MeetingIssue.objects.create(
            project=self.project,
            title="Problema scaduto",
            status=MeetingIssueStatus.OPEN,
            assigned_to=self.user,
            due_date=tuesday - timedelta(days=3),
        )

        with patch("django.utils.timezone.localdate", return_value=tuesday):
            run_meetings_digest()

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingRunTests(TasksBaseTestCase):
    """Schermata di conduzione: autosave sui punti e cattura rapida."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="conduci-pm", legacy_user_id=581, role_id=2, role_name="tasks"
        )
        self.estraneo = _create_user_with_legacy(
            username="conduci-estraneo", legacy_user_id=582, role_id=2, role_name="tasks"
        )
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user
        )
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            created_by=self.user,
            agenda_items=[
                {"id": "a1", "titolo": "Stato avanzamento", "nota": "", "durata_minuti": 15, "done": False},
                {"id": "a2", "titolo": "Criticità", "nota": "", "durata_minuti": 20, "done": False},
            ],
        )
        self.client.force_login(self.user)
        self.run_url = reverse("tasks:project_meeting_run", args=[self.project.id, self.meeting.id])
        self.item_url = reverse(
            "tasks:project_meeting_agenda_item_update", args=[self.project.id, self.meeting.id]
        )
        self.capture_url = reverse(
            "tasks:project_meeting_quick_capture", args=[self.project.id, self.meeting.id]
        )

    def test_la_pagina_somma_i_tempi_pianificati(self):
        response = self.client.get(self.run_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["planned_minutes"], 35)
        self.assertEqual(response.context["done_count"], 0)

    def test_autosave_nota_spunta_e_tempo_effettivo(self):
        self.client.post(self.item_url, {"item_id": "a1", "nota": "in linea col piano"})
        self.client.post(self.item_url, {"item_id": "a1", "done": "1"})
        self.client.post(self.item_url, {"item_id": "a1", "tempo_effettivo_minuti": "22"})
        self.meeting.refresh_from_db()
        item = self.meeting.agenda_items[0]
        self.assertEqual(item["nota"], "in linea col piano")
        self.assertTrue(item["done"])
        self.assertEqual(item["tempo_effettivo_minuti"], 22)

    def test_tempo_fuori_range_viene_scartato(self):
        self.client.post(self.item_url, {"item_id": "a1", "tempo_effettivo_minuti": "999"})
        self.meeting.refresh_from_db()
        self.assertIsNone(self.meeting.agenda_items[0]["tempo_effettivo_minuti"])

    def test_punto_inesistente_risponde_404(self):
        response = self.client.post(self.item_url, {"item_id": "nope", "nota": "x"})
        self.assertEqual(response.status_code, 404)

    def test_cattura_rapida_crea_azione_decisione_e_problema(self):
        from tasks.models import MeetingActionItem, MeetingDecision

        self.client.post(self.capture_url, {
            "kind": "action", "titolo": "Chiamare il fornitore",
            "owner_id": str(self.user.pk), "due_date": "2026-09-20",
        })
        self.client.post(self.capture_url, {
            "kind": "decision", "titolo": "Si procede con A", "impatto": "ALTO",
        })
        self.client.post(self.capture_url, {"kind": "issue", "titolo": "Manca il disegno"})

        action = MeetingActionItem.objects.get(project=self.project)
        self.assertEqual(action.assigned_to, self.user)
        self.assertEqual(action.source_meeting, self.meeting)
        self.assertEqual(MeetingDecision.objects.filter(meeting=self.meeting).count(), 1)
        self.assertTrue(MeetingIssue.objects.filter(source_meeting=self.meeting).exists())

    def test_cattura_rapida_senza_titolo_non_crea_nulla(self):
        from tasks.models import MeetingActionItem

        response = self.client.post(self.capture_url, {"kind": "action", "titolo": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MeetingActionItem.objects.exists())

    def test_chi_non_gestisce_la_commessa_non_conduce(self):
        """Fuori scope si esce con 404, in scope senza gestione con 403: mai scrittura."""
        self.client.force_login(self.estraneo)
        response = self.client.post(self.item_url, {"item_id": "a1", "nota": "x"})
        self.assertIn(response.status_code, (403, 404))
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.agenda_items[0]["nota"], "")

    def test_l_esito_riparte_dalle_note_prese_durante_la_riunione(self):
        self.client.post(self.item_url, {"item_id": "a1", "nota": "in linea col piano"})
        response = self.client.get(
            reverse("tasks:project_meeting_minutes", args=[self.project.id, self.meeting.id])
        )
        self.assertIn("Stato avanzamento: in linea col piano", response.context["form"].initial["note"])

    def test_un_verbale_gia_scritto_non_viene_sovrascritto(self):
        self.meeting.note = "verbale scritto a mano"
        self.meeting.save(update_fields=["note"])
        self.client.post(self.item_url, {"item_id": "a1", "nota": "nota del punto"})
        response = self.client.get(
            reverse("tasks:project_meeting_minutes", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.context["form"].initial["note"], "verbale scritto a mano")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingAgendaProposalTests(TasksBaseTestCase):
    """I convocati propongono punti, chi gestisce la commessa decide."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(
            username="proposta-pm", legacy_user_id=571, role_id=2, role_name="tasks"
        )
        self.convocato = _create_user_with_legacy(
            username="proposta-convocato", legacy_user_id=572, role_id=2, role_name="tasks"
        )
        self.estraneo = _create_user_with_legacy(
            username="proposta-estraneo", legacy_user_id=573, role_id=2, role_name="tasks"
        )
        self.project = Project.objects.create(
            name="", created_by=self.pm, project_manager=self.pm
        )
        self.meeting = KickoffMeeting.objects.create(
            project=self.project, data="2026-09-10", created_by=self.pm
        )
        self.meeting.partecipanti_utenti.add(self.convocato)
        self.create_url = reverse(
            "tasks:project_meeting_proposal_create", args=[self.project.id, self.meeting.id]
        )

    def test_il_convocato_puo_proporre(self):
        from tasks.models import MeetingAgendaProposal, MeetingProposalStatus

        self.client.force_login(self.convocato)
        self.client.post(self.create_url, {"titolo": "Parliamo del collaudo", "nota": "urgente"})
        proposal = MeetingAgendaProposal.objects.get(meeting=self.meeting)
        self.assertEqual(proposal.proposed_by, self.convocato)
        self.assertEqual(proposal.stato, MeetingProposalStatus.PENDING)

    def test_chi_non_e_convocato_non_propone(self):
        from tasks.models import MeetingAgendaProposal

        self.client.force_login(self.estraneo)
        self.client.post(self.create_url, {"titolo": "Punto non richiesto"})
        self.assertFalse(MeetingAgendaProposal.objects.filter(meeting=self.meeting).exists())

    def test_accettare_una_proposta_la_mette_in_agenda(self):
        from tasks.models import MeetingAgendaProposal, MeetingProposalStatus

        proposal = MeetingAgendaProposal.objects.create(
            meeting=self.meeting, proposed_by=self.convocato, titolo="Parliamo del collaudo"
        )
        self.client.force_login(self.pm)
        self.client.post(
            reverse("tasks:project_meeting_proposal_decide",
                    args=[self.project.id, self.meeting.id, proposal.id]),
            {"action": "accept"},
        )
        proposal.refresh_from_db()
        self.meeting.refresh_from_db()
        self.assertEqual(proposal.stato, MeetingProposalStatus.ACCEPTED)
        titoli = [item["titolo"] for item in self.meeting.agenda_items]
        self.assertEqual(titoli, ["Parliamo del collaudo"])

    def test_rifiutare_una_proposta_non_tocca_l_agenda(self):
        from tasks.models import MeetingAgendaProposal, MeetingProposalStatus

        proposal = MeetingAgendaProposal.objects.create(
            meeting=self.meeting, proposed_by=self.convocato, titolo="Fuori tema"
        )
        self.client.force_login(self.pm)
        self.client.post(
            reverse("tasks:project_meeting_proposal_decide",
                    args=[self.project.id, self.meeting.id, proposal.id]),
            {"action": "reject", "nota_decisione": "Non pertinente a questo incontro"},
        )
        proposal.refresh_from_db()
        self.meeting.refresh_from_db()
        self.assertEqual(proposal.stato, MeetingProposalStatus.REJECTED)
        self.assertEqual(proposal.nota_decisione, "Non pertinente a questo incontro")
        self.assertEqual(self.meeting.agenda_items, [])

    def test_il_convocato_non_puo_decidere(self):
        from tasks.models import MeetingAgendaProposal, MeetingProposalStatus

        proposal = MeetingAgendaProposal.objects.create(
            meeting=self.meeting, proposed_by=self.convocato, titolo="Punto"
        )
        self.client.force_login(self.convocato)
        self.client.post(
            reverse("tasks:project_meeting_proposal_decide",
                    args=[self.project.id, self.meeting.id, proposal.id]),
            {"action": "accept"},
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.stato, MeetingProposalStatus.PENDING)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingActionAndDecisionTests(TasksBaseTestCase):
    """Azioni strutturate (chi fa cosa entro quando) e registro decisioni."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="azioni-pm", legacy_user_id=561, role_id=2, role_name="tasks"
        )
        self.user.email = "azioni@example.com"
        self.user.save(update_fields=["email"])
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user
        )
        self.meeting = KickoffMeeting.objects.create(
            project=self.project, data="2026-09-10", created_by=self.user
        )
        self.client.force_login(self.user)
        self.minutes_url = reverse(
            "tasks:project_meeting_minutes", args=[self.project.id, self.meeting.id]
        )

    def _registra_esito(self, **extra):
        payload = {"note": "verbale", "problemi_aperti": "", "next_steps": ""}
        payload.update(extra)
        return self.client.post(self.minutes_url, payload)

    def test_esito_crea_azione_con_responsabile_e_scadenza(self):
        from tasks.models import MeetingActionItem, MeetingActionStatus

        self._registra_esito(**{
            "new_action_title": ["Ordinare il materiale", "   "],
            "new_action_description": ["Fornitore storico", ""],
            "new_action_assigned_to": [str(self.user.pk), ""],
            "new_action_due_date": ["2026-09-20", ""],
        })
        actions = list(MeetingActionItem.objects.filter(project=self.project))
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action.title, "Ordinare il materiale")
        self.assertEqual(action.assigned_to, self.user)
        self.assertEqual(action.due_date.isoformat(), "2026-09-20")
        self.assertEqual(action.status, MeetingActionStatus.OPEN)
        self.assertEqual(action.source_meeting, self.meeting)

    def test_azione_aperta_torna_nell_agenda_del_prossimo_incontro(self):
        import json

        from tasks.models import MeetingActionItem

        aperta = MeetingActionItem.objects.create(
            project=self.project, source_meeting=self.meeting, title="Azione aperta"
        )
        chiusa = MeetingActionItem.objects.create(
            project=self.project, source_meeting=self.meeting, title="Azione chiusa"
        )
        chiusa.mark_done(user=self.user)
        chiusa.save()

        response = self.client.get(
            reverse("tasks:project_meeting_create", args=[self.project.id])
        )
        items = json.loads(response.context["form"].initial["agenda_items_raw"])
        action_ids = [item.get("action_id") for item in items]
        self.assertIn(aperta.pk, action_ids)
        self.assertNotIn(chiusa.pk, action_ids)

    def test_chiusura_e_riapertura_azione_dal_dettaglio(self):
        from tasks.models import MeetingActionItem

        action = MeetingActionItem.objects.create(
            project=self.project, source_meeting=self.meeting, title="Azione"
        )
        url = reverse(
            "tasks:project_meeting_action_status",
            args=[self.project.id, self.meeting.id, action.id],
        )
        self.client.post(url, {"action": "done"})
        action.refresh_from_db()
        self.assertTrue(action.is_done)
        self.assertEqual(action.done_by, self.user)

        self.client.post(url, {"action": "reopen"})
        action.refresh_from_db()
        self.assertFalse(action.is_done)
        self.assertIsNone(action.done_at)

    def test_esito_registra_le_decisioni(self):
        from tasks.models import MeetingDecision, MeetingDecisionImpact

        self._registra_esito(**{
            "new_decision_testo": ["Si procede con il fornitore A", ""],
            "new_decision_dettaglio": ["Costo minore a parità di lead time", ""],
            "new_decision_decisa_da": [str(self.user.pk), ""],
            "new_decision_impatto": ["ALTO", ""],
        })
        decisions = list(MeetingDecision.objects.filter(project=self.project))
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].impatto, MeetingDecisionImpact.ALTO)
        self.assertEqual(decisions[0].meeting, self.meeting)

    def test_impatto_non_valido_ricade_su_medio(self):
        from tasks.models import MeetingDecision, MeetingDecisionImpact

        self._registra_esito(**{
            "new_decision_testo": ["Decisione"],
            "new_decision_impatto": ["CATASTROFICO"],
        })
        self.assertEqual(
            MeetingDecision.objects.get(project=self.project).impatto,
            MeetingDecisionImpact.MEDIO,
        )

    def test_minuta_riporta_azioni_e_decisioni(self):
        from tasks.minute_email import _minute_sections
        from tasks.models import MeetingActionItem, MeetingDecision

        MeetingActionItem.objects.create(
            project=self.project, source_meeting=self.meeting,
            title="Ordinare il materiale", assigned_to=self.user,
        )
        MeetingDecision.objects.create(
            project=self.project, meeting=self.meeting, testo="Si procede con A",
        )
        sections = dict(_minute_sections(self.meeting))
        self.assertIn("Ordinare il materiale", sections["Azioni"])
        self.assertIn("Si procede con A", sections["Decisioni"])

    def test_registro_decisioni_di_commessa(self):
        from tasks.models import MeetingDecision

        MeetingDecision.objects.create(
            project=self.project, meeting=self.meeting, testo="Si procede con A",
        )
        response = self.client.get(
            reverse("tasks:project_decisions", args=[self.project.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Si procede con A")

    def test_digest_del_lunedi_sollecita_le_azioni_scadute(self):
        from datetime import date, timedelta

        from tasks.models import MeetingActionItem
        from tasks.tasks import run_meetings_digest

        monday = date(2026, 9, 7)
        MeetingActionItem.objects.create(
            project=self.project,
            source_meeting=self.meeting,
            title="Azione scaduta",
            assigned_to=self.user,
            due_date=monday - timedelta(days=2),
        )
        with patch("django.utils.timezone.localdate", return_value=monday):
            run_meetings_digest()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Azione scaduta", mail.outbox[0].body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingAgendaTemplateTests(TasksBaseTestCase):
    """Modelli di ordine del giorno riutilizzabili + duplica dall'incontro precedente."""

    def setUp(self):
        super().setUp()
        _ensure_role(1, "admin")
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="modelli-pm", legacy_user_id=551, role_id=1, role_name="admin"
        )
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user
        )
        self.client.force_login(self.user)

    def test_creazione_modello_con_durate(self):
        from tasks.models import MeetingAgendaTemplate

        response = self.client.post(reverse("tasks:impostazioni"), {
            "tab": "modelli",
            "tpl_action": "template_create",
            "nome": "Avanzamento settimanale",
            "descrizione": "Riunione ricorrente",
            "items_text": "Stato avanzamento | 15\nCriticità aperte\n   \nProssimi passi | 999",
        })
        self.assertEqual(response.status_code, 302)
        template = MeetingAgendaTemplate.objects.get(nome="Avanzamento settimanale")
        self.assertEqual(
            template.items,
            [
                {"titolo": "Stato avanzamento", "nota": "", "durata_minuti": 15},
                {"titolo": "Criticità aperte", "nota": "", "durata_minuti": None},
                {"titolo": "Prossimi passi", "nota": "", "durata_minuti": None},
            ],
        )

    def test_il_form_incontro_riceve_i_modelli_attivi(self):
        from tasks.models import MeetingAgendaTemplate

        MeetingAgendaTemplate.objects.create(
            nome="Attivo", items=[{"titolo": "Punto", "nota": "", "durata_minuti": None}]
        )
        MeetingAgendaTemplate.objects.create(nome="Spento", items=[], is_active=False)

        response = self.client.get(
            reverse("tasks:project_meeting_create", args=[self.project.id])
        )
        nomi = [t["nome"] for t in response.context["agenda_templates_json"]]
        self.assertEqual(nomi, ["Attivo"])

    def test_duplica_odg_dell_incontro_precedente_esclude_i_problemi(self):
        issue = MeetingIssue.objects.create(
            project=self.project, title="Problema", status=MeetingIssueStatus.OPEN
        )
        KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            created_by=self.user,
            agenda_items=[
                {"id": "a1", "titolo": "Punto ricorrente", "durata_minuti": 10},
                {"id": f"issue-{issue.pk}", "titolo": "Problema", "issue_id": issue.pk},
            ],
        )
        response = self.client.get(
            reverse("tasks:project_meeting_create", args=[self.project.id])
        )
        self.assertTrue(response.context["has_previous_agenda"])
        self.assertEqual(
            response.context["previous_agenda_json"],
            [{"titolo": "Punto ricorrente", "nota": "", "durata_minuti": 10}],
        )

    def test_tab_modelli_si_apre(self):
        response = self.client.get(reverse("tasks:impostazioni"), {"tab": "modelli"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Modelli ordine del giorno")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingListaTests(TasksBaseTestCase):
    """Elenco trasversale: «i miei» incontri e ricerca nel verbale."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="lista-pm", legacy_user_id=541, role_id=2, role_name="tasks"
        )
        self.altro = _create_user_with_legacy(
            username="lista-altro", legacy_user_id=542, role_id=2, role_name="tasks"
        )
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user
        )
        self.mio = KickoffMeeting.objects.create(
            project=self.project, data="2026-09-10", titolo="Incontro mio",
            note="si è parlato di collaudo", created_by=self.user,
        )
        self.mio.partecipanti_utenti.add(self.user)
        self.altrui = KickoffMeeting.objects.create(
            project=self.project, data="2026-09-11", titolo="Incontro altrui",
            created_by=self.altro,
        )
        self.altrui.partecipanti_utenti.add(self.altro)
        self.client.force_login(self.user)
        self.url = reverse("tasks:incontri_lista")

    def test_default_mostra_solo_i_miei_incontri(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        titoli = [m.titolo for m in response.context["meetings"]]
        self.assertIn("Incontro mio", titoli)
        self.assertNotIn("Incontro altrui", titoli)

    def test_scope_tutti_mostra_anche_gli_altri(self):
        response = self.client.get(self.url, {"mine": "0"})
        titoli = [m.titolo for m in response.context["meetings"]]
        self.assertIn("Incontro altrui", titoli)

    def test_ricerca_nel_verbale(self):
        response = self.client.get(self.url, {"mine": "0", "q": "collaudo"})
        titoli = [m.titolo for m in response.context["meetings"]]
        self.assertEqual(titoli, ["Incontro mio"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingMinuteApprovalTests(TasksBaseTestCase):
    """La minuta approvata e' un documento chiuso: si riapre solo con un motivo."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="minuta-pm", legacy_user_id=531, role_id=2, role_name="tasks"
        )
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user
        )
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            stato=MeetingStatus.SVOLTO,
            note="verbale",
            created_by=self.user,
        )
        self.client.force_login(self.user)
        self.close_url = reverse(
            "tasks:project_meeting_minute_close", args=[self.project.id, self.meeting.id]
        )
        self.reopen_url = reverse(
            "tasks:project_meeting_minute_reopen", args=[self.project.id, self.meeting.id]
        )
        self.minutes_url = reverse(
            "tasks:project_meeting_minutes", args=[self.project.id, self.meeting.id]
        )

    def test_incontro_non_svolto_non_si_approva(self):
        self.meeting.stato = MeetingStatus.PIANIFICATO
        self.meeting.save(update_fields=["stato"])
        self.client.post(self.close_url)
        self.meeting.refresh_from_db()
        self.assertFalse(self.meeting.minuta_chiusa)

    def test_minuta_approvata_blocca_la_modifica_dell_esito(self):
        self.client.post(self.close_url)
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.minuta_chiusa)
        self.assertEqual(self.meeting.minuta_chiusa_da, self.user)

        response = self.client.post(self.minutes_url, {"note": "riscrittura"})
        self.assertEqual(response.status_code, 302)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.note, "verbale")

        response = self.client.get(self.minutes_url)
        self.assertEqual(response.status_code, 302)

    def test_riapertura_richiede_un_motivo(self):
        self.client.post(self.close_url)

        self.client.post(self.reopen_url, {"motivo": "  "})
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.minuta_chiusa)

        self.client.post(self.reopen_url, {"motivo": "errore nel verbale"})
        self.meeting.refresh_from_db()
        self.assertFalse(self.meeting.minuta_chiusa)
        self.assertEqual(self.meeting.minuta_riaperture, 1)

        response = self.client.post(self.minutes_url, {"note": "verbale corretto"})
        self.assertEqual(response.status_code, 302)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.note, "verbale corretto")

    def test_la_minuta_approvata_lo_dichiara_nel_documento(self):
        from tasks.minute_email import _facts

        self.client.post(self.close_url)
        self.meeting.refresh_from_db()
        labels = dict(_facts(self.meeting))
        self.assertIn("Minuta", labels)
        self.assertIn("Approvata il", labels["Minuta"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingAgendaCarryOverTests(TasksBaseTestCase):
    """Rolling agenda: i punti non trattati tornano nel prossimo incontro."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="carry-pm", legacy_user_id=521, role_id=2, role_name="tasks"
        )
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user
        )
        self.client.force_login(self.user)
        self.create_url = reverse("tasks:project_meeting_create", args=[self.project.id])

    def _new_meeting_agenda(self) -> list[dict]:
        import json

        response = self.client.get(self.create_url)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.context["form"].initial["agenda_items_raw"])

    def test_punto_non_trattato_torna_nel_prossimo_incontro(self):
        KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            stato=MeetingStatus.SVOLTO,
            created_by=self.user,
            agenda_items=[
                {"id": "a1", "titolo": "Trattato", "done": True},
                {"id": "a2", "titolo": "Rimasto fuori", "nota": "manca il fornitore", "done": False},
            ],
        )
        titoli = [item["titolo"] for item in self._new_meeting_agenda()]
        self.assertIn("Rimasto fuori", titoli)
        self.assertNotIn("Trattato", titoli)

    def test_il_punto_riportato_dichiara_l_incontro_di_origine(self):
        meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            stato=MeetingStatus.SVOLTO,
            created_by=self.user,
            agenda_items=[{"id": "a1", "titolo": "Rimasto fuori", "done": False}],
        )
        carried = self._new_meeting_agenda()[0]
        self.assertEqual(carried["source"], "carry_over")
        self.assertFalse(carried["done"])
        self.assertIn(
            {"label": "Riportato da", "value": f"Incontro {meeting.numero}"},
            carried["custom_fields"],
        )

    def test_i_problemi_aperti_non_vengono_duplicati_dal_carry_over(self):
        issue = MeetingIssue.objects.create(
            project=self.project, title="Problema aperto", status=MeetingIssueStatus.OPEN
        )
        KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            stato=MeetingStatus.SVOLTO,
            created_by=self.user,
            agenda_items=[{
                "id": f"issue-{issue.pk}",
                "titolo": f"Problema aperto: {issue.title}",
                "issue_id": issue.pk,
                "source": "meeting_issue",
                "done": False,
            }],
        )
        items = self._new_meeting_agenda()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["issue_id"], issue.pk)

    def test_nessun_carry_over_da_incontri_non_ancora_svolti(self):
        KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            stato=MeetingStatus.PIANIFICATO,
            created_by=self.user,
            agenda_items=[{"id": "a1", "titolo": "Non ancora discusso", "done": False}],
        )
        self.assertEqual(self._new_meeting_agenda(), [])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingAttendanceTests(TasksBaseTestCase):
    """Presenze effettive: chi c'era davvero, distinto dai convocati."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="presenze-pm", legacy_user_id=511, role_id=2, role_name="tasks"
        )
        self.user.email = "pm-presenze@example.com"
        self.user.save(update_fields=["email"])
        self.assente = _create_user_with_legacy(
            username="presenze-assente", legacy_user_id=512, role_id=2, role_name="tasks"
        )
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user
        )
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            partecipanti_email_extra="esterno@example.com\naltro@example.com",
            created_by=self.user,
        )
        self.meeting.partecipanti_utenti.add(self.user, self.assente)
        self.client.force_login(self.user)
        self.minutes_url = reverse(
            "tasks:project_meeting_minutes", args=[self.project.id, self.meeting.id]
        )

    def test_esito_propone_tutti_i_convocati_come_presenti(self):
        response = self.client.get(self.minutes_url)
        self.assertEqual(response.status_code, 200)
        initial = response.context["form"].initial
        self.assertCountEqual(initial["presenti_utenti"], [self.user.pk, self.assente.pk])
        self.assertCountEqual(
            initial["presenti_email_list"], ["esterno@example.com", "altro@example.com"]
        )

    def test_registrare_esito_salva_presenti_e_assenti(self):
        response = self.client.post(self.minutes_url, {
            "presenti_utenti": [self.user.pk],
            "presenti_email_list": ["esterno@example.com"],
            "note": "verbale",
            "problemi_aperti": "",
            "next_steps": "",
        })
        self.assertEqual(response.status_code, 302)
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.presenze_registrate)
        self.assertEqual(self.meeting.presenti_count, 2)
        self.assertEqual(self.meeting.convocati_count, 4)
        self.assertEqual([u.pk for u in self.meeting.assenti_utenti], [self.assente.pk])
        self.assertEqual(self.meeting.assenti_email, ["altro@example.com"])

    def test_presente_non_convocato_viene_rifiutato(self):
        estraneo = _create_user_with_legacy(
            username="presenze-estraneo", legacy_user_id=513, role_id=2, role_name="tasks"
        )
        response = self.client.post(self.minutes_url, {
            "presenti_utenti": [estraneo.pk],
            "note": "verbale",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.meeting.refresh_from_db()
        self.assertFalse(self.meeting.presenze_registrate)

    def test_minuta_mostra_presenti_e_assenti_solo_dopo_l_appello(self):
        from tasks.minute_email import _minute_sections

        labels = [label for label, _ in _minute_sections(self.meeting)]
        self.assertIn("Partecipanti", labels)
        self.assertNotIn("Presenti", labels)

        self.client.post(self.minutes_url, {
            "presenti_utenti": [self.user.pk],
            "presenti_email_list": ["esterno@example.com"],
            "note": "verbale",
        })
        self.meeting.refresh_from_db()
        sections = dict(_minute_sections(self.meeting))
        self.assertIn("Presenti", sections)
        self.assertIn("esterno@example.com", sections["Presenti"])
        self.assertIn(self.assente.username, sections["Assenti"])
        self.assertIn("altro@example.com", sections["Assenti"])

    def test_dettaglio_incontro_mostra_il_conteggio_presenze(self):
        self.client.post(self.minutes_url, {
            "presenti_utenti": [self.user.pk],
            "presenti_email_list": ["esterno@example.com"],
            "note": "verbale",
        })
        response = self.client.get(
            reverse("tasks:project_meeting_detail", args=[self.project.id, self.meeting.id])
        )
        self.assertContains(response, "2 presenti su 4 convocati")
