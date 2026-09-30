from unittest import mock
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from . import services
from .models import DispositivoSNMP, ProfiloSNMP, StatoSNMP
from .printer_snmp import interpreta_stampante, leggi_stampante
from .snmp import SNMPError, SYS_DESCR, SYS_OBJECT_ID, SYS_NAME


class PrinterDecodingTest(SimpleTestCase):
    def test_indices_zero_unknown_and_multiple_markers(self):
        result = interpreta_stampante({
            "contatori": {"7.1": 120, "7.2": 40}, "unita": {"7.1": 7, "7.2": 8},
            "nomi": {"7.8": b"Black", "7.2": b"Cyan", "7.9": b"Magenta", "7.4": b"Yellow"},
            "livelli": {"7.8": 0, "7.2": 50, "7.9": -3, "7.4": -2},
            "massimi": {"7.8": 100, "7.2": 200, "7.9": 100, "7.4": 100},
        }, {})
        self.assertEqual([c["pct"] for c in result["consumabili"]], [0, 25, None, None])
        self.assertEqual([c["valore"] for c in result["contatori"]], [120, 40])
        self.assertEqual(result["contatori"][1]["unita"], "fogli")

    @mock.patch("puresnmp.PyWrapper")
    def test_partial_walk_failure_keeps_other_tables(self, wrapper):
        async def walk(base):
            from .printer_snmp import COLUMNS
            if base == COLUMNS["livelli"]:
                raise TimeoutError("timeout toner")
            values = {"contatori": 123, "unita": 7, "nomi": b"Black", "massimi": 100}
            key = next(key for key, oid in COLUMNS.items() if oid == base)
            yield SimpleNamespace(oid=base + ".7.1", value=values[key])
        wrapper.return_value.walk.side_effect = walk
        result = leggi_stampante(SimpleNamespace(host="192.0.2.1"),
                                community="test", port=161, timeout=1, version="v2c")
        self.assertEqual(result["contatori"][0]["valore"], 123)
        self.assertIsNone(result["consumabili"][0]["pct"])
        self.assertIn("livelli", result["errori"])


class PrinterAutodetectTest(TestCase):
    def setUp(self):
        self.device = DispositivoSNMP.objects.create(nome="Kyocera 5054", host="192.0.2.54")
        self.identity = {
            SYS_DESCR: "KYOCERA TASKalfa 5054ci", SYS_NAME: "printer-test",
            SYS_OBJECT_ID: "1.3.6.1.4.1.1347.43.5.1",
        }
        self.snapshot = {
            "contatori": [{"indice": "7.1", "valore": 4321, "unita": "impressioni"}],
            "consumabili": [{"nome": "Toner Black", "pct": 0, "nota": ""}], "errori": {},
        }

    def poll(self, snapshot=None):
        with mock.patch("contatori.snmp.leggi_oids", return_value=(self.identity, {})), \
             mock.patch("contatori.snmp.leggi_colonna", return_value=[4321]), \
             mock.patch("contatori.printer_snmp.leggi_stampante", return_value=snapshot or self.snapshot):
            return services.interroga_dispositivo(self.device)

    def test_existing_profile_without_probes_is_repaired_and_rendered(self):
        self.device.profilo_snmp = ProfiloSNMP.objects.get(slug="kyocera")
        self.device.save()
        poll = self.poll()
        self.assertEqual(poll.valori.get().valore_numero, 4321)
        self.assertEqual(poll.dati_stampante, self.snapshot)
        self.device.refresh_from_db()
        self.assertEqual(self.device.categoria, "STAMPANTE")
        user = get_user_model().objects.create_superuser(username="printer-admin", password="test-only")
        self.client.force_login(user)
        response = self.client.get(reverse("contatori:snmp_dispositivo", args=[self.device.pk]))
        self.assertContains(response, "Toner Black")
        self.assertContains(response, "0%")
        self.assertContains(response, "4321")

    def test_first_poll_autodetect_and_history_same_cycle(self):
        first = self.poll()
        second = self.poll({**self.snapshot, "consumabili": [], "errori": {"livelli": "timeout"}})
        self.assertEqual(first.valori.count(), 1)
        self.assertEqual(second.stato, StatoSNMP.WARNING)
        first.refresh_from_db()
        self.assertEqual(first.dati_stampante["consumabili"][0]["pct"], 0)
        self.assertEqual(self.device.sonde.count(), 1)

    def test_failed_poll_does_not_present_old_snapshot_as_current(self):
        self.poll()
        with mock.patch("contatori.snmp.leggi_specifiche", side_effect=SNMPError("offline")):
            failed = services.interroga_dispositivo(self.device)
        self.assertEqual(failed.stato, StatoSNMP.ERROR)
        self.assertEqual(failed.dati_stampante, {})

    def test_firewall_detects_and_reads_profile_without_printer_queries(self):
        with mock.patch("contatori.snmp.leggi_oids", return_value=({
            SYS_DESCR: "FortiGate", SYS_OBJECT_ID: "1.3.6.1.4.1.12356.1",
        }, {})), mock.patch("contatori.snmp.leggi_colonna", return_value=[10, 20]), \
             mock.patch("contatori.printer_snmp.leggi_stampante") as printer:
            poll = services.interroga_dispositivo(self.device)
        self.assertEqual(poll.valori.count(), 2)
        self.assertTrue(all(v.valore_numero == 30 for v in poll.valori.all()))
        printer.assert_not_called()
