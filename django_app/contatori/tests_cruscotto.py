"""Centrale: KPI operativi ed elenco «da fare». Dati sintetici."""
from datetime import date
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from . import services
from .models import Fattura, LetturaContatori, Macchina, RigaFattura, StatoSNMP
from .tests import _AuthedClientMixin

OGGI = date(2026, 8, 10)  # 2026-Q3, precedente 2026-Q2


def _lettura(m, trim, base, giorno=date(2026, 7, 2)):
    return LetturaContatori.objects.create(macchina=m, trimestre=trim, data=giorno,
                                           a4_bn=base, a3_bn=0, a4_col=0, a3_col=0)


class CruscottoTests(TestCase):
    def setUp(self):
        self.a = Macchina.objects.create(reparto="Alfa", matricola="SYN-1", contratto="K1",
                                         host="192.0.2.41", snmp_stato=StatoSNMP.OK)
        self.b = Macchina.objects.create(reparto="Beta", matricola="SYN-2", contratto="K2",
                                         host="192.0.2.42", snmp_stato=StatoSNMP.ERROR)

    def _titoli(self):
        return [t["titolo"] for t in services.cruscotto_operativo(oggi=OGGI)["da_fare"]]

    def test_segnala_letture_mancanti_fattura_e_irraggiungibili(self):
        _lettura(self.a, "2026-Q2", 100)
        _lettura(self.a, "2026-Q3", 200)
        titoli = self._titoli()
        self.assertIn("1 MFC senza lettura 2026-Q3", titoli)
        self.assertIn("Fattura 2026-Q2 non caricata", titoli)
        self.assertIn("1 MFC non raggiungibili", titoli)
        self.assertIn("2 letture mensili non registrate", titoli)
        # Le criticita' rosse vengono prima
        da_fare = services.cruscotto_operativo(oggi=OGGI)["da_fare"]
        self.assertEqual(da_fare[0]["livello"], "danger")

    def test_riconciliazione_con_eccesso_fatturato(self):
        _lettura(self.a, "2026-Q2", 90)
        _lettura(self.b, "2026-Q2", 50)
        f = Fattura.objects.create(numero="F", data=date(2026, 7, 5), trimestre="2026-Q2",
                                   periodo_al=date(2026, 6, 30))
        RigaFattura.objects.create(fattura=f, contratto="K1", a4_bn=100)
        c = services.cruscotto_operativo(oggi=OGGI)
        self.assertEqual(c["riconciliazione"]["anomalie"], 1)
        self.assertIn("Riconciliazione 2026-Q2 da verificare", [t["titolo"] for t in c["da_fare"]])
        self.assertNotIn("Fattura 2026-Q2 non caricata", [t["titolo"] for t in c["da_fare"]])

    def test_variazione_copie(self):
        _lettura(self.a, "2026-Q1", 0)
        _lettura(self.a, "2026-Q2", 100)
        _lettura(self.a, "2026-Q3", 250)
        c = services.cruscotto_operativo(oggi=OGGI)
        self.assertEqual(c["consumo_ultimo"]["totale"], 150)
        self.assertEqual(c["variazione"], 50)

    def test_mensili_non_segnalate_il_primo_del_mese(self):
        c = services.cruscotto_operativo(oggi=date(2026, 8, 1))
        self.assertFalse(any("mensili" in t["titolo"] for t in c["da_fare"]))


class DashboardTests(_AuthedClientMixin, TestCase):
    def test_nessuna_interrogazione_snmp_all_apertura(self):
        Macchina.objects.create(reparto="Alfa", matricola="SYN-9", host="192.0.2.49")
        with mock.patch.object(services, "interroga_macchina") as interroga, \
                mock.patch.object(services, "interroga_dispositivo") as dispositivo:
            r = self.client.get(reverse("contatori:dashboard"))
        self.assertEqual(r.status_code, 200)
        interroga.assert_not_called()
        dispositivo.assert_not_called()
        self.assertContains(r, "Da fare")
        self.assertContains(r, "+ Inserisci")


class NavigazioneTests(_AuthedClientMixin, TestCase):
    def _attive(self, url):
        import re
        html = self.client.get(url).content.decode()
        nav = html[html.index('<nav class="cnav"'):html.index("</nav>", html.index('<nav class="cnav"'))]
        return re.findall(r'class="[^"]*\bactive\b[^"]*">([^<]+)<', nav)

    def test_una_sola_voce_attiva(self):
        self.assertEqual(self._attive(reverse("contatori:snmp_profili")), ["Profili SNMP"])
        self.assertEqual(self._attive(reverse("contatori:snmp_centrale")), ["Monitor SNMP"])
        self.assertEqual(self._attive(reverse("contatori:importa_lettura")), ["Stampanti MFC"])
        self.assertEqual(self._attive(reverse("contatori:fattura_nuova")), ["Riconciliazione"])

    def test_wizard_sotto_configurazione_con_voce_attiva(self):
        html = self.client.get(reverse("contatori:dashboard")).content.decode()
        inizio = html.index('<span class="cnav-label">Configurazione</span>')
        config = html[inizio:html.index("</nav>", inizio)]
        for tipo in ("dispositivo", "macchina", "profilo"):
            self.assertIn(reverse("contatori:wizard_avvia", args=[tipo]), config)
        for tipo, voce in (("dispositivo", "+ Dispositivo SNMP"), ("macchina", "+ MFC"), ("profilo", "+ Profilo SNMP")):
            wizard = self.client.get(reverse("contatori:wizard_avvia", args=[tipo]))["Location"]
            self.assertEqual(self._attive(wizard), [voce])


class StatoFlottaTests(_AuthedClientMixin, TestCase):
    """Riquadri della Centrale: conteggi esclusivi e lista filtrata coerente."""

    def setUp(self):
        super().setUp()
        from datetime import timedelta
        from django.utils import timezone
        from .models import DispositivoSNMP
        ora = timezone.now()
        recente, vecchia = ora - timedelta(hours=2), ora - timedelta(days=10)
        Macchina.objects.create(reparto="Ok", matricola="F-1", host="192.0.2.71",
                                snmp_stato=StatoSNMP.OK, snmp_ultimo_controllo=recente)
        Macchina.objects.create(reparto="Err", matricola="F-2", host="192.0.2.72", snmp_stato=StatoSNMP.ERROR,
                                snmp_ultimo_controllo=vecchia, snmp_ultimo_errore="Timeout sintetico")
        Macchina.objects.create(reparto="Vecchia", matricola="F-3", host="192.0.2.73",
                                snmp_stato=StatoSNMP.OK, snmp_ultimo_controllo=vecchia)
        Macchina.objects.create(reparto="SenzaIP", matricola="F-4", snmp_stato=StatoSNMP.MAI)
        Macchina.objects.create(reparto="Spenta", matricola="F-5", host="192.0.2.75", attiva=False,
                                snmp_stato=StatoSNMP.ERROR)
        DispositivoSNMP.objects.create(nome="Ups", host="192.0.2.81", snmp_stato=StatoSNMP.WARNING,
                                       snmp_ultimo_controllo=recente)
        # Stato MAI con data recente (dato incoerente): conta tra i non interrogati, non in attenzione
        DispositivoSNMP.objects.create(nome="Mai", host="192.0.2.82", snmp_ultimo_controllo=recente)
        DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.83", snmp_stato=StatoSNMP.ERROR,
                                       snmp_ultimo_controllo=recente, snmp_ultimo_errore="authorizationError")

    def test_conteggi_esclusivi(self):
        f = services.stato_flotta()
        self.assertEqual((f["ok"], f["attenzione"], f["errore"], f["non_interrogati"]), (1, 1, 2, 2))
        self.assertEqual(f["totale"], 6)  # MFC senza IP e disattivate escluse

    def test_lista_filtrata_coincide_col_riquadro(self):
        attesi = {"ok": {"Ok"}, "attenzione": {"Ups"}, "errore": {"Err", "Sw"}, "non_interrogati": {"Vecchia", "Mai"}}
        for chiave, nomi in attesi.items():
            r = self.client.get(reverse("contatori:snmp_centrale"), {"flotta": chiave})
            trovati = {d.nome for d in r.context["dispositivi"]} | {m.reparto for m in r.context["macchine"]}
            self.assertEqual(trovati, nomi, chiave)

    def test_ultimi_errori_con_causa(self):
        errori = services.ultimi_errori_snmp()
        self.assertEqual([e["nome"] for e in errori], ["Sw", "Err"])  # piu' recente prima
        self.assertEqual(errori[0]["errore"], "authorizationError")

    def test_query_della_centrale_non_crescono_con_la_flotta(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .models import DispositivoSNMP

        def conta():
            with CaptureQueriesContext(connection) as q:
                self.client.get(reverse("contatori:dashboard"))
            return len(q)

        conta()  # la prima richiesta riscalda cache di sessione, navigazione e ACL
        prima = conta()
        for i in range(5):
            Macchina.objects.create(reparto=f"N{i}", matricola=f"N-{i}", host=f"192.0.2.{120 + i}",
                                    snmp_stato=StatoSNMP.ERROR, snmp_ultimo_errore="x")
            DispositivoSNMP.objects.create(nome=f"D{i}", host=f"192.0.2.{140 + i}", snmp_stato=StatoSNMP.ERROR)
        self.assertEqual(conta(), prima)

    def test_centrale_mostra_riquadri_con_link_filtrati(self):
        r = self.client.get(reverse("contatori:dashboard"))
        self.assertContains(r, "Stato flotta")
        self.assertContains(r, "?flotta=errore")
        self.assertContains(r, "?flotta=non_interrogati")
        self.assertContains(r, "Timeout sintetico")


class FattureDaRiconciliareTests(TestCase):
    def test_solo_trimestri_con_problemi(self):
        m = Macchina.objects.create(reparto="Alfa", matricola="R-1", contratto="K1")
        _lettura(m, "2026-Q1", 100)
        for trim, al, fornitore in (("2026-Q1", date(2026, 3, 31), 100), ("2026-Q2", date(2026, 6, 30), 50)):
            f = Fattura.objects.create(numero=f"F-{trim}", data=al, trimestre=trim, periodo_al=al)
            RigaFattura.objects.create(fattura=f, contratto="K1", a4_bn=fornitore)
        # Q1 torna; Q2 non ha la lettura interna
        self.assertEqual([r["trimestre"] for r in services.fatture_da_riconciliare()], ["2026-Q2"])


class ConsumabiliFiltroTests(_AuthedClientMixin, TestCase):
    def test_filtro_critici(self):
        from .models import LetturaConsumabile
        a = Macchina.objects.create(reparto="Alfa", matricola="C-1", host="192.0.2.91")
        Macchina.objects.create(reparto="Beta", matricola="C-2", host="192.0.2.92")
        LetturaConsumabile.objects.create(macchina=a, nome="Toner nero", pct=3)
        r = self.client.get(reverse("contatori:consumabili"), {"filtro": "critici"})
        self.assertEqual([x["macchina"].reparto for x in r.context["righe"]], ["Alfa"])
        self.assertContains(r, "Mostra tutte")


class MenuRaggruppatoTests(_AuthedClientMixin, TestCase):
    def test_gruppi_e_configurazione_solo_per_gestione(self):
        r = self.client.get(reverse("contatori:dashboard"))
        for gruppo in ("Operatività", "Economico", "Configurazione"):
            self.assertContains(r, f'<span class="cnav-label">{gruppo}</span>', html=False)
        with mock.patch("contatori.templatetags.contatori_acl._puo_gestire", return_value=False):
            r = self.client.get(reverse("contatori:dashboard"))
        self.assertNotContains(r, '<span class="cnav-label">Configurazione</span>', html=False)
        self.assertNotContains(r, ">Profili SNMP<")
        self.assertNotContains(r, reverse("contatori:wizard_avvia", args=["dispositivo"]))
        # Le letture proposte sono solo gestione: in consultazione il riquadro non e' un link
        self.assertNotContains(r, reverse("contatori:letture_proposte"))


class SchedaInfoTests(_AuthedClientMixin, TestCase):
    def test_info_macchina(self):
        from .models import CommunitySNMP, ProfiloSNMP
        p = ProfiloSNMP.objects.create(slug="syn", nome="Profilo sintetico", produttore="Syn")
        c = CommunitySNMP.objects.create(nome="Stampanti lettura", segreto_cifrato="x", versione="v2c")
        m = Macchina.objects.create(reparto="Alfa", matricola="I-1", modello="Syn 1", host="192.0.2.95",
                                    profilo_snmp=p, community_salvata=c, snmp_stato=StatoSNMP.ERROR,
                                    snmp_ultimo_errore="Nessuna risposta sintetica")
        r = self.client.get(reverse("contatori:macchina", args=[m.pk]))
        for testo in ("Info", "Profilo sintetico", "Stampanti lettura", "SNMPv2c", "Nessuna risposta sintetica",
                      "192.0.2.95:161"):
            self.assertContains(r, testo)
        self.assertNotContains(r, "segreto")

    def test_info_dispositivo_ultima_riuscita_e_fallita(self):
        from .models import DispositivoSNMP, RilevazioneSNMP
        d = DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.96", versione="v2c")
        RilevazioneSNMP.objects.create(dispositivo=d, stato=StatoSNMP.OK)
        RilevazioneSNMP.objects.create(dispositivo=d, stato=StatoSNMP.ERROR, errore="Timeout sintetico")
        r = self.client.get(reverse("contatori:snmp_dispositivo", args=[d.pk]))
        self.assertContains(r, "Ultima interrogazione riuscita")
        self.assertContains(r, "Ultima interrogazione fallita")
        self.assertContains(r, "Timeout sintetico")


class ConsumabiliTests(_AuthedClientMixin, TestCase):
    def test_riepilogo_non_raggiungibile_marcato_per_ordinamento(self):
        from . import views
        m = Macchina.objects.create(reparto="Alfa", matricola="SYN-8", host="192.0.2.48")
        with mock.patch.object(views, "_leggi_consumabili_cfg", return_value=(None, "timeout")):
            r = self.client.get(reverse("contatori:consumabili_riepilogo", args=[m.pk]))
        self.assertContains(r, 'data-stato="errore"')
        self.assertContains(r, "Non raggiungibile")
