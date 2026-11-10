"""Export Excel, fabbisogno consumabili, «Apri ticket», letture mensili per mese e correzioni minori.

Dati sintetici (IP di documentazione 192.0.2.x).
"""
import io
from datetime import date, timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.models import AuditLog

from . import services
from .models import (
    AvvisoStampante,
    DispositivoSNMP,
    Fattura,
    LetturaConsumabile,
    LetturaContatori,
    LetturaMensileContatori,
    Macchina,
    RigaFattura,
    SostituzioneConsumabile,
    StatoSNMP,
)
from .tests import _AuthedClientMixin
from .tests_tabelle import _sola_lettura

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _foglio(response, nome=None):
    wb = load_workbook(io.BytesIO(response.content))
    ws = wb[nome] if nome else wb.active
    return [list(r) for r in ws.iter_rows(values_only=True)]


def _toner(macchina, livelli, nome="TK-SYN-K", ora=None):
    """Una lettura al giorno fino a ``ora`` con i livelli dati (l'ultimo è quello attuale)."""
    ora = ora or timezone.now()
    for i, pct in enumerate(reversed(livelli)):
        LetturaConsumabile.objects.create(macchina=macchina, nome=nome, pct=pct, rilevata_il=ora - timedelta(days=i))


class FabbisognoTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ora = timezone.now()
        self.a = Macchina.objects.create(reparto="Alfa", matricola="SYN-F1", host="192.0.2.31", modello="Synth 1")
        self.b = Macchina.objects.create(reparto="Beta", matricola="SYN-F2", host="192.0.2.32", modello="Synth 1")
        # Alfa: 2 punti al giorno da 30% -> 20% in 5 giorni => ~10 giorni residui.
        _toner(self.a, [30, 28, 26, 24, 22, 20], ora=self.ora)
        # Beta: 1 punto al giorno da 95% -> 90% => ~90 giorni residui.
        _toner(self.b, [95, 94, 93, 92, 91, 90], ora=self.ora)
        for giorni_fa in (300, 200, 100):
            SostituzioneConsumabile.objects.create(macchina=self.a, nome="TK-SYN-K", pct_prima=2, pct_dopo=100,
                                                   rilevata_il=self.ora - timedelta(days=giorni_fa))

    def test_una_funzione_per_tutti_i_numeri(self):
        dati = services.fabbisogno_consumabili(ora=self.ora)
        self.assertEqual(dati["entro_30"], {self.a.pk})
        riga = dati["righe"][0]
        self.assertEqual((riga["nome"], riga["n_macchine"], riga["durata_media"], riga["cambi_misurati"]),
                         ("TK-SYN-K", 2, 100, 2))
        self.assertEqual(riga["pezzi_anno"], 7.3)  # 2 MFC × 365 / 100
        self.assertEqual((riga["entro_30"], riga["entro_60"]), (1, 1))
        self.assertEqual(riga["modelli"], ["Synth 1"])

    def test_riquadro_filtro_ed_excel_in_consumabili(self):
        r = self.client.get(reverse("contatori:consumabili"))
        self.assertContains(r, "Finiscono entro 30 giorni")
        self.assertContains(r, "?filtro=entro_30")
        r = self.client.get(reverse("contatori:consumabili") + "?filtro=entro_30")
        self.assertEqual([x["macchina"].pk for x in r.context["righe"]], [self.a.pk])
        self.assertEqual(r.context["entro_30"], 1)
        x = self.client.get(r.context["url_excel"])
        self.assertEqual(x["Content-Type"], XLSX)
        righe = _foglio(x)
        self.assertEqual(righe[0][:5], ["Reparto", "Matricola", "Modello", "IP", "Consumabile"])
        self.assertEqual([riga[0] for riga in righe[1:]], ["Alfa"])  # solo le righe del filtro

    def test_voce_nella_centrale(self):
        da_fare = services.cruscotto_operativo()["da_fare"]
        voce = next(t for t in da_fare if "entro 30 giorni" in t["titolo"])
        self.assertEqual(voce["titolo"], "1 MFC con un consumabile che finisce entro 30 giorni")
        self.assertTrue(voce["url"].endswith("?filtro=entro_30"))

    def test_pagina_fabbisogno_ed_excel(self):
        r = self.client.get(reverse("contatori:consumabili_fabbisogno"))
        self.assertContains(r, "TK-SYN-K")
        self.assertContains(r, "Fabbisogno")
        righe = _foglio(self.client.get(reverse("contatori:consumabili_fabbisogno") + "?formato=xlsx"))
        self.assertEqual(righe[1][:2], ["TK-SYN-K", 2])


class ExportElenchiTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-E1", host="192.0.2.41", modello="Synth")
        self.d = Macchina.objects.create(reparto="Dismessa", matricola="SYN-E2", attiva=False)
        LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q1", data=date(2026, 3, 31),
                                        a4_bn=100, a3_bn=0, a4_col=10, a3_col=0)
        LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q2", data=date(2026, 6, 30),
                                        a4_bn=90, a3_bn=0, a4_col=20, a3_col=0)

    def test_gestisci_letture_tutte_le_righe_del_filtro(self):
        url = reverse("contatori:letture_gestisci") + "?tipo=trimestrali&cali=1"
        r = self.client.get(url)
        self.assertContains(r, "Scarica Excel")
        righe = _foglio(self.client.get(r.context["url_excel"]))
        self.assertEqual(righe[0][4:8], ["A4 BN", "A3 BN", "A4 COL", "A3 COL"])
        self.assertEqual(len(righe), 2)  # solo la lettura con il calo
        self.assertEqual(righe[1][2], "2026-Q2")
        self.assertEqual(righe[1][-1], "calo A4 BN")

    def test_registro_letture(self):
        r = self.client.get(reverse("contatori:letture_registro") + "?trimestri=4")
        righe = _foglio(self.client.get(r.context["url_excel"]))
        self.assertEqual(righe[0][:3], ["Reparto", "Matricola", "Attiva"])
        self.assertEqual(len(righe[0]), 3 + 4)
        dettaglio = _foglio(self.client.get(r.context["url_excel"]), "Letture")
        self.assertIn("2026-Q2", [riga[2] for riga in dettaglio])

    def test_stampanti_mfc_con_i_filtri(self):
        righe = _foglio(self.client.get(reverse("contatori:macchine") + "?formato=xlsx"))
        self.assertEqual([riga[0] for riga in righe[1:]], ["Alfa"])
        righe = _foglio(self.client.get(reverse("contatori:macchine") + "?dismesse=1&formato=xlsx"))
        self.assertEqual(sorted(riga[0] for riga in righe[1:]), ["Alfa", "Dismessa"])

    def test_monitor_snmp(self):
        DispositivoSNMP.objects.create(nome="Switch sintetico", host="192.0.2.42",
                                       categoria=DispositivoSNMP.Categoria.RETE)
        r = self.client.get(reverse("contatori:snmp_centrale") + "?q=sintetico")
        self.assertContains(r, "Scarica Excel")
        x = self.client.get(r.context["url_excel"])
        self.assertEqual([riga[0] for riga in _foglio(x, "Dispositivi")[1:]], ["Switch sintetico"])
        self.assertEqual(len(_foglio(x, "Stampanti MFC")), 1)  # nessuna MFC con «sintetico»

    def test_archivio_fatture(self):
        f = Fattura.objects.create(numero="SYN-1", data=date(2026, 7, 5), trimestre="2026-Q2",
                                   periodo_al=date(2026, 6, 30))
        RigaFattura.objects.create(fattura=f, contratto="C-SYN", a4_bn=80)
        x = self.client.get(reverse("contatori:fatture") + "?formato=xlsx")
        self.assertEqual(x["Content-Type"], XLSX)
        self.assertIn("SYN-1", [riga[1] for riga in _foglio(x)])
        self.assertEqual(_foglio(x, "Righe fatture")[1][:3], ["2026-Q2", "SYN-1", "C-SYN"])

    def test_stessi_permessi_della_pagina(self):
        _sola_lettura(self)
        # Gestisci letture è una pagina di gestione: anche il suo Excel.
        r = self.client.get(reverse("contatori:letture_gestisci") + "?formato=xlsx")
        self.assertRedirects(r, reverse("contatori:dashboard"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("contatori:macchine") + "?formato=xlsx")["Content-Type"], XLSX)


class LettureMensiliPerMeseTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-M1", host="192.0.2.51")
        self.mese = timezone.localdate().replace(day=1)
        prima = (self.mese - timedelta(days=1)).replace(day=1)
        due_fa = (prima - timedelta(days=1)).replace(day=1)
        for mese, base in ((due_fa, 1000), (prima, 1100)):
            LetturaMensileContatori.objects.create(macchina=self.m, mese=mese, a4_bn=base, a3_bn=0, a4_col=0, a3_col=0)
        self.prima = prima

    def test_matrice_mancanti_e_totali(self):
        dati = services.letture_mensili_per_mese()
        self.assertEqual(len(dati["mesi"]), 12)
        celle = {c["mese"]: c for c in dati["righe"][0]["celle"]}
        self.assertEqual(celle[self.prima]["copie"]["totale"], 100)
        self.assertEqual(celle[self.mese]["stato"], "mancante")  # mese corrente senza lettura
        totale = {t["mese"]: t for t in dati["totali"]}[self.prima]
        self.assertEqual((totale["copie"], totale["macchine"]), (100, 1))
        self.assertEqual(dati["mancanti"], 1)

    def test_pagina_ed_excel_della_mail(self):
        r = self.client.get(reverse("contatori:letture_mensili"))
        self.assertContains(r, "Letture mensili")
        self.assertContains(r, "manca")
        x = self.client.get(reverse("contatori:letture_mensili") + f"?formato=xlsx&mese={self.prima:%Y-%m}")
        self.assertEqual(x["Content-Type"], XLSX)
        wb = load_workbook(io.BytesIO(x.content))
        self.assertEqual(wb.active.title, f"Letture {self.prima:%m-%Y}")  # stesso file della mail

    def test_anno_scelto(self):
        anno = self.mese.year
        r = self.client.get(reverse("contatori:letture_mensili") + f"?anno={anno}")
        self.assertEqual(r.context["mesi"][0], date(anno, 1, 1))


class ApriTicketTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-K1", host="192.0.2.61", modello="Synth",
                                         snmp_stato=StatoSNMP.ERROR, snmp_ultimo_errore="Timeout sintetico")
        AvvisoStampante.objects.create(macchina=self.m, chiave="k1", testo="Carta inceppata", critico=True)
        LetturaConsumabile.objects.create(macchina=self.m, nome="Toner sintetico", pct=5)

    def _url(self, response):
        url = response.context["url_ticket"]
        self.assertTrue(url.startswith(reverse("tickets:nuovo")))
        return parse_qs(urlparse(url).query)

    def test_pannello_e_scheda_precompilano_il_form(self):
        r = self.client.get(reverse("contatori:anteprima", args=["mfc", self.m.pk]))
        self.assertContains(r, "Apri ticket")
        q = self._url(r)
        self.assertEqual((q["tipo"], q["categoria"], q["priorita"]), (["IT"], ["STAMPANTE"], ["ALTA"]))
        self.assertEqual(q["titolo"], ["Stampante Alfa: Carta inceppata"])
        descrizione = q["descrizione"][0]
        for testo in ("SYN-K1", "192.0.2.61", "Timeout sintetico", "Carta inceppata", "Toner sintetico 5%"):
            self.assertIn(testo, descrizione)
        r = self.client.get(reverse("contatori:macchina", args=[self.m.pk]))
        self.assertContains(r, "Apri ticket")

    def test_il_form_ticket_si_apre_compilato_senza_creare_nulla(self):
        from tickets.models import Ticket

        r = self.client.get(reverse("contatori:anteprima", args=["mfc", self.m.pk]))
        n = Ticket.objects.count()
        form = self.client.get(r.context["url_ticket"])
        self.assertEqual(form.status_code, 200)
        self.assertContains(form, 'value="Stampante Alfa: Carta inceppata"')
        self.assertContains(form, "Timeout sintetico")
        self.assertEqual(Ticket.objects.count(), n)

    def test_senza_permesso_di_aprire_ticket_niente_pulsante(self):
        with mock.patch("tickets.services.accesso.puo_aprire_ticket", return_value=False):
            r = self.client.get(reverse("contatori:anteprima", args=["mfc", self.m.pk]))
        self.assertNotContains(r, "Apri ticket")


class CorrezioniMinoriTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-C1", host="192.0.2.71")

    def test_prova_snmp_richiede_la_gestione(self):
        _sola_lettura(self)
        with mock.patch("contatori.services.interroga_macchina") as interroga:
            r = self.client.post(reverse("contatori:macchina_test_snmp", args=[self.m.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 403)
        interroga.assert_not_called()
        self.assertNotContains(self.client.get(reverse("contatori:macchine")), "/test-snmp/")
        self.assertNotContains(self.client.get(reverse("contatori:macchina", args=[self.m.pk])), "Prova SNMP")

    def test_correzione_ip_singola_ha_l_audit(self):
        self.client.post(reverse("contatori:discovery_applica_ip", args=[self.m.pk]), {"host": "192.0.2.72"})
        log = AuditLog.objects.get(azione="discovery_ip_corretti")
        self.assertEqual(log.dettaglio["corretti"], [{"macchina_id": self.m.pk, "da": "192.0.2.71", "a": "192.0.2.72"}])
