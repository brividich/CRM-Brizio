"""Modulo Presenti in azienda: lettura condivisa, aggancio all'anagrafica, appello live, uscite.

Nessun dato reale: Solari è simulato con righe sintetiche, nessuna connessione al database
delle timbrature.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import AmbitoRuolo, DipendenteRuoloOperativo, RuoloOperativo

from . import pdf, services, solari
from .models import Appello, AppelloSpunta, AvvisoUscitaMancante

CF_A = "RSSMRA80A01H501U"
CF_B = "VRDLGU85B02F205X"


def _solari_righe():
    oggi = date.today()
    return [
        {"solari_id": 11, "matricola": "1001", "cognome": "Rossi", "nome": "Mario", "codice_fiscale": CF_A,
         "entrata": datetime.combine(oggi, datetime.min.time()).replace(hour=7, minute=58), "badge": "B1",
         "turno": "N"},
        {"solari_id": 12, "matricola": "1002", "cognome": "Verdi", "nome": "Luigi", "codice_fiscale": CF_B,
         "entrata": datetime.combine(oggi, datetime.min.time()).replace(hour=8, minute=5), "badge": "B2",
         "turno": ""},
        {"solari_id": 13, "matricola": "1003", "cognome": "Bianchi", "nome": "Anna", "codice_fiscale": "",
         "entrata": datetime.combine(oggi, datetime.min.time()).replace(hour=9, minute=0), "badge": "B3",
         "turno": ""},
    ]


def _aggancio(codici):
    """Al posto della tabella legacy anagrafica_dipendenti (non gestita nei test)."""
    mappa = {CF_A: {"legacy_id": 501, "reparto": "CNC", "mansione": "Operatore"},
             CF_B: {"legacy_id": 502, "reparto": "Qualità", "mansione": "Controllore"}}
    return {cf: v for cf, v in mappa.items() if cf in codici}


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class ServiziTests(TestCase):
    def setUp(self):
        cache.clear()
        ambito, _ = AmbitoRuolo.objects.get_or_create(nome="Sicurezza ISO 45001")
        altro, _ = AmbitoRuolo.objects.get_or_create(nome="Produttivo")
        preposto = RuoloOperativo.objects.update_or_create(nome="Preposto T", defaults={"ambito": ambito})[0]
        soccorso = RuoloOperativo.objects.update_or_create(nome="Addetto Primo Soccorso T", defaults={"ambito": ambito})[0]
        capoturno = RuoloOperativo.objects.update_or_create(nome="Capoturno T", defaults={"ambito": altro})[0]
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=501, ruolo=preposto)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=501, ruolo=capoturno)
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=502, ruolo=soccorso, data_fine=timezone.localdate() - timedelta(days=1))

    def _stato(self):
        with patch.object(solari, "leggi_presenti", return_value=_solari_righe()) as m, \
             patch.object(services, "_anagrafica_per_cf", side_effect=_aggancio):
            s1 = services.stato()
            s2 = services.stato()
        return s1, s2, m

    def test_una_sola_lettura_per_la_durata_della_cache(self):
        s1, s2, m = self._stato()
        self.assertEqual(m.call_count, 1)
        self.assertEqual(len(s1["presenti"]), 3)
        self.assertEqual(s1, s2)

    def test_aggancio_per_codice_fiscale_e_incarichi_45001_in_essere(self):
        s, _, _ = self._stato()
        per_id = {p["solari_id"]: p for p in s["presenti"]}
        self.assertEqual(per_id[11]["legacy_id"], 501)
        self.assertEqual(per_id[11]["reparto"], "CNC")
        # Solo i ruoli dell'ambito 45001: «Capoturno» (produttivo) non è un incarico di sicurezza.
        self.assertEqual([i["nome"] for i in per_id[11]["incarichi"]], ["Preposto T"])
        # Assegnazione conclusa ieri: non conta.
        self.assertEqual(per_id[12]["incarichi"], [])
        self.assertIsNone(per_id[13]["legacy_id"])
        self.assertEqual(per_id[11]["entrata"], "07:58")

    def test_riepilogo_e_filtri(self):
        s, _, _ = self._stato()
        r = services.riepilogo(s["presenti"])
        self.assertEqual(r["totale"], 3)
        self.assertEqual(r["non_collegati"], 1)
        self.assertEqual(r["incarichi"][0]["nome"], "Preposto T")
        self.assertEqual(len(services.filtra(s["presenti"], q="verdi")), 1)
        self.assertEqual(len(services.filtra(s["presenti"], reparto="CNC")), 1)
        self.assertEqual(len(services.filtra(s["presenti"], incarico="Preposto T")), 1)

    def test_errore_di_rete_non_rompe_e_nasconde_il_pallino(self):
        with patch.object(solari, "leggi_presenti", side_effect=OSError("timeout")):
            s = services.stato()
            self.assertTrue(s["errore"])
            self.assertIsNone(services.ids_presenti())

    def test_non_configurato(self):
        with patch.dict("os.environ", {"SOLARI_DB_SERVER": ""}):
            self.assertFalse(solari.configurato())
            s = services.stato(forza=True)
        self.assertFalse(s["configurato"])

    def test_nome_database_non_sicuro_rifiutato(self):
        with patch.dict("os.environ", {"SOLARI_DB_SERVER": "srv", "SOLARI_DB_TIMBRATURE": "x];DROP"}):
            with self.assertRaises(solari.SolariNonConfigurato):
                solari.configurazione()

    def test_connessione_driver_18(self):
        env = {"SOLARI_DB_SERVER": r"srv\SOLARI", "SOLARI_DB_USER": "u", "SOLARI_DB_PASSWORD": "p",
               "SOLARI_DB_DRIVER": "{ODBC Driver 18 for SQL Server}", "SOLARI_DB_ENCRYPT": "1", "SOLARI_DB_TRUST_CERT": "1"}
        with patch.dict("os.environ", env):
            cs = solari.configurazione().connection_string()
        self.assertIn("Encrypt=yes;", cs)
        self.assertIn("TrustServerCertificate=yes;", cs)
        with patch.dict("os.environ", {**env, "SOLARI_DB_ENCRYPT": "", "SOLARI_DB_TRUST_CERT": ""}):
            cs = solari.configurazione().connection_string()
        self.assertNotIn("Encrypt", cs)

    def test_pallino(self):
        with patch.object(services, "ids_presenti", return_value={501}):
            html = Template("{% load presenti_tags %}{% pallino_presenza 501 %}|{% pallino_presenza 999 True %}"
                            ).render(Context({}))
        dentro, fuori = html.split("|")
        self.assertIn("is-dentro", dentro)
        self.assertIn("<style>", dentro)
        self.assertIn("is-fuori", fuori)
        self.assertIn("Fuori", fuori)
        self.assertNotIn("<style>", fuori)  # lo stile una sola volta per pagina
        with patch.object(services, "ids_presenti", return_value=None):
            self.assertEqual(Template("{% load presenti_tags %}{% pallino_presenza 501 %}").render(Context({})), "")

    def test_pallino_con_ids_passati_e_stile_separato(self):
        t = Template("{% load presenti_tags %}{% pallino_presenza 501 ids=ids stile=False %}|{% pallino_presenza 9 ids=ids stile=False %}|{% pallino_presenza 5 ids=nessuno %}")
        out = t.render(Context({"ids": {501}, "nessuno": None}))
        self.assertIn("is-dentro", out.split("|")[0])
        self.assertIn("is-fuori", out.split("|")[1])
        self.assertEqual(out.split("|")[2], "")
        self.assertNotIn("<style>", out)
        self.assertIn("<style>", Template("{% load presenti_tags %}{% pallino_presenza_stile %}").render(Context({})))

    def test_pdf(self):
        s, _, _ = self._stato()
        contenuto = pdf.genera_pdf(s["presenti"], timezone.localtime())
        self.assertTrue(contenuto.startswith(b"%PDF"))
        self.assertTrue(pdf.genera_pdf([], timezone.localtime(), contati=set()).startswith(b"%PDF"))


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisteTests(TestCase):
    def setUp(self):
        cache.clear()
        U = get_user_model()
        self.admin = U.objects.create_superuser("pres_admin", password="x")
        self.collega = U.objects.create_superuser("pres_collega", password="x")
        self.client.force_login(self.admin)
        p1 = patch.object(solari, "leggi_presenti", side_effect=lambda *a, **k: _solari_righe())
        p2 = patch.object(services, "_anagrafica_per_cf", side_effect=_aggancio)
        p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_lista_e_parziale(self):
        r = self.client.get(reverse("presenti:home"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ROSSI Mario")
        self.assertContains(r, 'hx-trigger="every 30s"')
        r = self.client.get(reverse("presenti:lista_parziale"), {"q": "bianchi"})
        self.assertContains(r, "BIANCHI Anna")
        self.assertNotContains(r, "ROSSI Mario")
        self.assertContains(r, "1 su 3")

    def test_pdf_e_guida(self):
        r = self.client.get(reverse("presenti:pdf"))
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertEqual(self.client.get(reverse("presenti:guida")).status_code, 200)
        r = self.client.get(reverse("presenti:guida"), {"formato": "pdf"})
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_appello_condiviso_fra_chi_conta(self):
        r = self.client.post(reverse("presenti:appello_avvia"), {"esercitazione": "1"})
        self.assertRedirects(r, reverse("presenti:appello"), fetch_redirect_response=False)
        a = Appello.objects.get()
        self.assertTrue(a.esercitazione)
        self.assertEqual(len(a.persone), 3)
        # Un secondo avvio entra nello stesso appello.
        self.client.post(reverse("presenti:appello_avvia"))
        self.assertEqual(Appello.objects.count(), 1)

        url = reverse("presenti:appello_spunta", args=[a.pk])
        self.client.post(url, {"solari_id": 11, "contato": "1"})
        # Il collega vede la spunta e ne aggiunge un'altra; la doppia spunta non duplica.
        altro = self.client_class()
        altro.force_login(self.collega)
        r = altro.get(reverse("presenti:appello_parziale", args=[a.pk]))
        self.assertContains(r, "Contato alle")
        altro.post(url, {"solari_id": 11, "contato": "1"})
        altro.post(url, {"solari_id": 12, "contato": "1"})
        self.assertEqual(AppelloSpunta.objects.filter(appello=a).count(), 2)
        r = altro.post(url, {"solari_id": 12, "contato": "0"})
        self.assertContains(r, "1</b> contati su <b>3")
        # Persona estranea all'appello: rifiutata.
        self.assertEqual(self.client.post(url, {"solari_id": 999, "contato": "1"}).status_code, 400)

        self.assertEqual(self.client.get(reverse("presenti:appello_stampa", args=[a.pk]))["Content-Type"],
                         "application/pdf")
        self.client.post(reverse("presenti:appello_chiudi", args=[a.pk]))
        a.refresh_from_db()
        self.assertFalse(a.aperto)
        # Ad appello chiuso le spunte non cambiano più.
        self.client.post(url, {"solari_id": 13, "contato": "1"})
        self.assertEqual(AppelloSpunta.objects.filter(appello=a).count(), 1)

    def test_verbale_e_elimina_solo_esercitazioni(self):
        self.client.post(reverse("presenti:appello_avvia"), {"esercitazione": "1", "nota": "prova"})
        a = Appello.objects.get()
        self.client.post(reverse("presenti:appello_spunta", args=[a.pk]), {"solari_id": 11, "contato": "1"})
        r = self.client.post(reverse("presenti:appello_chiudi", args=[a.pk]))
        self.assertRedirects(r, reverse("presenti:appello_verbale", args=[a.pk]), fetch_redirect_response=False)
        r = self.client.get(reverse("presenti:appello_verbale", args=[a.pk]))
        self.assertContains(r, "1/3")
        self.assertContains(r, "Elimina esercitazione")
        self.client.post(reverse("presenti:appello_verbale", args=[a.pk]), {"osservazioni": "Uscita nord ingombra"})
        a.refresh_from_db()
        self.assertEqual(a.osservazioni, "Uscita nord ingombra")
        r = self.client.get(reverse("presenti:appello_verbale_pdf", args=[a.pk]))
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        # Un collega che non l'ha avviata e non è amministratore del modulo non la elimina.
        altro = self.client_class()
        altro.force_login(self.collega)
        with patch("presenti.views.request_has_permission_code", return_value=False):
            self.assertEqual(altro.post(reverse("presenti:appello_elimina", args=[a.pk])).status_code, 403)
        self.client.post(reverse("presenti:appello_elimina", args=[a.pk]))
        self.assertFalse(Appello.objects.exists())

    def test_emergenza_reale_non_si_elimina(self):
        self.client.post(reverse("presenti:appello_avvia"))
        a = Appello.objects.get()
        self.assertEqual(self.client.post(reverse("presenti:appello_elimina", args=[a.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("presenti:appello_verbale", args=[a.pk])), "Elimina esercitazione")
        self.assertTrue(Appello.objects.exists())

    def test_impostazioni(self):
        r = self.client.post(reverse("presenti:impostazioni"),
                             {"azione": "salva", "presenti_sp_attivo": "1", "presenti_sp_raccolta": "Docs"})
        self.assertEqual(r.status_code, 302)
        from . import impostazioni

        self.assertTrue(impostazioni.attivo("presenti_sp_attivo"))
        self.assertFalse(impostazioni.attivo("presenti_avviso_uscite_attivo"))
        self.assertEqual(impostazioni.leggi("presenti_sp_raccolta"), "Docs")


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
def _accessi_finti():
    from datetime import datetime

    from fornitori.guestportal import Accesso

    oggi = timezone.localdate()
    return [Accesso(visita_id=77, stato="CHECKEDIN", tipo="SUPPLIER", nome="Paolo Verdi", azienda="Ditta Esempio Srl",
                    referente="Ufficio tecnico", motivo="", badge="V12",
                    ingresso=datetime.combine(oggi, datetime.min.time()).replace(hour=9, minute=15), uscita=None)]


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class EsterniTests(TestCase):
    """Visitatori e ditte del GuestPortal: in lista, nell'appello e nel PDF insieme ai dipendenti."""

    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser("pres_est", password="x")
        self.client.force_login(self.admin)
        for p in (patch.object(services, "_anagrafica_per_cf", side_effect=_aggancio),
                  patch("fornitori.guestportal.db_configurato", return_value=True)):
            p.start()
            self.addCleanup(p.stop)

    def _con(self, solari_ok=True, gp=None, gp_errore=False):
        ps = patch.object(solari, "leggi_presenti", side_effect=(lambda *a, **k: _solari_righe()) if solari_ok
                          else ConnectionError("giù"))
        pg = patch("fornitori.guestportal.presenti_ora",
                   side_effect=ConnectionError("giù") if gp_errore else (lambda: gp if gp is not None else _accessi_finti()))
        ps.start(), pg.start()
        self.addCleanup(ps.stop)
        self.addCleanup(pg.stop)

    def test_stato_include_esterni_con_id_negativo(self):
        self._con()
        s = services.stato()
        self.assertEqual(len(s["presenti"]), 3)
        self.assertEqual([(e["solari_id"], e["azienda"], e["entrata"]) for e in s["esterni"]],
                         [(-77, "Ditta Esempio Srl", "09:15")])
        self.assertEqual(s["errore_esterni"], "")

    def test_esterni_anche_se_solari_non_risponde(self):
        self._con(solari_ok=False)
        s = services.stato()
        self.assertTrue(s["errore"])
        self.assertEqual(len(s["esterni"]), 1)

    def test_guestportal_giu_avvisa_e_tiene_i_dipendenti(self):
        self._con(gp_errore=True)
        s = services.stato()
        self.assertEqual(len(s["presenti"]), 3)
        self.assertEqual(s["esterni"], [])
        self.assertIn("GuestPortal non risponde", s["errore_esterni"])
        r = self.client.get(reverse("presenti:lista_parziale"))
        self.assertContains(r, "GuestPortal non risponde")

    def test_lista_appello_e_pdf(self):
        self._con()
        r = self.client.get(reverse("presenti:lista_parziale"))
        self.assertContains(r, "Esterni in azienda (1)")
        self.assertContains(r, "Paolo Verdi")
        self.assertContains(r, "Ditta Esempio Srl")
        r = self.client.get(reverse("presenti:lista_parziale"), {"q": "esempio"})
        self.assertContains(r, "Paolo Verdi")
        self.assertNotContains(r, "ROSSI Mario")
        self.assertEqual(self.client.get(reverse("presenti:pdf"))["Content-Type"], "application/pdf")

        self.client.post(reverse("presenti:appello_avvia"))
        a = Appello.objects.get()
        self.assertEqual(len(a.persone), 4)
        url = reverse("presenti:appello_spunta", args=[a.pk])
        r = self.client.post(url, {"solari_id": -77, "contato": "1"})
        self.assertContains(r, "1</b> contati su <b>4")
        self.assertContains(r, "di cui 1 esterno")
        self.assertContains(r, "Esterno · Ditta Esempio Srl")
        self.assertEqual(self.client.get(reverse("presenti:appello_stampa", args=[a.pk]))["Content-Type"],
                         "application/pdf")

    def test_verbale_con_esterno_non_contato(self):
        """Gli esterni salvati nell'appello non hanno il reparto: il verbale deve aprirsi lo stesso."""
        self._con()
        self.client.post(reverse("presenti:appello_avvia"))
        a = Appello.objects.get()
        self.client.post(reverse("presenti:appello_chiudi", args=[a.pk]))
        r = self.client.get(reverse("presenti:appello_verbale", args=[a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Non contati alla chiusura (4)")
        self.assertContains(r, "PAOLO VERDI")
        self.assertContains(r, "<td>Ditta Esempio Srl</td>", html=True)
        self.assertContains(r, "<td>Esterno</td>", html=True)
        # Dipendente: si legge il reparto, se c'è.
        reparto = next(p["reparto"] for p in a.persone if p.get("reparto"))
        self.assertContains(r, f"<td>{reparto}</td>", html=True)
        self.assertTrue(self.client.get(reverse("presenti:appello_verbale_pdf", args=[a.pk])).content.startswith(b"%PDF"))

    def test_verbale_con_esterno_senza_azienda(self):
        self._con()
        self.client.post(reverse("presenti:appello_avvia"))
        a = Appello.objects.get()
        for p in a.persone:
            if p.get("esterno"):
                p["azienda"] = ""
        a.save(update_fields=["persone"])
        self.client.post(reverse("presenti:appello_chiudi", args=[a.pk]))
        r = self.client.get(reverse("presenti:appello_verbale", args=[a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "<td>—</td>", html=True)

    def test_pdf_con_esterni(self):
        self._con()
        s = services.stato()
        self.assertTrue(pdf.genera_pdf(s["presenti"], timezone.localtime(), esterni=s["esterni"]).startswith(b"%PDF"))
        self.assertTrue(pdf.genera_pdf([], timezone.localtime(), contati={-77}, esterni=s["esterni"]).startswith(b"%PDF"))


class AnalisiGiornataTests(SimpleTestCase):
    """Uscite non timbrate: si controllano tutte le timbrature del giorno, non solo l'ultima."""

    G = date(2026, 1, 13)

    def _t(self, *voci, giorno=None):
        g = giorno or self.G
        return [(datetime.combine(g, datetime.min.time()).replace(hour=int(h[:2]), minute=int(h[3:])), v)
                for h, v in (x.split() for x in voci)]

    def test_giornata_regolare(self):
        self.assertIsNone(solari.analizza_giornata(self._t("07:45 E", "12:00 U", "12:50 E", "17:00 U")))

    def test_uscita_mancante(self):
        e = solari.analizza_giornata(self._t("07:45 E", "12:00 U", "12:50 E"))
        self.assertEqual(e["tipo"], "uscita_mancante")
        self.assertIn("12:50", e["problema"])

    def test_uscita_timbrata_come_entrata(self):
        e = solari.analizza_giornata(self._t("06:47 E", "12:00 U", "12:55 E", "18:02 E"))
        self.assertEqual(e["tipo"], "verso_errato")
        self.assertIn("18:02", e["problema"])

    def test_due_uscite_di_fila_e_inizio_con_uscita(self):
        e = solari.analizza_giornata(self._t("07:30 E", "12:00 U", "17:00 U"))
        self.assertEqual(e["tipo"], "sequenza_irregolare")
        self.assertIn("due uscite di fila", e["problema"])
        e = solari.analizza_giornata(self._t("12:00 U", "13:00 E", "17:00 U"))
        self.assertIn("manca l'entrata", e["problema"])

    def test_rientro_timbrato_come_uscita(self):
        e = solari.analizza_giornata(self._t("07:50 E", "12:03 U", "13:01 U", "17:08 U"))
        self.assertEqual(e["tipo"], "verso_errato")
        self.assertIn("13:01", e["problema"])
        self.assertNotIn("17:08", e["problema"])

    def test_turno_a_cavallo_della_mezzanotte(self):
        domani = self.G + timedelta(days=1)
        sera = self._t("22:00 E")
        mattina = self._t("06:00 U", giorno=domani)
        self.assertIsNone(solari.analizza_giornata(sera, successiva=mattina[0]))
        self.assertIsNone(solari.analizza_giornata(mattina, precedente=sera[-1]))
        # Senza l'uscita del mattino dopo l'entrata della sera resta da sistemare.
        self.assertEqual(solari.analizza_giornata(sera)["tipo"], "uscita_mancante")


class PresenzaGiornataTests(SimpleTestCase):
    """Lista live: presenza decisa guardando tutte le timbrature di oggi (e ieri sera)."""

    def _leggi(self, righe):
        class _Cur:
            def execute(self, *a):
                pass

            def fetchall(self):
                return righe

        class _Conn:
            def cursor(self):
                return _Cur()

            def close(self):
                pass

        with patch.object(solari, "configurazione", return_value=solari.Configurazione(server="x", user="u", password="p", driver="d", db_anagrafico="A", db_timbrature="T", turno_elem=1)),              patch.object(solari, "_connetti", return_value=_Conn()):
            return {p["solari_id"]: p for p in solari.leggi_presenti()}

    def _r(self, sid, quando, verso):
        return (sid, "1", "ROSSI", "Mario", "CF", quando, "B", verso, "N")

    def test_rientro_timbrato_come_uscita_resta_presente(self):
        oggi = datetime.combine(date.today(), datetime.min.time())
        h = lambda hh, mm=0: oggi.replace(hour=hh, minute=mm)  # noqa: E731
        p = self._leggi([
            self._r(1, h(7, 50), "E"), self._r(1, h(12, 3), "U"), self._r(1, h(13, 1), "U"),
            self._r(2, h(7), "E"), self._r(2, h(12), "U"),
            self._r(3, h(7), "E"),
        ])
        self.assertIn(1, p)
        self.assertIn("rientro", p[1]["verifica"])
        self.assertNotIn(2, p)
        self.assertEqual(p[3]["verifica"], "")

    def test_turno_di_notte_iniziato_ieri_sera(self):
        ieri_sera = datetime.now() - timedelta(hours=3)
        if ieri_sera.date() == date.today():
            self.skipTest("serve un orario entro le 3 di notte per simulare ieri sera")
        p = self._leggi([self._r(5, ieri_sera, "E")])
        self.assertIn("turno di notte", p[5]["verifica"])


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class AndamentoTests(TestCase):
    """Cruscotto per reparto: persone dentro a ogni ora, solo numeri."""

    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser("pres_and", password="x")
        self.client.force_login(self.admin)
        oggi = datetime.combine(date.today(), datetime.min.time())
        giorno = {
            11: {"codice_fiscale": CF_A, "seq": [(oggi.replace(hour=6, minute=50), "E")]},
            12: {"codice_fiscale": CF_B, "seq": [(oggi.replace(hour=5, minute=30), "E"), (oggi.replace(hour=6, minute=10), "U")]},
        }
        for p in (patch.object(solari, "leggi_timbrature_giorno", return_value=giorno),
                  patch.object(solari, "leggi_presenti", side_effect=lambda *a, **k: _solari_righe()),
                  patch.object(services, "_anagrafica_per_cf", side_effect=_aggancio)):
            p.start()
            self.addCleanup(p.stop)

    def test_conteggi_per_ora_e_pagina(self):
        d = services.andamento()
        self.assertEqual(d["errore"], "")
        tot = d["totale"]["celle"]
        ore = d["ore"]
        if datetime.now().hour >= 7:
            self.assertEqual(tot[ore.index(6)], 1)   # alle 6:00 c'era solo chi era entrato alle 5:30
            self.assertEqual(tot[ore.index(7)], 1)   # alle 7:00 chi è entrato alle 6:50 (l'altro è uscito)
        r = self.client.get(reverse("presenti:andamento"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Andamento per reparto")
        self.assertNotContains(r, "Rossi")  # nessun nome


class UsciteTests(TestCase):
    def setUp(self):
        ieri = timezone.localdate() - timedelta(days=1)
        self.righe = [
            {"solari_id": 11, "matricola": "1001", "cognome": "Rossi", "nome": "Mario", "codice_fiscale": CF_A,
             "giorno": ieri, "entrata": datetime.combine(ieri, datetime.min.time()).replace(hour=8)},
            {"solari_id": 12, "matricola": "1002", "cognome": "Verdi", "nome": "Luigi", "codice_fiscale": CF_B,
             "giorno": ieri, "entrata": datetime.combine(ieri, datetime.min.time()).replace(hour=14)},
        ]
        p1 = patch.object(solari, "leggi_uscite_mancanti", side_effect=lambda *a: [dict(r) for r in self.righe])
        p2 = patch.object(services, "_anagrafica_per_cf", side_effect=_aggancio)
        p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_avviso_al_capo_una_volta_sola(self):
        from anagrafica.services import capo_team

        from . import uscite

        capi = {501: capo_team.Capo(700, "reparto", []), 502: capo_team.Capo(None)}
        with patch("anagrafica.services.capo_team.mappa_capi", return_value=capi), \
             patch.object(uscite, "_utente_e_email", return_value=(42, "capo@example.com")), \
             patch("core.notifiche.invia_notifica") as notifica, \
             patch("core.email_utils.send_hub_mail") as mail:
            esito = uscite.invia_avvisi()
            self.assertEqual(esito["capi_avvisati"], 1)
            self.assertEqual(esito["senza_capo"], 1)
            notifica.assert_called_once()
            mail.assert_called_once()
            self.assertIn("Rossi Mario", mail.call_args.args[1])
            # Secondo giro: niente di nuovo.
            esito = uscite.invia_avvisi()
            self.assertEqual(esito["gia_segnalate"], 2)
            notifica.assert_called_once()
        self.assertEqual(AvvisoUscitaMancante.objects.count(), 2)

    def test_problemi_di_timbratura_senza_mail(self):
        from anagrafica.services import capo_team

        from . import uscite

        for r in self.righe:
            r["tipo"] = "verso_errato"
        capi = {501: capo_team.Capo(700, "reparto", [])}
        with patch("anagrafica.services.capo_team.mappa_capi", return_value=capi),              patch.object(uscite, "_utente_e_email", return_value=(42, "capo@example.com")),              patch("core.notifiche.invia_notifica") as notifica,              patch("core.email_utils.send_hub_mail") as mail:
            esito = uscite.invia_avvisi()
        self.assertEqual(esito["solo_pagina"], 2)
        self.assertEqual(esito["capi_avvisati"], 0)
        notifica.assert_not_called()
        mail.assert_not_called()
        self.assertEqual(AvvisoUscitaMancante.objects.count(), 0)

    def test_disattivato(self):
        from core.models import SiteConfig

        from . import uscite

        SiteConfig.set("presenti_avviso_uscite_attivo", "0")
        self.assertTrue(uscite.invia_avvisi().get("disattivato"))

    def test_vista_filtra_la_squadra(self):
        U = get_user_model()
        capo = U.objects.create_superuser("pres_capo", password="x")
        self.client.force_login(capo)
        with patch("presenti.views.request_has_permission_code", side_effect=lambda req, code: code != "presenti.uscite.tutte"), \
             patch("core.operational_roles.get_legacy_anagrafica_id", return_value=700), \
             patch("anagrafica.services.capo_team.team_di", return_value={501}):
            r = self.client.get(reverse("presenti:uscite"))
        self.assertContains(r, "ROSSI Mario")
        self.assertNotContains(r, "VERDI Luigi")
        with patch("presenti.views.request_has_permission_code", return_value=True):
            r = self.client.get(reverse("presenti:uscite"))
        self.assertContains(r, "VERDI Luigi")


class ImportaIncarichiIniTests(TestCase):
    """Lettura del config.ini: BOM del Blocco note e file mancante."""

    def _esegui(self, percorso):
        import io

        from django.core.management import call_command
        from django.core.management.base import CommandError

        try:
            with patch.object(solari, "leggi_matricole", return_value={}):
                call_command("importa_incarichi_presenze", ini=str(percorso), stdout=io.StringIO())
        except CommandError as exc:
            return str(exc)
        return ""

    def test_file_con_bom_viene_letto(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as cartella:
            percorso = Path(cartella) / "config.ini"
            percorso.write_text(
                "\n[sharepoint]\nnome = a%b\n\n[incarichi_sicurezza]\nT999 = Preposto\n", encoding="utf-8-sig"
            )
            errore = self._esegui(percorso)
        self.assertNotIn("non trovata", errore)
        self.assertNotIn("Impossibile leggere", errore)

    def test_file_mancante_lo_dice(self):
        import tempfile
        from pathlib import Path

        errore = self._esegui(Path(tempfile.gettempdir()) / "non-esiste-pn" / "config.ini")
        self.assertIn("File non trovato", errore)
