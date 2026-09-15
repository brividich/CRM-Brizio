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
from assenze.models import AssenzaOrigineSharePoint as Origine
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


# ─── Chi gestisce la richiesta: origine, sola lettura, niente automazioni ──────


@override_settings(CACHES=_LOCMEM)
class OrigineSharePointTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_item_created_by_an_app_is_a_portal_request(self):
        self.assertTrue(views._sp_item_created_by_portal({"createdBy": {"application": {"id": "x", "displayName": "Hub"}}}))
        self.assertTrue(views._sp_item_created_by_portal({"createdBy": {"user": {"displayName": "App di SharePoint"}}}))
        self.assertFalse(views._sp_item_created_by_portal({"createdBy": {"user": {"displayName": "Mario Rossi"}}}))
        self.assertFalse(views._sp_item_created_by_portal({}))

    def test_pull_never_corrects_a_known_origin_push_does(self):
        views._record_sp_origin(7, "501", creata_su_sharepoint=False)
        views._record_sp_origin(7, "501", creata_su_sharepoint=True)
        self.assertFalse(Origine.objects.get(assenza_id=7).creata_su_sharepoint)

        views._record_sp_origin(8, "502", creata_su_sharepoint=True)
        views._record_sp_origin(8, "502", creata_su_sharepoint=False, overwrite=True)
        self.assertFalse(Origine.objects.get(assenza_id=8).creata_su_sharepoint)

    @patch("assenze.views._graph_configured", return_value=True)
    def test_rows_are_marked_only_when_born_on_sharepoint(self, _cfg):
        Origine.objects.create(assenza_id=1, creata_su_sharepoint=True)
        Origine.objects.create(assenza_id=2, creata_su_sharepoint=False)
        rows = [{"id": 1}, {"id": 2}, {"id": 3}]

        views._mark_sharepoint_managed(rows)

        self.assertEqual([r["gestita_sp"] for r in rows], [True, False, False])

    @patch("assenze.views._graph_configured", return_value=True)
    def test_many_ids_are_queried_in_chunks(self, _cfg):
        Origine.objects.create(assenza_id=2500, creata_su_sharepoint=True)

        with self.assertNumQueries(3):
            managed = views._sharepoint_managed_ids(range(1, 3001))

        self.assertEqual(managed, {2500})

    @patch("assenze.views._graph_configured", return_value=False)
    def test_nothing_is_read_only_without_sharepoint(self, _cfg):
        Origine.objects.create(assenza_id=1, creata_su_sharepoint=True)
        self.assertEqual(views._sharepoint_managed_ids([1]), set())

    @patch("assenze.views._fill_sp_lookups", return_value=[])
    @patch("assenze.views._update_assenza", return_value=True)
    @patch("assenze.views._graph_create", return_value=(True, {"id": "900"}))
    @patch("assenze.views._get_assenza", return_value={"id": 7, "sharepoint_item_id": ""})
    @patch("assenze.views._graph_configured", return_value=True)
    def test_request_sent_by_the_portal_is_recorded_as_portal(self, *_):
        result = views._sync_one_to_sharepoint(7, force_update=True)

        self.assertEqual(result["action"], "create")
        origine = Origine.objects.get(assenza_id=7)
        self.assertFalse(origine.creata_su_sharepoint)
        self.assertEqual(origine.sharepoint_item_id, "900")


class AutomationQueueSkipTests(TestCase):
    def test_sqlite_has_no_triggers_nothing_to_do(self):
        with patch("assenze.views._db_vendor", return_value="sqlite"), patch("assenze.views.connections") as conns:
            views._set_automation_queue_skip(True)
        conns.__getitem__.assert_not_called()

    def test_sql_server_sets_and_clears_the_session_flag(self):
        cursor = MagicMock()
        with patch("assenze.views._db_vendor", return_value="microsoft"), patch("assenze.views.connections") as conns:
            conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = cursor
            views._set_automation_queue_skip(True)
            views._set_automation_queue_skip(False)

        first, second = cursor.execute.call_args_list
        self.assertIn("sp_set_session_context", first.args[0])
        self.assertEqual(first.args[1], ["hub_skip_automation", 1])
        self.assertEqual(second.args[1], ["hub_skip_automation", None])

    def test_both_triggers_skip_writes_of_the_sync(self):
        from pathlib import Path

        sql_dir = Path(views.__file__).resolve().parents[2] / "sql"
        for name in ("trg_assenze_automation_after_insert.sql", "trg_assenze_automation_after_update.sql"):
            text = (sql_dir / name).read_text(encoding="utf-8")
            self.assertIn("SESSION_CONTEXT(N''hub_skip_automation'')", text, name)


@override_settings(CACHES=_LOCMEM)
@patch("assenze.views._table_exists", return_value=True)
@patch("assenze.views.legacy_table_columns", return_value=set())
@patch("assenze.views._graph_configured", return_value=True)
class SyncWritesSkipAutomationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_pull_turns_the_flag_on_and_always_off(self, *_):
        with patch("assenze.views._graph_delta_changes", return_value=([{"id": "3", "fields": {"x": 1}}], "")), \
                patch("assenze.views._find_assenza_id_by_sp_id", return_value=30), \
                patch("assenze.views._apply_sp_item_to_local", side_effect=RuntimeError("boom")), \
                patch("assenze.views._set_automation_queue_skip") as mock_skip:
            views._sync_pull_from_sharepoint()

        self.assertEqual([c.args[0] for c in mock_skip.call_args_list], [True, False])

    def test_push_turns_the_flag_on_and_off(self, *_):
        Outbox.objects.create(assenza_id=7)
        with patch("assenze.views._get_assenza", return_value={"id": 7}), \
                patch("assenze.views._sync_one_to_sharepoint", return_value={"ok": True, "action": "update"}), \
                patch("assenze.views._set_automation_queue_skip") as mock_skip:
            views._sp_push_outbox()

        self.assertEqual([c.args[0] for c in mock_skip.call_args_list], [True, False])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, CACHES=_LOCMEM)
@patch("assenze.views._graph_configured", return_value=True)
class ReadOnlyOnPortalTests(TestCase):
    def setUp(self):
        cache.clear()
        Origine.objects.create(assenza_id=42, creata_su_sharepoint=True)
        user = get_user_model().objects.create_superuser(
            username="assenze-sp-ro", email="ro@example.local", password="pass12345"
        )
        self.client.force_login(user)

    @patch("assenze.views._update_assenza")
    @patch("assenze.views._can_manage_record", return_value=True)
    @patch("assenze.views._get_assenza", return_value={"id": 42, "consenso": "In attesa"})
    @patch("assenze.views._assenze_permissions", return_value={"can_update_owned": True, "can_update_any": True})
    def test_capo_cannot_approve_a_request_born_on_sharepoint(self, _perms, _get, _can, mock_update, _cfg):
        response = self.client.post(
            reverse("assenze_api_car_consenso", args=[42]),
            data='{"consenso": "Approvato"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        mock_update.assert_not_called()

    @patch("assenze.views._delete_assenza")
    @patch("assenze.views._get_assenza", return_value={"id": 42, "sharepoint_item_id": "501"})
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_delete_any": True})
    def test_delete_is_refused_and_nothing_is_queued(self, _perms, _get, mock_delete, _cfg):
        response = self.client.post(reverse("assenze_api_evento_delete", args=[42]), data="{}", content_type="application/json")

        self.assertEqual(response.status_code, 409)
        mock_delete.assert_not_called()
        self.assertFalse(Outbox.objects.exists())

    @patch("assenze.views._update_assenza", return_value=True)
    @patch("assenze.views._sp_kick_push")
    @patch("assenze.views._can_manage_record", return_value=True)
    @patch("assenze.views._get_assenza", return_value={"id": 43, "consenso": "In attesa"})
    @patch("assenze.views._assenze_permissions", return_value={"can_update_owned": True, "can_update_any": True})
    def test_request_born_on_the_portal_is_still_approved_here(self, _perms, _get, _can, _kick, mock_update, _cfg):
        response = self.client.post(
            reverse("assenze_api_car_consenso", args=[43]),
            data='{"consenso": "Approvato"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        mock_update.assert_called_once()

    def test_admin_panel_hides_actions_for_requests_born_on_sharepoint(self, _cfg):
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        row = {"dipendente": "Mario Rossi", "tipo": "Ferie", "stato_label": "In attesa", "moderation_status": 2,
               "inizio_label": "14/09/2026", "fine_label": "15/09/2026", "motivo": ""}
        ctx = {
            "is_assenze_admin": True, "admin_can_moderate": True, "admin_can_delete": True, "admin_tabella_ok": True,
            "admin_stats": {}, "admin_by_tipo": [], "admin_q": "", "admin_audit_entries": [],
            "admin_sync_info": {"pending": 0},
            "admin_assenze": [{**row, "id": 1, "gestita_sp": True}, {**row, "id": 2, "gestita_sp": False}],
        }

        html = render_to_string("assenze/partials/_gestione_admin_panel.html", ctx, request=RequestFactory().get("/"))

        self.assertEqual(html.count(">Gestita su SharePoint<"), 1)
        self.assertIn('data-act="approva" data-id="2"', html)
        self.assertNotIn('data-act="approva" data-id="1"', html)


# ─── Persona e capo su SharePoint: abbinamento per email/username ─────────────


@override_settings(CACHES=_LOCMEM)
class SharePointLookupTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("assenze.views._graph_headers", return_value={})
    @patch("assenze.views._graph_settings", return_value={"site_id": "S", "list_id_assenze": "A"})
    @patch("assenze.views.requests.get")
    def test_maps_are_read_from_the_lists_pointed_by_the_lookup_columns(self, mock_get, *_):
        responses = {
            "/lists/A/columns": [
                {"name": "Nome", "lookup": {"listId": "DIP"}},
                {"name": "C_x002e_Reparto", "lookup": {"listId": "CAPI"}},
                {"name": "Title"},
            ],
            "/lists/CAPI/items": [
                {"id": "11", "fields": {"IndirizozEmail": "Capo.Uno@example.local"}},
                {"id": "12", "fields": {"IndirizozEmail": "doppio@example.local"}},
                {"id": "13", "fields": {"IndirizozEmail": "doppio@example.local"}},
            ],
            "/lists/DIP/items": [{"id": "21", "fields": {"Title": "ROSSI MARIO", "USERNAME": "m.rossi"}}],
        }

        def _page(url, **_kwargs):
            response = MagicMock(status_code=200)
            response.json.return_value = {"value": next(v for k, v in responses.items() if k in url)}
            return response

        mock_get.side_effect = _page

        maps = views._sp_lookup_maps()

        self.assertEqual(maps["capi_email"], {"capo.uno@example.local": 11})  # l'email doppia e' ambigua
        self.assertEqual(maps["dip_username"], {"m.rossi": 21})
        self.assertEqual(maps["dip_nome"], {"MARIO ROSSI": 21})
        calls = mock_get.call_count
        views._sp_lookup_maps()
        self.assertEqual(mock_get.call_count, calls)  # la seconda volta dalla cache

    @patch("assenze.views._capo_email_for_row", return_value="capo.uno@example.local")
    def test_person_by_username_email_or_name_capo_by_email(self, _capo):
        maps = {
            "capi_email": {"capo.uno@example.local": 11},
            "dip_username": {"m.rossi": 21, "l.bianchi@example.local": 22},
            "dip_nome": {"ANNA GIALLO": 23},
        }

        self.assertEqual(views._sp_lookup_ids_for_row({"aliasusername": "M.Rossi"}, maps), (21, 11))
        self.assertEqual(views._sp_lookup_ids_for_row({"email_esterna": "L.Bianchi@example.local"}, maps), (22, 11))
        self.assertEqual(views._sp_lookup_ids_for_row({"email_esterna": "m.rossi@example.local"}, maps), (21, 11))
        self.assertEqual(views._sp_lookup_ids_for_row({"copia_nome": "giallo  anna"}, maps), (23, 11))
        self.assertEqual(views._sp_lookup_ids_for_row({"copia_nome": "Nessuno"}, maps), (None, 11))

    @patch("assenze.views._effective_capo_option", return_value=("Capo.Area@Example.local", False))
    @patch("assenze.views._load_capi_options", return_value=[])
    def test_capo_email_uses_the_same_rule_as_the_form(self, _capi, mock_effective):
        from datetime import datetime

        email = views._capo_email_for_row(
            {"id": 7, "copia_nome": "Mario Rossi", "email_esterna": "m@example.local", "data_inizio": datetime(2026, 9, 23, 16, 30)}
        )

        self.assertEqual(email, "capo.area@example.local")
        self.assertEqual(mock_effective.call_args.kwargs["request_day"].isoformat(), "2026-09-23")

    @patch("assenze.views._update_assenza", return_value=True)
    @patch("assenze.views._graph_create", return_value=(True, {"id": "900"}))
    @patch(
        "assenze.views._sp_lookup_maps",
        return_value={"capi_email": {"capo.uno@example.local": 11}, "dip_username": {"m.rossi": 21}, "dip_nome": {}},
    )
    @patch("assenze.views._capo_email_for_row", return_value="capo.uno@example.local")
    @patch(
        "assenze.views._get_assenza",
        return_value={"id": 7, "sharepoint_item_id": "", "aliasusername": "m.rossi", "capo_reparto_lookup_id": 5},
    )
    @patch("assenze.views._graph_configured", return_value=True)
    def test_request_is_sent_with_person_and_capo_filled(self, _cfg, _get, _capo, _maps, mock_create, mock_update):
        result = views._sync_one_to_sharepoint(7, force_update=True)

        fields = mock_create.call_args.args[0]
        self.assertEqual(fields["NomeLookupId"], 21)
        self.assertEqual(fields["C_x002e_RepartoLookupId"], 11)  # non il vecchio 5
        self.assertEqual(result["lookup_missing"], [])
        self.assertEqual(mock_update.call_args_list[0].args[1], {"nome_lookup_id": 21, "capo_reparto_lookup_id": 11})

    @patch("assenze.views._sp_lookup_maps", side_effect=RuntimeError("Graph GET 503"))
    @patch("assenze.views._graph_create")
    @patch("assenze.views._get_assenza", return_value={"id": 7, "sharepoint_item_id": ""})
    @patch("assenze.views._graph_configured", return_value=True)
    def test_graph_error_on_lookups_keeps_the_request_queued(self, _cfg, _get, mock_create, _maps):
        Outbox.objects.create(assenza_id=7)

        result = views._sp_push_outbox()

        mock_create.assert_not_called()
        self.assertEqual(result["totals"]["failed"], 1)
        self.assertTrue(Outbox.objects.filter(assenza_id=7).exists())

    @patch("assenze.views._get_assenza", return_value={"id": 7})
    @patch("assenze.views._graph_configured", return_value=True)
    def test_push_counts_requests_sent_without_capo(self, *_):
        Outbox.objects.create(assenza_id=7)
        sent = {"ok": True, "action": "create", "sharepoint_item_id": "9", "lookup_missing": ["capo"]}

        with patch("assenze.views._sync_one_to_sharepoint", return_value=sent):
            result = views._sp_push_outbox()

        self.assertEqual(result["totals"]["senza_capo"], 1)
        self.assertEqual(result["totals"]["senza_nome"], 0)
