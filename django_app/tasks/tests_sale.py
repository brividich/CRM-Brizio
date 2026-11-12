"""Sale riunioni: prenotazione via Outlook, disponibilità del giorno, gestione (09/11/2026)."""
from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

from .models import KickoffMeeting, MeetingRoom
from .services import sale as svc
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SaleBase(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="sale-pm", legacy_user_id=711, role_id=2, role_name="tasks")
        self.user.email = "pm@example.com"
        self.user.save(update_fields=["email"])
        self.collega = _create_user_with_legacy(username="sale-col", legacy_user_id=712, role_id=2, role_name="tasks")
        self.collega.email = "collega@example.com"
        self.collega.save(update_fields=["email"])
        self.project = make_project(name="Commessa sale", created_by=self.user, project_manager=self.user)
        self.sala = MeetingRoom.objects.create(nome="Sala Prova", email="sala.prova@example.com", capienza=8)
        self.sala_locale = MeetingRoom.objects.create(nome="Saletta", ordine=2)
        self.client.force_login(self.user)

    def incontro(self, **altri):
        dati = {"project": self.project, "data": date(2026, 12, 1), "ora": time(10, 0), "sala": self.sala, "created_by": self.user}
        return KickoffMeeting.objects.create(**{**dati, **altri})


class OutlookPrenotazioneTests(SaleBase):
    def test_sala_invitata_come_risorsa(self):
        m = self.incontro(sync_outlook=True, partecipanti_email_extra="esterno@example.com")
        m.partecipanti_utenti.add(self.collega)
        from .meeting_outlook import sync_meeting_outlook_event

        with patch("tasks.meeting_outlook.graph_ready", return_value=True), \
                patch("tasks.meeting_outlook.create_event", return_value={"id": "EV1", "webLink": "https://x"}) as crea:
            livello, testo = sync_meeting_outlook_event(request=None, meeting=m)
        self.assertEqual(livello, "success")
        payload = crea.call_args.kwargs["payload"]
        self.assertEqual(payload["location"]["locationEmailAddress"], "sala.prova@example.com")
        self.assertEqual(payload["location"]["locationType"], "conferenceRoom")
        risorse = [a for a in payload["attendees"] if a["type"] == "resource"]
        self.assertEqual([a["emailAddress"]["address"] for a in risorse], ["sala.prova@example.com"])
        persone = {a["emailAddress"]["address"] for a in payload["attendees"] if a["type"] == "required"}
        self.assertEqual(persone, {"collega@example.com", "esterno@example.com"})
        self.assertIn("2 partecipanti", testo)
        self.assertIn("richiesta di prenotazione inviata alla sala Sala Prova", testo)

    def test_cc_ricevono_invito_come_facoltativi(self):
        m = self.incontro(sync_outlook=True, cc_email_extra="copia@example.com\ncollega@example.com")
        m.partecipanti_utenti.add(self.collega)
        from .meeting_outlook import sync_meeting_outlook_event

        with patch("tasks.meeting_outlook.graph_ready", return_value=True), \
                patch("tasks.meeting_outlook.create_event", return_value={"id": "EV1"}) as crea:
            _livello, testo = sync_meeting_outlook_event(request=None, meeting=m)
        att = crea.call_args.kwargs["payload"]["attendees"]
        facoltativi = [a["emailAddress"]["address"] for a in att if a["type"] == "optional"]
        self.assertEqual(facoltativi, ["copia@example.com"])  # il convocato non è ripetuto in copia
        self.assertIn("1 partecipanti, 1 in copia", testo)
        self.assertEqual(m.dati_convocazione()["cc"], ["collega@example.com", "copia@example.com"])

    def test_sala_senza_casella_non_si_prenota(self):
        m = self.incontro(sala=self.sala_locale, sync_outlook=True)
        from .meeting_outlook import sync_meeting_outlook_event

        with patch("tasks.meeting_outlook.graph_ready", return_value=True), \
                patch("tasks.meeting_outlook.create_event", return_value={"id": "EV1"}) as crea:
            _livello, testo = sync_meeting_outlook_event(request=None, meeting=m)
        self.assertNotIn("attendees", crea.call_args.kwargs["payload"])
        self.assertIn("non prenotata in Outlook", testo)

    def test_verifica_risposta_sala(self):
        m = self.incontro(outlook_event_id="EV1", outlook_organizer_email="pm@example.com")
        evento = {"attendees": [{"emailAddress": {"address": "Sala.Prova@example.com"}, "status": {"response": "accepted"}}]}
        with patch("core.outlook_calendar.graph_ready", return_value=True), \
                patch("core.outlook_calendar.get_event", return_value=evento):
            risposta = self.client.post(reverse("tasks:sala_verifica", args=[self.project.pk, m.pk]), HTTP_ACCEPT="application/json")
        self.assertEqual(risposta.json()["label"], "Sala confermata")
        m.refresh_from_db()
        self.assertEqual(m.sala_risposta, "accepted")

    def test_dettaglio_mostra_stato_sala(self):
        m = self.incontro(outlook_event_id="EV1", outlook_organizer_email="pm@example.com", sala_risposta="declined")
        pagina = self.client.get(reverse("tasks:project_meeting_detail", args=[self.project.pk, m.pk]))
        self.assertContains(pagina, "Sala rifiutata")


class DisponibilitaTests(SaleBase):
    def url(self, **params):
        return reverse("tasks:sale_disponibilita") + "?" + "&".join(f"{k}={v}" for k, v in params.items())

    def test_incontri_del_portale_senza_outlook(self):
        self.incontro()
        risposta = self.client.get(self.url(data="2026-12-01"), HTTP_ACCEPT="application/json").json()
        sala = next(s for s in risposta["sale"] if s["nome"] == "Sala Prova")
        self.assertEqual(sala["blocchi"][0]["inizio"], "10:00")
        self.assertEqual(sala["blocchi"][0]["fine"], "11:00")
        self.assertEqual(risposta["outlook"], "non_configurato")

    def test_escludi_incontro_corrente(self):
        m = self.incontro()
        risposta = self.client.get(self.url(data="2026-12-01", escludi=m.pk), HTTP_ACCEPT="application/json").json()
        self.assertTrue(all(not s["blocchi"] for s in risposta["sale"]))

    def test_outlook_sale_e_partecipanti(self):
        occupato = [{"start": datetime(2026, 12, 1, 14, 0), "end": datetime(2026, 12, 1, 15, 30), "status": "busy"}]
        calendario = {"sala.prova@example.com": occupato, "collega@example.com": occupato}
        with patch("core.outlook_calendar.graph_ready", return_value=True), \
                patch("core.outlook_calendar.get_schedule", return_value=calendario) as gs:
            risposta = self.client.get(self.url(data="2026-12-01", utenti=self.collega.pk), HTTP_ACCEPT="application/json").json()
        self.assertEqual(gs.call_args.kwargs["organizer_email"], "pm@example.com")
        sala = next(s for s in risposta["sale"] if s["nome"] == "Sala Prova")
        self.assertEqual(sala["blocchi"][0]["fonte"], "outlook")
        self.assertEqual(risposta["partecipanti"]["n"], 1)
        self.assertIn("occupato", risposta["partecipanti"]["blocchi"][0]["titolo"])

    def test_outlook_in_errore_resta_il_portale(self):
        self.incontro()
        with patch("core.outlook_calendar.graph_ready", return_value=True), \
                patch("core.outlook_calendar.get_schedule", side_effect=RuntimeError("Access is denied [HTTP 403]")):
            risposta = self.client.get(self.url(data="2026-12-01"), HTTP_ACCEPT="application/json").json()
        self.assertEqual(risposta["outlook"], "errore")
        self.assertTrue(any(s["blocchi"] for s in risposta["sale"]))

    def test_data_non_valida(self):
        self.assertEqual(self.client.get(self.url(data="x"), HTTP_ACCEPT="application/json").status_code, 400)

    def test_conflitti_portale(self):
        self.incontro()
        nuovo = self.incontro(ora=time(10, 30))
        self.assertTrue(svc.conflitti_portale(nuovo))
        libero = self.incontro(ora=time(12, 0))
        self.assertEqual(svc.conflitti_portale(libero), [])


class FormSalaTests(SaleBase):
    def test_form_ha_sala_e_griglia(self):
        pagina = self.client.get(reverse("tasks:project_meeting_create", args=[self.project.pk]))
        self.assertContains(pagina, "Disponibilità del giorno")
        self.assertContains(pagina, "Sala Prova")
        self.assertContains(pagina, "sale_disponibilita.js")
        self.assertContains(pagina, "Prenota la sala e invita in Outlook")

    def test_sala_diventa_il_luogo(self):
        from .forms import KickoffMeetingForm

        form = KickoffMeetingForm(data={"data": "2026-12-01", "ora": "10:00", "sala": self.sala.pk, "luogo": "", "stato": "PIANIFICATO"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["luogo"], "Sala Prova")

    def test_sala_disattivata_non_proposta(self):
        self.sala_locale.attiva = False
        self.sala_locale.save()
        from .forms import KickoffMeetingForm

        self.assertNotIn(self.sala_locale, list(KickoffMeetingForm().fields["sala"].queryset))


class ImpostazioniSaleTests(SaleBase):
    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()

    def test_aggiungi_modifica_elimina(self):
        url = reverse("tasks:impostazioni")
        self.client.post(url, {"tab": "sale", "sala_action": "nuova", "nome": "Sala Nuova", "email": "nuova@example.com", "capienza": "6"})
        nuova = MeetingRoom.objects.get(nome="Sala Nuova")
        self.assertEqual((nuova.email, nuova.capienza, nuova.attiva), ("nuova@example.com", 6, True))
        self.client.post(url, {"tab": "sale", "sala_action": "salva", "sala_id": nuova.pk, "nome": "Sala Nuova", "email": ""})
        nuova.refresh_from_db()
        self.assertEqual((nuova.email, nuova.attiva), ("", False))
        self.client.post(url, {"tab": "sale", "sala_action": "elimina", "sala_id": nuova.pk})
        self.assertFalse(MeetingRoom.objects.filter(pk=nuova.pk).exists())

    def test_email_non_valida_rifiutata(self):
        self.client.post(reverse("tasks:impostazioni"), {"tab": "sale", "sala_action": "nuova", "nome": "X", "email": "nonvalida"})
        self.assertFalse(MeetingRoom.objects.filter(nome="X").exists())

    def test_sala_con_incontri_solo_disattivata(self):
        self.incontro()
        self.client.post(reverse("tasks:impostazioni"), {"tab": "sale", "sala_action": "elimina", "sala_id": self.sala.pk})
        self.sala.refresh_from_db()
        self.assertFalse(self.sala.attiva)

    def test_pagina_impostazioni_elenca_sale(self):
        pagina = self.client.get(reverse("tasks:impostazioni") + "?tab=sale")
        self.assertContains(pagina, "Sale riunioni")
        self.assertContains(pagina, "sala.prova@example.com")

    def test_rotte_con_binding(self):
        from core.models import RoutePermissionBinding

        from .acl_bootstrap import bootstrap_tasks_acl_endpoints

        bootstrap_tasks_acl_endpoints(force=True)
        for nome in ("tasks:sale_disponibilita", "tasks:sala_verifica"):
            self.assertTrue(RoutePermissionBinding.objects.filter(route_name=nome).exists(), nome)


class GetScheduleTests(SaleBase):
    def test_parsing_risposta_graph(self):
        from unittest.mock import MagicMock

        from core import outlook_calendar

        risposta = MagicMock(status_code=200)
        risposta.json.return_value = {"value": [
            {"scheduleId": "Sala.Prova@example.com", "scheduleItems": [
                {"status": "busy", "start": {"dateTime": "2026-12-01T09:00:00.0000000"}, "end": {"dateTime": "2026-12-01T10:00:00.0000000"}},
                {"status": "free", "start": {"dateTime": "2026-12-01T11:00:00"}, "end": {"dateTime": "2026-12-01T12:00:00"}},
            ]},
            {"scheduleId": "nessuno@example.com", "error": {"message": "not found"}},
        ]}
        with patch.object(outlook_calendar, "_headers", return_value={}), \
                patch.object(outlook_calendar.requests, "post", return_value=risposta) as post:
            esito = outlook_calendar.get_schedule(
                organizer_email="pm@example.com", emails=["sala.prova@example.com", "nessuno@example.com"],
                start=datetime(2026, 12, 1, 8), end=datetime(2026, 12, 1, 19),
            )
        self.assertIn("getSchedule", post.call_args.args[0])
        self.assertEqual(list(esito), ["sala.prova@example.com"])
        self.assertEqual(esito["sala.prova@example.com"][0]["start"], datetime(2026, 12, 1, 9, 0))
        self.assertEqual(len(esito["sala.prova@example.com"]), 1)


class DurataTests(SaleBase):
    def test_durata_scelta_vale_per_sala_e_outlook(self):
        m = self.incontro(durata_minuti=150, sync_outlook=True)
        self.assertEqual(svc.finestra_incontro(m)[1].time(), time(12, 30))
        from .meeting_outlook import sync_meeting_outlook_event

        with patch("tasks.meeting_outlook.graph_ready", return_value=True), \
                patch("tasks.meeting_outlook.create_event", return_value={"id": "EV1"}) as crea:
            sync_meeting_outlook_event(request=None, meeting=m)
        self.assertEqual(crea.call_args.kwargs["payload"]["end"]["dateTime"], "2026-12-01T12:30:00")

    def test_senza_durata_vale_l_ordine_del_giorno(self):
        m = self.incontro(agenda_items=[{"id": "a", "titolo": "Punto", "durata_minuti": 45}])
        self.assertEqual(svc.finestra_incontro(m)[1].time(), time(10, 45))

    def test_form_salva_la_durata(self):
        from .forms import KickoffMeetingForm

        form = KickoffMeetingForm(data={"data": "2026-12-01", "ora": "10:00", "durata_minuti": "90", "stato": "PIANIFICATO"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["durata_minuti"], 90)
        self.assertContains(self.client.get(reverse("tasks:project_meeting_create", args=[self.project.pk])), "Dall&#x27;ordine del giorno")


class InvitoOutlookTests(SaleBase):
    def test_invito_vale_come_convocazione_e_non_si_ripete(self):
        from .meeting_outlook import sync_meeting_outlook_event

        m = self.incontro(sync_outlook=True, partecipanti_email_extra="esterno@example.com")
        with patch("tasks.meeting_outlook.graph_ready", return_value=True), \
                patch("tasks.meeting_outlook.create_event", return_value={"id": "EV1"}):
            livello, testo = sync_meeting_outlook_event(request=None, meeting=m)
        self.assertIn("Invito Outlook inviato", testo)
        m.refresh_from_db()
        self.assertTrue(m.convocazione_inviata)
        self.assertFalse(m.convocazione_da_reinviare)
        with patch("tasks.meeting_outlook.graph_ready", return_value=True), \
                patch("tasks.meeting_outlook.update_event", return_value={}) as aggiorna:
            self.assertEqual(sync_meeting_outlook_event(request=None, meeting=m), ("", ""))
            aggiorna.assert_not_called()
            m.ora = time(11, 0)
            m.save()
            livello, _ = sync_meeting_outlook_event(request=None, meeting=m)
            aggiorna.assert_called_once()
        self.assertEqual(livello, "success")

    def test_mail_senza_ics_se_c_e_l_invito(self):
        from .minute_email import send_meeting_invite

        m = self.incontro(outlook_event_id="EV1", partecipanti_email_extra="esterno@example.com")
        with patch("core.email_utils.send_hub_mail", return_value=1) as invio:
            send_meeting_invite(m)
        self.assertIsNone(invio.call_args.kwargs["attachments"])
        self.assertIn("invito Outlook", invio.call_args.args[1])

    def test_mail_con_ics_senza_outlook(self):
        from .minute_email import send_meeting_invite

        m = self.incontro(partecipanti_email_extra="esterno@example.com")
        with patch("core.email_utils.send_hub_mail", return_value=1) as invio:
            send_meeting_invite(m)
        self.assertEqual(invio.call_args.kwargs["attachments"][0][0], "convocazione-incontro.ics")

    def test_pulsante_invia_invito_outlook(self):
        m = self.incontro(partecipanti_email_extra="esterno@example.com")
        with patch("tasks.views.meetings._outlook_pronto", return_value=True):
            pagina = self.client.get(reverse("tasks:project_meeting_detail", args=[self.project.pk, m.pk]))
        self.assertContains(pagina, "Invia invito Outlook")
        with patch("tasks.meeting_outlook.graph_ready", return_value=True), \
                patch("tasks.meeting_outlook.create_event", return_value={"id": "EV9"}) as crea:
            self.client.post(reverse("tasks:project_meeting_send_outlook", args=[self.project.pk, m.pk]))
        crea.assert_called_once()
        m.refresh_from_db()
        self.assertTrue(m.sync_outlook)
        self.assertEqual(m.outlook_event_id, "EV9")

    def test_firma_invariata_per_incontri_senza_sala_e_durata(self):
        m = self.incontro(sala=None)
        self.assertNotIn("sala", m.dati_convocazione())
        self.assertNotIn("durata", m.dati_convocazione())


class ImpostazioniProtetteTests(SaleBase):
    """Regressione 09/11: il controllo d'accesso era finito sulla funzione delle sale invece che sulla pagina."""

    def test_pagina_impostazioni_ha_il_controllo(self):
        from .views import settings as vs

        self.assertTrue(hasattr(vs.impostazioni, "__wrapped__"), "impostazioni senza decoratore di accesso")
        self.assertFalse(hasattr(vs._handle_tasks_rooms_post, "__wrapped__"))

    def test_utente_senza_permesso_non_entra(self):
        risposta = self.client.get(reverse("tasks:impostazioni"))
        self.assertNotEqual(risposta.status_code, 200)
        risposta = self.client.post(reverse("tasks:impostazioni"), {"tab": "sale", "sala_action": "nuova", "nome": "Abusiva"})
        self.assertFalse(MeetingRoom.objects.filter(nome="Abusiva").exists())
