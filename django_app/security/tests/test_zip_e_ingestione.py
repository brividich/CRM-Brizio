"""ZIP allegati (i report WatchGuard programmati arrivano cosi'), idempotenza e mail di accompagnamento."""
import io
import zipfile
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from security.models import ParseStatus, SecurityMailboxMessage, SecurityMailboxSource, SecurityReport, SecuritySourceFile, SecurityVpnAccess
from security.services.mailbox_ingestion import run_mailbox_ingestion
from security.services.mailbox_providers import MailboxAttachment, MailboxMessage
from security.services.text_extraction import ARCHIVE_MAX_MEMBER_BYTES, expand_zip, is_zip

AUTH_CSV = (
    "user,ip,login,logout,duration,quota,method\n"
    "svc.fw,192.0.2.10,2026-09-29 00:00:05,2026-09-29 00:00:40,0:35,,Firewall\n"
    "mario.rossi,203.0.113.44,2026-09-29 08:00:00,2026-09-29 09:30:00,1:30:00,,SSLVPN\n"
)
DENIED_CSV = "user,ip,login,reason\nghost,198.51.100.9,2026-09-29 16:30:55,\"Authentication of SSLVPN user [ghost] was rejected\"\n"


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files:
            archive.writestr(name, content)
    return buffer.getvalue()


def _mail(pid, subject, body="", attachments=()):
    return MailboxMessage(
        provider_message_id=pid, internet_message_id=pid, sender="reports@example.test", recipients=[], subject=subject,
        received_at=timezone.now(), body_text=body, body_html="", attachments=list(attachments),
    )


class ExpandZipTests(SimpleTestCase):
    def test_members_are_extracted_with_their_names(self):
        members, warnings = expand_zip("r.zip", _zip([("a_Authentication_Allowed.csv", AUTH_CSV), ("sub/dir/b.txt", "x")]))
        self.assertEqual([name for name, _ in members], ["a_Authentication_Allowed.csv", "b.txt"])  # nessun percorso
        self.assertFalse(warnings)

    def test_corrupt_zip_does_not_raise(self):
        members, warnings = expand_zip("r.zip", b"PK\x03\x04 non e' uno zip")
        self.assertEqual(members, [])
        self.assertTrue(any("illeggibile" in w for w in warnings))

    def test_nested_archives_and_hidden_files_are_ignored(self):
        members, warnings = expand_zip("r.zip", _zip([("inner.zip", b"PK"), (".hidden", "x"), ("ok.csv", "a,b")]))
        self.assertEqual([name for name, _ in members], ["ok.csv"])
        self.assertTrue(any("annidato" in w for w in warnings))

    def test_path_traversal_names_keep_only_the_file_name(self):
        members, _ = expand_zip("r.zip", _zip([("../../etc/passwd.csv", "a,b")]))
        self.assertEqual([name for name, _ in members], ["passwd.csv"])

    def test_oversized_member_is_skipped(self):
        with mock.patch("security.services.text_extraction.ARCHIVE_MAX_MEMBER_BYTES", 10):
            members, warnings = expand_zip("r.zip", _zip([("big.csv", "x" * 50), ("small.csv", "ab")]))
        self.assertEqual([name for name, _ in members], ["small.csv"])
        self.assertTrue(any("troppo grande" in w for w in warnings))

    def test_zip_detection_by_extension_or_magic(self):
        self.assertTrue(is_zip("x.zip", b""))
        self.assertTrue(is_zip("x.bin", b"PK\x03\x04rest"))
        self.assertFalse(is_zip("x.csv", b"a,b"))
        self.assertGreater(ARCHIVE_MAX_MEMBER_BYTES, 1024)


class MailboxZipIngestionTests(TestCase):
    def setUp(self):
        self.source = SecurityMailboxSource.objects.create(
            name="Casella", code="casella", source_type="graph", mailbox_address="x@example.test",
            max_messages_per_run=100, process_attachments=True, process_email_body=True,
        )

    def _run(self, messages):
        provider = mock.Mock()
        provider.list_messages.return_value = messages
        with mock.patch("security.services.mailbox_ingestion.get_provider", return_value=provider):
            return run_mailbox_ingestion(self.source)

    def _firebox_mail(self):
        data = _zip([("FW_Authentication_Allowed_2026-09-29T00_00_to_2026-09-29T23_59.csv", AUTH_CSV),
                     ("FW_Authentication_Denied_2026-09-29T00_00_to_2026-09-29T23_59.csv", DENIED_CSV)])
        return _mail("m1", "Scheduled Firebox Report", "Report programmato in allegato.", [MailboxAttachment("reports.zip", "application/zip", data, len(data))])

    def test_zip_report_is_opened_parsed_and_split_by_kind(self):
        run = self._run([self._firebox_mail()])
        self.assertEqual(run.status, "success")
        self.assertEqual(SecuritySourceFile.objects.count(), 2)
        self.assertEqual(SecuritySourceFile.objects.filter(parse_status=ParseStatus.PARSED).count(), 2)
        self.assertEqual(SecurityVpnAccess.objects.filter(kind="firewall").count(), 1)
        self.assertEqual(SecurityVpnAccess.objects.filter(kind="vpn", action="allowed").count(), 1)
        self.assertEqual(SecurityVpnAccess.objects.filter(kind="vpn", action="denied").count(), 1)

    def test_covering_mail_does_not_create_a_fake_report(self):
        self._run([self._firebox_mail()])
        types = list(SecurityReport.objects.values_list("report_type", flat=True))
        self.assertEqual(sorted(types), ["watchguard_firebox_authentication_allowed", "watchguard_firebox_authentication_denied"])
        message = SecurityMailboxMessage.objects.get()
        self.assertEqual(message.parse_status, ParseStatus.SKIPPED)  # il corpo non e' un report: scartato, non fallito

    def test_second_run_over_the_same_mail_creates_nothing_new(self):
        self._run([self._firebox_mail()])
        counts = (SecuritySourceFile.objects.count(), SecurityReport.objects.count(), SecurityVpnAccess.objects.count())
        run = self._run([self._firebox_mail()])
        self.assertEqual(run.duplicate_messages_count, 1)
        self.assertEqual((SecuritySourceFile.objects.count(), SecurityReport.objects.count(), SecurityVpnAccess.objects.count()), counts)

    def test_corrupt_zip_attachment_does_not_break_the_run(self):
        bad = _mail("m2", "Scheduled Firebox Report", "x", [MailboxAttachment("reports.zip", "application/zip", b"PK\x03\x04 rotto", 12)])
        run = self._run([bad])
        self.assertEqual(run.status, "success")
        self.assertEqual(SecuritySourceFile.objects.count(), 0)

    def test_short_body_with_real_csv_is_still_parsed(self):
        run = self._run([_mail("m3", "Report", DENIED_CSV)])
        self.assertEqual(run.status, "success")
        self.assertEqual(SecurityVpnAccess.objects.filter(action="denied").count(), 1)
