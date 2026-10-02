"""Test offline di snmp_capture: walk, codifica snmprec, sanitizzazione, read-only."""
import ast
import asyncio
import tempfile
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase

from contatori import snmp_capture as cap


def _agent():
    from puresnmp.types import Counter64, IpAddress, TimeTicks
    from x690.types import Integer, ObjectIdentifier, OctetString

    rows = [
        ("1.0.8802.1.1.2.1.4.1.1.9.0.5.1", OctetString(b"core-sw-02")),
        ("1.3.6.1.2.1.1.1.0", OctetString(b"Linux nas01 5.10 admin@corp.example 10.20.0.5")),
        ("1.3.6.1.2.1.1.2.0", ObjectIdentifier("1.3.6.1.4.1.6574.1")),
        ("1.3.6.1.2.1.1.3.0", TimeTicks(123456)),
        ("1.3.6.1.2.1.1.4.0", OctetString(b"mario.rossi@corp.example")),
        ("1.3.6.1.2.1.1.5.0", OctetString(b"nas01")),
        ("1.3.6.1.2.1.2.2.1.6.1", OctetString(bytes.fromhex("001132aabbcc"))),
        ("1.3.6.1.2.1.4.20.1.1.10.20.0.5", IpAddress("10.20.0.5")),
        ("1.3.6.1.2.1.25.4.2.1.5.1", OctetString(b"--password=segreto")),
        ("1.3.6.1.2.1.31.1.1.1.6.1", Counter64(2 ** 40)),
        ("1.3.6.1.2.1.31.1.1.1.18.1", OctetString(b"PC Ufficio Rossi")),
        ("1.3.6.1.4.1.6574.1.5.1.0", OctetString(b"DS920+")),
        ("1.3.6.1.4.1.6574.2.1.1.5.0", Integer(1)),
        ("1.3.6.1.6.3.18.1.1.1.2.1", OctetString(b"publicRO")),
        ("1.3.6.1.4.1.99999.1.0", OctetString(b"value with publicRO inside")),
    ]
    rows.sort(key=lambda r: tuple(int(p) for p in r[0].split(".")))
    return [(ObjectIdentifier(o), v) for o, v in rows]


class FakeClient:
    def __init__(self, rows, too_big_above=None):
        self.rows = rows
        self.calls = []
        self.too_big_above = too_big_above

    def _after(self, start):
        key = tuple(int(p) for p in str(start).split("."))
        return [r for r in self.rows if tuple(int(p) for p in str(r[0]).split(".")) > key]

    async def bulkget(self, scalars, repeating, max_list_size=1):
        from puresnmp.exc import TooBig

        self.calls.append(("bulkget", max_list_size))
        if self.too_big_above and max_list_size > self.too_big_above:
            raise TooBig("too big")
        return SimpleNamespace(listing=OrderedDict(self._after(repeating[0])[:max_list_size]))

    async def multigetnext(self, oids):
        from puresnmp.exc import NoSuchOID

        self.calls.append(("getnext", 1))
        nxt = self._after(oids[0])
        if not nxt:
            raise NoSuchOID(oids[0])
        return [SimpleNamespace(oid=nxt[0][0], value=nxt[0][1])]


def _walk(client, **kw):
    return asyncio.run(cap.walk_async(client, **kw))


class WalkTests(SimpleTestCase):
    def test_bulk_walk_reads_whole_tree_including_iso_zero_branch(self):
        client = FakeClient(_agent())
        result = _walk(client, max_repetitions=4)
        oids = [r.oid for r in result.records]
        self.assertTrue(result.complete)
        self.assertEqual(oids[0], "1.0.8802.1.1.2.1.4.1.1.9.0.5.1")
        self.assertIn("1.3.6.1.4.1.6574.2.1.1.5.0", oids)
        self.assertTrue(all(c == ("bulkget", 4) for c in client.calls))

    def test_v1_uses_getnext_until_no_such_name(self):
        client = FakeClient(_agent())
        result = _walk(client, version="v1")
        self.assertTrue(result.complete)
        self.assertTrue(all(c[0] == "getnext" for c in client.calls))
        self.assertGreater(len(result.records), 5)

    def test_sensitive_subtrees_never_saved(self):
        result = _walk(FakeClient(_agent()))
        oids = [r.oid for r in result.records]
        self.assertNotIn("1.3.6.1.2.1.25.4.2.1.5.1", oids)
        self.assertNotIn("1.3.6.1.6.3.18.1.1.1.2.1", oids)
        self.assertEqual(result.dropped, 2)

    def test_too_big_halves_repetitions(self):
        client = FakeClient(_agent(), too_big_above=5)
        result = _walk(client, max_repetitions=25)
        self.assertTrue(result.complete)
        self.assertIn(("bulkget", 3), client.calls)

    def test_max_rows_marks_incomplete(self):
        result = _walk(FakeClient(_agent()), max_rows=3)
        self.assertFalse(result.complete)
        self.assertEqual(len(result.records), 3)

    def test_subtree_root_stops_when_leaving(self):
        result = _walk(FakeClient(_agent()), root="1.3.6.1.2.1.1")
        self.assertTrue(all(r.oid.startswith("1.3.6.1.2.1.1.") for r in result.records))

    def test_non_increasing_oid_aborts(self):
        rows = _agent()

        class Loop(FakeClient):
            async def bulkget(self, scalars, repeating, max_list_size=1):
                return SimpleNamespace(listing=OrderedDict([rows[3], rows[2]]))

        result = _walk(Loop(rows))
        self.assertFalse(result.complete)
        self.assertIn("non crescente", result.stop_reason)


class EncodingTests(SimpleTestCase):
    def test_snmprec_tags(self):
        recs = {r.oid: r for r in _walk(FakeClient(_agent())).records}
        self.assertEqual((recs["1.3.6.1.2.1.1.3.0"].tag, recs["1.3.6.1.2.1.1.3.0"].value), ("67", "123456"))
        self.assertEqual(recs["1.3.6.1.2.1.1.2.0"].tag, "6")
        self.assertEqual(recs["1.3.6.1.2.1.1.2.0"].value, "1.3.6.1.4.1.6574.1")
        self.assertEqual(recs["1.3.6.1.2.1.31.1.1.1.6.1"].tag, "70")
        self.assertEqual(recs["1.3.6.1.2.1.2.2.1.6.1"].tag, "4x")
        self.assertEqual(recs["1.3.6.1.2.1.2.2.1.6.1"].value, "001132aabbcc")
        self.assertEqual(recs["1.3.6.1.2.1.4.20.1.1.10.20.0.5"].tag, "64")

    def test_roundtrip_and_text_names(self):
        records = _walk(FakeClient(_agent())).records
        text = cap.render_snmprec(records)
        again = cap.parse_snmprec(text)
        self.assertEqual(cap.render_snmprec(again), text)
        readable = cap.render_text(records)
        self.assertIn("sysUpTime.0 (1.3.6.1.2.1.1.3.0) = TimeTicks: 123456", readable)
        self.assertIn("ifPhysAddress.1", readable)
        self.assertIn("00:11:32:aa:bb:cc", readable)

    def test_secret_redacted_anywhere(self):
        records = _walk(FakeClient(_agent())).records
        self.assertEqual(cap.redact_secret(records, ["publicRO"]), 1)
        self.assertNotIn("publicRO", cap.render_snmprec(records))


class SanitizeTests(SimpleTestCase):
    def test_pseudonymizes_consistently(self):
        out = cap.render_snmprec(cap.Sanitizer().apply(_walk(FakeClient(_agent())).records))
        for real in ("10.20.0.5", "nas01", "mario.rossi", "corp.example", "Rossi",
                     "001132aabbcc", "core-sw-02", ".10.20.0.5|"):
            self.assertNotIn(real, out)
        self.assertIn("1.3.6.1.2.1.4.20.1.1.192.0.2.1|64|192.0.2.1", out)
        self.assertIn("1.3.6.1.2.1.1.5.0|4|device-1", out)
        self.assertIn("|4x|020000000001", out)
        # I valori utili ai preset restano intatti.
        self.assertIn("1.3.6.1.4.1.6574.1.5.1.0|4|DS920+", out)
        self.assertIn("1.3.6.1.2.1.1.2.0|6|1.3.6.1.4.1.6574.1", out)


class CommandTests(SimpleTestCase):
    def test_raw_output_inside_repo_is_refused(self):
        target = Path(__file__).resolve().parent / "fixtures" / "snmp" / "raw.snmprec"
        with self.assertRaisesMessage(CommandError, "fuori dal repository"):
            call_command("snmp_capture", host="192.0.2.10", community="x", out=str(target))

    def test_capture_writes_files_without_secret(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("puresnmp.Client", lambda *a, **k: FakeClient(_agent())):
            out = Path(tmp) / "nas.snmprec"
            call_command("snmp_capture", "--v2c", host="192.0.2.10", community="publicRO",
                         out=str(out), stdout=mock.MagicMock())
            body = out.read_text() + out.with_suffix(".txt").read_text()
        self.assertIn("1.3.6.1.4.1.6574.1.5.1.0|4|DS920+", body)
        self.assertNotIn("publicRO", body)
        self.assertIn("COMPLETO", body)

    def test_prompts_for_community_when_not_given(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("getpass.getpass", return_value="publicRO") as prompt, \
                mock.patch("puresnmp.Client", lambda *a, **k: FakeClient(_agent())):
            out = Path(tmp) / "nas.snmprec"
            call_command("snmp_capture", host="192.0.2.10", out=str(out), stdout=mock.MagicMock())
            self.assertNotIn("publicRO", out.read_text())
        prompt.assert_called_once()

    def test_sanitize_from_raw_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.snmprec"
            raw.write_text(cap.render_snmprec(_walk(FakeClient(_agent())).records))
            out = Path(tmp) / "fixture.snmprec"
            call_command("snmp_capture", sanitize_from=str(raw), out=str(out), stdout=mock.MagicMock())
            self.assertNotIn("10.20.0.5", out.read_text())

    def test_v3_priv_without_plugin_is_explicit(self):
        with mock.patch("importlib.util.find_spec", return_value=None):
            with self.assertRaisesMessage(cap.CaptureError, "puresnmp-crypto"):
                cap.build_credentials(version="v3", v3_user="u", v3_auth="sha1",
                                      v3_auth_key="k" * 8, v3_priv="aes", v3_priv_key="p" * 8)


class ReadOnlyTests(SimpleTestCase):
    """Il modulo SNMP non deve mai inviare SET: fallisce se ne compare una."""

    def test_no_snmp_set_in_contatori(self):
        root = Path(__file__).resolve().parent
        violazioni = []
        for path in root.rglob("*.py"):
            if path.name.startswith("tests") or "migrations" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    nomi = [a.name for a in node.names]
                    if any("SetRequest" in n for n in nomi):
                        violazioni.append(f"{path.name}:{node.lineno} import SetRequest")
                if isinstance(node, ast.Attribute) and node.attr in ("multiset", "SetRequest"):
                    violazioni.append(f"{path.name}:{node.lineno} {node.attr}")
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "set"
                        and not (isinstance(node.func.value, ast.Name)
                                 and node.func.value.id == "cache")):
                    violazioni.append(f"{path.name}:{node.lineno} .set()")
        self.assertEqual(violazioni, [])
