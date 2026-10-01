"""Discovery regressions using synthetic transports only."""
import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest import TestCase, mock

from contatori import snmp


class DiscoveryTests(TestCase):
    def setUp(self):
        module = ModuleType("puresnmp")
        module.V1 = module.V2C = lambda value: value
        module.PyWrapper = lambda client: client
        self.factory = module.Client = mock.Mock()
        transport = ModuleType("puresnmp.transport")
        transport.send_udp = mock.Mock()
        patcher = mock.patch.dict(sys.modules, {"puresnmp": module, "puresnmp.transport": transport})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_multiple_communities_stop_at_first_success_without_secret_in_results(self):
        calls = []
        def client(host, credential, **kwargs):
            async def get(oid):
                calls.append((credential, oid))
                if credential == "synthetic-first":
                    raise TimeoutError()
                return "synthetic-value"
            return SimpleNamespace(get=get)
        self.factory.side_effect = client
        rows = snmp.scansiona_rete("192.0.2.1/32", communities=["synthetic-first", "synthetic-second", "synthetic-third"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["community_index"], 2)
        self.assertNotIn("synthetic-second", repr(rows))
        self.assertFalse(any(c == "synthetic-third" for c, _ in calls))
        self.assertFalse(rows.incompleta)
        self.assertEqual(rows.completati, 1)

    def test_global_deadline_preserves_detected_host_and_cancels_optional_get(self):
        cancelled = []
        async def get(oid):
            if oid == snmp.SYS_DESCR:
                return "device"
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.append(oid)
        self.factory.return_value = SimpleNamespace(get=get)
        rows = snmp.scansiona_rete("192.0.2.1/32", max_duration=.03)
        self.assertEqual(rows[0]["descr"], "device")
        self.assertTrue(rows.incompleta)
        self.assertEqual(cancelled, [snmp.SYS_NAME])

    def test_per_get_timeout_overrides_transport_retries(self):
        cancelled = []
        async def get(oid):
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.append(oid)
        self.factory.return_value = SimpleNamespace(get=get)
        rows = snmp.scansiona_rete("192.0.2.1/32", timeout=.01, max_duration=.5)
        self.assertEqual(rows, [])
        self.assertFalse(rows.incompleta)
        self.assertEqual(rows.completati, 1)
        self.assertEqual(cancelled, [snmp.SYS_DESCR])

    def test_optional_failure_keeps_identity_and_continues(self):
        async def get(oid):
            if oid == snmp.SYS_NAME:
                raise TimeoutError()
            return "serial" if oid == snmp.PRT_SERIAL else "device"
        self.factory.return_value = SimpleNamespace(get=get)
        rows = snmp.scansiona_rete("192.0.2.1/32")
        self.assertEqual(rows[0]["matricola"], "serial")
        self.assertEqual(rows[0]["nome"], "")

    def test_oversized_network_rejected_before_host_enumeration(self):
        import ipaddress
        for network in ["0.0.0.0/0", "::/0"]:
            with mock.patch.object(ipaddress.IPv4Network, "hosts", side_effect=AssertionError("enumerated")), \
                 mock.patch.object(ipaddress.IPv6Network, "hosts", side_effect=AssertionError("enumerated")):
                with self.assertRaises(snmp.SNMPError):
                    snmp.scansiona_rete(network)
        self.factory.assert_not_called()

    def test_invalid_credentials_and_version_rejected(self):
        for kwargs in ({"communities": []}, {"communities": ["x" * 61]},
                       {"communities": [str(i) for i in range(9)]}, {"version": "v3"}):
            with self.assertRaises(snmp.SNMPError):
                snmp.scansiona_rete("192.0.2.1/32", **kwargs)
        self.factory.assert_not_called()

    def test_global_timeout_includes_hosts_waiting_for_semaphore(self):
        self.factory.return_value = SimpleNamespace(get=mock.AsyncMock(side_effect=lambda oid: None))
        async def get(oid):
            await asyncio.sleep(60)
        self.factory.return_value.get = get
        rows = snmp.scansiona_rete("192.0.2.0/30", concurrency=1, max_duration=.02)
        self.assertEqual(rows.totali, 2)
        self.assertEqual(rows.completati, 0)
        self.assertTrue(rows.incompleta)
        self.assertEqual(self.factory.call_count, 1)
