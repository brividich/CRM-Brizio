"""Convocazione KICK-OFF: evento Outlook, file .ics e «cosa e' cambiato».

Copre la revisione del 02/11/2026: testi utente protetti nel corpo
dell'evento Outlook, durata dalla somma dei punti all'ordine del giorno,
.ics conforme (fuso orario, testo protetto, righe spezzate, organizzatore e
invitati nell'annullamento) e dettaglio delle modifiche dopo l'invio.
"""
from __future__ import annotations

from datetime import time, timedelta

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from tasks.meeting_outlook import _meeting_body_html, _meeting_start_end, meeting_duration_minutes
from tasks.minute_email import _ics_fold, _ics_text, build_meeting_ics, send_meeting_invite
from tasks.models import KickoffMeeting
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


def _unfold(ics: str) -> list[str]:
    """Righe logiche del .ics: le continuazioni iniziano con uno spazio."""
    righe: list[str] = []
    for riga in ics.split("\r\n"):
        if riga.startswith(" ") and righe:
            righe[-1] += riga[1:]
        else:
            righe.append(riga)
    return righe


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ConvocazioneIcsOutlookTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="conv-ics", legacy_user_id=511, role_id=2, role_name="tasks",
        )
        self.user.email = "pm@example.com"
        self.user.first_name = "Paola"
        self.user.last_name = "Rossi"
        self.user.save(update_fields=["email", "first_name", "last_name"])
        self.altro = _create_user_with_legacy(
            username="conv-ics-altro", legacy_user_id=512, role_id=2, role_name="tasks",
        )
        self.altro.email = "luca@example.com"
        self.altro.first_name = "Luca"
        self.altro.last_name = "Bianchi"
        self.altro.save(update_fields=["email", "first_name", "last_name"])
        self.project = make_project(name="Cliente <A&B>", created_by=self.user, project_manager=self.user)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data=timezone.localdate() + timedelta(days=5),
            ora=time(10, 30),
            titolo="Avvio <b>urgente</b>",
            luogo="Sala 1, piano terra; ingresso B",
            ordine_del_giorno="Note & <script>x</script>",
            partecipanti_email_extra="mario@example.com",
            agenda_items=[
                {"id": "a1", "titolo": "Stato avanzamento", "nota": "", "durata_minuti": 20},
                {"id": "a2", "titolo": "Rischi", "nota": "", "durata_minuti": 25},
                {"id": "a3", "titolo": "Varie", "nota": "", "durata_minuti": None},
            ],
            created_by=self.user,
        )
        self.meeting.partecipanti_utenti.add(self.user)
        self.client.force_login(self.user)

    # ── 1. evento Outlook ──────────────────────────────────────────────
    def test_corpo_evento_outlook_protegge_i_testi(self):
        html = _meeting_body_html(None, self.meeting)
        self.assertNotIn("<b>urgente</b>", html)
        self.assertNotIn("<script>", html)
        self.assertIn("Avvio &lt;b&gt;urgente&lt;/b&gt;", html)
        self.assertIn("Cliente &lt;A&amp;B&gt;", html)
        self.assertIn("Note &amp; &lt;script&gt;", html)

    # ── 2. durata ──────────────────────────────────────────────────────
    def test_durata_somma_dei_punti(self):
        self.assertEqual(self.meeting.durata_prevista_minuti(), 45)
        start, end = _meeting_start_end(self.meeting)
        self.assertEqual(end - start, timedelta(minutes=45))

    def test_durata_di_un_ora_senza_durate(self):
        self.meeting.agenda_items = [{"id": "a1", "titolo": "Punto", "nota": "", "durata_minuti": None}]
        self.meeting.save()
        self.assertIsNone(self.meeting.durata_prevista_minuti())
        self.assertEqual(meeting_duration_minutes(self.meeting), 60)

    def test_ics_usa_la_durata_e_il_fuso(self):
        righe = _unfold(build_meeting_ics(self.meeting).decode("utf-8"))
        giorno = self.meeting.data.strftime("%Y%m%d")
        self.assertIn(f"DTSTART;TZID=Europe/Rome:{giorno}T103000", righe)
        self.assertIn(f"DTEND;TZID=Europe/Rome:{giorno}T111500", righe)
        self.assertIn("BEGIN:VTIMEZONE", righe)
        self.assertIn("TZID:Europe/Rome", righe)

    def test_ics_giornata_intera_senza_fuso(self):
        self.meeting.ora = None
        self.meeting.save()
        ics = build_meeting_ics(self.meeting).decode("utf-8")
        self.assertIn("DTSTART;VALUE=DATE:", ics)
        self.assertNotIn("VTIMEZONE", ics)

    # ── 3. .ics conforme ───────────────────────────────────────────────
    def test_testo_ics_protetto(self):
        self.assertEqual(_ics_text("a,b;c\\d\ne"), "a\\,b\\;c\\\\d\\ne")
        righe = _unfold(build_meeting_ics(self.meeting).decode("utf-8"))
        self.assertIn("LOCATION:Sala 1\\, piano terra\\; ingresso B", righe)

    def test_righe_ics_spezzate_a_75_byte(self):
        self.meeting.agenda_items = [
            {"id": f"p{i}", "titolo": f"Punto àèìòù numero {i} con un titolo lungo", "nota": "", "durata_minuti": 5}
            for i in range(8)
        ]
        self.meeting.save()
        ics = build_meeting_ics(self.meeting)
        for riga in ics.split(b"\r\n"):
            self.assertLessEqual(len(riga), 75)
            riga.decode("utf-8")  # nessun carattere tagliato a meta'
        self.assertTrue(any(r.startswith(b" ") for r in ics.split(b"\r\n")))

    def test_fold_non_spezza_righe_corte(self):
        self.assertEqual(_ics_fold("SUMMARY:breve"), ["SUMMARY:breve"])

    def test_ics_organizzatore_e_invitati_solo_nell_annullamento(self):
        invito = _unfold(build_meeting_ics(self.meeting).decode("utf-8"))
        self.assertIn("ORGANIZER:mailto:pm@example.com", invito)
        self.assertFalse(any(r.startswith("ATTENDEE") for r in invito))

        annullo = _unfold(build_meeting_ics(self.meeting, cancel=True).decode("utf-8"))
        self.assertIn("METHOD:CANCEL", annullo)
        self.assertIn("ORGANIZER:mailto:pm@example.com", annullo)
        self.assertIn("ATTENDEE;ROLE=REQ-PARTICIPANT:mailto:mario@example.com", annullo)
        self.assertIn("ATTENDEE;ROLE=REQ-PARTICIPANT:mailto:pm@example.com", annullo)

    def test_organizzatore_esplicito_prevale(self):
        self.meeting.outlook_organizer_email = "organizza@example.com"
        self.meeting.save()
        righe = _unfold(build_meeting_ics(self.meeting).decode("utf-8"))
        self.assertIn("ORGANIZER:mailto:organizza@example.com", righe)

    # ── 7. cosa e' cambiato ────────────────────────────────────────────
    def _invia(self):
        self.assertTrue(send_meeting_invite(self.meeting)["sent"])
        self.meeting.refresh_from_db()

    def test_invio_salva_la_copia_dei_dati(self):
        self._invia()
        self.assertTrue(self.meeting.convocazione_dati)
        self.assertFalse(self.meeting.convocazione_da_reinviare)
        self.assertEqual(self.meeting.modifiche_convocazione(), [])

    def test_modifiche_elencate_voce_per_voce(self):
        self._invia()
        vecchia = self.meeting.data
        self.meeting.data = vecchia + timedelta(days=2)
        self.meeting.luogo = "Sala 2"
        self.meeting.partecipanti_email_extra = "anna@example.com"
        self.meeting.agenda_items = self.meeting.agenda_items + [
            {"id": "a4", "titolo": "Collaudo", "nota": "", "durata_minuti": 10}
        ]
        self.meeting.save()
        self.meeting.partecipanti_utenti.add(self.altro)
        self.meeting.partecipanti_utenti.remove(self.user)

        righe = self.meeting.modifiche_convocazione()
        self.assertIn(
            f"Data: {vecchia.strftime('%d-%m-%Y')} → {self.meeting.data.strftime('%d-%m-%Y')}", righe
        )
        self.assertIn("Luogo: Sala 1, piano terra; ingresso B → Sala 2", righe)
        self.assertIn("Esterni aggiunti: anna@example.com", righe)
        self.assertIn("Esterni tolti: mario@example.com", righe)
        self.assertIn("Punti dell'ordine del giorno aggiunti: Collaudo", righe)
        self.assertTrue(any(r.startswith("Convocati aggiunti: LUCA BIANCHI") for r in righe), righe)
        self.assertTrue(any(r.startswith("Convocati tolti: PAOLA ROSSI") for r in righe))

    def test_durata_cambiata_ha_una_riga_generica(self):
        self._invia()
        items = self.meeting.agenda_items
        items[0]["durata_minuti"] = 30
        self.meeting.agenda_items = items
        self.meeting.save()
        self.assertEqual(
            self.meeting.modifiche_convocazione(),
            ["Ordine del giorno: cambiati l'ordine dei punti o le durate"],
        )

    def test_invio_precedente_senza_copia_resta_generico(self):
        self._invia()
        KickoffMeeting.objects.filter(pk=self.meeting.pk).update(convocazione_dati="")
        self.meeting.refresh_from_db()
        self.meeting.luogo = "Altrove"
        self.meeting.save()
        self.assertTrue(self.meeting.convocazione_da_reinviare)
        self.assertEqual(self.meeting.modifiche_convocazione(), [])

        response = self.client.get(
            reverse("tasks:project_meeting_detail", args=[self.project.id, self.meeting.id])
        )
        self.assertContains(response, "data, luogo, convocati o ordine del giorno sono cambiati")

    def test_dettaglio_mostra_le_modifiche(self):
        self._invia()
        self.meeting.luogo = "Sala 2"
        self.meeting.save()
        response = self.client.get(
            reverse("tasks:project_meeting_detail", args=[self.project.id, self.meeting.id])
        )
        self.assertContains(response, "Convocazione da reinviare:")
        self.assertContains(response, "md-convocazione-modifiche")
        self.assertContains(response, "Luogo: Sala 1, piano terra; ingresso B → Sala 2")

    def test_reinvio_azzera_le_modifiche(self):
        self._invia()
        self.meeting.luogo = "Sala 2"
        self.meeting.save()
        self._invia()
        self.assertFalse(self.meeting.convocazione_da_reinviare)
        self.assertIn("Aggiornamento", mail.outbox[-1].subject)
