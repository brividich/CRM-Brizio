from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.test import TestCase
from django.utils import timezone

from automazioni.schedules import register_schedule, spec_by_name
from contatori.models import (
    DispositivoSNMP, LetturaContatori, LetturaMensileContatori, Macchina, StatoSNMP,
)
from contatori.services import leggi_mensile_macchina
from contatori.snmp import SNMPError
from contatori import tasks


class MonthlyReadingsTests(TestCase):
    def setUp(self):
        self.macchina = Macchina.objects.create(
            reparto="QA", matricola="MONTHLY-01", host="192.0.2.11",
            modello=Macchina.Modello.DX_C5840I,
        )
        self.valori = dict(a4_bn=10, a3_bn=20, a4_col=30, a3_col=40)
        self.mese = timezone.localdate().replace(day=1)

    @patch("contatori.services.interroga_macchina")
    def test_retry_non_rilegge_e_non_sovrascrive_trimestre(self, poll):
        poll.return_value = self.valori
        trimestre = LetturaContatori.objects.create(
            macchina=self.macchina, trimestre="2026-Q3", data=date(2026, 9, 1), a4_bn=99,
        )
        prima, creata = leggi_mensile_macchina(self.macchina)
        seconda, ricreata = leggi_mensile_macchina(self.macchina)
        self.assertTrue(creata)
        self.assertFalse(ricreata)
        self.assertEqual(prima.pk, seconda.pk)
        self.assertEqual(prima.totale, 100)
        self.assertEqual(prima.mese, self.mese)
        poll.assert_called_once_with(self.macchina)
        trimestre.refresh_from_db()
        self.assertEqual(trimestre.a4_bn, 99)

    @patch("contatori.services.interroga_macchina")
    def test_due_mesi_conservano_due_snapshot(self, poll):
        poll.return_value = self.valori
        with patch("contatori.services.timezone.localdate", return_value=date(2026, 8, 1)):
            leggi_mensile_macchina(self.macchina)
        with patch("contatori.services.timezone.localdate", return_value=date(2026, 9, 1)):
            leggi_mensile_macchina(self.macchina)
        self.assertEqual(LetturaMensileContatori.objects.count(), 2)

    @patch("contatori.services.interroga_macchina", side_effect=SNMPError("timeout"))
    def test_errore_non_crea_snapshot_falso(self, poll):
        with self.assertRaises(SNMPError):
            leggi_mensile_macchina(self.macchina)
        self.assertFalse(LetturaMensileContatori.objects.exists())

    @patch("contatori.services.interroga_macchina")
    def test_rifiuta_recupero_retrodatato(self, poll):
        with self.assertRaises(ValueError):
            leggi_mensile_macchina(self.macchina, mese=date(2000, 1, 1))
        poll.assert_not_called()

    @patch("contatori.services.interroga_macchina")
    def test_comando_salva_successi_anche_con_altra_macchina_in_errore(self, poll):
        Macchina.objects.create(reparto="Z QA", matricola="MONTHLY-02", host="192.0.2.12")
        poll.side_effect = [self.valori, SNMPError("timeout")]
        with self.assertRaises(CommandError):
            call_command("leggi_contatori_mensili", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(LetturaMensileContatori.objects.count(), 1)


class SchedulerIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_registrazione_idempotente_con_cron_mensile(self):
        from django_q.models import Schedule
        for name in ("contatori_poll_snmp", "contatori_letture_mensili"):
            spec = spec_by_name(name)
            register_schedule(spec)
            register_schedule(spec)
            self.assertEqual(Schedule.objects.filter(name=name).count(), 1)
        mensile = Schedule.objects.get(name="contatori_letture_mensili")
        self.assertEqual(mensile.cron, "0 8 1 * *")
        self.assertGreater(mensile.next_run, timezone.now())

    @patch("contatori.tasks.async_task")
    def test_poll_accoda_solo_attivi_senza_accumulare_duplicati(self, enqueue):
        device = DispositivoSNMP.objects.create(nome="Reader QA", host="192.0.2.21")
        DispositivoSNMP.objects.create(nome="Off QA", host="192.0.2.22", attivo=False)
        self.assertEqual(tasks.run_poll_snmp(), {"accodati": 1})
        self.assertEqual(tasks.run_poll_snmp(), {"accodati": 0})
        enqueue.assert_called_once_with("contatori.tasks.poll_dispositivo", device.pk, q_options={"timeout": 110})

    @patch("contatori.tasks.async_task", side_effect=RuntimeError("broker offline"))
    def test_errore_enqueue_rilascia_lock(self, enqueue):
        DispositivoSNMP.objects.create(nome="Reader QA", host="192.0.2.21")
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                tasks.run_poll_snmp()
        self.assertEqual(enqueue.call_count, 2)

    @patch("contatori.tasks.interroga_dispositivo")
    def test_errore_device_visibile_al_worker(self, poll):
        device = DispositivoSNMP.objects.create(nome="Reader QA", host="192.0.2.21")
        poll.return_value.stato = StatoSNMP.ERROR
        with self.assertRaises(RuntimeError):
            tasks.poll_dispositivo(device.pk)

    @patch("contatori.tasks.async_task")
    def test_mensile_accoda_solo_attive_configurate_senza_snapshot(self, enqueue):
        mese = timezone.localdate().replace(day=1)
        nuova = Macchina.objects.create(reparto="QA", matricola="NEW", host="192.0.2.31")
        presente = Macchina.objects.create(reparto="QA", matricola="OLD", host="192.0.2.32")
        Macchina.objects.create(reparto="QA", matricola="OFF", host="192.0.2.33", attiva=False)
        Macchina.objects.create(reparto="QA", matricola="NOIP")
        LetturaMensileContatori.objects.create(
            macchina=presente, mese=mese, a4_bn=1, a3_bn=2, a4_col=3, a3_col=4,
        )
        self.assertEqual(tasks.run_letture_mensili()["accodati"], 1)
        enqueue.assert_called_once_with(
            "contatori.tasks.leggi_mensile", nuova.pk, mese.isoformat(), q_options={"timeout": 110},
        )
