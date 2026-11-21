"""Minuta: una sola sezione «Attività» con quelle del piano e quelle decise nell'esito."""
from __future__ import annotations

from datetime import date

from django.test import override_settings

from tasks.minute_email import _minute_sections, build_minute_email
from tasks.models import MeetingActionItem, KickoffMeeting, Task
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MinutaAttivitaTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self.pm = _create_user_with_legacy(username="mn-pm", legacy_user_id=581, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa minuta", created_by=self.pm, project_manager=self.pm)
        self.meeting = KickoffMeeting.objects.create(project=self.project, numero=1, data=date(2026, 11, 20))
        self.task = Task.objects.create(
            title="Programma CAM", project=self.project, created_by=self.pm, assigned_to=self.pm,
            extra_data={"avviso_con_minuta": self.meeting.pk},
        )

    def test_una_sola_sezione_attivita_senza_doppioni(self):
        MeetingActionItem.objects.create(
            project=self.project, source_meeting=self.meeting, title="Ordinare il grezzo", assigned_to=self.pm,
        )
        # Voce d'esito collegata a un'attività già elencata: non si ripete.
        MeetingActionItem.objects.create(
            project=self.project, source_meeting=self.meeting, title="Voce collegata", linked_task=self.task,
        )
        sezioni = dict(_minute_sections(self.meeting))
        self.assertNotIn("Azioni", sezioni)
        self.assertNotIn("Attività assegnate", sezioni)
        attivita = sezioni["Attività"]
        self.assertIn("Programma CAM", attivita)
        self.assertIn("Ordinare il grezzo", attivita)
        self.assertNotIn("Voce collegata", attivita)

    def test_la_mail_della_minuta_non_dice_azioni(self):
        MeetingActionItem.objects.create(
            project=self.project, source_meeting=self.meeting, title="Ordinare il grezzo", assigned_to=self.pm,
        )
        _oggetto, testo, html = build_minute_email(self.meeting)
        self.assertIn("Attività", testo)
        self.assertNotIn("Azioni", testo)
        self.assertNotIn("Azioni", html)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class OrdineDelGiornoSenzaTempiTests(TasksBaseTestCase):
    """Decisione del committente: nessun minuto per punto nell'ordine del giorno."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create", "tasks_edit"])
        self.pm = _create_user_with_legacy(username="og-pm", legacy_user_id=591, role_id=2, role_name="tasks")
        self.pm.is_superuser = True
        self.pm.save(update_fields=["is_superuser"])
        self.project = make_project(name="Commessa odg", created_by=self.pm, project_manager=self.pm)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project, data=date.today(), titolo="Avanzamento",
            agenda_items=[{"id": "p1", "titolo": "Stato CAM", "durata_minuti": 15}],
        )

    def test_conduzione_esito_e_dettaglio_senza_minuti(self):
        from django.urls import reverse

        self.client.force_login(self.pm)
        for nome in ("project_meeting_run", "project_meeting_minutes", "project_meeting_detail"):
            pagina = self.client.get(reverse(f"tasks:{nome}", args=[self.project.pk, self.meeting.pk]))
            self.assertEqual(pagina.status_code, 200, nome)
            for testo in ("15 min", "min previsti", "run-elapsed", "Fuori tempo", "Trascorso", 'data-role="tempo"'):
                self.assertNotContains(pagina, testo, msg_prefix=nome)

    def test_convocazione_senza_durata_del_punto(self):
        from django.urls import reverse

        self.client.force_login(self.pm)
        pagina = self.client.get(reverse("tasks:project_meeting_edit", args=[self.project.pk, self.meeting.pk]))
        self.assertNotContains(pagina, "new-agenda-durata")
        self.assertNotContains(pagina, "Durata stimata")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MinutaHtmlTests(TasksBaseTestCase):
    """La mail della minuta è a sezioni: punti con stato, attività con responsabile, testi escapati."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        self.pm = _create_user_with_legacy(username="mh-pm", legacy_user_id=601, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa html", created_by=self.pm, project_manager=self.pm)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project, data=date(2026, 11, 21), titolo="Avanzamento",
            agenda_items=[
                {"id": "p1", "titolo": "Stato <CAM>", "done": True, "nota": "Prove giovedì"},
                {"id": "p2", "titolo": "Controllo", "done": False},
            ],
        )
        MeetingActionItem.objects.create(project=self.project, source_meeting=self.meeting, title="Chiedere la tolleranza")

    def test_sezioni_e_stati(self):
        _oggetto, _testo, html = build_minute_email(self.meeting)
        self.assertIn("Sabato 21/11/2026", html)
        self.assertIn("1 su 2 trattati", html)
        self.assertIn("Trattato", html)
        self.assertIn("Non trattato", html)
        self.assertIn("Responsabile da decidere", html)
        self.assertIn("Stato &lt;CAM&gt;", html)
        self.assertNotIn("Stato <CAM>", html)
        self.assertNotIn("- Chiedere la tolleranza", html)
