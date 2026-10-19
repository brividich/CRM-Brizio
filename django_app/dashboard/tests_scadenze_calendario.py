"""Scadenzario nei calendari: file .ics e calendario Outlook personale (Graph simulato in memoria)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import NotificaCanali, ScadenzaOutlook
from dashboard import scadenze_calendario as cal
from dashboard.scadenze_providers import ScadenzaItem


def _voce(titolo="Visita medica periodica", soggetto="ROSSI SINTETICO", giorno=date(2026, 11, 10), url="/anagrafica/visite/1/"):
    return ScadenzaItem(source="hr", kind="visita", kind_label="Visita medica", titolo=titolo, soggetto=soggetto,
                        reparto="Officina", data_scadenza=giorno, giorni=20, url=url)


class IcsTests(TestCase):
    def test_file_ics(self):
        testo = cal.genera_ics([_voce(titolo="Corso; antincendio, aggiornamento " + "x" * 80)]).decode("utf-8")
        self.assertTrue(testo.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertIn("DTSTART;VALUE=DATE:20261110", testo)
        self.assertIn("DTEND;VALUE=DATE:20261111", testo)
        self.assertIn("Corso\\; antincendio\\, aggiornamento", testo.replace("\r\n ", ""))
        self.assertTrue(all(len(r.encode("utf-8")) <= 75 for r in testo.split("\r\n")))

    def test_voce_senza_data_esclusa(self):
        self.assertNotIn("VEVENT", cal.genera_ics([_voce(giorno=None)]).decode())

    def test_chiave_stabile_anche_se_cambia_la_data(self):
        self.assertEqual(cal.chiave_voce(_voce()), cal.chiave_voce(_voce(giorno=date(2027, 1, 1))))
        self.assertNotEqual(cal.impronta(_voce()), cal.impronta(_voce(giorno=date(2027, 1, 1))))


class FintoOutlook:
    """Calendario Outlook in memoria al posto di Graph."""

    def __init__(self):
        self.eventi: dict[str, dict] = {}
        self.calendari = []
        self.n = 0

    def get_all(self, url, *, permesso, params=None, max_pages=50):
        if url.endswith("/calendars"):
            return list(self.calendari)
        return [{"id": k} for k in self.eventi]

    def scrivi(self, metodo, url, *, permesso, json=None):
        if url.endswith("/calendars") and metodo == "POST":
            self.calendari.append({"id": "cal-1", "name": json["name"]})
            return 201, {"id": "cal-1"}
        if metodo == "GET":
            return (200, {}) if self.calendari else (404, {})
        if metodo == "POST":
            self.n += 1
            eid = f"ev-{self.n}"
            self.eventi[eid] = json
            return 201, {"id": eid}
        eid = url.rsplit("/", 1)[-1]
        if eid not in self.eventi:
            return 404, {}
        if metodo == "PATCH":
            self.eventi[eid] = json
            return 200, {}
        if metodo == "DELETE":
            del self.eventi[eid]
            return 204, {}
        raise AssertionError(metodo)


class OutlookTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u.sintetico", email="u.sintetico@example.com", password="x")
        self.canali = NotificaCanali.objects.create(user=self.user, outlook_scadenze=True)
        self.finto = FintoOutlook()
        self.patches = [patch("core.m365_graph.get_all", self.finto.get_all),
                        patch("core.m365_graph.scrivi", self.finto.scrivi),
                        patch("dashboard.scadenze_digest._email_utente", return_value="u.sintetico@example.com")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _sync(self, voci):
        return cal.sincronizza_utente(self.canali, voci=voci)

    def test_crea_poi_niente_poi_aggiorna_poi_toglie(self):
        a, b = _voce(), _voce(titolo="Corso carrelli", url="/anagrafica/corsi/2/")
        self.assertEqual(self._sync([a, b])["creati"], 2)
        self.assertEqual(self.finto.calendari[0]["name"], "Scadenze NOVICROM HUB")
        evento = next(iter(self.finto.eventi.values()))
        self.assertTrue(evento["isAllDay"])
        self.assertEqual(self._sync([a, b]), {"creati": 0, "aggiornati": 0, "tolti": 0, "lasciati_fuori": 0})
        spostata = _voce(giorno=date(2026, 12, 1))
        self.assertEqual(self._sync([spostata, b])["aggiornati"], 1)
        self.assertEqual(self._sync([spostata])["tolti"], 1)
        self.assertEqual(len(self.finto.eventi), 1)
        self.assertEqual(ScadenzaOutlook.objects.count(), 1)

    def test_evento_cancellato_in_outlook_non_viene_ricreato(self):
        self._sync([_voce()])
        self.finto.eventi.clear()  # la persona lo cancella in Outlook
        esito = self._sync([_voce()])
        self.assertEqual(esito["lasciati_fuori"], 1)
        self.assertEqual(self.finto.eventi, {})
        self.assertTrue(ScadenzaOutlook.objects.get().rimosso_da_utente)
        # La scadenza cambia data: torna in calendario.
        self.assertEqual(self._sync([_voce(giorno=date(2027, 2, 1))])["creati"], 1)

    def test_spento_svuota_il_calendario(self):
        self._sync([_voce()])
        self.canali.outlook_scadenze = False
        self.canali.save()
        with patch("core.m365_graph.configurato", return_value=True):
            esito = cal.sincronizza_tutti()
        self.assertEqual(esito["svuotati"], 1)
        self.assertEqual(self.finto.eventi, {})
        self.assertFalse(ScadenzaOutlook.objects.exists())

    def test_errore_di_una_casella_registrato(self):
        from core.m365_graph import GraphError

        with patch("core.m365_graph.configurato", return_value=True), \
             patch("dashboard.scadenze_calendario.sincronizza_utente", side_effect=GraphError("manca il permesso «Calendars.ReadWrite»", 403)):
            esito = cal.sincronizza_tutti()
        self.assertEqual(esito["errori"], 1)
        self.canali.refresh_from_db()
        self.assertIn("Calendars.ReadWrite", self.canali.outlook_errore)


@override_settings(LEGACY_AUTH_ENABLED=False)
class PagineTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser(username="adm", email="a@a.it", password="x")
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)

    def test_scadenzario_scarica_ics(self):
        with patch("dashboard.views_scadenze.collect_all", return_value=[_voce()]):
            resp = self.client.get(reverse("scadenze_globali") + "?format=ics")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("text/calendar"))
        self.assertIn(b"BEGIN:VEVENT", resp.content)

    def test_pulsante_ics_e_opzione_outlook(self):
        with patch("dashboard.views_scadenze.collect_all", return_value=[]):
            self.assertContains(self.client.get(reverse("scadenze_globali")), "Calendario (.ics)")
        with patch("core.m365_graph.configurato", return_value=True):
            resp = self.client.get(reverse("notifiche_impostazioni"))
        self.assertContains(resp, "Metti le mie scadenze nel calendario Outlook")
        self.client.post(reverse("notifiche_impostazioni"), {"outlook_scadenze": "1"})
        self.assertTrue(NotificaCanali.objects.get(user=self.user).outlook_scadenze)


class LinkTests(TestCase):
    @override_settings(SITE_URL="")
    def test_link_relativo_non_finisce_nel_file(self):
        testo = cal.genera_ics([_voce()]).decode()
        self.assertNotIn("URL:/", testo)
        testo = cal.genera_ics([_voce()], base_url="https://hub.example.com/").decode()
        self.assertIn("URL:https://hub.example.com/anagrafica/visite/1/", testo)
