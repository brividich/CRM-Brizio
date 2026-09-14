"""Sincronizzazione SharePoint in background: coda locale, invio, lettura delta.

Nessun test parla con Graph: le chiamate HTTP e le query sulla tabella legacy
``assenze`` sono sostituite da mock; la coda e' il modello Django reale.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from assenze import tasks, views
from assenze.models import AssenzaSharePointOutbox as Outbox

_LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "assenze-sp-sync-tests"}}


@override_settings(CACHES=_LOCMEM)
class OutboxEnqueueTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("assenze.views._sp_kick_push")
    @patch("assenze.views._graph_configured", return_value=True)
    def test_upsert_creates_one_row_and_bumps_version(self, _cfg, mock_kick):
        self.assertEqual(views._sp_enqueue_upsert(7), {"ok": True, "queued": True})
        views._sp_enqueue_upsert(7)

        entry = Outbox.objects.get(assenza_id=7)
        self.assertEqual(entry.azione, Outbox.AZIONE_UPSERT)
        self.assertEqual(entry.versione, 2)
        self.assertEqual(mock_kick.call_count, 2)

    @patch("assenze.views._sp_kick_push")
    @patch("assenze.views._graph_configured", return_value=False)
    def test_nothing_is_queued_when_sharepoint_is_not_configured(self, _cfg, mock_kick):
        self.assertEqual(views._sp_enqueue_upsert(7)["reason"], "not_configured")
        self.assertFalse(Outbox.objects.exists())
        mock_kick.assert_not_called()

    @patch("assenze.views._sp_kick_push")
    @patch("assenze.views._graph_configured", return_value=True)
    def test_delete_of_record_never_sent_needs_no_queue(self, _cfg, _kick):
        self.assertEqual(views._sp_enqueue_delete(7, ""), {"ok": True, "queued": False})
        self.assertFalse(Outbox.objects.exists())

    @patch("assenze.views._sp_kick_push")
    @patch("assenze.views._graph_configured", return_value=True)
    def test_delete_replaces_pending_upsert(self, _cfg, _kick):
        views._sp_enqueue_upsert(7)
        views._sp_enqueue_delete(7, "501")

        entry = Outbox.objects.get(assenza_id=7)
        self.assertEqual(entry.azione, Outbox.AZIONE_DELETE)
        self.assertEqual(entry.sharepoint_item_id, "501")
        self.assertEqual(entry.versione, 2)


@override_settings(CACHES=_LOCMEM)
@patch("assenze.views._graph_configured", return_value=True)
class OutboxPushTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("assenze.views._sync_one_to_sharepoint", return_value={"ok": True, "action": "create", "sharepoint_item_id": "55"})
    @patch("assenze.views._get_assenza", return_value={"id": 7})
    def test_sent_record_leaves_the_queue(self, _get, mock_sync, _cfg):
        Outbox.objects.create(assenza_id=7)

        result = views._sp_push_outbox()

        mock_sync.assert_called_once_with(7, force_update=True)
        self.assertEqual(result["totals"]["created"], 1)
        self.assertEqual(result["pending"], 0)

    @patch("assenze.views._sync_one_to_sharepoint", return_value={"ok": False, "error": "Graph 503"})
    @patch("assenze.views._get_assenza", return_value={"id": 7})
    def test_failed_send_stays_queued_with_error(self, _get, _sync, _cfg):
        Outbox.objects.create(assenza_id=7)

        result = views._sp_push_outbox()

        entry = Outbox.objects.get(assenza_id=7)
        self.assertFalse(result["ok"])
        self.assertEqual(entry.tentativi, 1)
        self.assertIn("Graph 503", entry.ultimo_errore)

    @patch("assenze.views._get_assenza", return_value={"id": 7})
    def test_change_arrived_during_send_is_not_lost(self, _get, _cfg):
        Outbox.objects.create(assenza_id=7)

        def _sync_and_edit_meanwhile(item_id, force_update=True):
            Outbox.objects.filter(assenza_id=item_id).update(versione=2)
            return {"ok": True, "action": "update", "sharepoint_item_id": "55"}

        with patch("assenze.views._sync_one_to_sharepoint", side_effect=_sync_and_edit_meanwhile):
            views._sp_push_outbox()

        self.assertTrue(Outbox.objects.filter(assenza_id=7, versione=2).exists())

    @patch("assenze.views._graph_delete", return_value=(True, ""))
    def test_queued_delete_removes_sharepoint_item(self, mock_delete, _cfg):
        Outbox.objects.create(assenza_id=7, azione=Outbox.AZIONE_DELETE, sharepoint_item_id="501")

        result = views._sp_push_outbox()

        mock_delete.assert_called_once_with("501")
        self.assertEqual(result["totals"]["deleted"], 1)
        self.assertFalse(Outbox.objects.exists())

    @patch("assenze.views._sync_one_to_sharepoint")
    def test_second_concurrent_push_is_skipped(self, mock_sync, _cfg):
        Outbox.objects.create(assenza_id=7)
        cache.add(views._SP_PUSH_LOCK_KEY, "1", timeout=60)

        result = views._sp_push_outbox()

        self.assertEqual(result["reason"], "busy")
        mock_sync.assert_not_called()


@override_settings(CACHES=_LOCMEM)
@patch("assenze.views._table_exists", return_value=True)
@patch("assenze.views.legacy_table_columns", return_value=set())
@patch("assenze.views._graph_configured", return_value=True)
class DeltaPullTests(TestCase):
    def setUp(self):
        cache.clear()

    def _run(self, items, local_ids, *, apply_result="updated", duplicate_id=None):
        with patch("assenze.views._graph_delta_changes", return_value=(items, "https://graph.example/delta?token=B")), \
                patch("assenze.views._find_assenza_id_by_sp_id", side_effect=lambda sp_id: local_ids.get(sp_id)), \
                patch("assenze.views._find_duplicate_assenza_id", return_value=duplicate_id), \
                patch("assenze.views._apply_sp_item_to_local", return_value=apply_result) as mock_apply, \
                patch("assenze.views._delete_assenza", return_value=True) as mock_delete, \
                patch("assenze.views._graph_get_item", return_value=None):
            result = views._sync_pull_from_sharepoint()
        return result, mock_apply, mock_delete

    def test_applies_changes_skips_pending_and_propagates_deletions(self, *_):
        Outbox.objects.create(assenza_id=10)
        items = [
            {"id": "1", "fields": {"Consenso": "Approvato"}},
            {"id": "2", "deleted": {"state": "deleted"}},
            {"id": "3", "fields": {"Consenso": "In attesa"}},
        ]

        result, mock_apply, mock_delete = self._run(items, {"1": 10, "2": 20}, apply_result="inserted")

        self.assertEqual(
            result["totals"],
            {"inserted": 1, "updated": 0, "deleted": 1, "skipped_pending": 1, "discarded": 0, "failed": 0},
        )
        mock_delete.assert_called_once_with(20)
        mock_apply.assert_called_once()
        self.assertIsNone(mock_apply.call_args.args[1])
        self.assertEqual(cache.get(views._SP_DELTA_LINK_KEY), "https://graph.example/delta?token=B")

    def test_unlinked_item_already_on_portal_is_discarded_not_merged(self, *_):
        items = [{"id": "4", "fields": {"CopiaNome": "Mario Rossi", "Data_x0020_inizio": "2026-09-14T06:00:00Z"}}]

        result, mock_apply, mock_delete = self._run(items, {}, duplicate_id=77)

        self.assertEqual(result["totals"]["discarded"], 1)
        mock_apply.assert_not_called()
        mock_delete.assert_not_called()

    def test_linked_item_is_updated_even_if_it_matches_the_key(self, *_):
        items = [{"id": "5", "fields": {"Consenso": "Approvato"}}]

        # La chiave coinciderebbe (duplicate_id=77), ma l'elemento e' gia' collegato:
        # si aggiorna il record collegato invece di scartarlo.
        result, mock_apply, _delete = self._run(items, {"5": 50}, duplicate_id=77)

        self.assertEqual(result["totals"]["updated"], 1)
        self.assertEqual(result["totals"]["discarded"], 0)
        self.assertEqual(mock_apply.call_args.args[1], 50)

    def test_pending_local_record_is_not_deleted_by_sharepoint(self, *_):
        Outbox.objects.create(assenza_id=20)

        result, _apply, mock_delete = self._run([{"id": "2", "deleted": {"state": "deleted"}}], {"2": 20})

        mock_delete.assert_not_called()
        self.assertEqual(result["totals"]["skipped_pending"], 1)

    def test_only_last_occurrence_of_an_item_counts(self, *_):
        items = [{"id": "3", "fields": {"Consenso": "In attesa"}}, {"id": "3", "deleted": {"state": "deleted"}}]

        result, mock_apply, mock_delete = self._run(items, {"3": 30})

        mock_apply.assert_not_called()
        mock_delete.assert_called_once_with(30)

    def test_delta_token_does_not_advance_on_errors(self, *_):
        cache.set(views._SP_DELTA_LINK_KEY, "https://graph.example/delta?token=A")
        with patch("assenze.views._graph_delta_changes", return_value=([{"id": "3", "fields": {"x": 1}}], "https://graph.example/delta?token=B")), \
                patch("assenze.views._find_assenza_id_by_sp_id", return_value=None), \
                patch("assenze.views._apply_sp_item_to_local", side_effect=RuntimeError("boom")):
            result = views._sync_pull_from_sharepoint()

        self.assertFalse(result["ok"])
        self.assertEqual(cache.get(views._SP_DELTA_LINK_KEY), "https://graph.example/delta?token=A")


class DuplicateKeyTests(TestCase):
    """Chiave dell'import Excel: nominativo + giorno di inizio + giorno di fine."""

    def _payload(self, **over):
        from datetime import datetime

        data = {"copia_nome": "  mario   rossi ", "data_inizio": datetime(2026, 9, 14, 8, 0), "data_fine": datetime(2026, 9, 15, 17, 0)}
        data.update(over)
        return data

    @patch("assenze.views._fetch_all_dict")
    def test_same_person_same_days_different_hours_is_a_duplicate(self, mock_fetch):
        from datetime import datetime

        mock_fetch.return_value = [{"id": 9, "copia_nome": "MARIO ROSSI", "data_fine": datetime(2026, 9, 15, 12, 0)}]

        self.assertEqual(views._find_duplicate_assenza_id(self._payload()), 9)
        day_start, day_end = mock_fetch.call_args.args[1]
        self.assertEqual((day_start, day_end), (datetime(2026, 9, 14), datetime(2026, 9, 15)))

    @patch("assenze.views._fetch_all_dict")
    def test_other_person_or_other_end_day_is_not_a_duplicate(self, mock_fetch):
        from datetime import datetime

        mock_fetch.return_value = [
            {"id": 9, "copia_nome": "Luigi Verdi", "data_fine": datetime(2026, 9, 15, 17, 0)},
            {"id": 10, "copia_nome": "Mario Rossi", "data_fine": datetime(2026, 9, 16, 17, 0)},
        ]

        self.assertIsNone(views._find_duplicate_assenza_id(self._payload()))

    @patch("assenze.views._fetch_all_dict")
    def test_missing_dates_or_name_never_match(self, mock_fetch):
        self.assertIsNone(views._find_duplicate_assenza_id(self._payload(data_inizio=None)))
        self.assertIsNone(views._find_duplicate_assenza_id(self._payload(copia_nome="")))
        mock_fetch.assert_not_called()


@patch("assenze.views._graph_headers", return_value={})
@patch("assenze.views._graph_base_url", return_value="https://graph.example/items")
class GraphDeltaChangesTests(TestCase):
    @patch("assenze.views.requests.get")
    def test_follows_next_links_and_returns_delta_link(self, mock_get, *_):
        page1 = MagicMock(status_code=200)
        page1.json.return_value = {"value": [{"id": "1"}], "@odata.nextLink": "https://graph.example/next"}
        page2 = MagicMock(status_code=200)
        page2.json.return_value = {"value": [{"id": "2"}], "@odata.deltaLink": "https://graph.example/delta?token=Z"}
        mock_get.side_effect = [page1, page2]

        items, link = views._graph_delta_changes(None)

        self.assertEqual([i["id"] for i in items], ["1", "2"])
        self.assertEqual(link, "https://graph.example/delta?token=Z")
        self.assertEqual(mock_get.call_args_list[0].args[0], "https://graph.example/items/delta?$expand=fields")

    @patch("assenze.views.requests.get")
    def test_expired_token_restarts_full_enumeration(self, mock_get, *_):
        gone = MagicMock(status_code=410, text="resyncRequired")
        full = MagicMock(status_code=200)
        full.json.return_value = {"value": [{"id": "9"}], "@odata.deltaLink": "https://graph.example/delta?token=N"}
        mock_get.side_effect = [gone, full]

        items, link = views._graph_delta_changes("https://graph.example/delta?token=OLD")

        self.assertEqual([i["id"] for i in items], ["9"])
        self.assertEqual(link, "https://graph.example/delta?token=N")


@override_settings(CACHES=_LOCMEM)
class SyncJobTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("assenze.views._sp_push_outbox")
    @patch("assenze.views._graph_configured", return_value=False)
    def test_job_is_a_noop_without_sharepoint(self, _cfg, mock_push):
        self.assertIn("skipped", tasks.run_assenze_sharepoint_sync())
        mock_push.assert_not_called()

    @patch("assenze.views._sp_refresh_motivazioni")
    @patch("assenze.views._graph_configured", return_value=True)
    def test_job_sends_queue_before_reading_sharepoint(self, _cfg, _motiv):
        order = []
        with patch("assenze.views._sp_push_outbox", side_effect=lambda: order.append("push") or {}), \
                patch("assenze.views._maybe_pull", side_effect=lambda force: order.append("pull") or {}):
            tasks.run_assenze_sharepoint_sync()

        self.assertEqual(order, ["push", "pull"])

    @patch("assenze.views._load_motivazioni_local", return_value=["Visita"])
    def test_form_motivazioni_come_from_cache_or_local_never_graph(self, _local):
        with patch("assenze.views._graph_get_motivazioni") as mock_graph:
            self.assertEqual(views._motivazioni_options(), ["Visita"])
            cache.set(views._SP_MOTIVAZIONI_CACHE_KEY, ["Ferie", "Permesso"])
            self.assertEqual(views._motivazioni_options(), ["Ferie", "Permesso"])
        mock_graph.assert_not_called()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, CACHES=_LOCMEM)
class PagesDoNotCallGraphTests(TestCase):
    @patch("assenze.views._template_perm_context", return_value={})
    @patch("assenze.views._load_personal", return_value=[])
    @patch("assenze.views._load_pending_for_manager", return_value=[{"id": 5, "stato": "In attesa"}])
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.local", 77))
    @patch("assenze.views._graph_configured", return_value=True)
    @patch("assenze.views.requests")
    def test_gestione_page_makes_no_graph_request(self, mock_requests, *_):
        user = get_user_model().objects.create_superuser(
            username="assenze-nograph", email="nograph@example.local", password="pass12345"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("assenze_gestione"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(mock_requests.method_calls)
