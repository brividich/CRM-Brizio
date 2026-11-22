"""Incontro, fase «Prima»: ordine del giorno modificabile dalla scheda, convocazione, incontri precedenti."""
from __future__ import annotations

from django.urls import reverse
from django.utils import timezone

from .models import (
    KickoffMeeting,
    MeetingActionItem,
    MeetingAgendaProposal,
    MeetingDecision,
    MeetingIssue,
    MeetingStatus,
    Task,
)
from .services.filo_incontro import dagli_incontri_precedenti
from .tests_filo import FiloBase
from .tests_utils import _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class IncontroPrimaBase(FiloBase):
    def setUp(self):
        super().setUp()
        self.project = make_project(name="Commessa prima", created_by=self.user, project_manager=self.user)
        self.m = KickoffMeeting.objects.create(
            project=self.project, data=timezone.localdate(), created_by=self.user, titolo="Avanzamento",
            luogo="Sala riunioni",
            agenda_items=[
                {"id": "a", "titolo": "Stato del programma", "nota": "nota di a"},
                {"id": "b", "titolo": "Arrivo materiale"},
                {"id": "c", "titolo": "Piano di controllo", "done": True},
            ],
        )
        self.ids = [self.project.pk, self.m.pk]

    def url(self, nome, *extra):
        return reverse(f"tasks:{nome}", args=[*self.ids, *extra])

    def scheda(self, **params):
        return self.client.get(self.url("project_meeting_detail"), params)

    def ordine(self):
        self.m.refresh_from_db()
        return [i["id"] for i in self.m.agenda_items]

    def segna_convocazione_inviata(self):
        self.m.refresh_from_db()
        self.m.convocazione_inviata_at = timezone.now()
        campi = self.m.registra_convocazione_inviata()
        self.m.save(update_fields=["convocazione_inviata_at", *campi])

    def lettore(self):
        """Un collega che vede il modulo ma non gestisce la commessa (e non crea)."""
        _ensure_role(3, "tasks-lettura")
        _grant_role_actions(3, ["tasks_view"])
        self._refresh_acl_cache()
        lettore = _create_user_with_legacy(username="prima-lettore", legacy_user_id=912, role_id=3, role_name="tasks-lettura")
        # Ha un'attività nella commessa: la vede, ma non la gestisce.
        Task.objects.create(project=self.project, title="Attività del lettore", created_by=self.user, assigned_to=lettore)
        return lettore


class SchedaPrimaTests(IncontroPrimaBase):
    def test_due_riquadri_e_comandi_per_chi_gestisce(self):
        r = self.scheda()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="mprima"')
        self.assertContains(r, 'id="prima-odg"')
        self.assertContains(r, 'id="prima-convocazione"')
        self.assertContains(r, "+ Punto")
        self.assertContains(r, 'title="Sposta su"', count=3)
        self.assertContains(r, 'title="Sposta giù"', count=3)
        self.assertContains(r, "data-odg-togli", count=3)
        self.assertContains(r, "Modifica data, sala, convocati")
        self.assertContains(r, self.url("project_meeting_edit"))
        self.assertContains(r, "Convocazione non ancora inviata")
        self.assertContains(r, "Invia convocazione per mail")
        self.assertContains(r, "tasks/js/meeting_prima.js")

    def test_niente_ripetuto_e_nessun_tempo_per_punto(self):
        html = self.scheda().content.decode()
        # Quando e dove stanno solo nel riquadro «Convocazione», non anche nell'intestazione.
        self.assertEqual(html.count(self.m.data.strftime("%d-%m-%Y")), 1)
        self.assertEqual(html.count("Sala riunioni"), 1)
        # La modifica passa dal riquadro: niente secondo pulsante «Modifica incontro».
        self.assertNotIn("Modifica incontro", html)
        self.assertNotIn("md-docbar", html)
        for vietato in ("durata_minuti", "Durata", " min<", "minuti"):
            self.assertNotIn(vietato, html.split('id="mprima"')[1].split("</section>")[0])

    def test_chi_non_gestisce_legge_soltanto(self):
        self.client.force_login(self.lettore())
        r = self.scheda()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Stato del programma")
        for assente in ("+ Punto", "data-odg-sposta", "data-odg-togli", "Modifica data, sala, convocati", "Invia convocazione"):
            self.assertNotContains(r, assente)

    def test_incontro_svolto_o_annullato_senza_fase_prima(self):
        for stato in (MeetingStatus.SVOLTO, MeetingStatus.ANNULLATO):
            with self.subTest(stato=stato):
                KickoffMeeting.objects.filter(pk=self.m.pk).update(stato=stato)
                r = self.scheda()
                self.assertNotContains(r, 'id="mprima"')
                self.assertNotContains(r, "+ Punto")
                self.assertEqual(self.scheda(riquadro="prima").status_code, 409)

    def test_frammento_solo_i_riquadri(self):
        r = self.scheda(riquadro="prima")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertTrue(html.lstrip().startswith("<div") or "<html" not in html)
        self.assertNotIn("<html", html)
        for ident in ('id="prima-odg"', 'id="prima-invio"', 'id="prima-precedenti"'):
            self.assertIn(ident, html)


class OrdineDelGiornoDallaSchedaTests(IncontroPrimaBase):
    def test_aggiunge_un_punto_convocato(self):
        r = self.client.post(self.url("project_meeting_agenda_item_add"), {"titolo": "Imballo", "source": "scheda"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.m.refresh_from_db()
        nuovo = self.m.agenda_items[-1]
        self.assertEqual(nuovo["titolo"], "Imballo")
        # Aggiunto prima dell'incontro: non è un punto «aperto in riunione».
        self.assertEqual(nuovo["source"], "")
        self.assertIsNone(nuovo.get("durata_minuti"))
        self.assertContains(self.scheda(riquadro="prima"), "Imballo")

    def test_in_conduzione_il_punto_resta_aperto_in_riunione(self):
        self.client.post(self.url("project_meeting_agenda_item_add"), {"titolo": "Fuori sacco"}, **AJAX)
        self.m.refresh_from_db()
        self.assertEqual(self.m.agenda_items[-1]["source"], "live")

    def test_sposta_su_e_giu_senza_toccare_note_e_spunte(self):
        sposta = self.url("project_meeting_agenda_item_move")
        r = self.client.post(sposta, {"item_id": "c", "verso": "su"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["order"], ["a", "c", "b"])
        self.assertEqual(self.ordine(), ["a", "c", "b"])
        self.client.post(sposta, {"item_id": "a", "verso": "giu"}, **AJAX)
        self.assertEqual(self.ordine(), ["c", "a", "b"])
        per_id = {i["id"]: i for i in self.m.agenda_items}
        self.assertEqual(per_id["a"]["nota"], "nota di a")
        self.assertTrue(per_id["c"]["done"])

    def test_ai_bordi_non_si_sposta(self):
        sposta = self.url("project_meeting_agenda_item_move")
        r = self.client.post(sposta, {"item_id": "a", "verso": "su"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["moved"])
        self.client.post(sposta, {"item_id": "c", "verso": "giu"}, **AJAX)
        self.assertEqual(self.ordine(), ["a", "b", "c"])

    def test_sposta_richieste_non_valide(self):
        sposta = self.url("project_meeting_agenda_item_move")
        self.assertEqual(self.client.post(sposta, {"item_id": "zzz", "verso": "su"}, **AJAX).status_code, 404)
        self.assertEqual(self.client.post(sposta, {"item_id": "a", "verso": "lato"}, **AJAX).status_code, 400)
        self.assertEqual(self.client.get(sposta).status_code, 405)
        KickoffMeeting.objects.filter(pk=self.m.pk).update(stato=MeetingStatus.SVOLTO)
        r = self.client.post(sposta, {"item_id": "c", "verso": "su"}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["reason"], "not_planned")
        self.assertEqual(self.ordine(), ["a", "b", "c"])

    def test_toglie_un_punto_dalla_scheda(self):
        togli = self.url("project_meeting_agenda_item_delete")
        # Senza `fase=prima` vale la regola della conduzione: un punto normale non si toglie.
        self.assertEqual(self.client.post(togli, {"item_id": "b"}, **AJAX).status_code, 400)
        r = self.client.post(togli, {"item_id": "b", "fase": "prima"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ordine(), ["a", "c"])

    def test_non_si_toglie_un_punto_su_cui_e_nato_qualcosa(self):
        MeetingDecision.objects.create(project=self.project, meeting=self.m, testo="Si procede", punto="a", decisa_da=self.user)
        togli = self.url("project_meeting_agenda_item_delete")
        r = self.client.post(togli, {"item_id": "a", "fase": "prima"}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["reason"], "not_removable")
        self.assertEqual(self.ordine(), ["a", "b", "c"])
        # E la scheda non propone «Togli» su quel punto.
        self.assertContains(self.scheda(), "data-odg-togli", count=2)

    def test_dopo_l_incontro_la_scheda_non_toglie_piu(self):
        KickoffMeeting.objects.filter(pk=self.m.pk).update(stato=MeetingStatus.SVOLTO)
        r = self.client.post(self.url("project_meeting_agenda_item_delete"), {"item_id": "b", "fase": "prima"}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.ordine(), ["a", "b", "c"])

    def test_senza_permessi_risposta_json_403_e_niente_cambia(self):
        self.client.force_login(self.lettore())
        chiamate = (
            ("project_meeting_agenda_item_move", {"item_id": "c", "verso": "su"}),
            ("project_meeting_agenda_item_carry", {"tipo": "issue", "id": "1"}),
            ("project_meeting_agenda_item_delete", {"item_id": "b", "fase": "prima"}),
            ("project_meeting_agenda_item_add", {"titolo": "Abusivo", "source": "scheda"}),
        )
        for nome, dati in chiamate:
            with self.subTest(endpoint=nome):
                r = self.client.post(self.url(nome), dati, **AJAX)
                self.assertEqual(r.status_code, 403)
                self.assertEqual(r["Content-Type"].split(";")[0], "application/json")
                self.assertFalse(r.json()["ok"])
        self.assertEqual(self.ordine(), ["a", "b", "c"])

    def test_senza_accesso_risposta_json_401(self):
        self.client.logout()
        for nome in ("project_meeting_agenda_item_move", "project_meeting_agenda_item_carry"):
            with self.subTest(endpoint=nome):
                r = self.client.post(self.url(nome), {"item_id": "c", "verso": "su"}, **AJAX)
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r["Content-Type"].split(";")[0], "application/json")
        self.assertEqual(self.ordine(), ["a", "b", "c"])

    def test_gestisce_il_modulo_ma_non_la_commessa_403(self):
        altro = _create_user_with_legacy(username="prima-altro-pm", legacy_user_id=913, role_id=2, role_name="tasks")
        self.client.force_login(altro)
        r = self.client.post(self.url("project_meeting_agenda_item_move"), {"item_id": "c", "verso": "su"}, **AJAX)
        self.assertIn(r.status_code, (403, 404))
        self.assertEqual(self.ordine(), ["a", "b", "c"])


class ConvocazioneDaReinviareTests(IncontroPrimaBase):
    def test_dopo_una_modifica_il_riquadro_dice_da_reinviare(self):
        self.segna_convocazione_inviata()
        prima = self.scheda(riquadro="prima")
        self.assertNotContains(prima, "Convocazione da reinviare")
        self.assertContains(prima, "Convocazione inviata per mail il")

        self.client.post(self.url("project_meeting_agenda_item_add"), {"titolo": "Imballo", "source": "scheda"}, **AJAX)
        dopo = self.scheda(riquadro="prima")
        self.assertContains(dopo, "Convocazione da reinviare")
        self.assertContains(dopo, "Punti dell&#x27;ordine del giorno aggiunti: Imballo")
        self.assertContains(dopo, "Invia aggiornamento convocazione")
        # Anche la pagina intera, non solo il frammento.
        self.assertContains(self.scheda(), "Convocazione da reinviare")

    def test_anche_il_riordino_e_la_rimozione_chiedono_il_reinvio(self):
        self.segna_convocazione_inviata()
        self.client.post(self.url("project_meeting_agenda_item_move"), {"item_id": "c", "verso": "su"}, **AJAX)
        self.assertContains(self.scheda(riquadro="prima"), "Convocazione da reinviare")

        self.client.post(self.url("project_meeting_agenda_item_move"), {"item_id": "c", "verso": "giu"}, **AJAX)
        self.assertNotContains(self.scheda(riquadro="prima"), "Convocazione da reinviare")

        self.client.post(self.url("project_meeting_agenda_item_delete"), {"item_id": "b", "fase": "prima"}, **AJAX)
        dopo = self.scheda(riquadro="prima")
        self.assertContains(dopo, "Convocazione da reinviare")
        self.assertContains(dopo, "Punti dell&#x27;ordine del giorno tolti: Arrivo materiale")


class ProposteDallaSchedaTests(IncontroPrimaBase):
    def setUp(self):
        super().setUp()
        self.proposta = MeetingAgendaProposal.objects.create(meeting=self.m, proposed_by=self.user, titolo="Calibro a tampone")

    def decidi(self, verbo, **extra):
        return self.client.post(self.url("project_meeting_proposal_decide", self.proposta.pk), {"action": verbo}, **extra)

    def test_la_proposta_sta_nella_lista_con_accetta_e_rifiuta(self):
        r = self.scheda()
        self.assertContains(r, "Calibro a tampone")
        self.assertContains(r, 'data-proposta-decidi="accept"')
        self.assertContains(r, 'data-proposta-decidi="reject"')
        self.assertNotContains(r, "Proposte per l'ordine del giorno")

    def test_accetta_sul_posto_diventa_punto(self):
        r = self.decidi("accept", **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True, "stato": "ACCEPTED"})
        self.assertEqual(self.ordine()[-1], f"proposal-{self.proposta.pk}")
        frammento = self.scheda(riquadro="prima")
        self.assertContains(frammento, 'data-titolo="Calibro a tampone"', count=1)
        self.assertNotContains(frammento, "data-proposta-decidi")

    def test_rifiuta_sul_posto(self):
        r = self.decidi("reject", **AJAX)
        self.assertEqual(r.json()["stato"], "REJECTED")
        self.assertEqual(self.ordine(), ["a", "b", "c"])
        frammento = self.scheda(riquadro="prima")
        self.assertContains(frammento, "Rifiutata")
        self.assertNotContains(frammento, "data-proposta-decidi")

    def test_senza_ajax_resta_il_ritorno_alla_scheda(self):
        r = self.decidi("accept")
        self.assertRedirects(r, self.url("project_meeting_detail"), fetch_redirect_response=False)

    def test_senza_permessi_json_403(self):
        self.client.force_login(self.lettore())
        r = self.decidi("accept", **AJAX)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r["Content-Type"].split(";")[0], "application/json")
        self.proposta.refresh_from_db()
        self.assertTrue(self.proposta.is_pending)

    def test_il_convocato_che_non_gestisce_propone(self):
        lettore = self.lettore()
        self.m.partecipanti_utenti.add(lettore)
        self.client.force_login(lettore)
        r = self.scheda()
        self.assertContains(r, "Proponi un punto all'ordine del giorno")
        self.assertNotContains(r, "data-proposta-decidi")


class DagliIncontriPrecedentiTests(IncontroPrimaBase):
    def setUp(self):
        super().setUp()
        self.vecchio = KickoffMeeting.objects.create(
            project=self.project, data=timezone.localdate(), created_by=self.user, stato=MeetingStatus.SVOLTO,
        )
        self.problema = MeetingIssue.objects.create(
            project=self.project, source_meeting=self.vecchio, title="Tolleranza da chiarire", created_by=self.user,
        )
        self.attivita = MeetingActionItem.objects.create(
            project=self.project, source_meeting=self.vecchio, title="Chiedere il disegno aggiornato", created_by=self.user,
        )
        self.riporta = self.url("project_meeting_agenda_item_carry")

    def test_il_riquadro_elenca_problemi_e_attivita_ancora_aperti(self):
        r = self.scheda()
        self.assertContains(r, "Dagli incontri precedenti")
        self.assertContains(r, "Tolleranza da chiarire")
        self.assertContains(r, "Chiedere il disegno aggiornato")
        self.assertContains(r, "Aggiungi all'ordine del giorno", count=2)
        self.assertContains(r, f"incontro {self.vecchio.numero}")

    def test_un_clic_crea_il_punto_e_il_pulsante_sparisce(self):
        r = self.client.post(self.riporta, {"tipo": "issue", "id": self.problema.pk}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["already"])
        self.m.refresh_from_db()
        punto = self.m.agenda_items[-1]
        self.assertEqual(punto["issue_id"], self.problema.pk)
        self.assertEqual(punto["titolo"], "Problema aperto: Tolleranza da chiarire")

        frammento = self.scheda(riquadro="prima")
        self.assertContains(frammento, "Aggiungi all'ordine del giorno", count=1)
        self.assertNotContains(frammento, f'data-tipo="issue" data-id="{self.problema.pk}"')

    def test_niente_doppioni(self):
        for _ in range(2):
            r = self.client.post(self.riporta, {"tipo": "action", "id": self.attivita.pk}, **AJAX)
            self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["already"])
        self.m.refresh_from_db()
        self.assertEqual(sum(1 for i in self.m.agenda_items if i.get("action_id") == self.attivita.pk), 1)

    def test_tutto_riportato_il_riquadro_non_compare(self):
        self.client.post(self.riporta, {"tipo": "issue", "id": self.problema.pk}, **AJAX)
        self.client.post(self.riporta, {"tipo": "action", "id": self.attivita.pk}, **AJAX)
        r = self.scheda()
        self.assertNotContains(r, "Dagli incontri precedenti")
        self.assertNotContains(r, "data-odg-riporta")
        # Tolto il punto, la voce torna fra quelle da portare.
        self.client.post(self.url("project_meeting_agenda_item_delete"), {"item_id": f"issue-{self.problema.pk}", "fase": "prima"}, **AJAX)
        self.assertContains(self.scheda(riquadro="prima"), "Tolleranza da chiarire")
        self.assertContains(self.scheda(riquadro="prima"), "data-odg-riporta", count=1)

    def test_chiusi_e_nati_in_questo_incontro_non_si_riportano(self):
        self.problema.status = "RESOLVED"
        self.problema.save(update_fields=["status"])
        qui = MeetingActionItem.objects.create(project=self.project, source_meeting=self.m, title="Nata qui", created_by=self.user)
        voci = dagli_incontri_precedenti(self.m)
        self.assertEqual([(v["tipo"], v["id"]) for v in voci], [("action", self.attivita.pk)])
        for tipo, pk in (("issue", self.problema.pk), ("action", qui.pk), ("altro", 1)):
            with self.subTest(tipo=tipo, pk=pk):
                r = self.client.post(self.riporta, {"tipo": tipo, "id": pk}, **AJAX)
                self.assertEqual(r.status_code, 404)
        self.assertEqual(self.ordine(), ["a", "b", "c"])

    def test_di_un_altra_commessa_non_si_riporta(self):
        altra = make_project(name="Altra commessa", created_by=self.user, project_manager=self.user)
        estraneo = MeetingIssue.objects.create(project=altra, title="Non mio", created_by=self.user)
        r = self.client.post(self.riporta, {"tipo": "issue", "id": estraneo.pk}, **AJAX)
        self.assertEqual(r.status_code, 404)

    def test_la_scheda_prima_non_ripete_sotto_le_attivita_degli_altri_incontri(self):
        import re

        # I suggerimenti dei campi di testo (datalist) non sono righe della scheda.
        html = re.sub(r"<datalist.*?</datalist>", "", self.scheda().content.decode(), flags=re.S)
        self.assertEqual(html.count("Chiedere il disegno aggiornato"), 1)

    def test_chi_non_gestisce_vede_il_riquadro_senza_pulsante(self):
        self.client.force_login(self.lettore())
        r = self.scheda()
        self.assertContains(r, "Tolleranza da chiarire")
        self.assertNotContains(r, "data-odg-riporta")
