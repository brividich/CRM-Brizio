"""«Attività e incontro»: il terzo passo del kickoff in una pagina.

Attività con nota e collegamento, incontro facoltativo con ordine del giorno,
e la scelta di quando avvisare: subito o con la minuta dell'incontro.
"""
from __future__ import annotations

import json

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from tasks.models import TaskDependency
from tasks.services.kickoff_avvio import AVVISO_CON_MINUTA, avvisa_con_la_minuta
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, SITE_URL="https://hub.example.com")
class AttivitaEIncontroTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="av-pm", legacy_user_id=541, role_id=2, role_name="tasks")
        self.resp = _create_user_with_legacy(username="av-resp", legacy_user_id=542, role_id=2, role_name="tasks")
        self.resp.email = "resp@example.com"
        self.resp.save(update_fields=["email"])
        self.project = make_project(name="Commessa avvio", created_by=self.pm, project_manager=self.pm)
        self.url = reverse("tasks:project_pianifica", args=[self.project.pk])
        self.client.force_login(self.pm)

    def _dati(self, **extra):
        dati = {
            "att_chiave": ["a", "b", "c"],
            "att_titolo": ["Ordine materiale", "Programma CAM", ""],
            "att_resp": ["", str(self.resp.pk), ""],
            "att_scadenza": ["", "2026-12-04", ""],
            "att_note": ["", "Partire dal lato A.", ""],
            "att_odg": ["0", "1", "1"],
            "att_dopo": ["", "a", ""],
            "incontro": "1", "inc_data": "2026-11-26", "inc_ora": "10:00", "inc_durata": "45", "inc_sala": "",
            "inc_part": [str(self.pm.pk)],
            "odg_ordine": json.dumps([{"punto": "Lettura disegno"}, {"att": "b"}]),
            "invio": "subito",
        }
        dati.update(extra)
        return dati

    def test_la_pagina_si_apre_con_le_righe(self):
        pagina = self.client.get(self.url)
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, 'name="att_note"')
        self.assertContains(pagina, "data-ka-riga-modello")
        self.assertContains(pagina, "Quando avvisi le persone?")

    def test_attivita_incontro_e_ordine_del_giorno_in_un_salvataggio(self):
        risposta = self.client.post(self.url, self._dati())
        meeting = self.project.meetings.get()
        self.assertRedirects(
            risposta, reverse("tasks:project_meeting_detail", args=[self.project.pk, meeting.pk]),
            fetch_redirect_response=False,
        )
        materiale, cam = self.project.tasks.order_by("id")
        self.assertEqual(cam.assigned_to, self.resp)
        self.assertEqual(cam.description, "Partire dal lato A.")
        self.assertEqual(cam.due_date.isoformat(), "2026-12-04")
        # «Programma CAM» viene dopo «Ordine materiale».
        self.assertTrue(TaskDependency.objects.filter(predecessor=materiale, successor=cam).exists())
        # Ordine del giorno nell'ordine scelto: il punto libero, poi l'attività segnata «All'ODG».
        self.assertEqual([p["titolo"] for p in meeting.agenda_items], ["Lettura disegno", "Programma CAM"])
        self.assertEqual(meeting.agenda_items[1]["task_id"], cam.pk)
        # Chi ha un'attività è convocato anche se non era fra i partecipanti scelti.
        self.assertEqual(set(meeting.partecipanti_utenti.all()), {self.pm, self.resp})
        self.assertEqual(meeting.durata_minuti, 45)

    def test_invia_subito_manda_la_mail_con_la_nota(self):
        self.client.post(self.url, self._dati())
        messaggi = [m for m in mail.outbox if m.to == ["resp@example.com"] and "Programma CAM" in m.subject]
        self.assertEqual(len(messaggi), 1)
        self.assertIn("Partire dal lato A.", messaggi[0].body)
        self.assertNotIn(AVVISO_CON_MINUTA, self.project.tasks.get(title="Programma CAM").extra_data or {})

    def test_aspetta_la_minuta_non_avvisa_e_la_minuta_riporta_le_attivita(self):
        from tasks.minute_email import _minute_sections

        self.client.post(self.url, self._dati(invio="minuta"))
        self.assertEqual([m for m in mail.outbox if "Programma CAM" in m.subject], [])
        meeting = self.project.meetings.get()
        cam = self.project.tasks.get(title="Programma CAM")
        self.assertEqual(cam.extra_data[AVVISO_CON_MINUTA], meeting.pk)

        attivita = dict(_minute_sections(meeting))["Attività assegnate"]
        self.assertIn("Programma CAM", attivita)
        self.assertIn("Partire dal lato A.", attivita)
        # Anche l'attività fuori dall'ordine del giorno aspetta questa minuta: ci finisce.
        self.assertIn("Ordine materiale", attivita)

        self.assertEqual(avvisa_con_la_minuta(meeting, actor=self.pm), 1)
        cam.refresh_from_db()
        self.assertNotIn(AVVISO_CON_MINUTA, cam.extra_data)
        # Una seconda minuta non avvisa di nuovo.
        self.assertEqual(avvisa_con_la_minuta(meeting, actor=self.pm), 0)

    def test_senza_incontro_restano_solo_le_attivita(self):
        risposta = self.client.post(self.url, self._dati(incontro="0", invio="minuta"))
        self.assertRedirects(risposta, reverse("tasks:project_overview", args=[self.project.pk]), fetch_redirect_response=False)
        self.assertEqual(self.project.meetings.count(), 0)
        self.assertEqual(self.project.tasks.count(), 2)
        # Senza incontro non c'è minuta da aspettare: l'avviso parte.
        self.assertEqual(len([m for m in mail.outbox if "Programma CAM" in m.subject]), 1)

    def test_due_attivita_che_si_aspettano_a_vicenda_restano_con_un_solo_legame(self):
        self.client.post(self.url, self._dati(att_dopo=["b", "a", ""], incontro="0"))
        self.assertEqual(TaskDependency.objects.filter(successor__project=self.project).count(), 1)

    def test_niente_attivita_e_niente_incontro_non_salva(self):
        dati = self._dati(incontro="0", att_titolo=["", "", ""])
        risposta = self.client.post(self.url, dati)
        self.assertEqual(risposta.status_code, 400)
        self.assertContains(risposta, "Scrivi almeno un", status_code=400)
        self.assertEqual(self.project.tasks.count(), 0)

    def test_incontro_senza_data_non_salva_e_ripropone_le_righe(self):
        risposta = self.client.post(self.url, self._dati(inc_data=""))
        self.assertEqual(risposta.status_code, 400)
        self.assertContains(risposta, "Data dell&#x27;incontro", status_code=400)
        self.assertContains(risposta, 'value="Programma CAM"', status_code=400)
        self.assertEqual(self.project.tasks.count(), 0)
        self.assertEqual(self.project.meetings.count(), 0)
