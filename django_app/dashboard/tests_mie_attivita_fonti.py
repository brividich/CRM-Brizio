"""«Le mie attività»: voci assegnate nei moduli che prima non comparivano."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tasks.models import Project, SubTask, Task, TaskStatus
from tasks.tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project


class MieAttivitaFontiTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="ma-utente", legacy_user_id=741, role_id=2, role_name="tasks")
        self.altro = _create_user_with_legacy(username="ma-altro", legacy_user_id=742, role_id=2, role_name="tasks")
        self.client.force_login(self.user)

    def _request(self):
        return SimpleNamespace(user=self.user, legacy_user=None)

    def _pagina(self):
        return self.client.get(reverse("mie_attivita")).content.decode()

    # -- KICK-OFF -----------------------------------------------------------

    def test_attivita_senza_commessa_compare(self):
        Task.objects.create(title="Attività-senza-commessa", created_by=self.altro, assigned_to=self.user)
        self.assertIn("Attività-senza-commessa", self._pagina())

    def test_sotto_attivita_assegnata_compare_e_apre_la_madre(self):
        progetto = make_project(name="Commessa X", created_by=self.altro)
        madre = Task.objects.create(title="Madre-altrui", project=progetto, created_by=self.altro, assigned_to=self.altro)
        SubTask.objects.create(task=madre, title="Sotto-mia", assigned_to=self.user, due_date=date.today() + timedelta(days=3))
        self.assertIn("Sotto-mia", self._pagina())
        self.assertEqual(self.client.get(reverse("tasks:detail", args=[madre.pk])).status_code, 200)

    def test_sotto_attivita_chiusa_non_compare(self):
        madre = Task.objects.create(title="Madre", created_by=self.altro, assigned_to=self.altro)
        SubTask.objects.create(task=madre, title="Sotto-chiusa", assigned_to=self.user, status=TaskStatus.DONE)
        self.assertNotIn("Sotto-chiusa", self._pagina())

    # -- Ticket ---------------------------------------------------------------

    def test_ticket_trovati_per_utente_tecnico_e_nome_inverso(self):
        from dashboard.views import _board_related_tickets_queryset
        from tickets.models import Ticket, TicketIntervento

        self.user.first_name, self.user.last_name = "Mario", "Rossi"
        self.user.save()
        per_conto = Ticket.objects.create(titolo="Aperto per conto", aperto_da_user=self.user)
        inverso = Ticket.objects.create(titolo="Nome inverso", assegnato_a="Rossi Mario")
        tecnico = Ticket.objects.create(titolo="Da tecnico")
        TicketIntervento.objects.create(ticket=tecnico, tecnico_nome="x", tecnico_email="ma-utente@example.local",
                                        data_inizio=timezone.now())
        Ticket.objects.create(titolo="Di altri", assegnato_a="Luigi Verdi")
        self.user.email = "ma-utente@example.local"
        self.user.save()
        trovati = set(_board_related_tickets_queryset(self.user, None, None).values_list("pk", flat=True))
        self.assertTrue({per_conto.pk, inverso.pk, tecnico.pk} <= trovati)
        self.assertEqual(len(trovati), 3)

    # -- Altri moduli ---------------------------------------------------------

    def test_attrezzature_assegnate_anche_senza_scadenza(self):
        from attrezzature.models import AttrezzaturaTask
        from dashboard.mie_attivita_fonti import assegnate

        AttrezzaturaTask.objects.create(titolo="Attrezzo-mio", assegnato_a=self.user)
        AttrezzaturaTask.objects.create(titolo="Attrezzo-chiuso", assegnato_a=self.user, stato="completata")
        titoli = [v["title"] for v in assegnate(self._request())]
        self.assertIn("Attrezzo-mio", titoli)
        self.assertNotIn("Attrezzo-chiuso", titoli)

    def test_checklist_trova_il_responsabile_con_l_id_legacy(self):
        from checklist_operativa.models import ChiusuraEvento, ChiusuraVoce
        from core.legacy_models import AnagraficaDipendente
        from dashboard.mie_attivita_fonti import assegnate

        dip = AnagraficaDipendente.objects.create(nome="Ma", cognome="Utente", utente_id=741)
        evento = ChiusuraEvento.objects.create(nome="Chiusura estiva", data_inizio=date.today())
        ChiusuraVoce.objects.create(evento=evento, descrizione="Spegnere-compressore", responsabile=dip)
        ChiusuraVoce.objects.create(evento=evento, descrizione="Gia-fatto", responsabile=dip, confermato=True)
        titoli = [v["title"] for v in assegnate(SimpleNamespace(user=self.user, legacy_user=SimpleNamespace(id=741)))]
        self.assertIn("Spegnere-compressore", titoli)
        self.assertNotIn("Gia-fatto", titoli)

    def test_sezioni_nuove_in_pagina(self):
        pagina = self._pagina()
        self.assertIn("Approvazioni e richieste", pagina)
        self.assertIn("Altre voci assegnate a te", pagina)
        self.assertIn("Ordini di lavoro", pagina)


class ApprovazioniAssenzeMieTests(TestCase):
    """«Approvazioni assenze»: le richieste che aspettano me come capo, con le date."""

    RIGA = {"tipo": "Ferie", "dipendente": "Persona Prova", "inizio_label": "20/11/2026", "fine_label": "21/11/2026"}

    def _voci(self, ruolo):
        from types import SimpleNamespace
        from unittest import mock

        from dashboard import views_mie_attivita as ma

        utente = SimpleNamespace(id=42, ruolo=ruolo)
        with mock.patch("assenze.views._load_pending_for_manager", return_value=[self.RIGA]) as mie, \
                mock.patch.object(ma, "_board_data_assenze_da_approvare", return_value=[self.RIGA, self.RIGA]) as tutte:
            return ma._my_approvals(utente, True), mie, tutte

    def test_un_amministratore_vede_solo_le_sue_con_le_date(self):
        voci, mie, tutte = self._voci("ADMIN")
        self.assertEqual([(v["title"], v["meta"], v["status"]) for v in voci], [("Ferie", "Persona Prova", "20/11/2026 → 21/11/2026")])
        mie.assert_called_once_with(42, limit=12)
        tutte.assert_not_called()

    def test_l_ufficio_amministrazione_le_vede_tutte(self):
        voci, mie, _ = self._voci("Amministrazione")
        self.assertEqual(len(voci), 2)
        mie.assert_not_called()
