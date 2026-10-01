"""Synthetic asynchronous transports: no device, credential or database access."""
import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest import TestCase, mock

from contatori import snmp


class SnmpTimeoutTest(TestCase):
    def setUp(self):
        self.client = SimpleNamespace()
        module = ModuleType('puresnmp')
        module.Client = mock.Mock(return_value=self.client)
        module.PyWrapper = lambda client: client
        module.V1 = module.V2C = mock.Mock()
        transport = ModuleType('puresnmp.transport')
        transport.send_udp = mock.Mock()
        self.modules = mock.patch.dict(sys.modules, {'puresnmp': module, 'puresnmp.transport': transport})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_hanging_get_is_cancelled_and_partial_values_preserved(self):
        cancelled = []
        async def get(oid):
            if oid == '1.2.1':
                return 42
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.append(oid)
        self.client.get = get
        values, errors = snmp.leggi_oids('192.0.2.1', ['1.2.1', '1.2.2', '1.2.3'], max_duration=.02)
        self.assertEqual(values, {'1.2.1': 42})
        self.assertEqual(set(errors), {'1.2.2', '1.2.3'})
        self.assertEqual(cancelled, ['1.2.2'])

    def test_no_successful_get_reports_failure(self):
        self.client.get = mock.AsyncMock(side_effect=OSError('synthetic offline'))
        with self.assertRaises(snmp.SNMPError):
            snmp.leggi_oids('192.0.2.1', ['1.2.1'])

    def test_hanging_walk_cancelled_without_returning_partial_aggregate(self):
        cancelled = []
        async def walk(oid):
            yield SimpleNamespace(value=10)
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.append(True)
        self.client.walk = walk
        with self.assertRaisesRegex(snmp.SNMPError, 'WALK SNMP superato'):
            snmp.leggi_colonna('192.0.2.1', '1.2.1', max_duration=.02)
        self.assertEqual(cancelled, [True])

    def test_large_walk_rejected_without_partial_sum(self):
        async def walk(oid):
            for _ in range(257):
                yield SimpleNamespace(value=1)
        self.client.walk = walk
        with self.assertRaisesRegex(snmp.SNMPError, '256 righe'):
            snmp.leggi_colonna('192.0.2.1', '1.2.1')

    def test_shared_deadline_skips_remaining_walks(self):
        specs = [{'oid': '1.2.1'}, {'oid': '1.2.2', 'modalita': 'WALK'}]
        with mock.patch.object(snmp, 'monotonic', side_effect=[0, 0, 31]), \
             mock.patch.object(snmp, 'leggi_oids', return_value=({'1.2.1': 42}, {})), \
             mock.patch.object(snmp, 'leggi_colonna') as walk:
            values, errors = snmp.leggi_specifiche('192.0.2.1', specs)
        walk.assert_not_called()
        self.assertEqual(values, {'1.2.1': 42})
        self.assertIn('1.2.2', errors)

    def test_successful_walk_unchanged(self):
        async def walk(oid):
            yield SimpleNamespace(value=12)
            yield SimpleNamespace(value=34)
        self.client.walk = walk
        self.assertEqual(snmp.leggi_colonna('192.0.2.1', '1.2.1'), [12, 34])
