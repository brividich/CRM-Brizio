"""Altri dati delle stampanti: avvisi, cassetti, sportelli, registro avvisi e stime di consumo. Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import AvvisoStampante, DispositivoSNMP, RilevazioneSNMP, StatoSNMP
from .printer_snmp import interpreta_stampante, problemi_stampante
from .stampanti import registra_avvisi, stime

TABELLE = {
    "contatori": {"1.1": 1000}, "unita": {"1.1": 7},
    "nomi": {"1.1": b"Toner Nero"}, "livelli": {"1.1": 40}, "massimi": {"1.1": 100},
    "uptime": {"0": timedelta(hours=1)},  # TimeTicks: puresnmp li dà come timedelta
    "avvisi_gravita": {"1.1": 3, "1.2": 5}, "avvisi_livello": {"1.1": 3, "1.2": 3},
    "avvisi_gruppo": {"1.1": 13, "1.2": 5}, "avvisi_gruppo_indice": {"1.1": 1, "1.2": 1},
    "avvisi_codice": {"1.1": 8, "1.2": 507}, "avvisi_testo": {"1.1": b"Paper jam in tray 2", "1.2": b""},
    "avvisi_ora": {"1.1": timedelta(minutes=50), "1.2": 1000},
    "cassetti_nome": {"1.1": b"Cassetto 1", "1.2": b"Bypass"}, "cassetti_carta": {"1.1": b"A4", "1.2": b""},
    "cassetti_max": {"1.1": 500, "1.2": 100}, "cassetti_livello": {"1.1": 250, "1.2": 0}, "cassetti_stato": {"1.1": 0, "1.2": 8},
    "sportelli_nome": {"1.1": b"Sportello anteriore"}, "sportelli_stato": {"1.1": 3},
    "display": {"1.1": b"Carta inceppata", "1.2": b""},
    "stato_stampante": {"1": 3}, "errori_rilevati": {"1": bytes([0x04])},  # bit 5 = carta inceppata
}


class InterpretaAltriDatiTest(SimpleTestCase):
    def test_avvisi_cassetti_sportelli_stato(self):
        dati = interpreta_stampante(TABELLE, {})
        inceppo, pronta = dati["avvisi"]
        self.assertEqual(inceppo["testo"], "Paper jam in tray 2")
        self.assertEqual(inceppo["descrizione"], "carta inceppata")
        self.assertTrue(inceppo["critico"])
        self.assertEqual(inceppo["gruppo"], "percorso carta")
        self.assertEqual(inceppo["da_secondi"], 600)
        self.assertTrue(pronta["informativo"])
        self.assertEqual(pronta["testo"], "Pronta a stampare")
        a4, bypass = dati["cassetti"]
        self.assertEqual((a4["pct"], a4["carta"], a4["problema"]), (50, "A4", False))
        self.assertEqual((bypass["pct"], bypass["nota"], bypass["problema"]), (0, "vuoto", True))
        self.assertTrue(dati["sportelli"][0]["aperto"])
        self.assertEqual(dati["stato"]["stato"], "pronta")
        self.assertEqual(dati["stato"]["display"], ["Carta inceppata"])
        self.assertEqual(dati["stato"]["segnalazioni"], "carta inceppata")

    def test_problemi_escludono_gli_eventi_normali(self):
        problemi = problemi_stampante(interpreta_stampante(TABELLE, {}))
        testi = [t for t, _l in problemi]
        self.assertIn("Paper jam in tray 2", testi)
        self.assertIn("Sportello anteriore: aperto", testi)
        self.assertIn("Bypass: avviso", testi)
        self.assertNotIn("Pronta a stampare", testi)
        self.assertIn(("Sportello anteriore: aperto", StatoSNMP.ERROR), problemi)

    def test_senza_colonne_extra_nessuna_chiave_nuova(self):
        dati = interpreta_stampante({"contatori": {"1.1": 5}}, {})
        self.assertNotIn("avvisi", dati)
        self.assertEqual(problemi_stampante(dati), [])


class RegistroEStimeTest(TestCase):
    def setUp(self):
        self.device = DispositivoSNMP.objects.create(nome="MFC sintetica", host="192.0.2.80", categoria=DispositivoSNMP.Categoria.STAMPANTE)

    def test_registro_apre_aggiorna_e_chiude(self):
        t0 = timezone.now()
        dati = interpreta_stampante(TABELLE, {})
        registra_avvisi(self.device, dati, t0)
        inceppo = AvvisoStampante.objects.get(testo="Paper jam in tray 2")
        self.assertEqual(inceppo.aperto_il, t0 - timedelta(seconds=600))
        self.assertIsNone(inceppo.chiuso_il)
        registra_avvisi(self.device, dati, t0 + timedelta(minutes=5))
        self.assertEqual(AvvisoStampante.objects.filter(testo="Paper jam in tray 2").count(), 1)
        senza = interpreta_stampante({**TABELLE, "avvisi_codice": {"1.2": 507}, "avvisi_testo": {"1.2": b""}}, {})
        registra_avvisi(self.device, senza, t0 + timedelta(minutes=10))
        inceppo.refresh_from_db()
        self.assertEqual(inceppo.chiuso_il, t0 + timedelta(minutes=10))
        self.assertEqual(inceppo.durata_secondi, 1200)
        # una lettura senza dati estesi non chiude niente
        registra_avvisi(self.device, {"contatori": []}, t0 + timedelta(minutes=15))
        self.assertTrue(AvvisoStampante.objects.filter(chiuso_il__isnull=True, informativo=True).exists())

    def test_senza_tabella_avvisi_registra_gli_errori_rilevati(self):
        dati = interpreta_stampante({k: v for k, v in TABELLE.items() if not k.startswith("avvisi_")}, {})
        registra_avvisi(self.device, dati)
        self.assertEqual(list(AvvisoStampante.objects.values_list("testo", flat=True)), ["Carta inceppata"])

    def _lettura(self, giorni_fa, contatore, toner):
        RilevazioneSNMP.objects.create(
            dispositivo=self.device, stato=StatoSNMP.OK, rilevata_il=timezone.now() - timedelta(days=giorni_fa),
            dati_stampante={"contatori": [{"indice": "1.1", "valore": contatore, "unita": "impressioni"}],
                            "consumabili": [{"indice": "1.1", "nome": "Toner Nero", "pct": toner, "tipo": "toner"}]})

    def test_stima_pagine_e_fine_toner_dopo_la_sostituzione(self):
        self._lettura(20, 1000, 10)
        self._lettura(15, 1500, 100)  # toner sostituito
        self._lettura(10, 2000, 90)
        self._lettura(0, 3000, 70)
        out = stime(self.device)
        pagine = out["pagine"][0]
        self.assertEqual((pagine["totale"], pagine["al_giorno"]), (2000, 100))
        toner = out["consumabili"][0]
        self.assertEqual(toner["pct_al_mese"], 60.0)  # 30 punti in 15 giorni
        self.assertEqual(toner["giorni_residui"], 35)
        self.assertIsNotNone(toner["sostituito_il"])

    def test_pochi_dati_nessuna_stima(self):
        self._lettura(1, 1000, 50)
        self._lettura(0, 1010, 50)
        toner = stime(self.device)["consumabili"][0]
        self.assertNotIn("finisce_il", toner)
        self.assertEqual(toner["nota"], "servono almeno 3 giorni di letture")


class PaginaStampanteTest(TestCase):
    def test_scheda_mostra_avvisi_cassetti_e_previsione(self):
        user = get_user_model().objects.create(username="prt_admin", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)
        device = DispositivoSNMP.objects.create(nome="MFC sintetica", host="192.0.2.81", categoria=DispositivoSNMP.Categoria.STAMPANTE)
        dati = interpreta_stampante(TABELLE, {})
        for giorni_fa, pct in ((10, 60), (0, 40)):
            RilevazioneSNMP.objects.create(dispositivo=device, stato=StatoSNMP.ERROR, dati_stampante=dati | {
                "consumabili": [{**dati["consumabili"][0], "pct": pct}]}, rilevata_il=timezone.now() - timedelta(days=giorni_fa))
        registra_avvisi(device, dati)
        page = self.client.get(reverse("contatori:snmp_dispositivo", args=[device.pk]))
        self.assertEqual(page.status_code, 200)
        for testo in ("La stampante adesso", "Registro avvisi", "Paper jam in tray 2", "Cassetto 1",
                      "Sportello anteriore: aperto", "Finisce verso il", "Carta inceppata"):
            self.assertContains(page, testo)
