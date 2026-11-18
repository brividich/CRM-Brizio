"""Scheda dipendente: le tessere «Ticket» e «Asset in carico» aprono l'elenco filtrato sulla
persona che conta lo stesso numero, e solo a chi quell'elenco lo può aprire. Dati sintetici."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from tickets.models import StatoTicket, Ticket, TipoTicket

from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()
UTENTE_ID = 4321


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SchedaDipendenteKpiLinkTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        _ensure_anagrafica_table()
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo, utente_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["l.scheda", "Luca", "Scheda", 1, UTENTE_ID],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["l.scheda"])
            self.legacy_id = int(cursor.fetchone()[0])
        self.user = User.objects.create_superuser("kpi-scheda", "kpi-scheda@example.com", "x")
        UserOnboarding.objects.update_or_create(
            user=self.user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()}
        )
        self.client.force_login(self.user)

        def ticket(titolo, utente, **extra):
            dati = {"tipo": TipoTicket.IT, "descrizione": "x", "categoria": "ALTRO", "richiedente_nome": "Luca Scheda",
                    "richiedente_legacy_user_id": utente}
            dati.update(extra)
            return Ticket.objects.create(titolo=titolo, **dati)

        ticket("aperto IT", UTENTE_ID)
        ticket("chiuso MAN", UTENTE_ID, tipo=TipoTicket.MAN, stato=StatoTicket.CHIUSO)
        ticket("in carico IT", UTENTE_ID, stato=StatoTicket.IN_CARICO)
        # Stesso nome, altra persona: l'id anagrafica non è l'id utente (era il vecchio conteggio).
        ticket("di un omonimo", self.legacy_id)
        ticket("di un altro", 9999)
        Asset.objects.create(asset_tag="K7-S1", name="Portatile", assigned_legacy_user_id=UTENTE_ID)
        Asset.objects.create(asset_tag="K7-S2", name="Telefono", assigned_legacy_user_id=UTENTE_ID)
        Asset.objects.create(asset_tag="K7-S3", name="Vecchio", assigned_legacy_user_id=UTENTE_ID,
                             status=Asset.STATUS_RETIRED)
        Asset.objects.create(asset_tag="K7-S4", name="Di un altro", assigned_legacy_user_id=9999)

    def _scheda(self, gestisce_ticket=True):
        with mock.patch("tickets.views._can_manage_tickets", return_value=gestisce_ticket):
            r = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        self.assertEqual(r.status_code, 200)
        return r

    def _widget(self, r, wid):
        tutti = list(r.context["widgets_visible"]) + list(r.context["widgets_hidden"])
        return next(w for w in tutti if w["id"] == wid)

    def test_ticket_contati_per_id_utente_e_stesso_numero_nell_elenco(self):
        r = self._scheda()
        aperti, totali = self._widget(r, "tickets_aperti"), self._widget(r, "tickets_totali")
        self.assertEqual((aperti["count"], totali["count"]), (1, 3))
        base = reverse("tickets:gestione_list")
        self.assertEqual(aperti["kpi_url"], f"{base}?tipo=TUTTI&stato=APERTA&richiedente={UTENTE_ID}")
        self.assertEqual(totali["kpi_url"], f"{base}?tipo=TUTTI&vista=tutti&richiedente={UTENTE_ID}")
        with mock.patch("tickets.views._can_manage_tickets", return_value=True):
            for w in (aperti, totali):
                elenco = self.client.get(w["kpi_url"])
                self.assertEqual(elenco.status_code, 200)
                self.assertEqual(elenco.context["tickets_lista"].count(), w["count"], w["id"])
        self.assertContains(r, f'href="{aperti["kpi_url"].replace("&", "&amp;")}"')

    def test_senza_gestione_ticket_nessun_link(self):
        r = self._scheda(gestisce_ticket=False)
        for wid in ("tickets_aperti", "tickets_totali"):
            w = self._widget(r, wid)
            self.assertNotIn("kpi_url", w)
            self.assertEqual(w["link_url"], "")
        self.assertNotContains(r, "richiedente=")

    def test_asset_in_carico_apre_l_inventario_filtrato(self):
        r = self._scheda()
        url = r.context["asset_in_carico_url"]
        self.assertEqual(url, f"{reverse('assets:asset_list')}?status=ATTIVI&assegnatario={UTENTE_ID}")
        self.assertEqual(len(r.context["assets_assegnati"]), 2)
        inventario = self.client.get(url)
        self.assertEqual(inventario.status_code, 200)
        self.assertEqual(inventario.context["visible_count"], len(r.context["assets_assegnati"]))
        self.assertContains(inventario, "data-filtro-assegnatario")
        self.assertContains(r, f'href="{url.replace("&", "&amp;")}"')

    def test_ambito_ristretto_niente_link_asset(self):
        with mock.patch("assets.services.visibilita.ambito_ristretto", return_value=True):
            r = self._scheda()
        self.assertEqual(r.context["asset_in_carico_url"], "")

    def test_assegnatario_non_valido_ignorato(self):
        tutti = self.client.get(reverse("assets:asset_list")).context["visible_count"]
        self.assertEqual(self.client.get(reverse("assets:asset_list") + "?assegnatario=abc").context["visible_count"], tutti)
