"""Incremental mailbox ingestion: a backlog must never be silently dropped.

The old fetch asked Graph for the newest N messages and stopped. If more than
``max_messages_per_run`` mails arrived between two runs, the older ones fell out of the
window and were never imported - the next run again saw only the newest N. For a tool
whose promise is "no report is lost", that is a real hole, and it opens exactly during a
burst (a nightly batch of vendor reports), i.e. when it matters most.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from security.models import SecurityMailboxMessage, SecurityMailboxSource
from security.services.mailbox_ingestion import _watermark, run_mailbox_ingestion
from security.services.mailbox_providers import (
    GRAPH_MAX_PAGES,
    INCREMENTAL_OVERLAP_MINUTES,
    GraphMailboxProvider,
    MailboxMessage,
    incremental_since,
)


def _msg(index, received_at):
    return MailboxMessage(
        provider_message_id=f"id-{index}",
        internet_message_id=f"<{index}@example.test>",
        sender="reports@example.test",
        recipients=["soc@example.test"],
        subject=f"Report {index}",
        received_at=received_at,
        body_text="body",
        body_html="",
        attachments=[],
    )


def _graph_item(index, received_at):
    return {
        "id": f"id-{index}",
        "internetMessageId": f"<{index}@example.test>",
        "subject": f"Report {index}",
        "from": {"emailAddress": {"address": "reports@example.test"}},
        "toRecipients": [{"emailAddress": {"address": "soc@example.test"}}],
        "receivedDateTime": received_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body": {"content": "body"},
        "hasAttachments": False,
    }


class IncrementalSinceTests(TestCase):
    def test_first_run_has_no_lower_bound(self):
        source = SecurityMailboxSource(name="S", code="s", source_type="graph")
        self.assertIsNone(incremental_since(source))

    def test_since_is_last_success_minus_overlap(self):
        last = datetime(2026, 7, 13, 10, 0, tzinfo=dt_timezone.utc)
        source = SecurityMailboxSource(name="S", code="s", source_type="graph", last_success_at=last)

        self.assertEqual(
            incremental_since(source),
            last - timedelta(minutes=INCREMENTAL_OVERLAP_MINUTES),
        )


class GraphQueryTests(TestCase):
    """The Graph request itself must ask for the right window, in the right order."""

    def setUp(self):
        self.source = SecurityMailboxSource.objects.create(
            name="Graph", code="graph", source_type="graph",
            mailbox_address="soc@example.test", max_messages_per_run=50,
        )
        self.provider = GraphMailboxProvider()

    def _capture_urls(self, pages):
        calls = []

        def fake_request(url, **kwargs):
            calls.append(url)
            return pages.pop(0) if pages else {"value": []}

        return calls, fake_request

    def test_first_run_asks_ascending_and_without_filter(self):
        calls, fake = self._capture_urls([{"value": []}])
        with mock.patch("security.services.mailbox_providers._request_json", side_effect=fake):
            self.provider._get_messages("tok", self.source, limit=50)

        url = calls[-1]
        self.assertIn("receivedDateTime+asc", url.replace("%20", "+").replace("%3A", ":"))
        self.assertNotIn("filter", url)

    def test_incremental_run_filters_from_last_success(self):
        self.source.last_success_at = datetime(2026, 7, 13, 10, 0, tzinfo=dt_timezone.utc)
        self.source.save(update_fields=["last_success_at"])

        calls, fake = self._capture_urls([{"value": []}])
        with mock.patch("security.services.mailbox_providers._request_json", side_effect=fake):
            self.provider._get_messages("tok", self.source, limit=50)

        decoded = urllib_unquote(calls[-1])
        self.assertIn("receivedDateTime ge 2026-07-13T09:30:00Z", decoded)  # 10:00 minus 30' overlap

    def test_pagination_follows_next_link(self):
        pages = [
            {"value": [_graph_item(1, datetime(2026, 7, 13, 1, tzinfo=dt_timezone.utc))], "@odata.nextLink": "https://graph.example/page2"},
            {"value": [_graph_item(2, datetime(2026, 7, 13, 2, tzinfo=dt_timezone.utc))], "@odata.nextLink": "https://graph.example/page3"},
            {"value": [_graph_item(3, datetime(2026, 7, 13, 3, tzinfo=dt_timezone.utc))]},
        ]
        calls, fake = self._capture_urls(pages)
        with mock.patch("security.services.mailbox_providers._request_json", side_effect=fake):
            items = self.provider._get_messages("tok", self.source, limit=50)

        self.assertEqual(len(items), 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1], "https://graph.example/page2")

    def test_page_cap_is_logged_not_silent(self):
        endless = {"value": [_graph_item(1, datetime(2026, 7, 13, 1, tzinfo=dt_timezone.utc))],
                   "@odata.nextLink": "https://graph.example/next"}
        with mock.patch("security.services.mailbox_providers._request_json", return_value=endless):
            with self.assertLogs("security.services.mailbox_providers", level="WARNING") as logs:
                items = self.provider._get_messages("tok", self.source, limit=1000)

        self.assertEqual(len(items), GRAPH_MAX_PAGES)
        self.assertTrue(any("pagination stopped" in line for line in logs.output))


class WatermarkTests(TestCase):
    """The watermark is where the next run resumes. Getting it wrong loses mail."""

    def setUp(self):
        self.source = SecurityMailboxSource.objects.create(
            name="S", code="s", source_type="graph", mailbox_address="soc@example.test",
        )

    def test_watermark_is_the_newest_message_seen_not_now(self):
        """The heart of it: with a partially drained backlog, the un-fetched messages are
        NEWER than the fetched ones. Advancing to `now` would jump straight over them."""
        oldest = timezone.now() - timedelta(hours=5)
        newest_fetched = timezone.now() - timedelta(hours=3)
        messages = [_msg(1, oldest), _msg(2, newest_fetched)]

        self.assertEqual(_watermark(self.source, messages), newest_fetched)

    def test_watermark_falls_back_to_now_when_nothing_arrived(self):
        before = timezone.now()
        result = _watermark(self.source, [])
        self.assertGreaterEqual(result, before)

    def test_watermark_never_moves_backwards(self):
        """The overlap window deliberately re-reads old mail: it must not rewind us."""
        self.source.last_success_at = timezone.now()
        old = timezone.now() - timedelta(days=2)

        self.assertEqual(_watermark(self.source, [_msg(1, old)]), self.source.last_success_at)

    def test_backlog_larger_than_the_cap_is_drained_across_runs(self):
        """End to end: 5 messages, 2 per run. All 5 must land, none may be skipped."""
        base = timezone.now() - timedelta(hours=10)
        all_messages = [_msg(i, base + timedelta(hours=i)) for i in range(5)]
        self.source.max_messages_per_run = 2
        self.source.save(update_fields=["max_messages_per_run"])

        class BatchingProvider:
            """Stands in for Graph: applies the incremental filter and the batch cap."""

            def list_messages(self, source, limit=50):
                since = incremental_since(source)
                pending = [m for m in all_messages if since is None or m.received_at >= since]
                pending.sort(key=lambda m: m.received_at)  # oldest first, like the real query
                return pending[:limit]

        with mock.patch("security.services.mailbox_ingestion.get_provider", return_value=BatchingProvider()):
            for _ in range(4):
                run_mailbox_ingestion(self.source)
                self.source.refresh_from_db()

        imported = SecurityMailboxMessage.objects.count()
        self.assertEqual(imported, 5, "every message in the backlog must be imported exactly once")


def urllib_unquote(url: str) -> str:
    import urllib.parse

    return urllib.parse.unquote_plus(url)
