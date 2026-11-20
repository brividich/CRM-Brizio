"""KICK-OFF: pagine che si aprono con dati realistici, «modificato da altri»,
avviso a chi entra nel team, storico in pagina, pulsante «Modifica kickoff».

Revisione del 20/11/2026: la pagina Modifica kickoff andava in 500 appena un
ruolo operativo aveva persone mappate e nessun test la apriva in quella
condizione; il salvataggio della convocazione riscriveva l'ordine del giorno
cancellando le note prese nel frattempo in «Conduci incontro».
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from tasks.models import KickoffMeeting, MeetingStatus, TaskRoleAssignment, TaskRoleType
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)

VERSIONE_RE = re.compile(r'name="impronta" value="([0-9a-f]+)"')


def _versione(response) -> str:
    match = VERSIONE_RE.search(response.content.decode())
    assert match, "campo impronta assente"
    return match.group(1)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class KickoffRobustezzaTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create", "tasks_edit"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="ko-robusto", legacy_user_id=7101, role_id=2, role_name="tasks",
        )
        self.collega = _create_user_with_legacy(
            username="ko-collega2", legacy_user_id=7102, role_id=2, role_name="tasks",
        )
        # Ruoli mappati: la condizione che rompeva «Modifica kickoff».
        for ruolo in (TaskRoleType.PROJECT_MANAGER, TaskRoleType.PROGRAMMER, TaskRoleType.CAPOREPARTO):
            TaskRoleAssignment.objects.create(user=self.collega, role_type=ruolo)
        self.project = make_project(
            name="", client_name="Cliente", part_number="PN-R1", created_by=self.user,
            project_manager=self.user,
        )
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data=timezone.localdate() + timedelta(days=2),
            titolo="Avvio",
            partecipanti_email_extra="mario@example.com",
            agenda_items=[{"id": "p1", "titolo": "Disegni", "nota": "", "done": False}],
        )
        self.meeting.partecipanti_utenti.add(self.user)
        self.svolto = KickoffMeeting.objects.create(
            project=self.project, data=timezone.localdate() - timedelta(days=5), titolo="Precedente",
            stato=MeetingStatus.SVOLTO, svolto_at=timezone.now(),
            minuta_chiusa_at=timezone.now(), minuta_chiusa_da=self.user,
            agenda_items=[{"id": "q1", "titolo": "Avvio commessa", "nota": "ok", "done": True}],
        )
        self.client.force_login(self.user)

    def _url(self, name, meeting=None):
        if meeting is None:
            return reverse(name, args=[self.project.id])
        return reverse(name, args=[self.project.id, meeting.id])

    def _post_convocazione(self, versione, **extra):
        dati = {
            "titolo": "Avvio", "data": self.meeting.data.isoformat(), "stato": MeetingStatus.PIANIFICATO,
            "partecipanti_utenti": [self.user.pk], "partecipanti_email_extra": "mario@example.com",
            "agenda_items_raw": json.dumps([{"id": "p1", "titolo": "Disegni rev. B", "nota": "", "done": False}]),
            "impronta": versione,
        }
        dati.update(extra)
        return self.client.post(self._url("tasks:project_meeting_edit", self.meeting), dati)

    # ── 3. Tutte le pagine del kickoff si aprono ─────────────────────────────
    def test_pagine_del_kickoff_rispondono_200(self):
        pagine = [
            self._url("tasks:project_overview"),
            self._url("tasks:project_edit"),
            self._url("tasks:project_gantt"),
            self._url("tasks:project_meetings"),
            self._url("tasks:project_vrf_compile"),
            self._url("tasks:project_meeting_detail", self.meeting),
            self._url("tasks:project_meeting_edit", self.meeting),
            self._url("tasks:project_meeting_minutes", self.meeting),
            self._url("tasks:project_meeting_run", self.meeting),
            self._url("tasks:project_meeting_detail", self.svolto),
        ]
        for url in pagine:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    # ── 1. Convocazione: le note di «Conduci» non si perdono ─────────────────
    def test_convocazione_ferma_il_salvataggio_se_conduci_ha_scritto_nel_frattempo(self):
        versione = _versione(self.client.get(self._url("tasks:project_meeting_edit", self.meeting)))
        # Intanto, in «Conduci incontro», un collega scrive la nota del punto.
        self.client.post(
            self._url("tasks:project_meeting_agenda_item_update", self.meeting),
            {"item_id": "p1", "nota": "Quote da rivedere"},
        )
        response = self._post_convocazione(versione)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "qualcun altro ha modificato questo incontro")
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.agenda_items[0]["nota"], "Quote da rivedere")
        self.assertEqual(self.meeting.agenda_items[0]["titolo"], "Disegni")

        # «Salva comunque»: passa e resta nel registro come forzato.
        response = self._post_convocazione(versione, forza="1")
        self.assertEqual(response.status_code, 302)
        voce = AuditLog.objects.filter(azione="kickoff_meeting_edit").latest("created_at")
        self.assertIn("forzato", voce.dettaglio)

    def test_convocazione_senza_modifiche_altrui_salva(self):
        versione = _versione(self.client.get(self._url("tasks:project_meeting_edit", self.meeting)))
        self.assertEqual(self._post_convocazione(versione).status_code, 302)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.agenda_items[0]["titolo"], "Disegni rev. B")

    def test_pagina_aperta_prima_del_controllo_non_viene_fermata(self):
        self.assertEqual(self._post_convocazione("").status_code, 302)

    # ── Esito: le proprie note salvate da sole non fanno scattare l'avviso ───
    def test_esito_non_si_ferma_per_le_note_dei_punti_salvate_in_pagina(self):
        url = self._url("tasks:project_meeting_minutes", self.meeting)
        versione = _versione(self.client.get(url))
        self.client.post(
            self._url("tasks:project_meeting_agenda_item_update", self.meeting),
            {"item_id": "p1", "nota": "Scritta dalla pagina esito"},
        )
        response = self.client.post(url, {"note": "Verbale", "impronta": versione})
        self.assertEqual(response.status_code, 302)

    def test_esito_si_ferma_se_un_altro_ha_registrato_il_verbale(self):
        url = self._url("tasks:project_meeting_minutes", self.meeting)
        versione = _versione(self.client.get(url))
        KickoffMeeting.objects.filter(pk=self.meeting.pk).update(note="Verbale di un altro")
        response = self.client.post(url, {"note": "Il mio verbale", "impronta": versione})
        self.assertEqual(response.status_code, 200)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.note, "Verbale di un altro")

    # ── 2. Kickoff ───────────────────────────────────────────────────────────
    def _payload_kickoff(self, versione, **extra):
        dati = {
            "client_name": "Cliente Nuovo", "part_number": "PN-R1",
            "project_managers": [self.user.pk], "impronta": versione,
        }
        dati.update(extra)
        return dati

    def test_kickoff_fermato_se_modificato_da_altri(self):
        versione = _versione(self.client.get(self._url("tasks:project_edit")))
        type(self.project).objects.filter(pk=self.project.pk).update(client_name="Cliente Altro")
        response = self.client.post(self._url("tasks:project_edit"), self._payload_kickoff(versione))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "qualcun altro ha modificato questo kickoff")
        self.project.refresh_from_db()
        self.assertEqual(self.project.client_name, "Cliente Altro")

    # ── 6. Avviso a chi entra nel team ───────────────────────────────────────
    def test_chi_entra_nel_team_riceve_la_campanella(self):
        versione = _versione(self.client.get(self._url("tasks:project_edit")))
        with patch("tasks.services.notify.invia_notifica") as invia:
            self.client.post(self._url("tasks:project_edit"), self._payload_kickoff(
                versione, programmers=[self.collega.pk],
            ))
        destinatari = [c.args[0] for c in invia.call_args_list]
        self.assertEqual(destinatari, [7102])
        self.assertIn("Programmatore", invia.call_args_list[0].args[2])

    # ── 7. Storico in pagina ─────────────────────────────────────────────────
    def test_storico_modifiche_in_panoramica_e_nell_incontro(self):
        versione = _versione(self.client.get(self._url("tasks:project_edit")))
        self.client.post(self._url("tasks:project_edit"), self._payload_kickoff(versione))
        panoramica = self.client.get(self._url("tasks:project_overview"))
        self.assertContains(panoramica, "Kickoff modificato")
        self.assertContains(panoramica, "Cliente: Cliente → Cliente Nuovo")

        versione = _versione(self.client.get(self._url("tasks:project_meeting_edit", self.meeting)))
        self._post_convocazione(versione)
        dettaglio = self.client.get(self._url("tasks:project_meeting_detail", self.meeting))
        self.assertContains(dettaglio, "Incontro modificato")
        self.assertContains(dettaglio, "Disegni rev. B")

    # ── 5. Pulsante «Modifica kickoff» solo a chi può aprirla ────────────────
    def test_pulsante_modifica_nascosto_senza_permesso_di_modifica(self):
        _ensure_role(3, "tasks-crea")
        _grant_role_actions(3, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        pm = _create_user_with_legacy(username="ko-solo-crea", legacy_user_id=7103, role_id=3, role_name="tasks-crea")
        progetto = make_project(name="Suo", client_name="C", created_by=pm, project_manager=pm)
        self.client.force_login(pm)
        url_modifica = reverse("tasks:project_edit", args=[progetto.id])
        for nome in ("tasks:project_overview", "tasks:project_gantt"):
            with self.subTest(pagina=nome):
                pagina = self.client.get(reverse(nome, args=[progetto.id]))
                self.assertEqual(pagina.status_code, 200)
                self.assertNotContains(pagina, url_modifica)
