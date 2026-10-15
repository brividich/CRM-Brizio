"""Gestione dati: import multiplo fatture, archivio, registro letture, catalogo e scheda MFC.

Dati sintetici.
"""
from datetime import date, datetime, timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import fatture_multiple, services
from .forms import FatturaForm, LetturaForm
from .models import Fattura, LetturaContatori, LetturaMensileContatori, Macchina, RigaFattura
from .tests import _AuthedClientMixin

V = {"a4_bn": 1000, "a3_bn": 100, "a4_col": 500, "a3_col": 50}


def _letta(numero, trimestre="2023-Q1", al=date(2023, 3, 31), contratto="SYN/1", avvisi=()):
    return {"testata": {"numero": numero, "data": al, "fornitore": "BASE", "dettaglio": "FORMATO",
                        "periodo_dal": date(al.year, al.month - 2, 1), "periodo_al": al,
                        "trimestre": trimestre},
            "righe": [{"contratto": contratto, "descrizione": "Sintetica", **V}],
            "avvisi": list(avvisi)}


def _file(nome="f.xml"):
    return SimpleUploadedFile(nome, b"<x/>", content_type="text/xml")


class TrimestriVecchiFormTests(TestCase):
    def setUp(self):
        self.m = Macchina.objects.create(reparto="QA", matricola="SYN-T1", contratto="SYN/1")

    def test_lettura_di_un_trimestre_vecchio_si_salva(self):
        form = LetturaForm(data={"macchina": self.m.pk, "trimestre": "2021-Q2", "data": "2021-07-03",
                                 "fonte": "MANUALE", **V})
        self.assertTrue(form.is_valid(), form.errors)

    def test_fattura_di_un_trimestre_vecchio_si_salva(self):
        form = FatturaForm(data={"numero": "1/V1", "data": "2021-07-05", "fornitore": "BASE",
                                 "dettaglio": "FORMATO", "trimestre": "2021-Q2",
                                 "periodo_dal": "2021-04-01", "periodo_al": "2021-06-30"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_fattura_con_chiusura_fuori_trimestre_bloccata(self):
        form = FatturaForm(data={"numero": "1/V1", "data": "2021-07-05", "fornitore": "BASE",
                                 "dettaglio": "FORMATO", "trimestre": "2021-Q3",
                                 "periodo_al": "2021-06-30"})
        self.assertFalse(form.is_valid())
        self.assertIn("non è nel 2021-Q3", str(form.errors["periodo_al"]))


@mock.patch("contatori.fatture_multiple.leggi_fattura")
class ImportMultiploTests(TestCase):
    def setUp(self):
        Macchina.objects.create(reparto="QA", matricola="SYN-F1", contratto="SYN/1")

    def test_classifica_le_fatture_lette(self, leggi):
        Fattura.objects.create(numero="GIA", data=date(2023, 3, 31), trimestre="2023-Q1",
                               periodo_al=date(2023, 3, 31))
        leggi.side_effect = [_letta("A"), _letta("B", avvisi=["riga incerta"]), _letta("GIA"),
                             _letta("A"), fatture_multiple.FatturaNonLeggibile("formato non riconosciuto")]
        voci = fatture_multiple.classifica(fatture_multiple.leggi_file([_file() for _ in range(5)]))
        self.assertEqual([v["stato"] for v in voci],
                         ["pronta", "da_verificare", "gia_presente", "gia_presente", "non_leggibile"])
        self.assertEqual(voci[0]["copie"], 1650)

    def test_salva_con_i_controlli_della_pagina(self, leggi):
        leggi.side_effect = [_letta("A"), _letta("B", contratto="IGNOTO")]
        ok, ignoto = fatture_multiple.leggi_file([_file(), _file()])
        fattura, errori = fatture_multiple.salva(ok)
        self.assertEqual(errori, [])
        self.assertEqual(RigaFattura.objects.get(fattura=fattura).a4_bn, 1000)
        fattura, errori = fatture_multiple.salva(ignoto)
        self.assertIsNone(fattura)
        self.assertIn("contratto IGNOTO", errori[0])
        # Stessa fattura due volte: il form la rifiuta.
        self.assertIsNone(fatture_multiple.salva(ok)[0])


@mock.patch("contatori.fatture_multiple.leggi_fattura")
class ImportMultiploViewTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        Macchina.objects.create(reparto="QA", matricola="SYN-F2", contratto="SYN/1")

    def test_leggi_anteprima_e_salva_le_selezionate(self, leggi):
        leggi.side_effect = [_letta("A"), _letta("B", trimestre="2023-Q2", al=date(2023, 6, 30),
                                                 avvisi=["riga incerta"])]
        url = reverse("contatori:fatture_importa")
        self.client.post(url, {"azione": "leggi", "file_fatture": [_file("a.xml"), _file("b.xml")]})
        r = self.client.get(url)
        self.assertContains(r, "da verificare")
        self.assertContains(r, "riga incerta")
        self.assertEqual(r.context["pronte"], 1)
        r = self.client.post(url, {"azione": "salva", "voce": ["0"]}, follow=True)
        self.assertEqual(list(Fattura.objects.values_list("numero", flat=True)), ["A"])
        self.assertContains(r, "1 fatture salvate")
        # La fattura con avvisi si apre precompilata nella pagina singola.
        r = self.client.get(reverse("contatori:fattura_nuova") + "?da_import=1")
        self.assertEqual(r.context["form"].initial["numero"], "B")
        self.assertContains(r, "riga incerta")
        self.assertEqual(r.context["form"]["trimestre"].value(), "2023-Q2")

    def test_archivio_segnala_trimestri_senza_fattura(self, leggi):
        m = Macchina.objects.get()
        Fattura.objects.create(numero="A", data=date(2023, 3, 31), trimestre="2023-Q1",
                               periodo_al=date(2023, 3, 31))
        for t, d in (("2023-Q1", date(2023, 4, 2)), ("2023-Q2", date(2023, 7, 2))):
            LetturaContatori.objects.create(macchina=m, trimestre=t, data=d, **V)
        r = self.client.get(reverse("contatori:fatture"))
        self.assertEqual([a["trimestre"] for a in r.context["scoperti"]], ["2023-Q2"])
        self.assertContains(r, "fattura mancante")


def _aware(*args):
    return timezone.make_aware(datetime(*args))


class RegistroLettureTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.m = Macchina.objects.create(reparto="QA", matricola="SYN-R1", contratto="SYN/1",
                                         host="192.0.2.70")
        for t, d, a4 in (("2026-Q1", date(2026, 4, 2), 1000), ("2026-Q3", date(2026, 10, 2), 1500)):
            LetturaContatori.objects.create(macchina=self.m, trimestre=t, data=d, **{**V, "a4_bn": a4})

    def test_matrice_con_mancanti_e_copie(self):
        reg = services.registro_letture(4, oggi=date(2026, 11, 10))
        self.assertEqual(reg["trimestri"], ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"])
        celle = reg["righe"][0]["celle"]
        self.assertEqual(celle[1]["stato"], "mancante")
        self.assertIsNone(celle[2]["copie"])  # il trimestre prima manca: non calcolabile
        self.assertEqual(celle[3]["stato"], "in_corso")
        self.assertEqual(reg["mancanti"], 1)

    def test_calo_evidenziato(self):
        LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q4", data=date(2026, 12, 20),
                                        **{**V, "a4_bn": 900})
        reg = services.registro_letture(4, oggi=date(2027, 1, 20))
        cella = reg["righe"][0]["celle"][2]  # 2026-Q4
        self.assertEqual(cella["cali"], ["A4 BN"])
        self.assertEqual(reg["cali"], 1)

    def test_scheda_mfc_lacune_copie_ed_export(self):
        LetturaMensileContatori.objects.create(macchina=self.m, mese=date(2026, 9, 1),
                                               rilevata_il=_aware(2026, 9, 1, 0, 5), **V)
        LetturaMensileContatori.objects.create(macchina=self.m, mese=date(2026, 10, 1),
                                               rilevata_il=_aware(2026, 10, 1, 0, 5), **{**V, "a4_bn": 1200})
        righe = services.righe_letture_macchina(self.m)
        self.assertEqual([(r["trimestre"], r["lettura"] is None) for r in righe],
                         [("2026-Q3", False), ("2026-Q2", True), ("2026-Q1", False)])
        self.assertEqual(services.righe_mensili_macchina(self.m)[0]["copie"], 200)
        r = self.client.get(reverse("contatori:macchina", args=[self.m.pk]))
        self.assertContains(r, "Lettura mancante")
        self.assertContains(r, "+200")
        r = self.client.get(reverse("contatori:export_macchina", args=[self.m.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])

    def test_pagina_registro(self):
        r = self.client.get(reverse("contatori:letture_registro") + "?trimestri=12")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["registro"]["trimestri"]), 12)


class CatalogoMfcTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = Macchina.objects.create(reparto="Amministrazione", matricola="SYN-C1", contratto="SYN/1")
        self.b = Macchina.objects.create(reparto="Logistica", matricola="SYN-C2", contratto="SYN/2")
        Macchina.objects.create(reparto="Vecchia", matricola="SYN-C3", attiva=False)
        LetturaContatori.objects.create(macchina=self.a, trimestre=services.trimestre_corrente(),
                                        data=timezone.localdate(), **V)

    def test_filtri_e_dismesse(self):
        url = reverse("contatori:macchine")
        r = self.client.get(url)
        self.assertEqual([m.reparto for m in r.context["macchine"]], ["Amministrazione", "Logistica"])
        self.assertEqual(r.context["dismesse_nascoste"], 1)
        r = self.client.get(url, {"lettura": "mancante"})
        self.assertEqual([m.reparto for m in r.context["macchine"]], ["Logistica"])
        r = self.client.get(url, {"q": "syn/2"})
        self.assertEqual([m.reparto for m in r.context["macchine"]], ["Logistica"])
        r = self.client.get(url, {"dismesse": "1"})
        self.assertEqual(len(r.context["macchine"]), 3)


class DispositivoDisponibilitaTests(_AuthedClientMixin, TestCase):
    def test_disponibilita_e_uptime_leggibile(self):
        from .models import DispositivoSNMP, RilevazioneSNMP, StatoSNMP
        from .templatetags.contatori_formato import durata
        d = DispositivoSNMP.objects.create(nome="Switch sintetico", host="192.0.2.80",
                                           sys_uptime_seconds=3 * 86400 + 7200)
        ora = timezone.now()
        for ore, stato in ((1, StatoSNMP.OK), (2, StatoSNMP.ERROR), (3, StatoSNMP.WARNING), (50, StatoSNMP.OK)):
            r = RilevazioneSNMP.objects.create(dispositivo=d, stato=stato)
            RilevazioneSNMP.objects.filter(pk=r.pk).update(rilevata_il=ora - timedelta(hours=ore))
        disp = services.disponibilita_dispositivo(d, ora)
        self.assertEqual((disp["24h"]["totale"], disp["24h"]["errori"], disp["24h"]["pct"]), (3, 1, 66.7))
        self.assertEqual(disp["7g"]["totale"], 4)
        self.assertEqual(durata(3 * 86400 + 7200), "3 g 2 h")
        self.assertEqual(durata(None), "")
        r = self.client.get(reverse("contatori:snmp_dispositivo", args=[d.pk]))
        self.assertContains(r, "3 g 2 h")
        self.assertContains(r, "Risposte ultime 24 ore")


class LetturePerTrimestreTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = Macchina.objects.create(reparto="Alfa", matricola="SYN-M1")
        self.b = Macchina.objects.create(reparto="Beta", matricola="SYN-M2")
        self.c = Macchina.objects.create(reparto="Gamma", matricola="SYN-M3")
        LetturaContatori.objects.create(macchina=self.b, trimestre="2023-Q4", data=date(2024, 1, 3), **V)
        LetturaContatori.objects.create(macchina=self.c, trimestre="2024-Q1", data=date(2024, 4, 2), **V)
        self.url = reverse("contatori:letture_trimestre") + "?trimestre=2024-Q1"

    def _riga(self, m, data="2024-04-03", **valori):
        return {f"m{m.pk}-data": data, f"m{m.pk}-fonte": "MANUALE",
                **{f"m{m.pk}-{c}": v for c, v in {**V, **valori}.items()}}

    def test_pagina_con_campi_vuoti_e_lettura_esistente(self):
        r = self.client.get(self.url)
        self.assertEqual(r.context["da_inserire"], 2)
        self.assertContains(r, f'name="m{self.a.pk}-a4_bn"')
        self.assertNotContains(r, f'name="m{self.a.pk}-a4_bn" value="0"')
        self.assertContains(r, "prima: 2023-Q4")

    def test_salva_le_valide_e_tiene_quelle_con_errori(self):
        dati = {"trimestre": "2024-Q1", **self._riga(self.a), **self._riga(self.b, a4_bn=10)}
        r = self.client.post(reverse("contatori:letture_trimestre"), dati)
        self.assertEqual(r.status_code, 200)  # resta in pagina: Beta ha un calo
        self.assertTrue(LetturaContatori.objects.filter(macchina=self.a, trimestre="2024-Q1").exists())
        self.assertFalse(LetturaContatori.objects.filter(macchina=self.b, trimestre="2024-Q1").exists())
        self.assertContains(r, "Più basso del 2023-Q4")
        # Con la conferma esplicita la riga passa.
        dati = {"trimestre": "2024-Q1", **self._riga(self.b, a4_bn=10), f"m{self.b.pk}-conferma_calo": "on"}
        r = self.client.post(reverse("contatori:letture_trimestre"), dati)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LetturaContatori.objects.get(macchina=self.b, trimestre="2024-Q1").a4_bn, 10)

    def test_righe_vuote_saltate_e_data_fuori_trimestre_bloccata(self):
        r = self.client.post(reverse("contatori:letture_trimestre"),
                             {"trimestre": "2024-Q1", **self._riga(self.a, data="2023-12-01")})
        self.assertContains(r, "La data non è del 2024-Q1")
        self.assertFalse(LetturaContatori.objects.filter(trimestre="2024-Q1", macchina=self.a).exists())
        r = self.client.post(reverse("contatori:letture_trimestre"), {"trimestre": "2024-Q1"}, follow=True)
        self.assertContains(r, "Nessuna lettura inserita")


class MonitorSnmpTests(_AuthedClientMixin, TestCase):
    def test_ricerca_e_disponibilita_24h(self):
        from .models import DispositivoSNMP, RilevazioneSNMP
        a = DispositivoSNMP.objects.create(nome="Switch piano terra", host="192.0.2.90")
        b = DispositivoSNMP.objects.create(nome="UPS sala server", host="192.0.2.91")
        for stato in ("OK", "OK", "ERROR", "OK"):
            RilevazioneSNMP.objects.create(dispositivo=a, stato=stato)
        self.assertEqual(services.disponibilita_flotta([a.pk, b.pk]), {a.pk: 75.0})
        r = self.client.get(reverse("contatori:snmp_centrale"), {"q": "ups"})
        self.assertEqual([d.nome for d in r.context["dispositivi"]], ["UPS sala server"])
        r = self.client.get(reverse("contatori:snmp_centrale"))
        self.assertEqual(r.context["disponibilita"], {a.pk: 75.0})
