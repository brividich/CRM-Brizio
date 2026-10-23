"""Letture automatiche: registro, storico dei giri, «Esegui ora», pagina. Dati sintetici."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import SecurityLetturaLog
from security.services import letture, soc_settings


class EsitoTests(TestCase):
    def test_classificazione(self):
        L = SecurityLetturaLog
        self.assertEqual(letture.esito({"ok": True, "letti": 3})[0], L.OK)
        self.assertEqual(letture.esito({"attivo": False})[0], L.SPENTA)
        self.assertEqual(letture.esito({"skipped": "spento"})[0], L.SPENTA)
        self.assertEqual(letture.esito({"ok": False, "errore": "403"}), (L.ERRORE, "403"))
        self.assertEqual(letture.esito({"ok": False, "motivo": "Graph non configurato"}), (L.ERRORE, "Graph non configurato"))
        stato, testo = letture.esito({"ok": False, "dispositivi": {"pc": 10}, "patch": {"errore": "401"}})
        self.assertEqual(stato, L.PARZIALE)
        self.assertIn("Patch: 401", testo)
        self.assertEqual(letture.esito({"nvd": 4, "errors": ["KEV: timeout"]})[0], L.PARZIALE)

    def test_riepilogo_leggibile(self):
        righe = letture.righe_riepilogo({"ok": True, "dispositivi": {"pc": 12, "senza_agente": 2},
                                         "patch": {"errore": "401"}, "at": "x"})
        self.assertEqual(righe[0]["titolo"], "PC e protezione")
        self.assertIn(("PC", 12), righe[0]["voci"])
        self.assertEqual(righe[1]["errore"], "401")


class EseguiTests(TestCase):
    def test_giro_registrato_e_spento_non_registrato(self):
        with mock.patch("security.services.defender_vuln.run", return_value={"ok": True, "righe": 5, "salvate": 4}):
            self.assertEqual(letture.esegui("defender_vuln")["salvate"], 4)
        log = SecurityLetturaLog.objects.get()
        self.assertEqual((log.stato, log.manuale, log.riepilogo["salvate"]), (SecurityLetturaLog.OK, False, 4))
        self.assertIsNotNone(log.finita_il)
        with mock.patch("security.services.defender_vuln.run", return_value={"attivo": False}):
            letture.esegui("defender_vuln")
        self.assertEqual(SecurityLetturaLog.objects.count(), 1)

    def test_errore_registrato_e_rilanciato_nel_ciclo(self):
        with mock.patch("security.services.entra_signals.run", side_effect=RuntimeError("graph giù")):
            self.assertFalse(letture.esegui("entra")["ok"])
            with self.assertRaises(RuntimeError):
                letture.esegui("entra", rilancia=True)
        self.assertEqual(SecurityLetturaLog.objects.filter(stato=SecurityLetturaLog.ERRORE).count(), 2)
        self.assertIn("graph giù", SecurityLetturaLog.objects.first().messaggio)

    def test_giro_in_corso_blocca_il_secondo(self):
        SecurityLetturaLog.objects.create(codice="watchguard", stato=SecurityLetturaLog.IN_CORSO)
        with mock.patch("security.services.watchguard_api.run", side_effect=AssertionError("non deve partire")):
            self.assertTrue(letture.esegui("watchguard")["saltato"])
        SecurityLetturaLog.objects.update(avviata_il=timezone.now() - timedelta(minutes=letture.BLOCCO_MINUTI + 1))
        with mock.patch("security.services.watchguard_api.run", return_value={"ok": True}):
            letture.esegui("watchguard")
        self.assertEqual(SecurityLetturaLog.objects.filter(stato=SecurityLetturaLog.OK).count(), 1)

    def test_accoda_e_esegui_da_coda(self):
        utente = get_user_model().objects.create(username="lt_user")
        with mock.patch("django_q.tasks.async_task") as coda:
            ok, _ = letture.accoda("tabella_mac", utente)
        self.assertTrue(ok)
        log = SecurityLetturaLog.objects.get()
        self.assertEqual((log.stato, log.manuale, log.utente), (SecurityLetturaLog.CODA, True, utente))
        self.assertEqual(coda.call_args.args[1:], ("tabella_mac", log.pk))
        self.assertFalse(letture.accoda("tabella_mac", utente)[0])  # già in coda
        with mock.patch("contatori.tabella_mac.run", return_value={"attivo": False}):
            letture.esegui_da_coda("tabella_mac", log.pk)
        log.refresh_from_db()
        self.assertEqual(log.stato, SecurityLetturaLog.SPENTA)  # a mano: si registra anche spenta
        self.assertTrue(letture.esegui_da_coda("tabella_mac", log.pk)["saltato"])  # riconsegna della coda

    def test_task_pianificati_passano_dal_registro(self):
        from assets.tasks import run_m365_licenze_sync
        from security.tasks import run_defender_software_task

        with mock.patch("core.m365_graph.configurato", return_value=False):
            self.assertFalse(run_m365_licenze_sync()["ok"])
        soc_settings.save({"defender.software.attivo": True}, None)
        with mock.patch("security.services.defender_software.sincronizza", return_value={"righe": 7}), \
                mock.patch("core.m365_graph.configurato", return_value=True):
            self.assertEqual(run_defender_software_task()["righe"], 7)
        self.assertEqual(set(SecurityLetturaLog.objects.values_list("codice", flat=True)), {"m365_licenze", "defender_software"})


class PaginaTests(TestCase):
    def test_pagina_e_permessi(self):
        SecurityLetturaLog.objects.create(codice="watchguard", stato=SecurityLetturaLog.PARZIALE, finita_il=timezone.now(),
                                          riepilogo={"dispositivi": {"pc": 42}, "patch": {"errore": "401"}},
                                          messaggio="Patch: 401")
        admin = get_user_model().objects.create(username="lt_admin", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        page = self.client.get(reverse("security:letture"))
        self.assertContains(page, "WatchGuard Endpoint Security")
        self.assertContains(page, "Riuscita in parte")
        self.assertContains(page, "<strong>42</strong> PC", html=False)
        self.assertContains(page, "Esegui ora")
        self.assertContains(self.client.get(reverse("security:letture") + "?parziale=1"), 'data-running="0"')
        with mock.patch("django_q.tasks.async_task"):
            self.client.post(reverse("security:lettura_esegui", args=["intune"]))
        self.assertTrue(SecurityLetturaLog.objects.filter(codice="intune", manuale=True).exists())
        self.assertEqual(self.client.post(reverse("security:lettura_esegui", args=["inesistente"])).status_code, 404)
        utente = get_user_model().objects.create(username="lt_semplice")
        self.client.force_login(utente)
        with mock.patch("django_q.tasks.async_task"):
            self.client.post(reverse("security:lettura_esegui", args=["cve"]))
        self.assertFalse(SecurityLetturaLog.objects.filter(codice="cve").exists())
