"""Controlli dell'infrastruttura (monitoring.infra_checks) e allarme infra_health_alert."""
from __future__ import annotations

from collections import namedtuple
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from monitoring import health, infra_checks

Uso = namedtuple("Uso", "total used free")


def _task(minuti_fa: int, *, ok=True, func="security.tasks.run_security_cycle_task"):
    from django_q.models import Task

    fine = timezone.now() - timedelta(minutes=minuti_fa)
    return Task.objects.create(id=f"t{minuti_fa}{ok}{func[-4:]}", name=f"t{minuti_fa}", func=func,
                               started=fine - timedelta(seconds=5), stopped=fine, success=ok)


class QclusterTests(TestCase):
    def setUp(self):
        from django_q.models import Schedule

        Schedule.objects.create(func="security.tasks.run_security_cycle_task", schedule_type="I", minutes=15)

    def test_ok_se_ha_lavorato_da_poco(self):
        _task(5)
        self.assertEqual(infra_checks.check_qcluster().status, health.STATUS_OK)

    def test_fermo_oltre_soglia(self):
        _task(120)
        r = infra_checks.check_qcluster()
        self.assertEqual(r.status, health.STATUS_FAIL)
        self.assertIn("fermo", r.message)
        self.assertFalse(r.critical)  # mai togliere il sito dal bilanciamento

    def test_mai_partito(self):
        self.assertEqual(infra_checks.check_qcluster().status, health.STATUS_FAIL)

    def test_coda_con_fallimenti(self):
        _task(10, ok=False, func="dpi.tasks.run_dpi_expiry_reminders")
        r = infra_checks.check_qcluster_coda()
        self.assertEqual(r.status, health.STATUS_WARN)
        self.assertIn("run_dpi_expiry_reminders", r.message)


class QclusterSenzaScheduleTests(TestCase):
    def test_saltato_senza_lavori_pianificati(self):
        self.assertEqual(infra_checks.check_qcluster().status, health.STATUS_SKIPPED)


class DiscoTests(TestCase):
    def _con_libero(self, pct):
        gb = 1024 ** 3
        return mock.patch("monitoring.infra_checks.shutil.disk_usage",
                          return_value=Uso(100 * gb, (100 - pct) * gb, pct * gb))

    def test_soglie(self):
        for pct, atteso in ((40, health.STATUS_OK), (10, health.STATUS_WARN), (3, health.STATUS_FAIL)):
            with self.subTest(pct=pct), self._con_libero(pct):
                r = infra_checks.check_disk_space()
                self.assertEqual(r.status, atteso)
                self.assertIn("GB liberi", r.message)


@override_settings(SITE_URL="https://hub.example.test")
class CertificatoTests(TestCase):
    def setUp(self):
        cache.delete(infra_checks._TLS_CACHE_KEY)

    def _scade_tra(self, giorni):
        return mock.patch.object(infra_checks, "_scadenza_certificato", return_value=timezone.now() + timedelta(days=giorni, hours=1))

    def test_soglie_e_cache(self):
        with self._scade_tra(90):
            self.assertEqual(infra_checks.check_tls_cert().status, health.STATUS_OK)
        with self._scade_tra(3) as letto:  # dalla cache: nessuna nuova connessione
            self.assertEqual(infra_checks.check_tls_cert().status, health.STATUS_OK)
            letto.assert_not_called()
        cache.delete(infra_checks._TLS_CACHE_KEY)
        with self._scade_tra(20):
            self.assertEqual(infra_checks.check_tls_cert().status, health.STATUS_WARN)
        cache.delete(infra_checks._TLS_CACHE_KEY)
        with self._scade_tra(3):
            self.assertEqual(infra_checks.check_tls_cert().status, health.STATUS_FAIL)

    def test_non_raggiungibile_e_avviso(self):
        with mock.patch.object(infra_checks, "_scadenza_certificato", side_effect=OSError("rete")):
            self.assertEqual(infra_checks.check_tls_cert().status, health.STATUS_WARN)

    @override_settings(SITE_URL="http://hub.example.test")
    def test_http_saltato(self):
        self.assertEqual(infra_checks.check_tls_cert().status, health.STATUS_SKIPPED)


class AllarmeTests(TestCase):
    def _esiti(self, **stati):
        def fatto(nome):
            return lambda: health.CheckResult(name=nome, status=stati.get(nome, health.STATUS_OK), latency_ms=0,
                                              message=f"{nome} sintetico")
        return [mock.patch.object(health, f"check_{n}", side_effect=fatto(n)) for n in health.INFRA_CHECK_NAMES]

    def _con(self, **stati):
        patches = self._esiti(**stati)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

    def test_guasto_apre_segnalazione_e_manda_mail(self):
        from monitoring.models import Issue

        self._con(qcluster=health.STATUS_FAIL, disk_space=health.STATUS_WARN)
        with mock.patch.object(health, "emit_monitoring_alert", return_value=True) as mail:
            esito = health.run_infra_health_alert()
        self.assertTrue(esito["emailed"])
        self.assertIn("qcluster", mail.call_args.kwargs["subject"])
        self.assertNotIn("disk_space", mail.call_args.kwargs["subject"])  # gli avvisi non mandano mail
        self.assertEqual(Issue.objects.count(), 2)

    def test_tutto_ok_niente_mail(self):
        self._con()
        with mock.patch.object(health, "emit_monitoring_alert") as mail:
            esito = health.run_infra_health_alert()
        mail.assert_not_called()
        self.assertEqual(esito["status"], health.STATUS_OK)

    def test_registro_readyz_contiene_i_controlli_mai_critici(self):
        for nome in health.INFRA_CHECK_NAMES:
            self.assertIn(nome, health.available_checks())
