"""Battito del SOC: calendario atteso, ritardi, mappa di 14 giorni, coda dei lavori, pagina. Dati sintetici."""
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_q.models import Schedule

from security.models import SecurityLetturaLog
from security.services import battito, soc_settings


def _schedule(nome, func, **kw):
    return Schedule.objects.create(name=nome, func=func, repeats=-1, next_run=timezone.now() + timedelta(minutes=5), **kw)


class CalendarioTests(TestCase):
    def test_intervallo_e_cron(self):
        ogni15 = Schedule(schedule_type="I", minutes=15)
        self.assertEqual(battito.intervallo_minuti(ogni15), 15)
        ora = timezone.make_aware(datetime(2026, 10, 20, 12, 0))
        self.assertEqual(battito.doveva_partire_dopo(ogni15, ora), ora - timedelta(minutes=40))
        mattina = Schedule(schedule_type="C", cron="20 6 * * *")
        self.assertIsNone(battito.intervallo_minuti(mattina))
        giri = battito.giri_attesi(mattina, ora - timedelta(days=2), ora)
        self.assertEqual([timezone.localtime(g).strftime("%d %H:%M") for g in giri], ["19 06:20", "20 06:20"])
        limite = battito.doveva_partire_dopo(mattina, ora)
        self.assertEqual(timezone.localtime(limite).strftime("%d %H:%M"), "20 06:10")


class StatoTests(TestCase):
    def setUp(self):
        _schedule("security_cve_enrichment", "security.tasks.enrich_cve_task", schedule_type="H")
        soc_settings.save({"cve.arricchimento.attivo": True}, None)

    def _cve(self, ora):
        s = battito.stato(ora)
        return {c["codice"]: c for g in s["gruppi"] for c in g["componenti"]}["cve"], s

    def test_lettura_regolare_poi_in_ritardo(self):
        ora = timezone.now()
        SecurityLetturaLog.objects.create(codice="cve", stato="ok", avviata_il=ora - timedelta(minutes=20),
                                          finita_il=ora - timedelta(minutes=19))
        cve, s = self._cve(ora)
        self.assertEqual(cve["tono"], "ok")
        self.assertIsNotNone(cve["prossimo"])
        self.assertEqual(len(cve["celle"]), battito.GIORNI_MAPPA)
        self.assertEqual(cve["celle"][-1]["tono"], "ok")
        self.assertEqual(cve["celle"][-2]["tono"], "assente")  # ieri doveva girare 24 volte e non c'è nulla
        # Ogni ora: con l'ultimo giro di 3 ore fa è in ritardo (2 intervalli + 10 minuti).
        cve, s = self._cve(ora + timedelta(hours=3))
        self.assertEqual(cve["tono"], "ritardo")
        self.assertTrue(any(p.get("codice") == "cve" for p in s["problemi"]))
        self.assertIn("ciclo", {c["codice"] for g in s["gruppi"] for c in g["componenti"]})

    def test_ultimo_giro_in_errore(self):
        ora = timezone.now()
        SecurityLetturaLog.objects.create(codice="cve", stato="errore", messaggio="NVD: timeout",
                                          avviata_il=ora - timedelta(minutes=10), finita_il=ora - timedelta(minutes=9))
        cve, _s = self._cve(ora)
        self.assertEqual(cve["tono"], "ko")
        self.assertIn("NVD: timeout", cve["frase"])

    def test_spenta(self):
        soc_settings.save({"cve.arricchimento.attivo": False}, None)
        cve, _s = self._cve(timezone.now())
        self.assertEqual(cve["tono"], "spenta")
        self.assertIsNone(cve["prossimo"])

    def test_cella_giorno_senza_giri(self):
        oggi = timezone.localdate()
        ieri = oggi - timedelta(days=1)
        self.assertEqual(battito._cella(ieri, [], 96, True, oggi)["tono"], "assente")
        self.assertEqual(battito._cella(ieri, ["ok"] * 96, 96, True, oggi)["tono"], "ok")
        self.assertEqual(battito._cella(ieri, ["ok"] * 40, 96, True, oggi)["tono"], "parziale")
        self.assertEqual(battito._cella(ieri, ["errore"], 1, True, oggi)["tono"], "ko")
        self.assertEqual(battito._cella(ieri, [], 1, False, oggi)["tono"], "spenta")

    def test_coda_ferma(self):
        from django_q.models import Task

        Schedule.objects.update(next_run=timezone.now() - timedelta(hours=2))
        _schedule("altro1", "x.y", schedule_type="I", minutes=5)
        _schedule("altro2", "x.z", schedule_type="I", minutes=5)
        Schedule.objects.update(next_run=timezone.now() - timedelta(hours=2))
        self.assertFalse(Task.objects.exists())
        coda = battito._coda(timezone.now())
        self.assertEqual(coda["tono"], "ko")
        self.assertIn("qcluster", coda["frase"])


class PaginaTests(TestCase):
    def test_pagina(self):
        _schedule("security_cycle", "security.tasks.run_security_cycle_task", schedule_type="I", minutes=15)
        SecurityLetturaLog.objects.create(codice="caselle", stato="ok", finita_il=timezone.now())
        admin = get_user_model().objects.create(username="bt_admin", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        r = self.client.get(reverse("security:battito"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Battito del SOC")
        self.assertContains(r, "Caselle dei report")
        self.assertContains(r, "Mappa degli ultimi 14 giorni")
        self.assertContains(r, "Ciclo del SOC")
        self.assertNotIn("{%", r.content.decode())
