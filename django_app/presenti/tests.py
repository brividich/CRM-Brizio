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
from django.test import TestCase, override_settings
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

    def test_impostazioni(self):
        r = self.client.post(reverse("presenti:impostazioni"),
                             {"azione": "salva", "presenti_sp_attivo": "1", "presenti_sp_raccolta": "Docs"})
        self.assertEqual(r.status_code, 302)
        from . import impostazioni

        self.assertTrue(impostazioni.attivo("presenti_sp_attivo"))
        self.assertFalse(impostazioni.attivo("presenti_avviso_uscite_attivo"))
        self.assertEqual(impostazioni.leggi("presenti_sp_raccolta"), "Docs")


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
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
