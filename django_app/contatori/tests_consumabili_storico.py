"""Storico consumabili, stima giorni residui, pagina flotta senza SNMP all'apertura. Dati sintetici."""
from datetime import datetime, timedelta, timezone as dt_tz
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services, tasks
from .models import LetturaConsumabile, Macchina
from .tests import _AuthedClientMixin

T0 = datetime(2026, 9, 1, 8, 0, tzinfo=dt_tz.utc)


def _serie(macchina, nome, valori, passo=1):
    for i, pct in enumerate(valori):
        LetturaConsumabile.objects.create(macchina=macchina, nome=nome, pct=pct,
                                          rilevata_il=T0 + timedelta(days=i * passo))


class StimaTests(TestCase):
    def test_ritmo_costante(self):
        serie = [(T0, 100), (T0 + timedelta(days=30), 70)]
        self.assertEqual(services._stima_giorni(serie, T0), 70)

    def test_dopo_sostituzione_usa_solo_il_nuovo_tratto(self):
        serie = [(T0, 20), (T0 + timedelta(days=5), 10), (T0 + timedelta(days=6), 90),
                 (T0 + timedelta(days=16), 80)]
        self.assertEqual(services._stima_giorni(serie, T0), 80)

    def test_non_stimabile(self):
        self.assertIsNone(services._stima_giorni([(T0, 50)], T0))
        self.assertIsNone(services._stima_giorni([(T0, 50), (T0 + timedelta(hours=5), 49)], T0))
        self.assertIsNone(services._stima_giorni([(T0, 50), (T0 + timedelta(days=5), 50)], T0))


class StatoTests(TestCase):
    def setUp(self):
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-C1", host="192.0.2.71")

    def test_salva_ignora_percentuali_non_valide(self):
        n = services.salva_consumabili(self.m, [{"nome": "Nero", "pct": 40}, {"nome": "Scarti", "pct": -2},
                                                {"nome": "Ciano", "pct": "x"}])
        self.assertEqual(n, 3)
        self.assertEqual(sorted(LetturaConsumabile.objects.values_list("nome", "pct")),
                         [("Ciano", None), ("Nero", 40), ("Scarti", None)])

    def test_ultimo_stato_con_critici_e_stima(self):
        _serie(self.m, "Nero", [40, 30, 20, 12], passo=10)
        _serie(self.m, "Ciano", [90, 88, 86, 84], passo=10)
        stato = services.stato_consumabili([self.m], ora=T0 + timedelta(days=31))[self.m.pk]
        self.assertEqual([v["nome"] for v in stato["critici"]], ["Nero"])
        nero = next(v for v in stato["voci"] if v["nome"] == "Nero")
        self.assertEqual(nero["pct"], 12)
        self.assertEqual(nero["giorni"], 13)  # 28 punti in 30 giorni -> 12 / 0,93
        self.assertEqual(stato["peggiore"]["nome"], "Nero")


class FlottaTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ok = Macchina.objects.create(reparto="Zeta ok", matricola="SYN-C2", host="192.0.2.72")
        self.crit = Macchina.objects.create(reparto="Beta critica", matricola="SYN-C3", host="192.0.2.73")
        self.mai = Macchina.objects.create(reparto="Gamma mai", matricola="SYN-C4", host="192.0.2.74")
        adesso = timezone.now()
        LetturaConsumabile.objects.create(macchina=self.ok, nome="Nero", pct=70, rilevata_il=adesso)
        LetturaConsumabile.objects.create(macchina=self.crit, nome="Nero", pct=6, rilevata_il=adesso)

    def test_nessuna_snmp_all_apertura_e_critici_in_cima(self):
        with mock.patch.object(services, "leggi_consumabili_macchina") as leggi:
            r = self.client.get(reverse("contatori:consumabili"))
        leggi.assert_not_called()
        ordine = [x["macchina"].reparto for x in r.context["righe"]]
        self.assertEqual(ordine, ["Beta critica", "Gamma mai", "Zeta ok"])
        self.assertEqual(r.context["critici"], 1)

    def test_leggi_ora_accoda_e_la_riga_segue_lo_stato(self):
        cache.clear()
        with mock.patch("contatori.tasks.async_task") as accoda, \
                mock.patch.object(services, "leggi_consumabili_macchina", side_effect=AssertionError("no SNMP")):
            r = self.client.post(reverse("contatori:consumabili_aggiorna", args=[self.mai.pk]))
        accoda.assert_called_once()
        self.assertContains(r, f'id="cons-{self.mai.pk}"')
        self.assertContains(r, "Lettura in coda")
        with mock.patch.object(services, "leggi_consumabili_macchina",
                               return_value=([{"nome": "Nero", "pct": 55, "nota": ""}], None)):
            tasks.leggi_consumabili(self.mai.pk)
        r = self.client.get(reverse("contatori:macchina_consumabili", args=[self.mai.pk]) + "?vista=riga")
        self.assertContains(r, "55%")
        self.assertNotContains(r, "Lettura in coda")
        self.assertTrue(LetturaConsumabile.objects.filter(macchina=self.mai, pct=55).exists())

    def test_leggi_ora_senza_gestione_negato(self):
        with mock.patch("contatori.permessi.puo_gestire", return_value=False), \
                mock.patch("contatori.tasks.async_task") as accoda:
            r = self.client.post(reverse("contatori:consumabili_aggiorna", args=[self.mai.pk]))
        self.assertEqual(r.status_code, 403)
        accoda.assert_not_called()

    def test_centrale_segnala_consumabili_da_ordinare(self):
        titoli = [t["titolo"] for t in services.cruscotto_operativo()["da_fare"]]
        self.assertIn("1 MFC con consumabili da ordinare", titoli)


class TaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-C5", host="192.0.2.75")

    def test_task_salva_e_segnala_errori(self):
        with mock.patch.object(services, "leggi_consumabili_macchina",
                               return_value=([{"nome": "Nero", "pct": 33}], None)):
            self.assertEqual(tasks.leggi_consumabili(self.m.pk)["salvati"], 1)
        with mock.patch.object(services, "leggi_consumabili_macchina", return_value=(None, "timeout")):
            with self.assertRaises(RuntimeError):
                tasks.leggi_consumabili(self.m.pk)

    def test_smistamento_un_job_per_mfc(self):
        with mock.patch("contatori.tasks.async_task") as accoda:
            self.assertEqual(tasks.run_letture_consumabili(), {"accodati": 1})
            self.assertEqual(tasks.run_letture_consumabili(), {"accodati": 0})  # lock: niente doppioni
        self.assertEqual(accoda.call_count, 1)
