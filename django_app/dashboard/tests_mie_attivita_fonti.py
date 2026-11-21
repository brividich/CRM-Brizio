"""«Le mie attività»: voci assegnate nei moduli che prima non comparivano."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tasks.models import SubTask, Task, TaskStatus
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
    """«Assenze della squadra»: le richieste che aspettano me come capo, con le date."""

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
        mie.assert_called_once_with(42, limit=12, manager_name="", manager_email="")
        tutte.assert_not_called()

    def test_l_ufficio_amministrazione_le_vede_tutte(self):
        voci, mie, _ = self._voci("Amministrazione")
        self.assertEqual(len(voci), 2)
        mie.assert_not_called()


class FontiDaAuditTests(TestCase):
    """Fonti aggiunte dopo il controllo dei moduli: SDS, spostamenti, team SMS, ticket del team."""

    def setUp(self):
        from django.test import RequestFactory

        self.user = get_user_model().objects.create_user(username="gestore", password="x", email="gestore@esempio.example")
        self.request = RequestFactory().get("/")
        self.request.user = self.user

    def test_schede_di_sicurezza_da_leggere(self):
        from unittest import mock

        from dashboard import mie_attivita_fonti as fonti

        profilo = SimpleNamespace(da_leggere=[SimpleNamespace(prodotto=SimpleNamespace(nome="Solvente X"))])
        with mock.patch("schede_sicurezza.services.assegnazioni.profilo_sds_utente", return_value=profilo):
            voci = fonti._sds(self.user)
        self.assertEqual([(v["code"], v["title"], v["status"]) for v in voci], [("SDS", "Solvente X", "Da leggere")])
        self.assertEqual(voci[0]["url"], reverse("schede_sicurezza:sds_da_leggere"))

    def test_spostamenti_da_decidere(self):
        from unittest import mock

        from dashboard import mie_attivita_fonti as fonti

        sp = SimpleNamespace(
            richiesto_da=self.user, inizio_nuovo=date(2026, 12, 1), fine_nuovo=date(2026, 12, 5), motivo="Materiale in ritardo",
            task=SimpleNamespace(title="Attrezzaggio", project=SimpleNamespace(name="Commessa 1")),
        )
        with mock.patch("tasks.services.spostamenti.richieste_da_decidere", return_value=[sp]),                 mock.patch("tasks.access.scoped_projects_queryset"):
            voce = fonti._spostamenti(self.request)[0]
        self.assertEqual(voce["title"], "Attrezzaggio · Commessa 1")
        self.assertIn("nuove date 01/12/2026 → 05/12/2026", voce["meta"])
        self.assertEqual(voce["status"], "Da decidere")

    def test_team_sms_vede_le_segnalazioni_da_classificare(self):
        from django.contrib.auth.models import Group

        from dashboard import mie_attivita_fonti as fonti
        from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig

        S = SuggestionCorner.Stato
        with_stato = SimpleNamespace(pk=5, opportunity="Corrimano scala", stato_label="Da classificare")
        from unittest import mock

        with mock.patch.object(SuggestionCorner.objects, "filter") as filtro:
            filtro.return_value.order_by.return_value.__getitem__.return_value = [with_stato]
            self.assertEqual(fonti._suggestion_team(self.user), [])  # fuori dal team: niente
            self.user.groups.add(Group.objects.get_or_create(name=SuggestionCornerConfig.load().sms_team_group_name)[0])
            voci = fonti._suggestion_team(self.user)
        self.assertEqual([(v["code"], v["status"]) for v in voci], [("SC#5", "Da classificare")])
        filtro.assert_called_once_with(stato__in=(S.INSERITA, S.DA_CLASSIFICARE, S.CLASSIFICATA))

    def test_ticket_del_team_senza_assegnatario(self):
        from unittest import mock

        from dashboard import mie_attivita_fonti as fonti
        from tickets.models import StatoTicket, Ticket, TicketImpostazioni, TipoTicket

        TicketImpostazioni.objects.update_or_create(
            tipo=TipoTicket.IT, defaults={"team_gestori": [{"nome": "Gestore", "email": "Gestore@esempio.example"}]},
        )
        TicketImpostazioni.objects.update_or_create(tipo=TipoTicket.MAN, defaults={"team_gestori": []})
        campi = {"titolo": "Stampante ferma", "descrizione": "x", "richiedente_nome": "Persona Prova"}
        libero = Ticket.objects.create(tipo=TipoTicket.IT, stato=StatoTicket.APERTA, **campi)
        Ticket.objects.create(tipo=TipoTicket.IT, stato=StatoTicket.APERTA, assegnato_a="Altro Tecnico", **campi)
        Ticket.objects.create(tipo=TipoTicket.MAN, stato=StatoTicket.APERTA, **campi)  # non è il mio team
        Ticket.objects.create(tipo=TipoTicket.IT, stato=StatoTicket.CHIUSO, **campi)
        with mock.patch("tickets.views._can_manage_tickets", return_value=True):
            esito = fonti.ticket_team_da_assegnare(self.request)
        self.assertEqual(esito["total"], 1)
        self.assertEqual(esito["items"][0]["url"], reverse("tickets:gestione_detail", args=[libero.pk]))
        with mock.patch("tickets.views._can_manage_tickets", return_value=False):
            self.assertEqual(fonti.ticket_team_da_assegnare(self.request)["total"], 0)


class FontiSecondaTornataTests(TestCase):
    """Segnalazioni di modifica, rilevazioni di sicurezza, manutenzioni, onboarding, riepilogo assenze."""

    def setUp(self):
        from django.test import RequestFactory

        self.user = get_user_model().objects.create_user(username="resp", password="x", email="resp@esempio.example")
        self.request = RequestFactory().get("/")
        self.request.user = self.user
        self.request.legacy_user = SimpleNamespace(id=77, nome="Resp", email="resp@esempio.example", ruolo="")

    def test_rilevazioni_di_sicurezza_solo_per_chi_chiude(self):
        from unittest import mock

        from dashboard import mie_attivita_fonti as fonti
        from rilevazione_incidenti.models import RilevazioneIncidente

        ora = timezone.now()
        RilevazioneIncidente.objects.create(nominativo="Persona Prova", tipologia_scheda="Near Miss", reparto="Tornitura", data_segnalazione=ora)
        RilevazioneIncidente.objects.create(nominativo="Persona Prova", tipologia_scheda="Near Miss", reparto="Fresatura",
                                            data_segnalazione=ora, approvazione_rls="Approvato")
        RilevazioneIncidente.objects.create(nominativo="Persona Prova", tipologia_scheda="Near Miss", reparto="Chiusa",
                                            data_segnalazione=ora, chiusura_rspp=True)
        RilevazioneIncidente.objects.create(nominativo="Persona Prova", tipologia_scheda="Near Miss", reparto="Vecchia",
                                            data_segnalazione=ora - timedelta(days=500))
        with mock.patch("rilevazione_incidenti.views._can_manage_rspp", return_value=False):
            self.assertEqual(fonti._incidenti(self.request), [])
        with mock.patch("rilevazione_incidenti.views._can_manage_rspp", return_value=True), \
                mock.patch("rilevazione_incidenti.views._use_local", return_value=True):
            voci = fonti._incidenti(self.request)
        stati = {v["title"].split(" · ")[-1]: v["status"] for v in voci}
        self.assertEqual(stati, {"Tornitura": "In attesa RLS", "Fresatura": "Da chiudere (RSPP)"})

    def test_onboarding_una_riga_per_pratica(self):
        from unittest import mock

        from anagrafica.models import OnboardingPratica, OnboardingTask
        from dashboard import mie_attivita_fonti as fonti

        pr = OnboardingPratica.objects.create(dipendente_nome="Nuovo Assunto", reparto="Tornitura")
        ieri = date.today() - timedelta(days=1)
        OnboardingTask.objects.create(pratica=pr, codice="a", titolo="Contratto", categoria="HR", scadenza=ieri)
        OnboardingTask.objects.create(pratica=pr, codice="b", titolo="Badge", categoria="HR")
        OnboardingTask.objects.create(pratica=pr, codice="c", titolo="Account", categoria="IT")
        OnboardingTask.objects.create(pratica=pr, codice="d", titolo="Fatto", categoria="HR", stato="COMPLETATO")
        cfg = {"emails": [], "utenti_ids": [], "ticket": False}
        with mock.patch("anagrafica.views._helpers._check_hr_permission", return_value=False), \
                mock.patch("anagrafica.services.avviso_it_ingresso.configurazione", return_value=cfg):
            self.assertEqual(fonti._onboarding(self.request), [])
        with mock.patch("anagrafica.views._helpers._check_hr_permission", return_value=True), \
                mock.patch("anagrafica.services.avviso_it_ingresso.configurazione", return_value=cfg):
            voci = fonti._onboarding(self.request)
        self.assertEqual([(v["title"], v["status"], v["due"]) for v in voci], [("Nuovo Assunto", "2 voci da fare, 1 in ritardo", ieri)])
        self.assertEqual(voci[0]["url"], reverse("anagrafica:onboarding_detail", args=[pr.pk]))
        solo_it = {"emails": ["resp@esempio.example"], "utenti_ids": [], "ticket": False}
        with mock.patch("anagrafica.views._helpers._check_hr_permission", return_value=False), \
                mock.patch("anagrafica.services.avviso_it_ingresso.configurazione", return_value=solo_it):
            voci = fonti._onboarding(self.request)
        self.assertEqual([(v["status"], v["url"]) for v in voci], [("1 voce da fare", "#")])

    def test_segnalazioni_di_modifica_e_manutenzioni_interrogano_senza_errori(self):
        from unittest import mock

        from dashboard import mie_attivita_fonti as fonti

        self.assertEqual(fonti._manutenzioni(self.user), [])
        with mock.patch("procedure_refresh.segnalazioni.destinatari_gestori", return_value={77}), \
                mock.patch("procedure_refresh.views._can_manage", return_value=True):
            self.assertEqual(fonti._segnalazioni_modifica(self.request), [])
        with mock.patch("procedure_refresh.segnalazioni.destinatari_gestori", return_value={1}), \
                mock.patch("procedure_refresh.views._can_manage", return_value=True) as gate:
            self.assertEqual(fonti._segnalazioni_modifica(self.request), [])
            gate.assert_not_called()

    def test_riepilogo_assenze_da_accettare_e_accettate(self):
        from unittest import mock

        from assenze.views._helpers import riepilogo_per_capo
        from dashboard import views_mie_attivita as ma

        self.assertEqual(set(riepilogo_per_capo(77, tutte=True)), {"da_approvare", "approvate", "prossime"})
        da_fare = [{"title": "Ferie", "meta": "Persona Prova", "status": "20/11/2026 → 21/11/2026", "url": "/x"}]
        riepilogo = {"da_approvare": 4, "approvate": 1, "prossime": [
            {"dipendente": "Altra Persona", "tipo": "Permesso", "inizio_label": "25-11-2026 08:00", "fine_label": "25-11-2026 12:00"}]}
        with mock.patch.object(ma, "_my_approvals", return_value=da_fare), \
                mock.patch("assenze.views._helpers.riepilogo_per_capo", return_value=riepilogo):
            s = ma._assenze_squadra(self.request.legacy_user, False)
        self.assertEqual(s["nota"], "4 da accettare · 1 accettata in corso o in arrivo")
        self.assertEqual([i["status"] for i in s["items"]], ["20/11/2026 → 21/11/2026", "Accettata"])
        self.assertEqual((s["total"], s["informative"]), (5, 1))
