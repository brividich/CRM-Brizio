"""Scadenzario generale: regole di visibilità, catalogo, scadenze generiche, avvisi, import."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dashboard.scadenze_providers import ScadenzaItem
from scadenzario import avvisi as av
from scadenzario import visibilita as vis
from scadenzario.models import (
    AvvisoInviato, CategoriaScadenza, RegolaVisibilita, ScadenzaGenerica, VoceConfig,
)

OGGI = date(2026, 11, 4)


def _item(source="hr", kind="qualifica", elemento="Carrellista", titolo="Carrellista", soggetto="Rossi Mario", giorni=5):
    return ScadenzaItem(source=source, kind=kind, kind_label=kind.title(), titolo=titolo, soggetto=soggetto,
                        reparto="", data_scadenza=OGGI + timedelta(days=giorni), giorni=giorni, url="/x/",
                        elemento=elemento, elemento_label=elemento)


def _utente(username="sz.user", **extra):
    from core.models import UserOnboarding

    user = get_user_model().objects.create_user(username, f"{username}@example.com", "pwd12345", **extra)
    UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())
    return user


def _ident(legacy=10, portale=(), aziendali=(), admin=False):
    return vis.Identita(legacy_user_id=legacy, ruoli_portale=frozenset(portale),
                        ruoli_aziendali=frozenset(aziendali), amministratore=admin)


class ChiaviTests(TestCase):
    def test_percorso_chiavi(self):
        self.assertEqual(vis.chiavi_di("hr", "qualifica", "Patentino Carrellista"),
                         ["hr", "hr|qualifica", "hr|qualifica|patentino-carrellista"])
        self.assertEqual(vis.chiavi_di("hr"), ["hr"])
        self.assertEqual(vis.antenati("a|b|c"), ["a", "a|b", "a|b|c"])


class ApplicaTests(TestCase):
    def setUp(self):
        self.request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True), method="GET")
        self.ident = _ident(legacy=10, portale={3}, aziendali={7})
        p = patch.object(vis, "identita_di", return_value=self.ident)
        p.start()
        self.addCleanup(p.stop)

    def _applica(self, voci, sistema=()):
        self.request.user = SimpleNamespace(is_authenticated=True)  # niente cache fra i casi
        return vis.applica(self.request, voci, raccogli_sistema=lambda fonti: [v for v in sistema if v.source in fonti])

    def test_senza_configurazione_restano_le_voci_del_modulo(self):
        voci = [_item()]
        self.assertEqual(self._applica(voci), voci)

    def test_voce_spenta_e_riaccesa_sotto(self):
        VoceConfig.objects.create(chiave="hr|qualifica", attiva=False)
        VoceConfig.objects.create(chiave="hr|qualifica|saldatore", attiva=True)
        voci = [_item(), _item(elemento="Saldatore", titolo="Saldatore")]
        self.assertEqual([v.elemento for v in self._applica(voci)], ["Saldatore"])

    def test_solo_regole_toglie_a_chi_non_e_nelle_regole(self):
        VoceConfig.objects.create(chiave="hr", modalita=VoceConfig.MODALITA_REGOLE)
        self.assertEqual(self._applica([_item()]), [])
        RegolaVisibilita.objects.create(chiave="hr|qualifica", persona_legacy_id=10)
        self.assertEqual(len(self._applica([_item()])), 1)

    def test_regola_aggiunge_voci_che_il_modulo_non_mostra(self):
        from core.models import AccessGroup

        altro = AccessGroup.objects.create(code="sz_altro", label="Altro")
        mio = AccessGroup.objects.create(code="sz_qualita", label="Qualità")
        self.ident.ruoli_portale = frozenset({mio.pk})
        sistema = [_item(source="asset", kind="administrative", elemento="Revisione", titolo="Revisione")]
        self.assertEqual(self._applica([], sistema), [])  # configurazione vuota
        RegolaVisibilita.objects.create(chiave="asset|administrative", ruolo_portale=altro)
        self.assertEqual(self._applica([], sistema), [])  # ruolo diverso
        RegolaVisibilita.objects.create(chiave="asset|administrative", ruolo_portale=mio)
        self.assertEqual(len(self._applica([], sistema)), 1)

    def test_regola_per_ruolo_aziendale_e_niente_doppioni(self):
        from anagrafica.models import RuoloOperativo

        ruolo = RuoloOperativo.objects.create(id=7, nome="RSPP")
        RegolaVisibilita.objects.create(chiave="hr|visita", ruolo_aziendale=ruolo)
        visita = _item(kind="visita", elemento="Periodica", titolo="Periodica")
        esito = self._applica([visita], [visita, _item(kind="visita", elemento="Preassuntiva", titolo="Preassuntiva")])
        self.assertEqual(sorted(v.elemento for v in esito), ["Periodica", "Preassuntiva"])

    def test_errore_lascia_le_voci_del_modulo(self):
        VoceConfig.objects.create(chiave="hr", attiva=False)
        with patch.object(vis.Configurazione, "attiva", side_effect=RuntimeError("x")):
            voci = [_item()]
            self.assertEqual(self._applica(voci), voci)


class CatalogoTests(TestCase):
    def test_albero_con_generiche_e_voci_osservate(self):
        from scadenzario import catalogo

        cat = CategoriaScadenza.objects.create(nome="Estintori")
        ScadenzaGenerica.objects.create(categoria=cat, titolo="Estintore 12", data_scadenza=OGGI + timedelta(days=400))
        radici = catalogo.costruisci(voci=[_item()], configurate={"hr|qualifica|vecchia": "Vecchia qualifica"})
        hr = catalogo.trova(radici, "hr")
        self.assertEqual(hr.n_voci, 1)
        self.assertIsNotNone(catalogo.trova(radici, "hr|qualifica|carrellista"))
        vecchia = catalogo.trova(radici, "hr|qualifica|vecchia")
        self.assertFalse(vecchia.presente)
        self.assertIsNotNone(catalogo.trova(radici, f"generiche|cat-{cat.pk}"))
        attivita = ScadenzaGenerica.objects.get()
        self.assertEqual(catalogo.trova(radici, f"generiche|cat-{cat.pk}|s{attivita.pk}").etichetta, "Estintore 12")


class PannelloTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("sz.admin", "sz.admin@example.com", "pwd12345")
        self.client.force_login(self.admin)

    def test_utente_normale_403(self):
        user = _utente()
        self.client.force_login(user)
        with patch("scadenzario.views.puo_gestire_pannello", return_value=False):
            self.assertEqual(self.client.get(reverse("scadenzario:gestione")).status_code, 403)

    def test_salva_voce_e_regole(self):
        with patch("dashboard.scadenze_providers.collect_sistema", return_value=[_item()]):
            resp = self.client.get(reverse("scadenzario:gestione") + "?chiave=hr|qualifica")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cerca ruolo o persona")
        resp = self.client.post(reverse("scadenzario:gestione_voce"),
                                {"chiave": "hr|qualifica", "attiva": "0", "modalita": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(VoceConfig.objects.get(chiave="hr|qualifica").attiva)
        with patch("scadenzario.forms.persone_choices", return_value=[(42, "Bianchi Anna")]):
            self.client.post(reverse("scadenzario:gestione_regola_aggiungi"),
                             {"chiave": "hr|qualifica", "tipo": "persona", "persona": "42", "livello": "VEDE"})
        regola = RegolaVisibilita.objects.get()
        self.assertEqual((regola.persona_legacy_id, regola.persona_nome), (42, "Bianchi Anna"))
        self.client.post(reverse("scadenzario:gestione_regola_togli", args=[regola.pk]))
        self.assertFalse(RegolaVisibilita.objects.exists())
        # «Come la voce superiore» su entrambi i campi = impostazione tolta
        self.client.post(reverse("scadenzario:gestione_voce"), {"chiave": "hr|qualifica", "attiva": "", "modalita": ""})
        self.assertFalse(VoceConfig.objects.exists())

    def test_chiave_non_valida(self):
        resp = self.client.post(reverse("scadenzario:gestione_voce"), {"chiave": "a||b", "attiva": "0"})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(VoceConfig.objects.exists())

    def test_rotte_condivise(self):
        from core.middleware import is_acl_shared_path

        self.assertTrue(is_acl_shared_path(reverse("scadenzario:gestione")))
        self.assertTrue(is_acl_shared_path(reverse("scadenzario:scadenza_dettaglio", args=[1])))


class GenericheTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("sz.gadmin", "sz.gadmin@example.com", "pwd12345")
        self.client.force_login(self.admin)
        self.cat = CategoriaScadenza.objects.create(nome="Certificati")

    def test_nuova_calcola_scadenza_e_rinnovo(self):
        resp = self.client.post(reverse("scadenzario:scadenza_nuova"), {
            "categoria": self.cat.pk, "titolo": "CPI", "ultimo_controllo": "2026-01-10", "validita_mesi": "12",
            "is_active": "on",
        })
        s = ScadenzaGenerica.objects.get()
        self.assertRedirects(resp, reverse("scadenzario:scadenza_dettaglio", args=[s.pk]))
        self.assertEqual(s.data_scadenza, date(2027, 1, 10))
        resp = self.client.post(reverse("scadenzario:scadenza_rinnovo", args=[s.pk]), {"eseguito_il": "2026-11-01"})
        s.refresh_from_db()
        self.assertEqual((s.ultimo_controllo, s.data_scadenza), (date(2026, 11, 1), date(2027, 11, 1)))
        r = s.rinnovi.get()
        self.assertEqual(r.scadenza_precedente, date(2027, 1, 10))

    def test_rinnovo_futuro_rifiutato(self):
        s = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="X", data_scadenza=OGGI)
        domani = timezone.localdate() + timedelta(days=1)
        self.client.post(reverse("scadenzario:scadenza_rinnovo", args=[s.pk]), {"eseguito_il": domani.isoformat()})
        self.assertFalse(s.rinnovi.exists())

    def test_gestore_di_una_sola_categoria(self):
        altra = CategoriaScadenza.objects.create(nome="Contratti")
        s1 = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Mia", data_scadenza=OGGI)
        s2 = ScadenzaGenerica.objects.create(categoria=altra, titolo="Altrui", data_scadenza=OGGI)
        RegolaVisibilita.objects.create(chiave=f"generiche|cat-{self.cat.pk}", persona_legacy_id=10,
                                        livello=RegolaVisibilita.LIVELLO_GESTISCE)
        user = _utente("sz.gestore")
        self.client.force_login(user)
        with patch("scadenzario.visibilita.identita_di", return_value=_ident(legacy=10)):
            elenco = self.client.get(reverse("scadenzario:elenco"))
            self.assertContains(elenco, "Mia")
            self.assertNotContains(elenco, "Altrui")
            self.assertEqual(self.client.get(reverse("scadenzario:scadenza_modifica", args=[s1.pk])).status_code, 200)
            self.assertEqual(self.client.get(reverse("scadenzario:scadenza_dettaglio", args=[s2.pk])).status_code, 403)
            self.assertEqual(self.client.get(reverse("scadenzario:scadenza_modifica", args=[s2.pk])).status_code, 403)

    def test_utente_senza_regole_non_vede_le_generiche(self):
        user = _utente("sz.nessuno")
        self.client.force_login(user)
        with patch("scadenzario.visibilita.identita_di", return_value=_ident(legacy=11)):
            self.assertEqual(self.client.get(reverse("scadenzario:elenco")).status_code, 403)

    def test_export_excel(self):
        ScadenzaGenerica.objects.create(categoria=self.cat, titolo="CPI", data_scadenza=OGGI)
        resp = self.client.get(reverse("scadenzario:elenco") + "?format=xlsx")
        self.assertEqual(resp["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_fonte_nello_scadenzario_globale_per_regola(self):
        from dashboard.scadenze_providers import collect_all

        s = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="CPI capannone", data_scadenza=timezone.localdate())
        user = _utente("sz.lettore")
        request = SimpleNamespace(user=user, method="GET", legacy_user=None, session={}, GET={})
        with patch("scadenzario.visibilita.identita_di", return_value=_ident(legacy=12)):
            voci = collect_all(request, sources={"generiche"})
            self.assertEqual(voci, [])
            RegolaVisibilita.objects.create(chiave=f"generiche|cat-{self.cat.pk}|s{s.pk}", persona_legacy_id=12)
            request.user = _utente("sz.lettore2")
            voci = collect_all(request, sources={"generiche"})
        self.assertEqual([v.titolo for v in voci], ["CPI capannone"])


class AvvisiTests(TestCase):
    def setUp(self):
        self.cat = CategoriaScadenza.objects.create(nome="Verifiche", email_avviso="cat@example.com")
        self.s = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Messa a terra",
                                                 data_scadenza=OGGI + timedelta(days=10), email_avviso="a@example.com; b@example.com")
        self.conf = {"preavviso": 30, "ripeti": 7, "riepilogo": 60}

    def test_regole_di_invio(self):
        self.assertEqual(av.da_avvisare(self.s, OGGI, self.conf)[0], True)
        self.s.data_scadenza = OGGI + timedelta(days=40)
        self.assertEqual(av.da_avvisare(self.s, OGGI, self.conf)[1], "fuori preavviso")
        self.s.data_scadenza = OGGI - timedelta(days=3)
        self.assertTrue(av.da_avvisare(self.s, OGGI, self.conf)[0])  # anche dopo la scadenza
        self.cat.avvisa_dopo_scadenza = False
        self.assertFalse(av.da_avvisare(self.s, OGGI, self.conf)[0])

    def test_invio_e_ripetizione(self):
        with patch("core.email_utils.send_hub_mail") as mail:
            esito = av.invia_avvisi_attivita(oggi=OGGI)
            self.assertEqual(esito["inviati"], 1)
            self.assertEqual(mail.call_args.args[2], ["a@example.com", "b@example.com"])
            a = AvvisoInviato.objects.get()
            a.inviato_il = timezone.make_aware(timezone.datetime(2026, 11, 4, 7, 15))
            a.save()
            self.assertEqual(av.invia_avvisi_attivita(oggi=OGGI + timedelta(days=3))["inviati"], 0)
            self.assertEqual(av.invia_avvisi_attivita(oggi=OGGI + timedelta(days=7))["inviati"], 1)

    def test_errore_invio_registrato(self):
        with patch("core.email_utils.send_hub_mail", side_effect=OSError("smtp giù")):
            esito = av.invia_avvisi_attivita(oggi=OGGI)
        self.assertEqual(esito["errori"], 1)
        self.assertFalse(AvvisoInviato.objects.get().riuscito)
        # Un invio fallito non conta per la ripetizione: domani si riprova.
        self.assertTrue(av.da_avvisare(self.s, OGGI + timedelta(days=1), self.conf)[0])

    def test_riepilogo_categoria(self):
        with patch("core.email_utils.send_hub_mail") as mail:
            esito = av.invia_riepiloghi_categorie(oggi=OGGI)
        self.assertEqual(esito["inviati"], 1)
        self.assertEqual(mail.call_args.args[2], ["cat@example.com"])
        self.assertIn("Messa a terra", mail.call_args.kwargs["body_html_fragment"])


class _Cursore:
    def __init__(self, dati):
        self.dati, self.righe = dati, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql):
        for tabella, righe in self.dati.items():
            if f"FROM {tabella}" in sql:
                self.righe = righe
                return
        self.righe = []

    def fetchall(self):
        return self.righe


class _Connessione:
    def __init__(self, dati):
        self.dati = dati

    def cursor(self):
        return _Cursore(self.dati)

    def close(self):
        pass


class ImportTests(TestCase):
    DATI = {
        "families": [{"id": 1, "name": "Estintori", "description": "", "alert_emails": "x@example.com"}],
        "products": [{
            "id": 5, "family_id": 1, "name": "Estintore 3", "description": "", "location": "Officina",
            "last_check_date": date(2026, 5, 1), "validita_mesi": 6, "expiry_date": date(2026, 11, 1),
            "preavviso_days": 15, "repeat_interval_days": None, "alert_emails": "y@example.com", "is_active": 1,
        }],
        "alert_logs": [{"id": 9, "product_id": 5, "sent_at": timezone.datetime(2026, 10, 20, 6, 0), "note": "Sent"}],
    }

    def test_prova_e_import_rilanciabile(self):
        with patch("pymysql.connect", return_value=_Connessione(self.DATI)):
            call_command("importa_scadenzario")
            self.assertFalse(ScadenzaGenerica.objects.exists())
            call_command("importa_scadenzario", "--apply", "--con-avvisi")
            call_command("importa_scadenzario", "--apply", "--con-avvisi")
        s = ScadenzaGenerica.objects.get()
        self.assertEqual((s.legacy_id, s.ubicazione, s.preavviso_giorni, s.categoria.nome), (5, "Officina", 15, "Estintori"))
        self.assertEqual(AvvisoInviato.objects.filter(importato=True).count(), 1)
        self.assertTrue(timezone.is_aware(AvvisoInviato.objects.get().inviato_il))


class PagineTests(TestCase):
    def test_tutte_le_pagine_si_aprono(self):
        admin = get_user_model().objects.create_superuser("sz.pagine", "sz.pagine@example.com", "pwd12345")
        self.client.force_login(admin)
        cat = CategoriaScadenza.objects.create(nome="Contratti", email_avviso="c@example.com")
        s = ScadenzaGenerica.objects.create(categoria=cat, titolo="Assistenza", data_scadenza=timezone.localdate(),
                                            validita_mesi=12, email_avviso="a@example.com")
        AvvisoInviato.objects.create(scadenza=s, categoria=cat, destinatari="a@example.com", esito="scade oggi")
        RegolaVisibilita.objects.create(chiave=f"generiche|cat-{cat.pk}", persona_legacy_id=5, persona_nome="Verdi Luca")
        pagine = [
            reverse("scadenze_globali"),
            reverse("scadenzario:gestione"),
            reverse("scadenzario:gestione") + f"?chiave=generiche|cat-{cat.pk}",
            reverse("scadenzario:gestione") + "?chiave=__pannello__",
            reverse("scadenzario:elenco"),
            reverse("scadenzario:scadenza_nuova"),
            reverse("scadenzario:scadenza_dettaglio", args=[s.pk]),
            reverse("scadenzario:scadenza_modifica", args=[s.pk]),
            reverse("scadenzario:categorie"),
            reverse("scadenzario:categoria_modifica", args=[cat.pk]),
            reverse("scadenzario:avvisi"),
            reverse("guida_modulo", args=["scadenzario"]),
        ]
        for url in pagine:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200, url)
        resp = self.client.get(reverse("scadenzario:gestione") + f"?chiave=generiche|cat-{cat.pk}")
        self.assertContains(resp, "Persona: Verdi Luca")
        self.assertContains(self.client.get(reverse("scadenze_globali")), "Assistenza")


class ImportNonSovrascriveTests(TestCase):
    def test_rilancio_tiene_le_modifiche_e_aggiorna_le_riscrive(self):
        with patch("pymysql.connect", return_value=_Connessione(ImportTests.DATI)):
            call_command("importa_scadenzario", "--apply")
            ScadenzaGenerica.objects.update(email_avviso="portale@example.com")
            CategoriaScadenza.objects.update(email_avviso="cat.portale@example.com")
            call_command("importa_scadenzario", "--apply", "--con-avvisi")
            s = ScadenzaGenerica.objects.get()
            self.assertEqual(s.email_avviso, "portale@example.com")
            self.assertEqual(s.categoria.email_avviso, "cat.portale@example.com")
            self.assertEqual(AvvisoInviato.objects.filter(scadenza=s, importato=True).count(), 1)
            call_command("importa_scadenzario", "--apply", "--aggiorna")
        s = ScadenzaGenerica.objects.get()
        self.assertEqual(s.email_avviso, "y@example.com")
        self.assertEqual(s.categoria.email_avviso, "x@example.com")


class CollegamentiTests(TestCase):
    """Collegare e unire le attività alle cose già presenti, sempre con una conferma."""

    def setUp(self):
        from sistema_gestione.models import Certificazione

        self.admin = _utente("coll.admin", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        self.cat = CategoriaScadenza.objects.create(nome="Categoria sintetica", email_avviso="cat@example.com")
        self.s = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Certificato ISO 9001",
                                                 data_scadenza=self.oggi + timedelta(days=5), email_avviso="a@example.com")
        self.cert = Certificazione.objects.create(norma="ISO9001", ente="Ente Esempio",
                                                  scade_il=self.oggi + timedelta(days=40))

    def _post(self, **dati):
        return self.client.post(reverse("scadenzario:scadenza_collega", args=[self.s.pk]), dati)

    def test_suggerisce_ma_non_collega_da_solo(self):
        from scadenzario.collegamenti import suggerimenti

        proposte = suggerimenti([self.s])
        self.assertEqual(proposte[self.s.pk][0]["tipo"], "certificazione")
        self.s.refresh_from_db()
        self.assertEqual(self.s.collegata_tipo, "")
        r = self.client.get(reverse("scadenzario:collega_elenco"))
        self.assertContains(r, "Certificato ISO 9001")

    def test_unire_lascia_una_voce_sola_con_la_data_del_modulo(self):
        from scadenzario.collegamenti import allinea_unite
        from scadenzario.fonte import collect_generiche
        from dashboard.scadenze_providers import ScadenzeContext

        self._post(tipo="certificazione", oggetto=self.cert.pk, unisci="1")
        self.s.refresh_from_db()
        self.assertTrue(self.s.unita)
        self.assertEqual(self.s.data_scadenza, self.cert.scade_il)
        self.assertEqual(collect_generiche(ScadenzeContext.build(SimpleNamespace(user=self.admin), sistema=True)), [])
        # Il modulo cambia data: l'attività la segue, così gli avvisi restano giusti.
        nuova = self.oggi + timedelta(days=90)
        type(self.cert).objects.filter(pk=self.cert.pk).update(scade_il=nuova)
        self.assertEqual(allinea_unite(), 1)
        self.s.refresh_from_db()
        self.assertEqual(self.s.data_scadenza, nuova)
        # Non si rinnova qui, e si può separare.
        self.client.post(reverse("scadenzario:scadenza_rinnovo", args=[self.s.pk]), {"eseguito_il": self.oggi.isoformat()})
        self.assertEqual(self.s.rinnovi.count(), 0)
        self.client.post(reverse("scadenzario:scadenza_scollega", args=[self.s.pk]), {"tipo": "certificazione", "solo_separa": "1"})
        self.s.refresh_from_db()
        self.assertFalse(self.s.unita)
        self.assertEqual(self.s.collegata_tipo, "certificazione")

    def test_tipo_senza_data_non_si_unisce(self):
        from anagrafica.models import TipoQualifica

        q = TipoQualifica.objects.create(nome="Qualifica sintetica")
        self._post(tipo="qualifica", oggetto=q.pk, unisci="1")
        self.s.refresh_from_db()
        self.assertEqual(self.s.collegata_tipo, "")
        self._post(tipo="qualifica", oggetto=q.pk)
        self.s.refresh_from_db()
        self.assertEqual((self.s.collegata_tipo, self.s.unita), ("qualifica", False))

    def test_senza_gestione_non_si_collega(self):
        utente = _utente("coll.utente", is_staff=False)
        self.client.force_login(utente)
        with patch("scadenzario.views.puo_gestire_categoria", return_value=False):
            r = self._post(tipo="certificazione", oggetto=self.cert.pk)
        self.assertIn(r.status_code, (302, 403))
        self.s.refresh_from_db()
        self.assertEqual(self.s.collegata_tipo, "")

    def test_scheda_e_certificazione_da_attivita(self):
        r = self.client.get(reverse("scadenzario:scadenza_dettaglio", args=[self.s.pk]),
                            {"cerca_tipo": "certificazione", "cerca": "Esempio"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["id"] for x in r.context["risultati"]], [self.cert.pk])
        url = reverse("sistema_gestione:esterni_certificazione_nuova") + f"?da_attivita={self.s.pk}"
        r = self.client.get(url)
        self.assertContains(r, "Certificato ISO 9001")


class RiquadroSchedaTests(TestCase):
    """Il riquadro nelle schede dei moduli mostra solo ciò che chi chiede può vedere."""

    def setUp(self):
        self.admin = _utente("riq.admin", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)
        self.url = reverse("scadenzario:scheda_riquadro")
        self.cat = CategoriaScadenza.objects.create(nome="Categoria sintetica")
        self.s = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Attività sintetica", collegata_tipo="corso",
                                                 collegata_id=7, data_scadenza=timezone.localdate() + timedelta(days=9))

    def test_vuoto_se_non_ce_nulla(self):
        r = self.client.get(self.url, {"percorso": "/x/", "collegata": "corso:8"})
        self.assertEqual(r.content, b"")
        r = self.client.get(self.url, {"percorso": "http://altro.example/", "collegata": "corso:7"})
        self.assertEqual(r.content, b"")

    def test_attivita_collegata(self):
        r = self.client.get(self.url, {"percorso": "/x/", "collegata": "corso:7", "nome": "Corso sintetico"})
        self.assertContains(r, "Attività sintetica")
        self.assertContains(r, "q=Corso+sintetico")

    def test_voci_solo_della_scheda(self):
        voce = _item()
        voce.url = "/modulo/5/#parte"
        altra = _item()
        altra.url = "/modulo/6/"
        altra.titolo = "Altra sintetica"
        with patch("dashboard.scadenze_providers.collect_all", return_value=[voce, altra]):
            r = self.client.get(self.url, {"percorso": "/modulo/5/", "fonti": voce.source})
        self.assertContains(r, "Me ne occupo io")
        self.assertNotContains(r, "Altra sintetica")

    def test_chi_non_vede_lattivita_non_la_trova(self):
        self.client.force_login(_utente("riq.utente"))
        r = self.client.get(self.url, {"percorso": "/x/", "collegata": "corso:7"})
        self.assertEqual(r.content, b"")

    def test_presa_torna_alla_scheda_ma_non_fuori(self):
        r = self.client.post(reverse("scadenzario:presa_in_carico"), {"azione": "lascia", "chiave": "x", "next": "/modulo/5/"})
        self.assertEqual(r.url, "/modulo/5/")
        r = self.client.post(reverse("scadenzario:presa_in_carico"), {"azione": "lascia", "chiave": "x", "next": "https://altro.example/"})
        self.assertEqual(r.url, reverse("scadenze_globali"))


from scadenzario.models import PresaInCarico  # noqa: E402


class AssegnazioneTests(TestCase):
    """Chi riceve o perde una scadenza lo viene a sapere; assegna solo chi può."""

    def setUp(self):
        self.admin = _utente("ass.admin", is_superuser=True, is_staff=True)
        self.collega = _utente("ass.collega")
        self.terzo = _utente("ass.terzo")
        self.client.force_login(self.admin)
        self.voce = _item(giorni=3)
        self.dati = {"chiave": "c" * 40, "data": self.voce.data_scadenza.isoformat()}

    def _post(self, **extra):
        with patch("scadenzario.views_calendario._scadenza_visibile", return_value=self.voce), \
                patch("scadenzario.views_calendario.avvisa_utente") as avvisa:
            r = self.client.post(reverse("scadenzario:presa_in_carico"), {**self.dati, **extra})
        return r, avvisa

    def test_assegna_notifica_la_persona(self):
        r, avvisa = self._post(azione="assegna", persona="Collega (ass.collega)")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PresaInCarico.objects.get().utente, self.collega)
        self.assertEqual(avvisa.call_args.args[0], self.collega)

    def test_nome_non_in_elenco_non_assegna(self):
        self._post(azione="assegna", persona="Qualcuno a caso")
        self.assertFalse(PresaInCarico.objects.exists())

    def test_chi_non_ha_la_scadenza_non_assegna(self):
        self.client.force_login(self.terzo)
        with patch("scadenzario.views_calendario.puo_gestire_pannello", return_value=False):
            r, _ = self._post(azione="assegna", persona="Collega (ass.collega)")
        self.assertEqual(r.status_code, 403)

    def test_nota_non_assegna_la_scadenza(self):
        r, avvisa = self._post(azione="nota", nota="chiamata la ditta")
        self.assertEqual(r.status_code, 302)
        p = PresaInCarico.objects.get()
        self.assertEqual((p.utente_id, p.fornitore_id, p.nota, p.nota_da_id), (None, None, "chiamata la ditta", self.admin.id))
        self.assertFalse(p.assegnata)
        avvisa.assert_not_called()
        # Nota svuotata e nessuno incaricato: la riga sparisce.
        self._post(azione="nota", nota="")
        self.assertFalse(PresaInCarico.objects.exists())

    def test_nota_non_cambia_chi_se_ne_occupa(self):
        PresaInCarico.objects.create(chiave=self.dati["chiave"], utente=self.collega, descrizione="x", data_scadenza=self.voce.data_scadenza)
        self.client.force_login(self.terzo)
        self._post(azione="nota", nota="sollecitato")
        p = PresaInCarico.objects.get()
        self.assertEqual((p.utente_id, p.nota), (self.collega.id, "sollecitato"))

    def test_presa_mantiene_la_nota(self):
        PresaInCarico.objects.create(chiave=self.dati["chiave"], nota="già sentito", descrizione="x", data_scadenza=self.voce.data_scadenza)
        self._post(azione="prendi")
        p = PresaInCarico.objects.get()
        self.assertEqual((p.utente_id, p.nota), (self.admin.id, "già sentito"))

    def test_assegna_a_fornitore_esterno(self):
        from anagrafica.models import Fornitore

        f = Fornitore.objects.create(ragione_sociale="Ditta Sintetica Srl")
        PresaInCarico.objects.create(chiave=self.dati["chiave"], utente=self.collega, descrizione="x", data_scadenza=self.voce.data_scadenza)
        r, avvisa = self._post(azione="assegna", persona=f"Ditta Sintetica Srl · fornitore esterno [F{f.pk}]")
        self.assertEqual(r.status_code, 302)
        p = PresaInCarico.objects.get()
        self.assertEqual((p.utente_id, p.fornitore_id, p.assegnato_da_id), (None, f.pk, self.admin.id))
        self.assertEqual(p.incaricato_nome, "Ditta Sintetica Srl")
        # Chi l'aveva prima lo viene a sapere.
        self.assertEqual(avvisa.call_args.args[0], self.collega)
        self.assertIn("fornitore esterno", avvisa.call_args.args[2])

    def test_fornitore_non_attivo_non_assegna(self):
        from anagrafica.models import Fornitore

        f = Fornitore.objects.create(ragione_sociale="Ditta Spenta", is_active=False)
        self._post(azione="assegna", persona=f"Ditta Spenta · fornitore esterno [F{f.pk}]")
        self.assertFalse(PresaInCarico.objects.exists())

    def test_chi_affida_al_fornitore_puo_lasciare(self):
        from anagrafica.models import Fornitore

        f = Fornitore.objects.create(ragione_sociale="Ditta Sintetica Srl")
        PresaInCarico.objects.create(chiave=self.dati["chiave"], fornitore=f, assegnato_da=self.collega,
                                     descrizione="x", data_scadenza=self.voce.data_scadenza)
        self.client.force_login(self.terzo)
        with patch("scadenzario.views_calendario.puo_gestire_pannello", return_value=False):
            self._post(azione="lascia")
        self.assertTrue(PresaInCarico.objects.exists())
        self.client.force_login(self.collega)
        with patch("scadenzario.views_calendario.puo_gestire_pannello", return_value=False):
            self._post(azione="lascia")
        self.assertFalse(PresaInCarico.objects.exists())

    def test_subentro_avvisa_chi_laveva(self):
        PresaInCarico.objects.create(chiave=self.dati["chiave"], utente=self.collega, descrizione="x", data_scadenza=self.voce.data_scadenza)
        _, avvisa = self._post(azione="prendi")
        self.assertEqual(PresaInCarico.objects.get().utente, self.admin)
        self.assertEqual(avvisa.call_args.args[0], self.collega)

    def test_responsabile_avvisato_a_scaletta(self):
        from scadenzario.avvisi import _ricorda_al_responsabile

        conf = {"preavviso": 30}
        cat = CategoriaScadenza.objects.create(nome="Categoria sintetica")
        oggi = timezone.localdate()
        s = ScadenzaGenerica.objects.create(categoria=cat, titolo="Sintetica", responsabile=self.collega, data_scadenza=oggi + timedelta(days=7))
        with patch("scadenzario.notifiche.avvisa_utente") as avvisa:
            _ricorda_al_responsabile(s, oggi, conf)
            self.assertEqual(avvisa.call_count, 1)
            s.data_scadenza = oggi + timedelta(days=9)
            _ricorda_al_responsabile(s, oggi, conf)
            s.data_scadenza = oggi + timedelta(days=60)
            _ricorda_al_responsabile(s, oggi, conf)
            self.assertEqual(avvisa.call_count, 1)

    def test_le_mie_scadenze_in_home(self):
        from django.core.cache import cache
        from django.test import RequestFactory

        from dashboard.views_mie_attivita import _mie_scadenze
        from scadenzario.calendario import chiave_scadenza

        cache.clear()
        mia, altrui, lontana = _item(titolo="Mia", soggetto="X", giorni=2), _item(titolo="Altrui", soggetto="Y", giorni=2), _item(titolo="Lontana", soggetto="Z", giorni=40)
        for v in (mia, lontana):
            PresaInCarico.objects.create(chiave=chiave_scadenza(v), utente=self.admin, descrizione="x", data_scadenza=v.data_scadenza)
        request = RequestFactory().get("/")
        request.user = self.admin
        with patch("dashboard.scadenze_providers.collect_all", return_value=[mia, altrui, lontana]) as raccolta:
            righe = _mie_scadenze(request)
            _mie_scadenze(request)
        self.assertEqual([r["title"] for r in righe], ["Mia"])
        self.assertNotIn("hr", raccolta.call_args.kwargs["sources"])
        self.assertEqual(raccolta.call_count, 1)
        cache.clear()

    def test_task_in_errore_risulta_fallito(self):
        from scadenzario import tasks

        with patch("scadenzario.avvisi.invia_avvisi_attivita", side_effect=RuntimeError("sintetico")):
            with self.assertRaises(RuntimeError):
                tasks.run_avvisi_attivita()


class GuidaTests(TestCase):
    """Guida completa: si apre e si scarica, cita ogni fonte, le immagini esistono."""

    def setUp(self):
        self.user = _utente("guida.admin", is_superuser=True, is_staff=True)
        self.client.force_login(self.user)

    def test_pagina_e_pdf(self):
        r = self.client.get(reverse("scadenzario:guida"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="collegamenti"')
        r = self.client.get(reverse("scadenzario:guida"), {"formato": "pdf"})
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_ogni_fonte_e_nella_guida(self):
        from dashboard.scadenze_providers import PROVIDERS, SOURCE_LABELS

        from .guida import SEZIONI

        fonti = next(s for s in SEZIONI if s["id"] == "fonti")
        nomi = {t for tipo, c in fonti["blocchi"] if tipo == "def" for t, _ in c}
        for code in PROVIDERS:
            self.assertIn(SOURCE_LABELS[code], nomi)

    def test_le_immagini_esistono(self):
        from django.contrib.staticfiles import finders

        from .guida import SEZIONI

        for s in SEZIONI:
            for tipo, c in s["blocchi"]:
                if tipo == "img":
                    self.assertTrue(finders.find(c[0]), c[0])


class AnteprimaAvvisiTests(TestCase):
    OGGI = date(2026, 11, 6)

    def setUp(self):
        self.cat = CategoriaScadenza.objects.create(nome="Contratti", email_avviso="c@example.com")

    def _s(self, titolo, giorni, email=""):
        return ScadenzaGenerica.objects.create(
            categoria=self.cat, titolo=titolo, data_scadenza=self.OGGI + timedelta(days=giorni), email_avviso=email)

    def test_divide_e_non_scrive_e_coincide_con_il_vero_invio(self):
        from scadenzario import avvisi as av

        parte = self._s("Parte", 5, "a@example.com")
        self._s("Senza", 5)
        self._s("Lontana", 200, "b@example.com")
        attesa = self._s("Attesa", 5, "d@example.com")
        AvvisoInviato.objects.create(scadenza=attesa, categoria=self.cat, riuscito=True,
                                     inviato_il=timezone.make_aware(timezone.datetime(2026, 11, 5, 8, 0)))
        prima = AvvisoInviato.objects.count()
        esito = av.anteprima(oggi=self.OGGI)
        self.assertEqual([r["scadenza"].pk for r in esito["partono"]], [parte.pk])
        self.assertEqual([r["scadenza"].titolo for r in esito["senza"]], ["Senza"])
        self.assertEqual([r["scadenza"].pk for r in esito["aspettano"]], [attesa.pk])
        self.assertEqual(esito["aspettano"][0]["prossimo"], date(2026, 11, 12))
        self.assertEqual(AvvisoInviato.objects.count(), prima)
        self.assertEqual(av.invia_avvisi_attivita(oggi=self.OGGI, dry_run=True)["inviati"], len(esito["partono"]))

    def test_categorie_limita_e_prossimi_invii(self):
        from scadenzario import avvisi as av

        self._s("Parte", 5, "a@example.com")
        self.assertEqual(av.anteprima(oggi=self.OGGI, categorie=set())["partono"], [])
        roma = timezone.get_current_timezone()
        prima = timezone.datetime(2026, 11, 5, 7, 0, tzinfo=roma)
        dopo = timezone.datetime(2026, 11, 5, 7, 15, tzinfo=roma)
        self.assertEqual(av.prossimo_invio(prima), date(2026, 11, 5))
        self.assertEqual(av.prossimo_invio(dopo), date(2026, 11, 6))
        self.assertEqual(av.prossimo_riepilogo(dopo), date(2026, 12, 1))
        self.assertEqual(av.prossimo_riepilogo(timezone.datetime(2026, 12, 1, 7, 0, tzinfo=roma)), date(2026, 12, 1))

    def test_comando_non_invia(self):
        from io import StringIO

        self._s("Parte", 5, "a@example.com")
        with patch("core.email_utils.send_hub_mail") as invio:
            out = StringIO()
            call_command("scadenzario_avvisi", "--giorno", "2026-11-06", stdout=out)
        invio.assert_not_called()
        self.assertIn("1 mail", out.getvalue())
        self.assertFalse(AvvisoInviato.objects.exists())


class GestioneSemplificataTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("sz.g", "sz.g@example.com", "pwd12345")
        self.client.force_login(self.admin)
        self.cat = CategoriaScadenza.objects.create(nome="Contratti", email_avviso="c@example.com")
        self.a = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Uno", data_scadenza=timezone.localdate(),
                                                 validita_mesi=12, email_avviso="u@example.com")
        self.b = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Due", data_scadenza=timezone.localdate())

    def _massa(self, **dati):
        return self.client.post(reverse("scadenzario:scadenze_massa"), {"ids": [self.a.pk, self.b.pk], **dati})

    def test_massa_responsabile_e_destinatari(self):
        self._massa(azione="responsabile", responsabile=self.admin.pk)
        self.a.refresh_from_db()
        self.assertEqual(self.a.responsabile_id, self.admin.pk)
        self._massa(azione="destinatari_aggiungi", email="n@example.com; u@example.com")
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.destinatari, ["u@example.com", "n@example.com"])
        self.assertEqual(self.b.destinatari, ["n@example.com", "u@example.com"])
        self._massa(azione="destinatari_categoria")
        self.b.refresh_from_db()
        self.assertEqual(self.b.destinatari, ["c@example.com"])
        self._massa(azione="sospendi")
        self.b.refresh_from_db()
        self.assertFalse(self.b.is_active)

    def test_massa_rifiuta_indirizzo_non_valido(self):
        self._massa(azione="destinatari_sostituisci", email="non-valido")
        self.a.refresh_from_db()
        self.assertEqual(self.a.destinatari, ["u@example.com"])

    def test_massa_tocca_solo_le_categorie_gestite(self):
        altra = CategoriaScadenza.objects.create(nome="Altra")
        fuori = ScadenzaGenerica.objects.create(categoria=altra, titolo="Fuori")
        with patch("scadenzario.views.categorie_gestibili", return_value={self.cat.pk}):
            self.client.post(reverse("scadenzario:scadenze_massa"),
                             {"ids": [self.a.pk, fuori.pk], "azione": "sospendi"})
        self.a.refresh_from_db(); fuori.refresh_from_db()
        self.assertFalse(self.a.is_active)
        self.assertTrue(fuori.is_active)
        with patch("scadenzario.views.categorie_gestibili", return_value=set()):
            r = self.client.post(reverse("scadenzario:scadenze_massa"), {"ids": [fuori.pk], "azione": "sospendi"})
        self.assertEqual(r.status_code, 403)

    def test_regola_dal_menu_unico_torna_alla_categoria(self):
        from core.models import AccessGroup

        gruppo = AccessGroup.objects.create(code="sz_prova", label="Prova")
        pagina = reverse("scadenzario:categoria_modifica", args=[self.cat.pk])
        r = self.client.post(reverse("scadenzario:gestione_regola_aggiungi"), {
            "chiave": f"generiche|cat-{self.cat.pk}", "chi": f"ruolo_portale:{gruppo.pk}",
            "livello": "GESTISCE", "next": pagina,
        })
        self.assertRedirects(r, pagina, fetch_redirect_response=False)
        regola = RegolaVisibilita.objects.get()
        self.assertEqual((regola.ruolo_portale_id, regola.livello), (gruppo.pk, "GESTISCE"))
        self.assertContains(self.client.get(reverse("scadenzario:categorie")), "Prova")
        self.assertContains(self.client.get(pagina), "Prova")

    def test_next_esterno_ignorato(self):
        r = self._massa(azione="sospendi", next="https://esempio.invalid/x")
        self.assertEqual(r.url, reverse("scadenzario:elenco"))

    def test_da_sistemare_e_contatori_stabili(self):
        from scadenzario.controlli import da_sistemare

        titoli = {v["titolo"] for v in da_sistemare()}
        self.assertIn("Attività senza responsabile", titoli)
        self.assertIn("Categorie senza nessuno assegnato", titoli)
        self.assertContains(self.client.get(reverse("scadenzario:gestione")), "Da sistemare")
        r = self.client.get(reverse("scadenzario:elenco"), {"stato": "scadute"})
        self.assertEqual(r.context["n_tutte"], 2)
        self.assertEqual(len(r.context["righe"]), 0)
        r = self.client.get(reverse("scadenzario:elenco"), {"senza": "destinatari"})
        self.assertEqual([s.pk for s in r.context["righe"]], [self.b.pk])

    def test_rinnovato_oggi_solo_con_validita(self):
        r = self.client.get(reverse("scadenzario:scadenza_dettaglio", args=[self.b.pk]))
        self.assertNotContains(r, "Rinnovato oggi")
        r = self.client.get(reverse("scadenzario:scadenza_dettaglio", args=[self.a.pk]))
        self.assertContains(r, "Rinnovato oggi")
