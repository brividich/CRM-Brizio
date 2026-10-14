"""Incontri e azioni KICK-OFF: convocazione tracciata, annullamento, azioni a chi le fa.

Copre la revisione del 14/10/2026: servizio unico «attivita' da incontro»,
legame attivita' -> azioni/problemi, «Le mie azioni», registro azioni con le
azioni d'incontro, promemoria nel giorno lavorativo precedente, appello in
conduzione, eliminazione limitata agli incontri mai svolti.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tasks.models import (
    KickoffMeeting,
    MeetingActionItem,
    MeetingActionStatus,
    MeetingDecision,
    MeetingIssue,
    MeetingIssueStatus,
    MeetingStatus,
    Task,
    TaskStatus,
)
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class IncontriAzioniTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="incontri-azioni", legacy_user_id=411, role_id=2, role_name="tasks",
        )
        self.user.email = "pm@example.com"
        self.user.save(update_fields=["email"])
        self.other = _create_user_with_legacy(
            username="incontri-altro", legacy_user_id=412, role_id=2, role_name="tasks",
        )
        self.project = make_project(name="", created_by=self.user, project_manager=self.user)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data=timezone.localdate() + timedelta(days=3),
            titolo="Avvio",
            partecipanti_email_extra="mario@example.com",
            agenda_items=[{"id": "a1", "titolo": "Stato avanzamento", "nota": "", "done": False}],
            created_by=self.user,
        )
        self.meeting.partecipanti_utenti.add(self.user)
        self.client.force_login(self.user)

    def _url(self, name, *extra):
        return reverse(name, args=[self.project.id, self.meeting.id, *extra])

    # ── attivita' ───────────────────────────────────────────────────────
    def test_attivita_di_un_giorno_e_valida(self):
        oggi = timezone.localdate()
        task = Task(title="Giornata", project=self.project, created_by=self.user, next_step_due=oggi, due_date=oggi)
        task.clean()  # non solleva
        task.due_date = oggi - timedelta(days=1)
        with self.assertRaises(ValidationError):
            task.clean()

    def test_attivita_completata_chiude_azioni_e_problemi_collegati(self):
        task = Task.objects.create(title="Collaudo", project=self.project, created_by=self.user)
        action = MeetingActionItem.objects.create(project=self.project, title="Fare collaudo", linked_task=task)
        issue = MeetingIssue.objects.create(project=self.project, title="Pezzo mancante", linked_task=task)
        task.status = TaskStatus.DONE
        task.save()
        action.refresh_from_db()
        issue.refresh_from_db()
        self.assertEqual(action.status, MeetingActionStatus.DONE)
        self.assertEqual(issue.status, MeetingIssueStatus.RESOLVED)
        self.assertIn("Collaudo", issue.resolution_note)

    def test_cambio_stato_a_completata_porta_avanzamento_al_cento(self):
        task = Task.objects.create(title="Avanzamento", project=self.project, created_by=self.user, progress=40)
        self.client.post(reverse("tasks:change_status", args=[task.id]), {"status": TaskStatus.DONE})
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DONE)
        self.assertEqual(task.progress, 100)

    def test_titolo_lungo_tagliato_e_assegnatario_avvisato(self):
        with patch("tasks.services.meeting_tasks.notify_user") as notify:
            response = self.client.post(self._url("tasks:project_meeting_task_from_step"), {
                "title": "X" * 260, "assigned_to": str(self.other.pk),
            })
        self.assertEqual(response.status_code, 200)
        task = Task.objects.get(pk=response.json()["task_id"])
        self.assertEqual(len(task.title), 200)
        self.assertIn(f"#{self.meeting.numero} (", task.description)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], self.other)

    def test_crea_da_step_rispetta_il_blocco_vrf(self):
        bloccato = {"status": "blocked", "label": "", "is_blocked": True, "days_pending": 40, "show_upload_cta": True}
        with patch("tasks.views._shared._vrf_status_detail", return_value=bloccato):
            response = self.client.post(self._url("tasks:project_meeting_task_from_step"), {"title": "Bloccata"})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Task.objects.filter(title="Bloccata").exists())

    # ── convocazione ────────────────────────────────────────────────────
    def test_invio_convocazione_tracciato_e_aggiornamento(self):
        self.client.post(self._url("tasks:project_meeting_send_invite"))
        self.meeting.refresh_from_db()
        self.assertIsNotNone(self.meeting.convocazione_inviata_at)
        self.assertFalse(self.meeting.convocazione_da_reinviare)

        self.meeting.luogo = "Sala B"
        self.meeting.save()
        self.assertTrue(self.meeting.convocazione_da_reinviare)
        detail = self.client.get(self._url("tasks:project_meeting_detail"))
        self.assertContains(detail, "Convocazione da reinviare")
        self.assertContains(detail, "Invia aggiornamento convocazione")

        mail.outbox.clear()
        self.client.post(self._url("tasks:project_meeting_send_invite"))
        self.assertIn("Aggiornamento convocazione", mail.outbox[0].subject)

    def test_rinvio_azzera_il_promemoria(self):
        KickoffMeeting.objects.filter(pk=self.meeting.pk).update(reminder_sent_at=timezone.now())
        nuova = self.meeting.data + timedelta(days=7)
        response = self.client.post(self._url("tasks:project_meeting_edit"), {
            "titolo": "Avvio", "data": nuova.isoformat(), "stato": MeetingStatus.PIANIFICATO,
            "partecipanti_utenti": [self.user.pk], "partecipanti_email_extra": "mario@example.com",
            "agenda_items_raw": "[]",
        })
        self.assertEqual(response.status_code, 302)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.data, nuova)
        self.assertIsNone(self.meeting.reminder_sent_at)

    def test_invio_dal_form_con_la_spunta(self):
        self.client.post(self._url("tasks:project_meeting_edit"), {
            "titolo": "Avvio", "data": self.meeting.data.isoformat(), "stato": MeetingStatus.PIANIFICATO,
            "partecipanti_utenti": [self.user.pk], "partecipanti_email_extra": "mario@example.com",
            "agenda_items_raw": "[]", "invia_convocazione": "on",
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Convocazione", mail.outbox[0].subject)

    def test_pianifica_prossimo_riprende_convocati(self):
        self.meeting.cc_email_extra = "copia@example.com"
        self.meeting.save()
        response = self.client.get(
            reverse("tasks:project_meeting_create", args=[self.project.id]) + f"?da={self.meeting.id}"
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial["partecipanti_email_extra"], "mario@example.com")
        self.assertEqual(form.initial["cc_email_extra"], "copia@example.com")
        self.assertIn(self.user.pk, form.initial["partecipanti_utenti"])

    # ── annullamento ed eliminazione ────────────────────────────────────
    def test_annullamento_richiede_motivo_e_avvisa(self):
        url = self._url("tasks:project_meeting_cancel")
        self.client.post(url, {"motivo": ""})
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.stato, MeetingStatus.PIANIFICATO)

        self.client.post(url, {"motivo": "Cliente non disponibile", "avvisa": "1"})
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.stato, MeetingStatus.ANNULLATO)
        self.assertEqual(self.meeting.annullato_motivo, "Cliente non disponibile")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Annullato", mail.outbox[0].subject)
        self.assertIn("Cliente non disponibile", mail.outbox[0].body)
        ics = [a[1] for a in mail.outbox[0].attachments if a[0].endswith(".ics")]
        self.assertTrue(ics)
        contenuto = ics[0].decode() if isinstance(ics[0], bytes) else str(ics[0])
        self.assertIn("METHOD:CANCEL", contenuto)

    def test_incontro_svolto_non_si_elimina(self):
        KickoffMeeting.objects.filter(pk=self.meeting.pk).update(stato=MeetingStatus.SVOLTO)
        self.client.post(self._url("tasks:project_meeting_delete"))
        self.assertTrue(KickoffMeeting.objects.filter(pk=self.meeting.pk).exists())

    def test_incontro_con_decisioni_non_si_elimina(self):
        MeetingDecision.objects.create(project=self.project, meeting=self.meeting, testo="Si procede")
        self.client.post(self._url("tasks:project_meeting_delete"))
        self.assertTrue(KickoffMeeting.objects.filter(pk=self.meeting.pk).exists())

    def test_incontro_pianificato_si_elimina(self):
        self.client.post(self._url("tasks:project_meeting_delete"))
        self.assertFalse(KickoffMeeting.objects.filter(pk=self.meeting.pk).exists())

    # ── conduzione ──────────────────────────────────────────────────────
    def test_appello_in_conduzione(self):
        url = self._url("tasks:project_meeting_attendance")
        response = self.client.post(url, {"user_id": self.user.pk, "presente": "1"})
        self.assertTrue(response.json()["ok"])
        self.client.post(url, {"email": "mario@example.com", "presente": "1"})
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.presenze_registrate)
        self.assertEqual(self.meeting.presenti_count, 2)
        response = self.client.post(url, {"email": "estraneo@example.com", "presente": "1"})
        self.assertEqual(response.status_code, 404)

    def test_autosave_aggiorna_solo_il_punto(self):
        response = self.client.post(self._url("tasks:project_meeting_agenda_item_update"), {"item_id": "a1", "nota": "Ok"})
        self.assertTrue(response.json()["ok"])
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.agenda_items[0]["nota"], "Ok")

    def test_cattura_rapida_avvisa_il_responsabile(self):
        with patch("tasks.services.meeting_tasks.notify_user") as notify:
            self.client.post(self._url("tasks:project_meeting_quick_capture"), {
                "kind": "action", "titolo": "Chiamare il fornitore", "owner_id": str(self.other.pk),
            })
        notify.assert_called_once()
        self.assertIn("Chiamare il fornitore", notify.call_args.args[1])

    # ── le mie azioni e registro ────────────────────────────────────────
    def test_le_mie_azioni_e_chiusura_dal_responsabile(self):
        mia = MeetingActionItem.objects.create(
            project=self.project, source_meeting=self.meeting, title="Mia azione", assigned_to=self.user,
            due_date=timezone.localdate() - timedelta(days=1),
        )
        MeetingActionItem.objects.create(project=self.project, title="Di un altro", assigned_to=self.other)
        response = self.client.get(reverse("tasks:mie_azioni"))
        self.assertContains(response, "Mia azione")
        self.assertNotContains(response, "Di un altro")

        self.client.post(reverse("tasks:mia_voce_stato", args=["azione", mia.pk]), {"action": "done"})
        mia.refresh_from_db()
        self.assertEqual(mia.status, MeetingActionStatus.DONE)

    def test_registro_azioni_comprende_le_azioni_d_incontro_e_filtra(self):
        MeetingActionItem.objects.create(project=self.project, source_meeting=self.meeting, title="Azione registro")
        Task.objects.create(title="Attivita registro", project=self.project, created_by=self.user)
        url = reverse("tasks:project_actions", args=[self.project.id])
        response = self.client.get(url)
        self.assertContains(response, "Azione registro")
        self.assertContains(response, "Azione incontro")
        response = self.client.get(url, {"tipo": "action"})
        self.assertContains(response, "Azione registro")
        self.assertNotContains(response, "Attivita registro")

    def test_elenco_incontri_mie_comprende_le_copie(self):
        altro = make_project(name="Altra", created_by=self.other)
        meeting = KickoffMeeting.objects.create(project=altro, data=timezone.localdate(), created_by=self.other)
        meeting.cc_utenti.add(self.user)
        from tasks.meeting_alerts import _mine_filter

        self.assertTrue(KickoffMeeting.objects.filter(_mine_filter(self.user), pk=meeting.pk).exists())

    def test_guida_mostra_tutte_le_sezioni(self):
        from tasks.guida import SEZIONI

        response = self.client.get(reverse("tasks:guida"))
        self.assertEqual(response.status_code, 200)
        for sezione in SEZIONI:
            self.assertContains(response, f'id="{sezione["id"]}"')
        lista = self.client.get(reverse("tasks:mie_azioni"))
        self.assertContains(lista, reverse("tasks:guida"))


class PromemoriaGiornoLavorativoTests(SimpleTestCase):
    def test_venerdi_copre_il_lunedi(self):
        from tasks.tasks import meeting_reminder_dates

        venerdi = date(2026, 10, 16)
        self.assertEqual(meeting_reminder_dates(venerdi), [date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)])

    def test_giorno_feriale_copre_solo_domani(self):
        from tasks.tasks import meeting_reminder_dates

        self.assertEqual(meeting_reminder_dates(date(2026, 10, 14)), [date(2026, 10, 15)])

    def test_prima_di_un_festivo(self):
        from tasks.tasks import meeting_reminder_dates

        # 31/10/2026 e' sabato, 01/11 domenica e Ognissanti: il venerdi' 30 copre fino a lunedi' 2.
        self.assertEqual(meeting_reminder_dates(date(2026, 10, 30))[-1], date(2026, 11, 2))
