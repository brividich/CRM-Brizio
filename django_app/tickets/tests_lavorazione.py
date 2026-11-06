"""Azioni del tecnico: Prendo io, Risolvi, viste dell'elenco. Solo dati sintetici."""
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from tickets.models import (
    EsitoIntervento,
    PrioritaTicket,
    StatoTicket,
    Ticket,
    TipoTicket,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class LavorazioneBase(TestCase):
    def setUp(self):
        self.tecnico = User.objects.create_user(
            username="syn.lav.tec", first_name="Tec", last_name="Nico", email="tec@example.com"
        )
        UserOnboarding.objects.update_or_create(user=self.tecnico, defaults={"completed": True})
        self.client.force_login(self.tecnico)
        for nome in ("_can_manage_tickets", "_can_open_tickets"):
            p = patch(f"tickets.views.{nome}", return_value=True)
            p.start()
            self.addCleanup(p.stop)
        p = patch("tickets.views._update_ticket_sharepoint", return_value=None)
        p.start()
        self.addCleanup(p.stop)
        p = patch("tickets.views._get_assets_for_select", return_value=[])
        p.start()
        self.addCleanup(p.stop)

    def _ticket(self, **extra):
        dati = {
            "tipo": TipoTicket.MAN, "titolo": "Guasto sintetico", "descrizione": "Sintetica",
            "categoria": "CNC", "richiedente_nome": "Richiedente Sintetico",
        }
        dati.update(extra)
        return Ticket.objects.create(**dati)

    def _api(self, ticket, **dati):
        return self.client.post(
            reverse("tickets:api_stato"),
            data=json.dumps({"ticket_id": ticket.pk, **dati}),
            content_type="application/json",
        )


class PrendoIoTests(LavorazioneBase):
    def test_assegna_e_prende_in_carico(self):
        ticket = self._ticket()
        response = self._api(ticket, azione="prendi")
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.stato, StatoTicket.IN_CARICO)
        self.assertEqual(ticket.assegnato_email, "tec@example.com")
        self.assertTrue(ticket.assegnato_a)
        self.assertIsNotNone(ticket.data_presa_in_carico)
        self.assertEqual(ticket.stato_log.get().a_stato, StatoTicket.IN_CARICO)

    def test_dall_elenco_non_toglie_il_ticket_a_un_collega(self):
        ticket = self._ticket(assegnato_a="Collega Sintetico", stato=StatoTicket.IN_CARICO)
        response = self._api(ticket, azione="prendi", solo_se_libero=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Collega Sintetico", response.json()["error"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.assegnato_a, "Collega Sintetico")

    def test_dalla_scheda_si_puo_subentrare(self):
        ticket = self._ticket(assegnato_a="Collega Sintetico", stato=StatoTicket.IN_CARICO)
        self.assertEqual(self._api(ticket, azione="prendi").status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assegnato_email, "tec@example.com")
        self.assertEqual(ticket.stato_log.count(), 0)

    def test_ticket_chiuso_non_si_prende(self):
        ticket = self._ticket(stato=StatoTicket.CHIUSO)
        self.assertEqual(self._api(ticket, azione="prendi").status_code, 409)

    def test_senza_permesso_sul_tipo_403(self):
        ticket = self._ticket()
        with patch("tickets.views._api_require_ticket_access") as guardia:
            from django.http import JsonResponse

            guardia.return_value = JsonResponse({"ok": False}, status=403)
            self.assertEqual(self._api(ticket, azione="prendi").status_code, 403)
        ticket.refresh_from_db()
        self.assertEqual(ticket.stato, StatoTicket.APERTA)


class RisolviTests(LavorazioneBase):
    def test_chiude_con_il_solo_lavoro(self):
        ticket = self._ticket()
        response = self._api(ticket, azione="risolvi", intervento_svolto="Sostituito fusibile sintetico")
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.stato, StatoTicket.CHIUSO)
        self.assertTrue(ticket.risolto_da_nome)
        self.assertTrue(ticket.assegnato_a)
        intervento = ticket.interventi.get()
        self.assertEqual(intervento.esito, EsitoIntervento.COMPLETATO)
        self.assertIsNone(intervento.ore_lavorate)
        self.assertTrue(ticket.commenti.filter(is_interno=False, testo__contains="fusibile").exists())

    def test_senza_lavoro_non_chiude(self):
        ticket = self._ticket()
        response = self._api(ticket, azione="risolvi", intervento_svolto="  ")
        self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.stato, StatoTicket.APERTA)
        self.assertEqual(ticket.interventi.count(), 0)

    def test_campi_facoltativi(self):
        ticket = self._ticket()
        self._api(
            ticket, azione="risolvi", intervento_svolto="Sintetico", intervento_ore="1,5", tipo_fermo="TOTALE",
            ore_fermo="3", componente="Mandrino", causa="Usura", ricorrente=True, costo_materiali="12,50",
            rapportino="R-1",
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.ore_fermo_macchina, Decimal("3.00"))
        self.assertEqual(ticket.componente, "Mandrino")
        self.assertEqual(ticket.causa_radice, "Usura")
        self.assertTrue(ticket.ricorrente)
        intervento = ticket.interventi.get()
        self.assertEqual(intervento.durata_ore, 1.5)
        self.assertEqual(intervento.materiali_costo_eur, Decimal("12.50"))
        self.assertEqual(intervento.numero_rapportino, "R-1")

    def test_numeri_non_validi(self):
        ticket = self._ticket()
        for extra in ({"ore_fermo": "abc"}, {"costo_materiali": "-1"}, {"intervento_ore": "x"}):
            with self.subTest(extra=extra):
                response = self._api(ticket, azione="risolvi", intervento_svolto="Sintetico", **extra)
                self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.stato, StatoTicket.APERTA)

    def test_visita_collegata_usa_orari_e_tecnici(self):
        ticket = self._ticket()
        ora = timezone.localtime().replace(second=0, microsecond=0)
        dal = (ora - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
        al = (ora - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        self._api(ticket, azione="risolvi", intervento_svolto="Sintetico", intervento_ore="2",
                  intervento_dal=dal, intervento_quando=al, tecnico="Ditta Sintetica")
        intervento = ticket.interventi.get()
        self.assertEqual(intervento.tecnico_nome, "Ditta Sintetica")
        self.assertEqual(intervento.data_fine - intervento.data_inizio, timedelta(hours=2))

    def test_chiusura_mai_prima_dell_apertura(self):
        ticket = self._ticket()
        ieri = (timezone.localtime() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self._api(ticket, azione="risolvi", intervento_svolto="Sintetico", intervento_quando=ieri)
        ticket.refresh_from_db()
        self.assertGreaterEqual(ticket.closed_at, ticket.created_at)

    def test_doppio_clic_non_duplica(self):
        ticket = self._ticket()
        self._api(ticket, azione="risolvi", intervento_svolto="Sintetico")
        self.assertEqual(self._api(ticket, azione="risolvi", intervento_svolto="Sintetico").status_code, 409)
        self.assertEqual(ticket.interventi.count(), 1)


class SchedaTests(LavorazioneBase):
    def _scheda(self, ticket, query=""):
        return self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk]) + query)

    def test_prendo_io_se_non_e_mio_risolvi_se_e_mio(self):
        libero = self._ticket()
        pagina = self._scheda(libero)
        self.assertContains(pagina, 'id="btn-prendo"')
        self.assertContains(pagina, 'id="btn-risolvi"')
        self.assertNotContains(pagina, "Segna come risolto")
        mio = self._ticket(assegnato_email="tec@example.com", assegnato_a="Tec Nico", stato=StatoTicket.IN_CARICO)
        pagina = self._scheda(mio)
        self.assertNotContains(pagina, 'id="btn-prendo"')
        self.assertContains(pagina, 'id="btn-risolvi"')

    def test_azione_risolvi_apre_il_pannello(self):
        ticket = self._ticket()
        self.assertContains(self._scheda(ticket), 'aria-label="Risolvi il ticket" hidden')
        self.assertNotContains(self._scheda(ticket, "?azione=risolvi"), 'aria-label="Risolvi il ticket" hidden')

    def test_dopo_la_chiusura_propone_il_prossimo(self):
        chiuso = self._ticket(stato=StatoTicket.CHIUSO)
        self._ticket(titolo="Media sintetica", priorita=PrioritaTicket.MEDIA)
        self._ticket(titolo="Urgente sintetico", priorita=PrioritaTicket.URGENTE)
        self._ticket(titolo="Di altri sintetico", priorita=PrioritaTicket.URGENTE, assegnato_a="Collega Sintetico")
        pagina = self._scheda(chiuso, "?chiuso=1")
        self.assertContains(pagina, "Prossimo: Urgente sintetico")
        self.assertContains(pagina, 'id="btn-riapri"')

    def test_ore_proposte_dalla_presa_in_carico(self):
        presa = timezone.now() - timedelta(minutes=95)
        ticket = self._ticket(stato=StatoTicket.IN_CARICO, data_presa_in_carico=presa)
        self.assertContains(self._scheda(ticket), 'id="rv-ore" min="0" step="0.25" value="1.5"')
        lontana = self._ticket(stato=StatoTicket.IN_CARICO, data_presa_in_carico=timezone.now() - timedelta(days=3))
        self.assertContains(self._scheda(lontana), 'id="rv-ore" min="0" step="0.25" value=""')

    def test_riaprire_riporta_in_carico(self):
        ticket = self._ticket()
        self._api(ticket, azione="risolvi", intervento_svolto="Sintetico")
        self.assertEqual(self._api(ticket, stato="IN_CARICO", nota="Riaperto").status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.stato, StatoTicket.IN_CARICO)
        self.assertIsNone(ticket.closed_at)


class ElencoTests(LavorazioneBase):
    def setUp(self):
        super().setUp()
        self.libero = self._ticket(titolo="Libero sintetico", priorita=PrioritaTicket.BASSA)
        self.urgente = self._ticket(titolo="Urgente sintetico", priorita=PrioritaTicket.URGENTE)
        self.mio = self._ticket(titolo="Mio sintetico", assegnato_email="tec@example.com", assegnato_a="Tec Nico",
                                stato=StatoTicket.IN_CARICO)
        self.altrui = self._ticket(titolo="Altrui sintetico", assegnato_a="Collega Sintetico",
                                   stato=StatoTicket.IN_CARICO)
        self.chiuso = self._ticket(titolo="Chiuso sintetico", stato=StatoTicket.CHIUSO)
        self.risolto = self._ticket(titolo="Risolto sintetico", stato=StatoTicket.RISOLTO)

    def _elenco(self, query="?tipo=MAN"):
        return self.client.get(reverse("tickets:gestione_list") + query)

    def _titoli(self, pagina):
        return [t.titolo for t in pagina.context["tickets_man"]]

    def test_si_apre_su_da_fare_con_prima_gli_urgenti(self):
        titoli = self._titoli(self._elenco())
        self.assertEqual(titoli[0], "Urgente sintetico")
        self.assertNotIn("Chiuso sintetico", titoli)
        self.assertNotIn("Risolto sintetico", titoli)
        self.assertEqual(len(titoli), 4)

    def test_viste(self):
        self.assertEqual(self._titoli(self._elenco("?tipo=MAN&vista=miei")), ["Mio sintetico"])
        self.assertCountEqual(self._titoli(self._elenco("?tipo=MAN&vista=liberi")), ["Libero sintetico", "Urgente sintetico"])
        self.assertCountEqual(self._titoli(self._elenco("?tipo=MAN&vista=chiusi")), ["Chiuso sintetico", "Risolto sintetico"])

    def test_i_conteggi_coincidono_con_le_righe(self):
        pagina = self._elenco()
        for vista in pagina.context["viste_gestione"]:
            with self.subTest(vista=vista["codice"]):
                righe = self._titoli(self._elenco(f"?tipo=MAN&vista={vista['codice']}"))
                self.assertEqual(vista["conta"], len(righe))

    def test_un_filtro_di_stato_vale_piu_della_vista(self):
        self.assertEqual(self._titoli(self._elenco("?tipo=MAN&stato=CHIUSO")), ["Chiuso sintetico"])

    def test_azione_giusta_sulla_riga(self):
        pagina = self._elenco()
        self.assertContains(pagina, f"prendiInCaricoInline({self.libero.pk},this)")
        self.assertContains(pagina, reverse("tickets:gestione_detail", args=[self.mio.pk]) + "?azione=risolvi")
        self.assertNotContains(pagina, f"prendiInCaricoInline({self.altrui.pk},this)")
        self.assertNotContains(pagina, f"{reverse('tickets:gestione_detail', args=[self.altrui.pk])}?azione=risolvi")
