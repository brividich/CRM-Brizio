"""Il sistema dei permessi applicato ai moduli: azioni permesse e vietate per ruolo.

Ticket IT/Manutenzione, Diario preposto, Segnalazione incidenti, Assenze,
Assistente AI, ricerca globale, esportazioni e la pagina «Ruoli e permessi».
Le view si chiamano direttamente (RequestFactory) con il motore vero: si
sostituisce solo il render, per leggere il contesto e lo status.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from core.models import AccessGroup, AuditLog, RuoloPermessoModulo
from core.permessi.preset import applica_preset
from core.permessi.registro import moduli_registrati
from core.tests_permessi import PersoneMixin, ensure_anagrafica_table

User = get_user_model()


def fake_render(request, template, context=None, status=200, **kwargs):
    response = HttpResponse(template, status=status)
    response.context_data = context or {}
    return response


class ModuliBase(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        ensure_anagrafica_table()
        applica_preset()
        self.factory = RequestFactory()
        self.attiva_sistema()
        from anagrafica.models import RuoloOperativo

        # Organigramma sintetico: capo squadra <- operaio.
        self.r_capo = RuoloOperativo.objects.create(nome="Capo squadra TEST")
        self.r_op = RuoloOperativo.objects.create(nome="Operaio TEST", riporta_a=self.r_capo)

    def nell_organigramma(self, legacy, ruolo):
        from django.db import connection

        from anagrafica.models import DipendenteRuoloOperativo

        with connection.cursor() as c:
            c.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, utente_id) VALUES (%s, %s, %s)",
                [7000 + legacy.id, legacy.nome, legacy.id],
            )
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=7000 + legacy.id, ruolo=ruolo)
        from core.permessi.team import invalida_cache_team

        invalida_cache_team()

    def req(self, user, legacy, method="get", path="/", data=None, **extra):
        request = getattr(self.factory, method)(path, data or {}, **extra)
        request.user = self.ricarica(user)
        request.legacy_user = legacy
        request.session = {}
        request._messages = _Messaggi()
        return request


class _Messaggi(list):
    def add(self, level, message, extra_tags=""):
        self.append(message)

    def __iter__(self):
        return iter(list.__iter__(self))


# ── Ticket ───────────────────────────────────────────────────────────────────


@patch("tickets.views.render", side_effect=fake_render)
class TicketTests(ModuliBase):
    def setUp(self):
        super().setUp()
        from tickets.models import Ticket, TipoTicket

        self.capo, self.capo_l = self.persona("Capo squadra", ruoli=("ruolo-preposto",))
        self.op, self.op_l = self.persona("Operaio")
        self.altro, self.altro_l = self.persona("Altro reparto")
        self.it, self.it_l = self.persona("Tecnico IT", ruoli=("ruolo-tecnico-it",))
        self.dir, self.dir_l = self.persona("Direttore", ruoli=("ruolo-direzione",))
        self.nell_organigramma(self.capo_l, self.r_capo)
        self.nell_organigramma(self.op_l, self.r_op)

        def ticket(tipo, user, legacy, titolo):
            return Ticket.objects.create(
                tipo=tipo, titolo=titolo, descrizione="x", categoria="ALTRO",
                richiedente_nome=legacy.nome, richiedente_user=user, richiedente_legacy_user_id=legacy.id,
            )

        self.man_op = ticket(TipoTicket.MAN, self.op, self.op_l, "Perdita olio")
        self.it_op = ticket(TipoTicket.IT, self.op, self.op_l, "Stampante")
        self.man_altro = ticket(TipoTicket.MAN, self.altro, self.altro_l, "Porta rotta")

    def dashboard(self, user, legacy):
        from tickets import views

        return set(views.ticket_dashboard(self.req(user, legacy, path="/tickets/")).context_data["tickets"])

    def test_dipendente_vede_solo_i_propri(self, _r):
        self.assertEqual(self.dashboard(self.op, self.op_l), {self.man_op, self.it_op})
        self.assertEqual(self.dashboard(self.altro, self.altro_l), {self.man_altro})

    def test_preposto_vede_manutenzione_del_team_ma_non_l_it_del_team(self, _r):
        visti = self.dashboard(self.capo, self.capo_l)
        self.assertIn(self.man_op, visti)
        self.assertNotIn(self.it_op, visti)
        self.assertNotIn(self.man_altro, visti)

    def test_dettaglio_altrui_negato(self, _r):
        from tickets import views

        risposta = views.ticket_detail(self.req(self.altro, self.altro_l), self.man_op.pk)
        self.assertEqual(risposta.status_code, 403)

    def test_omonimo_non_e_richiedente(self, _r):
        from tickets import views

        omonimo, omonimo_l = self.persona(self.op_l.nome)
        risposta = views.ticket_detail(self.req(omonimo, omonimo_l), self.it_op.pk)
        self.assertEqual(risposta.status_code, 403)

    def test_tecnico_it_gestisce_it_non_manutenzione(self, _r):
        from tickets import views
        from tickets.models import TipoTicket

        request = self.req(self.it, self.it_l)
        self.assertTrue(views._can_manage_tickets(request, TipoTicket.IT))
        self.assertFalse(views._can_manage_tickets(request, TipoTicket.MAN))

    def test_direzione_vede_tutti_ma_non_gestisce(self, _r):
        from tickets import views

        self.assertEqual(self.dashboard(self.dir, self.dir_l), {self.man_op, self.it_op, self.man_altro})
        self.assertFalse(views._can_manage_tickets(self.req(self.dir, self.dir_l)))

    def test_ricerca_globale_non_mostra_ticket_altrui(self, _r):
        from tickets.models import Ticket
        from tickets.views import ticket_visibili_queryset

        visibili = set(ticket_visibili_queryset(self.req(self.altro, self.altro_l), Ticket.objects.all()))
        self.assertEqual(visibili, {self.man_altro})

    def test_ricerca_globale_anche_con_sistema_spento(self, _r):
        from tickets.models import Ticket
        from tickets.views import ticket_visibili_queryset

        self.attiva_sistema(False)
        visibili = set(ticket_visibili_queryset(self.req(self.altro, self.altro_l), Ticket.objects.all()))
        self.assertNotIn(self.man_op, visibili)


# ── Diario preposto ──────────────────────────────────────────────────────────


@patch("diario_preposto.views.render", side_effect=fake_render)
@patch("core.permessi.negato.render", side_effect=fake_render)
class DiarioTests(ModuliBase):
    def setUp(self):
        super().setUp()
        from diario_preposto.models import SegnalazionePreposto

        self.capo, self.capo_l = self.persona("Capo squadra", ruoli=("ruolo-preposto",))
        self.resp, self.resp_l = self.persona("Responsabile", ruoli=("ruolo-responsabile",))
        self.dip, self.dip_l = self.persona("Dipendente")
        self.sic, self.sic_l = self.persona("RSPP", ruoli=("ruolo-sicurezza",))
        self.nell_organigramma(self.resp_l, self.r_capo)
        self.nell_organigramma(self.capo_l, self.r_op)
        from django.utils import timezone

        self.mia = SegnalazionePreposto.objects.create(
            titolo="Ponteggio", descrizione="x", creato_da=self.capo, data_segnalazione=timezone.now()
        )

    def test_dipendente_non_vede_le_segnalazioni(self, *_):
        from diario_preposto import views

        lista = views.lista(self.req(self.dip, self.dip_l)).context_data["segnalazioni"]
        self.assertEqual(list(lista), [])
        self.assertEqual(views.dettaglio(self.req(self.dip, self.dip_l), self.mia.pk).status_code, 403)

    def test_preposto_vede_e_modifica_le_proprie(self, *_):
        from diario_preposto import views

        self.assertEqual(list(views.lista(self.req(self.capo, self.capo_l)).context_data["segnalazioni"]), [self.mia])
        self.assertTrue(views.dettaglio(self.req(self.capo, self.capo_l), self.mia.pk).context_data["can_write"])

    def test_responsabile_vede_quelle_del_team_ma_non_modifica(self, *_):
        from diario_preposto import views

        self.assertEqual(list(views.lista(self.req(self.resp, self.resp_l)).context_data["segnalazioni"]), [self.mia])
        self.assertEqual(views.modifica(self.req(self.resp, self.resp_l), self.mia.pk).status_code, 403)

    def test_esportazione_negata_a_chi_non_puo_esportare(self, *_):
        from diario_preposto import views

        self.assertEqual(views.export_excel(self.req(self.dip, self.dip_l)).status_code, 403)
        self.assertEqual(views.export_pdf(self.req(self.dip, self.dip_l), self.mia.pk).status_code, 403)

    def test_api_risponde_json_403(self, *_):
        from diario_preposto import views
        from diario_preposto.models import SegnalazioneAllegato

        allegato = SegnalazioneAllegato.objects.create(segnalazione=self.mia, nome_file="a.pdf", file="x/a.pdf")
        request = self.req(
            self.resp, self.resp_l, method="post", path="/diario-preposto/api/allegato/delete/",
            data={"allegato_id": allegato.pk},
        )
        risposta = views.api_allegato_delete(request)
        self.assertEqual(risposta.status_code, 403)
        self.assertFalse(json.loads(risposta.content)["ok"])

    def test_sicurezza_vede_tutto(self, *_):
        from diario_preposto import views

        self.assertEqual(list(views.lista(self.req(self.sic, self.sic_l)).context_data["segnalazioni"]), [self.mia])


# ── Segnalazione incidenti ───────────────────────────────────────────────────


@patch("rilevazione_incidenti.views.render", side_effect=fake_render)
@patch("core.permessi.negato.render", side_effect=fake_render)
class IncidentiTests(ModuliBase):
    def setUp(self):
        super().setUp()
        from rilevazione_incidenti.models import RilevazioneIncidente

        self.dip, self.dip_l = self.persona("Dipendente")
        self.altro, self.altro_l = self.persona("Altro")
        self.sic, self.sic_l = self.persona("RSPP", ruoli=("ruolo-sicurezza",))
        self.mia = RilevazioneIncidente.objects.create(
            nominativo="Dipendente", tipologia_scheda="Near Miss", segnalato_da_legacy_id=self.dip_l.id
        )
        self.altrui = RilevazioneIncidente.objects.create(
            nominativo="Altro", tipologia_scheda="Near Miss", segnalato_da_legacy_id=self.altro_l.id
        )
        self.storica = RilevazioneIncidente.objects.create(nominativo="Storico", tipologia_scheda="Accident")

    def ids(self, user, legacy):
        from rilevazione_incidenti import views

        items = views.lista(self.req(user, legacy)).context_data["items"]
        return {int(f["sp_id"]) for f in items}

    def test_dipendente_vede_solo_le_proprie(self, *_):
        self.assertEqual(self.ids(self.dip, self.dip_l), {self.mia.pk})

    def test_sicurezza_vede_tutte_compreso_lo_storico(self, *_):
        self.assertEqual(self.ids(self.sic, self.sic_l), {self.mia.pk, self.altrui.pk, self.storica.pk})

    def test_dettaglio_altrui_negato(self, *_):
        from rilevazione_incidenti import views

        self.assertEqual(views.dettaglio(self.req(self.dip, self.dip_l), str(self.altrui.pk)).status_code, 403)

    def test_gestione_e_export_solo_sicurezza(self, *_):
        from rilevazione_incidenti import views

        self.assertFalse(views._can_manage_rspp(self.req(self.dip, self.dip_l)))
        self.assertTrue(views._can_manage_rspp(self.req(self.sic, self.sic_l)))
        self.assertEqual(views.export_csv(self.req(self.dip, self.dip_l)).status_code, 403)
        self.assertEqual(views.export_csv(self.req(self.sic, self.sic_l)).status_code, 200)

    def test_elimina_negata_al_dipendente(self, *_):
        from rilevazione_incidenti import views
        from rilevazione_incidenti.models import RilevazioneIncidente

        risposta = views.elimina(self.req(self.dip, self.dip_l, method="post"), str(self.mia.pk))
        self.assertEqual(risposta.status_code, 403)
        self.assertTrue(RilevazioneIncidente.objects.filter(pk=self.mia.pk).exists())


# ── Assenze ──────────────────────────────────────────────────────────────────


class AssenzeTests(ModuliBase):
    def perms(self, user, legacy):
        from assenze import views

        return views._assenze_permissions(self.req(user, legacy))

    def test_dipendente_solo_proprie(self):
        p = self.perms(*self.persona("Dipendente"))
        self.assertEqual(p["view_scope"], "own")
        self.assertTrue(p["can_insert"])
        self.assertFalse(p["can_update_owned"] or p["can_update_any"] or p["can_view_calendar"])

    def test_responsabile_approva_il_team(self):
        p = self.perms(*self.persona("Resp", ruoli=("ruolo-responsabile",)))
        self.assertEqual(p["view_scope"], "reparto")
        self.assertTrue(p["can_update_owned"])
        self.assertFalse(p["can_update_any"])

    def test_hr_vede_tutto_ma_non_approva(self):
        p = self.perms(*self.persona("HR", ruoli=("ruolo-hr",)))
        self.assertEqual(p["view_scope"], "all")
        self.assertFalse(p["can_update_any"] or p["can_update_owned"])

    def test_direzione_vede_tutto_senza_approvare(self):
        p = self.perms(*self.persona("Dir", ruoli=("ruolo-direzione",)))
        self.assertEqual(p["view_scope"], "all")
        self.assertFalse(p["can_update_any"] or p["can_update_owned"])
        # Le proprie assenze le chiede come tutti (ruolo base), non per altri.
        self.assertTrue(p["can_insert"])
        self.assertFalse(p["can_insert_for_others"])

    def test_perimetro_del_capo_e_il_team_d_organigramma(self):
        from assenze import views

        capo, capo_l = self.persona("Capo", ruoli=("ruolo-responsabile",))
        op, op_l = self.persona("Operaio")
        self.nell_organigramma(capo_l, self.r_capo)
        self.nell_organigramma(op_l, self.r_op)
        with patch("assenze.views._has_assenze_column", return_value=True):
            where, params, _join = views._combined_manager_assignment_where_clause(legacy_user_id=capo_l.id)
        self.assertIn("utente_id IN", where)
        self.assertEqual(params, [op_l.id])
        request = self.req(capo, capo_l)
        self.assertTrue(views._can_manage_record(request, {"utente_id": op_l.id}))
        self.assertFalse(views._can_manage_record(request, {"utente_id": capo_l.id + 999}))


# ── Assistente AI ────────────────────────────────────────────────────────────


class AssistenteAiTests(ModuliBase):
    def test_tool_di_moduli_non_visibili_non_girano(self):
        from ai_assistant.tools import _anagrafica_context, _ticket_context, tool_consentito

        request = self.req(*self.persona("Dipendente"))
        self.assertFalse(tool_consentito(request, _anagrafica_context))
        self.assertTrue(tool_consentito(request, _ticket_context))

    def test_hr_usa_il_tool_anagrafica(self):
        from ai_assistant.tools import _anagrafica_context, tool_consentito

        self.assertTrue(tool_consentito(self.req(*self.persona("HR", ruoli=("ruolo-hr",))), _anagrafica_context))

    def test_sistema_spento_valgono_i_gate_dei_tool(self):
        from ai_assistant.tools import _anagrafica_context, tool_consentito

        self.attiva_sistema(False)
        self.assertTrue(tool_consentito(self.req(*self.persona("Dipendente")), _anagrafica_context))

    def test_carichi_macchina_negato_senza_permesso(self):
        from ai_assistant.tools import _carichi_context

        request = self.req(*self.persona("Dipendente"))
        contesto = _carichi_context(request, "qual è la saturazione delle macchine questa settimana? carichi")
        self.assertIn("negato", contesto.text)


# ── Pagina «Ruoli e permessi» ────────────────────────────────────────────────


class PaginaRuoliTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        applica_preset()
        self.admin = User.objects.create_user(username="admin.ruoli@example.test", password="x", is_superuser=True)
        self.client.force_login(self.admin)

    def test_tutte_le_schede_si_aprono(self):
        for tab in ("persone", "matrice", "modulo", "anteprima", "registro", "sistema", "guida"):
            with self.subTest(tab=tab):
                risposta = self.client.get(f"/admin-portale/ruoli-portale/?tab={tab}")
                self.assertEqual(risposta.status_code, 200)

    def test_riepilogo_per_modulo_ogni_modulo_si_apre_e_mostra_i_grant(self):
        for chiave in moduli_registrati():
            with self.subTest(modulo=chiave):
                risposta = self.client.get(f"/admin-portale/ruoli-portale/?tab=modulo&modulo={chiave}")
                self.assertEqual(risposta.status_code, 200)
        # Un grant concesso dalla matrice compare come tale nel riepilogo.
        from core.models import PermissionDefinition

        PermissionDefinition.objects.create(code="tasks.elenco.view", label="Elenco attivita", module="tasks")
        ruolo = AccessGroup.objects.get(code="ruolo-magazzino")
        self.client.post(f"/admin-portale/ruoli-portale/matrice/{ruolo.id}/", {"c__kickoff__vedere": "tutti"})
        risposta = self.client.get("/admin-portale/ruoli-portale/?tab=modulo&modulo=kickoff")
        pagine = risposta.context["pagine"]
        self.assertEqual([p["code"] for p in pagine], ["tasks.elenco.view"])
        colonna = [r.id for r in risposta.context["ruoli_colonne"]].index(ruolo.id)
        self.assertTrue(any(p["stati"][colonna] == "matrice" for p in pagine))

    def test_matrice_mostra_lo_stato_reale_delle_pagine(self):
        from core.models import GroupPermissionGrant, PermissionDefinition

        PermissionDefinition.objects.create(code="tasks.elenco.view", label="Elenco attivita", module="tasks")
        ruolo = AccessGroup.objects.get(code="ruolo-magazzino")
        self.client.post(f"/admin-portale/ruoli-portale/matrice/{ruolo.id}/", {"c__kickoff__vedere": "tutti"})
        risposta = self.client.get(f"/admin-portale/ruoli-portale/?tab=matrice&ruolo={ruolo.id}")
        self.assertContains(risposta, "rp-pag rp-pag-pieno")
        self.assertContains(risposta, "pagine 1/1")
        # Tolta a mano dalla pagina Accessi: la cella lo segnala.
        GroupPermissionGrant.objects.filter(group=ruolo, permission_id="tasks.elenco.view").delete()
        risposta = self.client.get(f"/admin-portale/ruoli-portale/?tab=matrice&ruolo={ruolo.id}")
        self.assertContains(risposta, "pagine 0/1 · a mano")
        # Dati per l'anteprima lato pagina dei badge prima del salvataggio.
        self.assertContains(risposta, 'id="rp-anteprima"')
        self.assertContains(risposta, 'data-azione="vedere"')
        self.assertIn("kickoff", risposta.context["anteprima_pagine"]["moduli"])

    def test_non_amministratore_respinto(self):
        user, _ = self.persona("Curioso")
        self.client.force_login(user)
        risposta = self.client.get("/admin-portale/ruoli-portale/")
        self.assertIn(risposta.status_code, (302, 403))

    def test_assegnazione_ruoli_registrata(self):
        _user, legacy = self.persona("Nuovo preposto")
        preposto = AccessGroup.objects.get(code="ruolo-preposto")
        self.client.post(f"/admin-portale/ruoli-portale/persona/{legacy.id}/", {"ruoli": [preposto.id], "nota": "nomina"})
        self.assertTrue(preposto.memberships.filter(legacy_user_id=legacy.id).exists())
        voce = AuditLog.objects.filter(modulo="permessi", azione="permessi_ruoli_persona").latest("id")
        self.assertEqual(voce.dettaglio["aggiunti"], [preposto.label])

    def test_modifica_matrice_registrata(self):
        ruolo = AccessGroup.objects.get(code="ruolo-magazzino")
        self.client.post(f"/admin-portale/ruoli-portale/matrice/{ruolo.id}/", {"c__kickoff__vedere": "tutti"})
        self.assertTrue(RuoloPermessoModulo.objects.filter(ruolo=ruolo, modulo="kickoff", azione="vedere").exists())
        voce = AuditLog.objects.filter(modulo="permessi", azione="permessi_matrice").latest("id")
        self.assertEqual(voce.dettaglio["modifiche"][0]["dopo"], "tutti")

    def test_attivazione_richiede_conferma_e_si_registra(self):
        from core.permessi.motore import sistema_ruoli_attivo

        self.client.post("/admin-portale/ruoli-portale/sistema/", {"azione": "attiva"})
        self.assertFalse(sistema_ruoli_attivo())
        self.client.post("/admin-portale/ruoli-portale/sistema/", {"azione": "attiva", "conferma": "1"})
        self.assertTrue(sistema_ruoli_attivo())
        self.assertTrue(AuditLog.objects.filter(modulo="permessi", azione="permessi_sistema_attiva").exists())


class RispostaNegataTests(TestCase):
    def test_api_riceve_json_con_il_contatto(self):
        from core.permessi.negato import risposta_negata

        request = RequestFactory().get("/qualcosa/api/dati/", HTTP_ACCEPT="application/json")
        risposta = risposta_negata(request)
        self.assertEqual(risposta.status_code, 403)
        dati = json.loads(risposta.content)
        self.assertEqual(dati["reason"], "forbidden")
        self.assertIn("reparto IT", dati["contatto"])
