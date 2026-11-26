"""Quote CMM: esclusione report, rimisure, note, quote unite, deriva e segnali, cruscotto, avvisi, FAI, PDF. Dati inventati."""
from __future__ import annotations

import json
from datetime import date, timedelta

from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from . import report_cmm_indice as cmm
from .models import AliasQuotaCMM, CartellaReportCMM, ImpostazioniQuoteCMM, MisuraCMM, NotaQuotaCMM, ReportCMM
from .tests import ProduzioneBase


class CalcoliTests(SimpleTestCase):
    def test_deriva(self):
        sale = [0.1 + i * 0.04 for i in range(20)]               # da 10% a 86% della tolleranza
        d = cmm.deriva(sale)
        self.assertEqual(d["verso"], "sup")
        self.assertTrue(1 <= d["pezzi"] <= 5)
        self.assertIsNone(cmm.deriva([0.1, -0.1] * 10))            # rumore senza tendenza
        self.assertIsNone(cmm.deriva([0.0 + i * 0.001 for i in range(20)]))   # pendenza trascurabile
        self.assertIsNone(cmm.deriva([0.5] * 5))                   # troppo pochi punti

    def test_segnali(self):
        xs = [10.0, 10.02, 9.98, 10.01, 9.99] * 2 + [10.03] * 9 + [10.0, 9.97, 10.01]
        regole = {g["regola"] for g in cmm.segnali(xs)}
        self.assertIn("lato", regole)
        sale = [1, 2, 3, 4, 5, 6, 7, 5, 4, 3]
        self.assertTrue(any(g["regola"] == "trend" and g["su"] for g in cmm.segnali(sale)))
        self.assertTrue(any(g["regola"] == "3sigma" for g in cmm.segnali([0.0] * 30 + [5.0] + [0.0] * 5)))

    def test_ultima_per_seriale(self):
        report = [[1, "SN1", "OP", "2026-01-01"], [2, "SN2", "OP", "2026-01-02"], [3, "sn-1", "OP", "2026-01-03"]]
        self.assertEqual(cmm.ultima_per_seriale(report), [1, 2])


class QuoteBase(ProduzioneBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.cartella = CartellaReportCMM.objects.create(pn="PN-ALFA-1", percorso="C:/finto/PN-ALFA-1")
        self.giorno = date(2026, 3, 1)

    def report(self, sn, valori, prog="PRG_A", op="OP/2026/100", giorni=0, **extra):
        r = ReportCMM.objects.create(cartella=self.cartella, pn="PN-ALFA-1", op=op, percorso=f"C:/finto/{prog}/{sn}_{giorni}.pdf",
                                     file=f"{sn}.pdf", programma=f"{prog}_REV0", programma_base=prog, seriale=sn,
                                     data=self.giorno + timedelta(days=giorni), righe=len(valori), avvisato=True, **extra)
        for k, (nome, x, nom, ts, ti) in enumerate(valori):
            fuori = x > nom + ts or x < nom + ti
            MisuraCMM.objects.create(report=r, indice=k, nome=nome, chiave=cmm.chiave_quota(nome), tipo="diameter",
                                     misurato=x, nominale=nom, tol_sup=ts, tol_inf=ti, fuori=fuori,
                                     fuori_di=round(x - nom - ts, 6) if fuori else None, sezione="DIAMETRI")
        r.fuori = r.misure.filter(fuori=True).count()
        r.save()
        return r


class EsclusioneTests(QuoteBase):
    def test_escludi_e_riammetti(self):
        r = self.report("SN1", [("D10", 10.0, 10.0, 0.02, -0.02)])
        url = reverse("produzione:report_escludi", args=[r.pk])
        self.client.post(url, {"azione": "escludi", "motivo": "Doppione dello stesso report", "nota": "copia"})
        r.refresh_from_db()
        self.assertTrue(r.escluso)
        self.assertEqual((r.escluso_motivo, r.escluso_nota, r.escluso_da), ("Doppione dello stesso report", "copia", self.admin))
        d = cmm.dati_programma("PN-ALFA-1", "PRG_A")
        self.assertEqual(d["report"][0][6], 1)
        self.assertEqual(cmm.dati_programma("PN-ALFA-1", "PRG_A", con_esclusi=False)["report"], [])
        pagina = self.client.get(reverse("produzione:report_cmm", args=[r.pk]))
        self.assertContains(pagina, "Escluso dall")
        self.client.post(url, {"azione": "riammetti"})
        r.refresh_from_db()
        self.assertFalse(r.escluso)

    def test_escludere_serve_il_permesso(self):
        from tasks.tests_utils import _create_user_with_legacy

        r = self.report("SN1", [("D10", 10.0, 10.0, 0.02, -0.02)])
        self.client.force_login(_create_user_with_legacy(username="prod-op2", legacy_user_id=683, role_id=2, role_name="operatore"))
        resp = self.client.post(reverse("produzione:report_escludi", args=[r.pk]), {"azione": "escludi"})
        self.assertIn(resp.status_code, (302, 403))
        r.refresh_from_db()
        self.assertFalse(r.escluso)


class NoteAliasTests(QuoteBase):
    def test_note(self):
        r = self.report("SN1", [("D10", 10.0, 10.0, 0.02, -0.02)])
        api = reverse("produzione:api_quote_nota")
        resp = self.client.post(api, json.dumps({"pn": "PN-ALFA-1", "prog": "PRG_A", "quota": "D10|10.0000", "report": r.pk,
                                                 "testo": "Cambiato inserto"}), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        d = cmm.dati_programma("PN-ALFA-1", "PRG_A")
        self.assertEqual([(n["testo"], n["ri"], n["quota"]) for n in d["note"]], [("Cambiato inserto", 0, "D10|10.0000")])
        nota = NotaQuotaCMM.objects.get()
        self.assertEqual(self.client.post(reverse("produzione:api_quote_nota_elimina", args=[nota.pk])).status_code, 200)
        self.assertFalse(NotaQuotaCMM.objects.exists())
        vuota = self.client.post(api, json.dumps({"pn": "PN-ALFA-1", "report": r.pk, "testo": ""}), content_type="application/json")
        self.assertEqual(vuota.status_code, 400)

    def test_unire_quote_anche_di_altri_programmi(self):
        self.report("SN1", [("Ø_Cerchio2", 10.01, 10.0, 0.02, -0.02)], prog="PRG_A", giorni=1)
        self.report("SN2", [("017,00", 10.02, 10.0, 0.02, -0.02)], prog="PRG_B", giorni=2)
        self.report("SN3", [("Ø_Cerchio3", 10.0, 10.0, 0.02, -0.02), ("Ø_Cerchio2", 10.0, 10.0, 0.02, -0.02)], prog="PRG_A", giorni=3)
        cand = self.client.get(reverse("produzione:api_quote_candidati"), {"pn": "PN-ALFA-1"}).json()["quote"]
        self.assertIn({"prog": "PRG_B", "id": "017,00|10.0000"}, [{"prog": c["prog"], "id": c["id"]} for c in cand])
        api = reverse("produzione:api_quote_alias")
        for origine, prog in (("017,00|10.0000", "PRG_B"), ("Ø_CERCHIO3|10.0000", "PRG_A")):
            resp = self.client.post(api, json.dumps({"pn": "PN-ALFA-1", "prog_origine": prog, "quota_origine": origine,
                                                     "prog_destinazione": "PRG_A", "quota_destinazione": "Ø_CERCHIO2|10.0000"}),
                                    content_type="application/json")
            self.assertEqual(resp.status_code, 200, resp.content)
        d = cmm.dati_programma("PN-ALFA-1", "PRG_A")
        self.assertEqual([q["id"] for q in d["quote"]], ["Ø_CERCHIO2|10.0000"])          # Ø_Cerchio3 confluita
        self.assertEqual([r[1] for r in d["report"]], ["SN1", "SN2", "SN3"])             # SN2 arriva da PRG_B
        self.assertEqual(len(d["valori"][0]), 4)
        self.assertEqual({u["prog"] for u in d["quote"][0]["unite"]}, {"PRG_A", "PRG_B"})
        al = AliasQuotaCMM.objects.get(prog_origine="PRG_B")
        self.client.post(reverse("produzione:api_quote_alias_elimina", args=[al.pk]))
        self.assertEqual(len(cmm.dati_programma("PN-ALFA-1", "PRG_A")["report"]), 2)


class AnalisiTests(QuoteBase):
    def test_rimisure_e_deriva_nelle_quote_critiche(self):
        for i in range(20):
            self.report(f"SN{i:02d}", [("Ø95", 95.0 - 0.034 + 0.0015 * i, 95.0, 0.0, -0.034)], giorni=i)
        self.report("SN05", [("Ø95", 94.99, 95.0, 0.0, -0.034)], giorni=30)      # rimisura di SN05, ultima
        analisi = cmm.analisi_pn("PN-ALFA-1")
        self.assertEqual(analisi[0]["n"], 20)                                       # SN05 conta una volta
        self.assertIsNotNone(analisi[0]["deriva"])
        critiche = cmm.quote_critiche("PN-ALFA-1")
        self.assertEqual(critiche[0]["quota"]["nome"], "Ø95")

    def test_anomalie_dello_stesso_op_e_sn(self):
        with connection.cursor() as cur:
            cur.execute("ALTER TABLE anomalie ADD COLUMN seriale TEXT")
            cur.execute("ALTER TABLE anomalie ADD COLUMN descrizione TEXT")
            cur.execute("INSERT INTO anomalie (ex_op_nominativo, op_lookup_id, chiudere, seriale, descrizione) "
                        "VALUES ('OP/2026/100', 41, 0, 'SN7', 'Ø fuori')")
        from core.legacy_utils import legacy_table_columns
        legacy_table_columns.cache_clear()
        self.report("SN6", [("D10", 10.0, 10.0, 0.02, -0.02)], giorni=1)
        self.report("SN7", [("D10", 10.03, 10.0, 0.02, -0.02)], giorni=2)
        d = cmm.dati_programma("PN-ALFA-1", "PRG_A")
        self.assertEqual(list(d["anomalie"]), [1])
        self.assertEqual(d["anomalie"][1][0]["aperta"], True)

    def test_cruscotto(self):
        self.report("SN1", [("D10", 10.03, 10.0, 0.02, -0.02)], giorni=0)
        self.giorno = date.today()
        self.report("SN2", [("D10", 10.03, 10.0, 0.02, -0.02)], giorni=0)
        # prima del giro: analisi non ancora calcolata, la pagina non la ricalcola («in calcolo»)
        from unittest import mock

        from . import articoli
        from .models import ArticoloPN

        ArticoloPN.objects.create(pn="PN-ALFA-1")
        with mock.patch.object(cmm, "analisi_pn", side_effect=AssertionError("la tabella non deve ricalcolare")):
            prima = self.client.get(reverse("produzione:quote_cruscotto"), {"f": "tutti"})
        self.assertFalse(prima.context["righe"][0]["analisi_pronta"])
        self.assertContains(prima, "in calcolo")
        self.assertEqual(articoli.aggiorna_cpk(60), 1)                   # il giro: analisi del P/N
        self.assertEqual(articoli.da_analizzare(), [])                   # niente di nuovo da rifare
        a = ArticoloPN.objects.get(pn="PN-ALFA-1")
        self.assertEqual((a.quote_fuori_ultimo, a.quote_deriva), (1, 0))
        pagina = self.client.get(reverse("produzione:quote_cruscotto"))
        self.assertEqual(pagina.status_code, 200)
        r = pagina.context["righe"][0]
        self.assertEqual((r["pn"], r["fuori_rec"], r["fuori_ultimo"]), ("PN-ALFA-1", 1, 1))
        self.assertEqual(r["ultimo"][0], "SN2")                           # ultimo report del P/N (sottoquery)
        from . import manutenzione_db
        from django.db import connection as conn
        if conn.vendor != "microsoft":
            self.assertEqual(manutenzione_db.manutenzione(), {"saltata": "solo SQL Server"})
        else:
            esito = manutenzione_db.manutenzione()
            self.assertIn("statistiche", esito)
        self.assertTrue(r["da_guardare"])
        self.assertContains(pagina, "Quote CMM")
        # mappa: l'ultima settimana ha SN2 (fuori) → cella rossa, link ai report di quella settimana
        cella = r["celle"][-1]
        self.assertEqual((cella["fuori"], cella["n"], cella["livello"]), (1, 1, "alto"))
        self.assertEqual(len(pagina.context["settimane"]), 12)
        self.assertContains(pagina, "Mappa qualità")
        self.assertContains(pagina, f"da={cella['da']:%Y-%m-%d}")
        self.assertEqual(pagina.context["quote_guardare"][0]["pn"], "PN-ALFA-1")
        self.assertEqual(cmm._cella_mappa(0, 0, date.today())["livello"], "vuoto")
        self.assertEqual(cmm._cella_mappa(0, 5, date.today())["livello"], "zero")
        self.assertEqual(cmm._cella_mappa(1, 10, date.today())["livello"], "basso")
        self.assertEqual(cmm._cella_mappa(2, 10, date.today())["livello"], "medio")
        # scheda P/N: Qualità CMM e report della settimana scelta dalla mappa
        url = reverse("produzione:pn_scheda")
        q = self.client.get(url, {"pn": "PN-ALFA-1", "sez": "qualita"}, follow=True)
        self.assertContains(q, "Carta di controllo")
        oggi = date.today().isoformat()
        sett = self.client.get(reverse("produzione:pn", args=["PN-ALFA-1"]), {"sez": "report", "da": oggi, "a": oggi})
        self.assertEqual([x.seriale for x in sett.context["report_cmm"]["ultimi"]], ["SN2"])
        self.assertContains(sett, "nella settimana")

    def test_pdf_di_capacita(self):
        for i in range(6):
            self.report(f"SN{i}", [("D10", 10.0 + i * 0.002, 10.0, 0.02, -0.02), ("Planarità", 0.004 + i * 0.001, 0.0, 0.02, 0.0)], giorni=i)
        resp = self.client.get(reverse("produzione:quote_pdf"), {"pn": "PN-ALFA-1", "prog": "PRG_A"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_fai_mostra_il_report_del_primo_articolo(self):
        self.report("SN1", [("D10", 10.03, 10.0, 0.02, -0.02)], giorni=0)
        self.report("SN2", [("D10", 10.0, 10.0, 0.02, -0.02)], giorni=1)
        f = self._fai("OP/2026/100")
        pagina = self.client.get(reverse("tasks:fai_scheda", args=[f.pk]))
        self.assertEqual(pagina.context["fai_cmm"]["report"].seriale, "SN1")
        self.assertContains(pagina, "Report CMM del primo articolo")
        pn = self.client.get(reverse("produzione:pn_scheda"), {"pn": "PN-ALFA-1"}, follow=True)
        self.assertIsNotNone(pn.context["fai_cmm"])


class AvvisiTests(QuoteBase):
    def test_avvisa_una_volta_i_destinatari(self):
        from core.models import Notifica

        from .avvisi_cmm import invia_avvisi

        imp = ImpostazioniQuoteCMM.attuali()
        imp.destinatari.set([self.admin])
        r = self.report("SN1", [("D10", 10.03, 10.0, 0.02, -0.02)])
        ReportCMM.objects.filter(pk=r.pk).update(avvisato=False, data=timezone.localdate())
        self.assertEqual(invia_avvisi("PN-ALFA-1")["fuori"], 1)
        n = Notifica.objects.get(legacy_user_id=681)
        self.assertIn("SN1", n.messaggio)
        self.assertEqual(n.url_azione, reverse("produzione:report_cmm", args=[r.pk]))
        self.assertEqual(invia_avvisi("PN-ALFA-1")["fuori"], 0)                   # già avvisato

    def test_report_vecchi_non_avvisano(self):
        from core.models import Notifica

        from .avvisi_cmm import invia_avvisi

        imp = ImpostazioniQuoteCMM.attuali()
        imp.destinatari.set([self.admin])
        r = self.report("SN2", [("D10", 10.03, 10.0, 0.02, -0.02)])
        ReportCMM.objects.filter(pk=r.pk).update(avvisato=False, data=timezone.localdate() - timedelta(days=400))
        self.assertEqual(invia_avvisi("PN-ALFA-1")["fuori"], 0)
        self.assertFalse(Notifica.objects.filter(legacy_user_id=681).exists())
        self.assertTrue(ReportCMM.objects.get(pk=r.pk).avvisato)                 # segnato comunque

    def test_impostazioni_salvano_i_destinatari(self):
        resp = self.client.post(reverse("produzione:impostazioni"), {"azione": "avvisi", "avvisa_fuori": "1",
                                                                     "destinatari": [str(self.admin.pk)]})
        self.assertEqual(resp.status_code, 302)
        imp = ImpostazioniQuoteCMM.attuali()
        self.assertTrue(imp.avvisa_fuori)
        self.assertFalse(imp.avvisa_deriva)
        self.assertEqual(list(imp.destinatari.all()), [self.admin])
