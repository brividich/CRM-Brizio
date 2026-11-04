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
        self.assertContains(resp, "Aggiungi una regola")
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
