from datetime import date, datetime
from io import StringIO
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import HttpResponse
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .views import (
    _anagrafica_employee_ids_for_capo,
    _build_submit_token,
    _certificazione_presenza_dipendenti_attivi,
    _diagnose_sharepoint_sync_item,
    _fetch_first_row_from_cursor,
    _find_inserted_assenza_id,
    _graph_delete,
    _insert_assenza,
    _insert_row_and_return_id,
    _load_capi_options,
    _motivazione_for_storage,
    _norm_tipo,
    _owned_capo_ids_for_legacy_user,
    _resolve_capo_local_id,
    _resolve_capo_local_id_from_anagrafica_hr,
    _resolve_default_capo_for_user,
    _reconcile_pending_item_ids_with_sharepoint,
    _resolve_request_display_name,
    _sp_fields_from_row,
    _sp_item_to_local,
    _strip_tipo_metadata_from_motivazione,
    _sync_on_page_load_enabled,
    _tipo_for_display,
    _tipo_for_storage,
    _validate_business_rules,
)

User = get_user_model()


class SharePointStatusParsingTests(SimpleTestCase):
    def _make_item(self, *, consenso="In attesa", moderation_status=None):
        fields = {
            "Consenso": consenso,
            "CopiaNome": "Mario Rossi",
            "emailesterna": "mario.rossi@example.local",
            "Tipoassenza": "Permesso",
            "Data_x0020_inizio": "2025-10-22T06:00:00.000Z",
            "Datafine": "2025-10-23T14:00:00.000Z",
        }
        if moderation_status is not None:
            fields["_ModerationStatus"] = moderation_status
        return {
            "id": "321",
            "fields": fields,
            "createdDateTime": "2025-10-20T08:00:00Z",
            "lastModifiedDateTime": "2025-10-20T09:00:00Z",
        }

    def test_custom_consenso_wins_when_moderation_stays_pending(self):
        _sp_id, data = _sp_item_to_local(self._make_item(consenso="Approvato", moderation_status="2"))
        self.assertEqual(data["consenso"], "Approvato")
        self.assertEqual(data["moderation_status"], 0)

    def test_system_moderation_still_wins_when_it_is_final(self):
        _sp_id, data = _sp_item_to_local(self._make_item(consenso="Approvato", moderation_status="1"))
        self.assertEqual(data["consenso"], "Rifiutato")
        self.assertEqual(data["moderation_status"], 1)

    def test_custom_consenso_is_used_when_moderation_is_missing(self):
        _sp_id, data = _sp_item_to_local(self._make_item(consenso="Rifiutato", moderation_status=None))
        self.assertEqual(data["consenso"], "Rifiutato")
        self.assertEqual(data["moderation_status"], 1)


class AssenzeSyncFlagTests(SimpleTestCase):
    @override_settings(ASSENZE_SYNC_ON_PAGE_LOAD=True)
    def test_sync_on_page_load_enabled_when_setting_true(self):
        self.assertTrue(_sync_on_page_load_enabled())

    @override_settings(ASSENZE_SYNC_ON_PAGE_LOAD="0")
    def test_sync_on_page_load_disabled_when_setting_zero_string(self):
        self.assertFalse(_sync_on_page_load_enabled())


class SharePointDeleteTests(SimpleTestCase):
    @patch("assenze.views._graph_headers", return_value={})
    @patch("assenze.views._graph_base_url", return_value="https://graph.example/items")
    @patch("assenze.views.requests.delete")
    def test_graph_delete_treats_item_not_found_as_success(
        self,
        mock_delete,
        _mock_base_url,
        _mock_headers,
    ):
        mock_delete.return_value.status_code = 404
        mock_delete.return_value.text = '{"error":{"code":"itemNotFound"}}'
        mock_delete.return_value.json.return_value = {"error": {"code": "itemNotFound"}}

        ok, err = _graph_delete("4018")

        self.assertTrue(ok)
        self.assertEqual(err, "")


class AssenzeSqlServerInsertTests(SimpleTestCase):
    def test_fetch_first_row_from_cursor_advances_to_query_result_set(self):
        cursor = MagicMock()
        cursor.description = None
        cursor.fetchone.return_value = (77,)

        state = {"calls": 0}

        def nextset():
            state["calls"] += 1
            if state["calls"] == 1:
                cursor.description = [("id",)]
                return True
            return False

        cursor.nextset.side_effect = nextset

        result = _fetch_first_row_from_cursor(cursor)

        self.assertEqual(result, (77,))
        cursor.fetchone.assert_called_once()

    def test_fetch_first_row_from_cursor_returns_none_when_no_query_result_exists(self):
        cursor = MagicMock()
        cursor.description = None

        def nextset():
            cursor.description = [("id",)]
            raise RuntimeError("no more results")

        cursor.nextset.side_effect = nextset

        self.assertIsNone(_fetch_first_row_from_cursor(cursor))

    def test_insert_row_and_return_id_uses_output_into_clause_for_sql_server(self):
        cursor = MagicMock()
        cursor.description = [("id",)]
        cursor.fetchone.return_value = (51,)
        cursor.nextset.return_value = False
        conn = MagicMock()
        conn.ops.quote_name.side_effect = lambda column: column

        with patch("assenze.views._db_vendor", return_value="microsoft"), patch(
            "assenze.views.connections",
            {"default": conn},
        ):
            result = _insert_row_and_return_id(cursor, "assenze", ["title", "consenso"], ["Richiesta", "In attesa"])

        self.assertEqual(result, 51)
        first_sql, first_params = cursor.execute.call_args_list[0].args
        self.assertIn("INSERT INTO", first_sql)
        self.assertIn("assenze", first_sql)
        self.assertIn("title", first_sql)
        self.assertIn("consenso", first_sql)
        self.assertIn("OUTPUT INSERTED.id INTO @inserted_ids", first_sql)
        self.assertEqual(first_params, ["Richiesta", "In attesa"])
        self.assertEqual(len(cursor.execute.call_args_list), 1)

    def test_insert_assenza_sql_server_reuses_trigger_safe_insert_flow(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (88,)
        cursor_manager = MagicMock()
        cursor_manager.__enter__.return_value = cursor
        connection = MagicMock()
        connection.cursor.return_value = cursor_manager
        connection.ops.quote_name.side_effect = lambda column: column

        with patch("assenze.views._db_vendor", return_value="sql_server"), patch(
            "assenze.views._prepare_row_data",
            return_value={"title": "Richiesta", "consenso": "In attesa"},
        ), patch("assenze.views.connections", {"default": connection}):
            result = _insert_assenza({"title": "Richiesta"})

        self.assertEqual(result, 88)
        insert_sql = cursor.execute.call_args_list[0].args[0]
        self.assertIn("OUTPUT INSERTED.id INTO @inserted_ids", insert_sql)

    def test_insert_assenza_falls_back_to_lookup_when_driver_returns_no_identity(self):
        cursor = MagicMock()
        cursor_manager = MagicMock()
        cursor_manager.__enter__.return_value = cursor
        connection = MagicMock()
        connection.cursor.return_value = cursor_manager

        with patch(
            "assenze.views._prepare_row_data",
            return_value={"copia_nome": "Mario Rossi", "tipo_assenza": "Permesso"},
        ), patch("assenze.views._insert_row_and_return_id", return_value=None), patch(
            "assenze.views._find_inserted_assenza_id",
            return_value=144,
        ) as mock_find, patch("assenze.views.connections", {"default": connection}):
            result = _insert_assenza({"tipo_assenza": "Permesso"})

        self.assertEqual(result, 144)
        mock_find.assert_called_once_with({"copia_nome": "Mario Rossi", "tipo_assenza": "Permesso"})

    def test_find_inserted_assenza_id_matches_latest_row(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (203,)
        cursor_manager = MagicMock()
        cursor_manager.__enter__.return_value = cursor
        connection = MagicMock()
        connection.cursor.return_value = cursor_manager
        connection.ops.quote_name.side_effect = lambda column: column

        with patch("assenze.views.connections", {"default": connection}), patch(
            "assenze.views._select_limited",
            side_effect=lambda base_sql, _order, _limit: base_sql,
        ):
            result = _find_inserted_assenza_id(
                {
                    "sharepoint_item_id": None,
                    "copia_nome": "Mario Rossi",
                    "email_esterna": "mario@example.com",
                    "tipo_assenza": "Permesso",
                    "moderation_status": 2,
                }
            )

        self.assertEqual(result, 203)
        sql, params = cursor.execute.call_args.args
        self.assertIn("sharepoint_item_id", sql)
        self.assertIn("IS NULL", sql)
        self.assertIn("copia_nome", sql)
        self.assertEqual(params, ["Mario Rossi", "mario@example.com", "Permesso", 2])


class AssenzeTipoMappingTests(SimpleTestCase):
    def test_storage_maps_flessibilita_to_canonical_value(self):
        self.assertEqual(_tipo_for_storage("Flessibilita"), "Flessibilità")

    def test_legacy_infortunio_is_still_rendered_as_flessibilita(self):
        self.assertEqual(_norm_tipo("Infortunio"), "Flessibilità")

    def test_storage_persists_certifica_presenza_as_real_type(self):
        self.assertEqual(_tipo_for_storage("Certifica presenza"), "Certifica presenza")
        self.assertEqual(
            _motivazione_for_storage("Certifica presenza", "Turno mattina"),
            "Turno mattina",
        )

    def test_display_recovers_certifica_presenza_from_marker(self):
        self.assertEqual(_tipo_for_display("Altro", "[CERTIFICA_PRESENZA] Turno mattina"), "Certifica presenza")
        self.assertEqual(_strip_tipo_metadata_from_motivazione("[CERTIFICA_PRESENZA] Turno mattina"), "Turno mattina")

    def test_graph_payload_restores_certifica_presenza_from_local_marker(self):
        fields = _sp_fields_from_row(
            {
                "copia_nome": "Mario Rossi",
                "email_esterna": "mario@example.com",
                "tipo_assenza": "Certifica presenza",
                "motivazione_richiesta": "[CERTIFICA_PRESENZA] Turno mattina",
                "salta_approvazione": True,
                "consenso": "Approvato",
            }
        )

        self.assertEqual(fields["Tipoassenza"], "Certifica presenza")
        self.assertEqual(fields["Motivazionerichiesta"], "Turno mattina")

class SharePointSyncDiagnosticsTests(SimpleTestCase):
    @patch("assenze.views._graph_get_item")
    @patch("assenze.views._get_assenza")
    def test_diagnostic_flags_sharepoint_pending_conflict(self, mock_get_assenza, mock_graph_get_item):
        mock_get_assenza.return_value = {
            "id": 7,
            "sharepoint_item_id": "321",
            "copia_nome": "Mario Rossi",
            "data_inizio": None,
            "data_fine": None,
            "consenso": "Approvato",
            "moderation_status": 0,
        }
        mock_graph_get_item.return_value = {
            "id": "321",
            "fields": {
                "Consenso": "Approvato",
                "_ModerationStatus": "2",
            },
        }

        row = _diagnose_sharepoint_sync_item(7)

        self.assertIsNotNone(row)
        self.assertEqual(row["level"], "warn")
        self.assertEqual(row["sp_resolved_status"], "Approvato")
        self.assertIn("_ModerationStatus", row["diagnostic"])

    @patch("assenze.views._graph_get_item")
    @patch("assenze.views._get_assenza")
    def test_diagnostic_reports_aligned_status(self, mock_get_assenza, mock_graph_get_item):
        mock_get_assenza.return_value = {
            "id": 8,
            "sharepoint_item_id": "654",
            "copia_nome": "Luca Bova",
            "data_inizio": None,
            "data_fine": None,
            "consenso": "Rifiutato",
            "moderation_status": 1,
        }
        mock_graph_get_item.return_value = {
            "id": "654",
            "fields": {
                "Consenso": "Rifiutato",
                "_ModerationStatus": "1",
            },
        }

        row = _diagnose_sharepoint_sync_item(8)

        self.assertIsNotNone(row)
        self.assertEqual(row["level"], "ok")
        self.assertEqual(row["sp_resolved_status"], "Rifiutato")


class SharePointPendingReconcileTests(SimpleTestCase):
    @patch("assenze.views._update_assenza")
    @patch("assenze.views._graph_get_item")
    @patch("assenze.views._get_assenza")
    @patch("assenze.views._graph_configured", return_value=True)
    def test_reconcile_updates_pending_record_from_sharepoint(
        self,
        _mock_graph_configured,
        mock_get_assenza,
        mock_graph_get_item,
        mock_update_assenza,
    ):
        mock_get_assenza.return_value = {
            "id": 99,
            "sharepoint_item_id": "6272",
            "consenso": "In attesa",
            "moderation_status": 2,
        }
        mock_graph_get_item.return_value = {
            "id": "6272",
            "fields": {
                "Consenso": "Rifiutato",
                "_ModerationStatus": "2",
            },
        }
        mock_update_assenza.return_value = True

        result = _reconcile_pending_item_ids_with_sharepoint([99], force=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"], 1)
        mock_update_assenza.assert_called_once()


class CertificazionePresenzaDipendentiTests(SimpleTestCase):
    @patch("assenze.views._fetch_all_dict")
    @patch("assenze.views.legacy_table_columns")
    def test_employee_list_filters_to_active_when_attivo_column_exists(self, mock_columns, mock_fetch):
        mock_columns.return_value = {"nome", "cognome", "attivo"}
        mock_fetch.return_value = [
            {"cognome": "Marra", "nome": "Luca", "attivo": 1},
            {"cognome": "Romano", "nome": "Gianluca", "attivo": 1},
        ]

        names = _certificazione_presenza_dipendenti_attivi()

        self.assertEqual(names, ["Marra Luca", "Romano Gianluca"])
        sql = mock_fetch.call_args.args[0]
        self.assertIn("FROM anagrafica_dipendenti", sql)
        self.assertIn("attivo = 1", sql)

    @patch("assenze.views._fetch_all_dict")
    @patch("assenze.views.legacy_table_columns")
    def test_employee_list_deduplicates_case_insensitive_display_names(self, mock_columns, mock_fetch):
        mock_columns.return_value = {"nome", "cognome", "attivo"}
        mock_fetch.return_value = [
            {"cognome": "MARRA", "nome": "LUCA", "attivo": 1},
            {"cognome": "Marra", "nome": "Luca", "attivo": 1},
            {"cognome": "Romano", "nome": "Gianluca", "attivo": 1},
        ]

        names = _certificazione_presenza_dipendenti_attivi()

        self.assertEqual(names, ["MARRA LUCA", "Romano Gianluca"])


class AssenzeIdentityDisplayNameTests(SimpleTestCase):
    @patch("assenze.views._fetch_all_dict")
    @patch("assenze.views.legacy_table_columns")
    @patch("assenze.views._table_exists", return_value=True)
    def test_request_display_name_prefers_anagrafica_nome_cognome(self, _mock_table_exists, mock_columns, mock_fetch):
        mock_columns.return_value = {"id", "utente_id", "nome", "cognome", "email", "aliasusername"}
        mock_fetch.return_value = [{"id": 10, "nome": "Luca", "cognome": "Bova"}]

        result = _resolve_request_display_name(
            legacy_user_id=77,
            email="l.bova@example.local",
            username="l.bova",
            fallback_name="L Bova",
        )

        self.assertEqual(result, "Luca Bova")
        sql = mock_fetch.call_args.args[0]
        self.assertIn("FROM anagrafica_dipendenti", sql)
        self.assertIn("utente_id = %s", sql)

    @patch("assenze.views._fetch_all_dict")
    @patch("assenze.views.legacy_table_columns")
    @patch("assenze.views._table_exists", return_value=True)
    def test_request_display_name_matches_alias_from_username_local_part(self, _mock_table_exists, mock_columns, mock_fetch):
        mock_columns.return_value = {"id", "nome", "cognome", "email", "aliasusername"}
        mock_fetch.return_value = [{"id": 291, "nome": "Luca", "cognome": "Bova"}]

        result = _resolve_request_display_name(
            legacy_user_id=4,
            email="l.bova@example",
            username="l.bova@example",
            fallback_name="L Bova",
        )

        self.assertEqual(result, "Luca Bova")
        params = mock_fetch.call_args.args[1]
        self.assertIn("l.bova", params)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssenzeSubmitTokenTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-token-user", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())

    @patch("assenze.views._template_perm_context", return_value={})
    @patch("assenze.views._load_motivazioni_local", return_value=["Motivo"])
    @patch("assenze.views._graph_get_motivazioni", return_value=[])
    @patch("assenze.views._load_capi_options", return_value=[])
    @patch("assenze.views._resolve_default_capo_for_user", return_value="")
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_richiesta_renders_submit_token(
        self,
        _mock_perms,
        _mock_identity,
        _mock_default_capo,
        _mock_capi,
        _mock_graph_motivazioni,
        _mock_local_motivazioni,
        _mock_template_ctx,
    ):
        self.client.force_login(self.user)

        response = self.client.get(reverse("assenze_richiesta"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["submit_token"])
        self.assertContains(response, 'name="submit_token"')
        today = timezone.localdate().strftime("%Y-%m-%d")
        self.assertEqual(response.context["form_data"]["date_start"], today)
        self.assertEqual(response.context["form_data"]["date_end"], today)

    @patch("assenze.views._resolve_request_display_name", return_value="Luca Bova")
    @patch("assenze.views._template_perm_context", return_value={})
    @patch("assenze.views._load_motivazioni_local", return_value=["Motivo"])
    @patch("assenze.views._graph_get_motivazioni", return_value=[])
    @patch("assenze.views._load_capi_options", return_value=[])
    @patch("assenze.views._resolve_default_capo_for_user", return_value="")
    @patch("assenze.views._legacy_identity", return_value=("L Bova", "l.bova@example.com", 77))
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_richiesta_shows_full_name_in_dipendente_field(
        self,
        _mock_perms,
        _mock_identity,
        _mock_default_capo,
        _mock_capi,
        _mock_graph_motivazioni,
        _mock_local_motivazioni,
        _mock_template_ctx,
        _mock_display_name,
    ):
        self.client.force_login(self.user)

        response = self.client.get(reverse("assenze_richiesta"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Luca Bova"')

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("ok"))
    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._resolve_capo_local_id", return_value=None)
    @patch("assenze.views._resolve_capo_lookup_id", return_value=None)
    @patch("assenze.views._resolve_nome_lookup_id", return_value=77)
    @patch("assenze.views._validate_business_rules", return_value=(None, ""))
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_enforces_csrf_and_accepts_full_form_flow(
        self,
        _mock_perms,
        _mock_identity,
        _mock_table_exists,
        _mock_validate_rules,
        _mock_resolve_nome,
        _mock_resolve_capo,
        _mock_resolve_capo_local,
        mock_insert,
        _mock_graph_configured,
        _mock_render,
    ):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        get_response = csrf_client.get(reverse("assenze_richiesta"))
        self.assertEqual(get_response.status_code, 200)
        session = csrf_client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        submit_token = _build_submit_token(request, "assenze_invio")
        csrf_token = get_response.cookies["csrftoken"].value

        response_ok = csrf_client.post(
            reverse("assenze_invio"),
            {
                "submit_token": submit_token,
                "csrfmiddlewaretoken": csrf_token,
                "tipoassenza": "Permesso",
                "motivazione": "Motivo",
                "date_start": "2026-03-10",
                "date_end": "2026-03-10",
                "time_start": "08:00",
                "time_end": "12:00",
                "caporeparto": "",
            },
        )

        self.assertEqual(response_ok.status_code, 200)
        mock_insert.assert_called_once()

        response_missing_csrf = csrf_client.post(
            reverse("assenze_invio"),
            {
                "submit_token": submit_token,
                "tipoassenza": "Permesso",
                "motivazione": "Motivo",
                "date_start": "2026-03-10",
                "date_end": "2026-03-10",
                "time_start": "08:00",
                "time_end": "12:00",
                "caporeparto": "",
            },
        )
        self.assertEqual(response_missing_csrf.status_code, 403)

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("ok"))
    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._resolve_capo_local_id", return_value=None)
    @patch("assenze.views._resolve_capo_lookup_id", return_value=None)
    @patch("assenze.views._resolve_nome_lookup_id", return_value=77)
    @patch("assenze.views._validate_business_rules", return_value=(None, ""))
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._resolve_request_display_name", return_value="Mario Rossi")
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_saves_certificato_medico_only_for_malattia(
        self,
        _mock_perms,
        _mock_display_name,
        _mock_identity,
        _mock_table_exists,
        _mock_validate_rules,
        _mock_resolve_nome,
        _mock_resolve_capo_lookup,
        _mock_resolve_capo_local,
        mock_insert,
        _mock_graph_configured,
        _mock_render,
    ):
        self.client.force_login(self.user)
        session = self.client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        submit_token = _build_submit_token(request, "assenze_invio")

        response = self.client.post(
            reverse("assenze_invio"),
            {
                "submit_token": submit_token,
                "tipoassenza": "Malattia",
                "motivazione": "Influenza",
                "certificato_medico": "CERT-12345",
                "date_start": "2026-03-12",
                "date_end": "2026-03-12",
                "time_start": "08:00",
                "time_end": "17:00",
                "caporeparto": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = mock_insert.call_args.args[0]
        self.assertEqual(payload["tipo_assenza"], "Malattia")
        self.assertEqual(payload["certificato_medico"], "CERT-12345")

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("ok"))
    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._resolve_capo_local_id", return_value=None)
    @patch("assenze.views._resolve_capo_lookup_id", return_value=None)
    @patch("assenze.views._resolve_nome_lookup_id", return_value=77)
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._resolve_request_display_name", return_value="Mario Rossi")
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_ferie_forces_full_day_times(
        self,
        _mock_perms,
        _mock_display_name,
        _mock_identity,
        _mock_table_exists,
        _mock_resolve_nome,
        _mock_resolve_capo_lookup,
        _mock_resolve_capo_local,
        mock_insert,
        _mock_graph_configured,
        _mock_render,
    ):
        self.client.force_login(self.user)
        session = self.client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        submit_token = _build_submit_token(request, "assenze_invio")

        response = self.client.post(
            reverse("assenze_invio"),
            {
                "submit_token": submit_token,
                "tipoassenza": "Ferie",
                "motivazione": "Ferie",
                "date_start": "2026-03-12",
                "date_end": "2026-03-13",
                "time_start": "08:00",
                "time_end": "12:00",
                "caporeparto": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = mock_insert.call_args.args[0]
        self.assertEqual(payload["data_inizio"].strftime("%H:%M"), "00:00")
        self.assertEqual(payload["data_fine"].strftime("%H:%M"), "23:59")

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("error"))
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_rejects_permesso_across_multiple_days(
        self,
        _mock_perms,
        _mock_table_exists,
        mock_insert,
        mock_render,
    ):
        self.client.force_login(self.user)
        session = self.client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        submit_token = _build_submit_token(request, "assenze_invio")

        response = self.client.post(
            reverse("assenze_invio"),
            {
                "submit_token": submit_token,
                "tipoassenza": "Permesso",
                "motivazione": "Motivo",
                "date_start": "2026-03-12",
                "date_end": "2026-03-13",
                "time_start": "08:00",
                "time_end": "12:00",
                "caporeparto": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        mock_insert.assert_not_called()
        self.assertEqual(mock_render.call_args.kwargs["error"], "Il permesso deve iniziare e finire nello stesso giorno.")

    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_rejects_missing_submit_token(self, _mock_perms):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assenze_invio"),
            {
                "tipoassenza": "Permesso",
                "date_start": "2026-03-10",
                "date_end": "2026-03-10",
            },
        )

        self.assertEqual(response.status_code, 403)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssenzeLegacyTipoSubmitMappingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-submit-mapping-user", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())
        self.client.force_login(self.user)

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("ok"))
    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._resolve_capo_local_id", return_value=None)
    @patch("assenze.views._resolve_capo_lookup_id", return_value=None)
    @patch("assenze.views._resolve_nome_lookup_id", return_value=77)
    @patch("assenze.views._validate_business_rules", return_value=(None, ""))
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._resolve_request_display_name", return_value="Mario Rossi")
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_persists_flessibilita_as_canonical_value(
        self,
        _mock_perms,
        _mock_display_name,
        _mock_identity,
        _mock_table_exists,
        _mock_validate_rules,
        _mock_resolve_nome,
        _mock_resolve_capo_lookup,
        _mock_resolve_capo_local,
        mock_insert,
        _mock_graph_configured,
        _mock_render,
    ):
        session = self.client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        submit_token = _build_submit_token(request, "assenze_invio")

        response = self.client.post(
            reverse("assenze_invio"),
            {
                "submit_token": submit_token,
                "tipoassenza": "Flessibilita",
                "motivazione": "Recupero ore",
                "date_start": "2026-03-12",
                "date_end": "2026-03-12",
                "time_start": "08:00",
                "time_end": "17:00",
                "caporeparto": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = mock_insert.call_args.args[0]
        self.assertEqual(payload["tipo_assenza"], "Flessibilità")
        self.assertEqual(payload["motivazione_richiesta"], "Recupero ore")

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("ok"))
    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._resolve_capo_local_id", return_value=None)
    @patch("assenze.views._resolve_capo_lookup_id", return_value=None)
    @patch("assenze.views._resolve_nome_lookup_id", return_value=77)
    @patch("assenze.views._validate_business_rules", return_value=(None, ""))
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._resolve_request_display_name", return_value="Mario Rossi")
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_marks_certifica_presenza_without_violating_legacy_check(
        self,
        _mock_perms,
        _mock_display_name,
        _mock_identity,
        _mock_table_exists,
        _mock_validate_rules,
        _mock_resolve_nome,
        _mock_resolve_capo_lookup,
        _mock_resolve_capo_local,
        mock_insert,
        _mock_graph_configured,
        _mock_render,
    ):
        session = self.client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        submit_token = _build_submit_token(request, "assenze_invio")

        response = self.client.post(
            reverse("assenze_invio"),
            {
                "submit_token": submit_token,
                "tipoassenza": "Certifica presenza",
                "motivazione": "Turno mattina",
                "date_start": "2026-03-12",
                "date_end": "2026-03-12",
                "time_start": "06:00",
                "time_end": "14:00",
                "caporeparto": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = mock_insert.call_args.args[0]
        self.assertEqual(payload["tipo_assenza"], "Certifica presenza")
        self.assertEqual(payload["motivazione_richiesta"], "Turno mattina")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssenzeCaporepartoLocalSourceTests(TestCase):
    @patch("assenze.views._load_local_capi_options", return_value=[{"Value": "Legacy", "Email": "legacy@example.com", "LookupId": "legacy@example.com"}])
    @patch("assenze.views._load_anagrafica_hr_capi_options", return_value=[{"Value": "HR Capo", "Email": "hr@example.com", "LookupId": "legacy_user:77", "LegacyUserId": "77"}])
    def test_load_capi_options_prefers_anagrafica_hr(self, _mock_hr_options, _mock_local_options):
        options = _load_capi_options()

        self.assertEqual(options[0]["Email"], "hr@example.com")

    def test_load_capi_options_prefers_local_config(self):
        from core.models import OptioneConfig

        OptioneConfig.objects.create(tipo="caporeparto", valore="capo@example.com", ordine=10, is_active=True)

        options = _load_capi_options()

        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["LookupId"], "capo@example.com")

    def test_load_capi_options_exposes_linked_legacy_user_id(self):
        from core.models import OptioneConfig

        OptioneConfig.objects.create(
            tipo="caporeparto",
            valore="capo@example.com",
            legacy_user_id=77,
            ordine=10,
            is_active=True,
        )

        options = _load_capi_options()

        self.assertEqual(options[0]["LegacyUserId"], "77")

    @patch("assenze.views._resolve_anagrafica_hr_effective_capo_ids", return_value=(77, 501))
    def test_resolve_default_capo_uses_anagrafica_hr_effective_manager(self, _mock_effective_capo):
        capi = [
            {
                "Value": "Capo HR",
                "Email": "capo.hr@example.com",
                "LookupId": "legacy_user:77",
                "LegacyLookupId": "",
                "LegacyUserId": "77",
                "AnagraficaLegacyId": "501",
            }
        ]

        resolved = _resolve_default_capo_for_user(
            name="Mario Rossi",
            email="mario@example.com",
            username="m.rossi",
            capi=capi,
            legacy_user_id=12,
        )

        self.assertEqual(resolved, "capo.hr@example.com")

    @patch("assenze.views._load_anagrafica_hr_capi_options")
    def test_resolve_capo_local_id_from_anagrafica_hr_options(self, mock_hr_options):
        mock_hr_options.return_value = [
            {
                "Value": "Capo HR",
                "Email": "capo.hr@example.com",
                "LookupId": "legacy_user:77",
                "LegacyLookupId": "",
                "LegacyUserId": "77",
                "AnagraficaLegacyId": "501",
            }
        ]

        self.assertEqual(_resolve_capo_local_id_from_anagrafica_hr("capo.hr@example.com"), 77)
        self.assertEqual(_resolve_capo_local_id_from_anagrafica_hr("501"), 77)

    @patch("assenze.views._legacy_capi_table_exists", return_value=False)
    def test_owned_capo_ids_include_current_legacy_user_even_without_legacy_table(self, _mock_legacy_exists):
        local_ids, lookup_ids = _owned_capo_ids_for_legacy_user(77)

        self.assertEqual(local_ids, {77})
        self.assertEqual(lookup_ids, set())

    @patch("assenze.views._find_local_capo_id_by_column")
    @patch("assenze.views._resolve_local_capo_legacy_user")
    @patch("assenze.views.legacy_table_columns")
    @patch("assenze.views._legacy_capi_table_exists", return_value=True)
    def test_resolve_capo_local_id_uses_capi_reparto_row_linked_to_legacy_user(
        self,
        _mock_table_exists,
        mock_columns,
        mock_resolve_legacy_user,
        mock_find_local_capo,
    ):
        mock_columns.return_value = {"id", "utente_id", "indirizzo_email", "title", "sharepoint_item_id"}
        mock_resolve_legacy_user.return_value = SimpleNamespace(id=77)

        def _fake_find(column_name, value):
            if column_name == "utente_id" and value == 77:
                return 12
            return None

        mock_find_local_capo.side_effect = _fake_find

        resolved = _resolve_capo_local_id("capo@example.com")

        self.assertEqual(resolved, 12)
        self.assertEqual(mock_find_local_capo.call_args_list[0].args, ("utente_id", 77))

    @patch("assenze.views._find_local_capo_id_by_column")
    @patch("assenze.views._resolve_local_capo_legacy_user", return_value=None)
    @patch("assenze.views.legacy_table_columns")
    @patch("assenze.views._legacy_capi_table_exists", return_value=True)
    def test_resolve_capo_local_id_falls_back_to_sharepoint_lookup_id(
        self,
        _mock_table_exists,
        mock_columns,
        _mock_resolve_legacy_user,
        mock_find_local_capo,
    ):
        mock_columns.return_value = {"id", "sharepoint_item_id"}

        def _fake_find(column_name, value):
            if column_name == "sharepoint_item_id" and value == 456:
                return 34
            return None

        mock_find_local_capo.side_effect = _fake_find

        resolved = _resolve_capo_local_id("456")

        self.assertEqual(resolved, 34)
        self.assertEqual(mock_find_local_capo.call_args_list[0].args, ("sharepoint_item_id", 456))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GestioneAssenzeDeleteUrlTests(TestCase):
    def setUp(self):
        # Superuser per bypassare ACLMiddleware: questi test verificano il
        # rendering della pagina/URL, non il gating ACL (pilotato via mock).
        self.user = get_user_model().objects.create_superuser(
            username="assenze-gestione-user", email="assenze-gestione@example.com", password="pass12345"
        )

    @patch("assenze.views._template_perm_context", return_value={})
    @patch("assenze.views._load_personal")
    @patch("assenze.views._reconcile_pending_item_ids_with_sharepoint", return_value={"updated": 0})
    @patch("assenze.views._load_pending_for_manager", return_value=[])
    @patch("assenze.views._sync_on_page_load_enabled", return_value=False)
    @patch("assenze.views._legacy_identity", return_value=("Luca Bova", "luca@example.com", 77))
    def test_gestione_renders_row_specific_delete_url(
        self,
        _mock_identity,
        _mock_sync_enabled,
        _mock_pending,
        _mock_reconcile,
        mock_load_personal,
        _mock_template_ctx,
    ):
        mock_load_personal.return_value = [
            {
                "id": 42,
                "tipo": "Flessibilita",
                "tipo_raw": "Flessibilita",
                "inizio": "11/03/2026 08:00",
                "fine": "11/03/2026 17:00",
                "inizio_iso": "2026-03-11T08:00:00Z",
                "fine_iso": "2026-03-11T17:00:00Z",
                "motivazione": "",
                "stato": "In attesa",
                "note_gestione": "",
            }
        ]
        self.client.force_login(self.user)

        response = self.client.get(reverse("assenze_gestione"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-delete-url="/assenze/api/eventi/42/delete"')

    @patch("assenze.views._template_perm_context", return_value={})
    @patch("assenze.views._load_personal")
    @patch("assenze.views._reconcile_pending_item_ids_with_sharepoint", return_value={"updated": 0})
    @patch("assenze.views._load_pending_for_manager")
    @patch("assenze.views._sync_on_page_load_enabled", return_value=False)
    @patch("assenze.views._legacy_identity", return_value=("Luca Bova", "luca@example.com", 77))
    def test_gestione_exposes_summary_context(
        self,
        _mock_identity,
        _mock_sync_enabled,
        mock_pending,
        _mock_reconcile,
        mock_load_personal,
        _mock_template_ctx,
    ):
        mock_load_personal.return_value = [
            {"id": 1, "stato": "In attesa", "certificato_medico": ""},
            {"id": 2, "stato": "Approvato", "certificato_medico": "CERT-1"},
            {"id": 3, "stato": "Rifiutato", "certificato_medico": ""},
        ]
        mock_pending.return_value = [
            {"id": 10, "tipo": "Ferie", "certificato_medico": ""},
            {"id": 11, "tipo": "Permesso", "certificato_medico": "CERT-2"},
        ]
        self.client.force_login(self.user)

        response = self.client.get(reverse("assenze_gestione"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["summary_personali"],
            {
                "total": 3,
                "approved": 1,
                "waiting": 1,
                "rejected": 1,
                "editable": 1,
                "medical": 1,
            },
        )
        self.assertEqual(
            response.context["summary_da_approvare"],
            {
                "total": 2,
                "medical": 1,
                "ferie": 1,
                "permesso": 1,
                "other": 0,
            },
        )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GestioneAssenzeDeleteApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-delete-user", password="pass12345")

    def _superuser(self, username: str):
        # I superuser bypassano ACLMiddleware: serve per i test che colpiscono
        # la view protetta `api_evento_delete` pilotando i permessi via mock.
        return get_user_model().objects.create_superuser(
            username=username, email=f"{username}@example.com", password="pass12345"
        )

    @patch("assenze.views._delete_assenza", return_value=True)
    @patch("assenze.views._graph_delete", return_value=(True, ""))
    @patch("assenze.views._graph_configured", return_value=True)
    @patch("assenze.views._legacy_identity", return_value=("Luca Bova", "luca@example.com", 77))
    @patch("assenze.views._get_assenza")
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_delete_any": False})
    def test_delete_allows_local_cleanup_when_sharepoint_item_is_already_missing(
        self,
        _mock_perms,
        mock_get_assenza,
        _mock_identity,
        _mock_graph_configured,
        mock_graph_delete,
        mock_delete_assenza,
    ):
        mock_get_assenza.return_value = {
            "id": 42,
            "sharepoint_item_id": "4018",
            "copia_nome": "Luca Bova",
            "email_esterna": "luca@example.com",
        }
        self.client.force_login(self._superuser("su-delete-cleanup"))

        response = self.client.post(
            reverse("assenze_api_evento_delete", args=[42]),
            content_type="application/json",
            data="{}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "item_id": 42})
        mock_graph_delete.assert_called_once_with("4018")
        mock_delete_assenza.assert_called_once_with(42)

    @patch("assenze.views._notify_assenza_deleted")
    @patch("assenze.views._delete_assenza", return_value=True)
    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._legacy_identity", return_value=("Luca Bova", "luca@example.com", 77))
    @patch("assenze.views._get_assenza")
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_delete_any": True})
    def test_delete_approved_request_triggers_notification(
        self,
        _mock_perms,
        mock_get_assenza,
        _mock_identity,
        _mock_graph_configured,
        _mock_delete_assenza,
        mock_notify,
    ):
        # moderation_status == 0 => richiesta approvata => notifica.
        mock_get_assenza.return_value = {
            "id": 7,
            "sharepoint_item_id": "",
            "copia_nome": "Luca Bova",
            "email_esterna": "luca@example.com",
            "moderation_status": 0,
        }
        self.client.force_login(self._superuser("su-delete-notify"))

        response = self.client.post(
            reverse("assenze_api_evento_delete", args=[7]),
            content_type="application/json",
            data="{}",
        )

        self.assertEqual(response.status_code, 200)
        mock_notify.assert_called_once()
        # Il record passato alla notifica e' quello eliminato.
        self.assertEqual(mock_notify.call_args.args[1].get("id"), 7)

    @patch("assenze.views._notify_assenza_deleted")
    @patch("assenze.views._delete_assenza", return_value=True)
    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._legacy_identity", return_value=("Luca Bova", "luca@example.com", 77))
    @patch("assenze.views._get_assenza")
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_delete_any": True})
    def test_delete_pending_request_does_not_notify(
        self,
        _mock_perms,
        mock_get_assenza,
        _mock_identity,
        _mock_graph_configured,
        _mock_delete_assenza,
        mock_notify,
    ):
        # moderation_status == 2 (in attesa) => nessuna notifica.
        mock_get_assenza.return_value = {
            "id": 8,
            "sharepoint_item_id": "",
            "copia_nome": "Luca Bova",
            "email_esterna": "luca@example.com",
            "moderation_status": 2,
        }
        self.client.force_login(self._superuser("su-delete-pending"))

        response = self.client.post(
            reverse("assenze_api_evento_delete", args=[8]),
            content_type="application/json",
            data="{}",
        )

        self.assertEqual(response.status_code, 200)
        mock_notify.assert_not_called()

    @patch("assenze.views._delete_assenza", return_value=True)
    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._legacy_identity", return_value=("Luca Bova", "luca@example.com", 77))
    @patch("assenze.views._get_assenza")
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_delete_any": True})
    def test_delete_succeeds_even_if_notification_raises(
        self,
        _mock_perms,
        mock_get_assenza,
        _mock_identity,
        _mock_graph_configured,
        _mock_delete_assenza,
    ):
        # La notifica e' fail-open: un suo errore non deve ribaltare la delete.
        mock_get_assenza.return_value = {
            "id": 9,
            "sharepoint_item_id": "",
            "copia_nome": "Luca Bova",
            "email_esterna": "luca@example.com",
            "moderation_status": 0,
        }
        self.client.force_login(self._superuser("su-delete-failopen"))

        with patch("assenze.views._notify_assenza_deleted", side_effect=RuntimeError("boom")):
            response = self.client.post(
                reverse("assenze_api_evento_delete", args=[9]),
                content_type="application/json",
                data="{}",
            )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "item_id": 9})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssenzeCarConsensoTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="assenze-car-user",
            email="assenze-car@example.com",
            password="pass12345",
        )
        self.client.force_login(self.user)

    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._has_assenze_column", return_value=True)
    @patch("assenze.views._update_assenza", return_value=True)
    @patch("assenze.views._get_assenza")
    @patch("assenze.views._assenze_permissions", return_value={"can_update_any": True, "can_update_owned": False})
    def test_car_approval_stores_approval_datetime(
        self,
        _mock_perms,
        mock_get_assenza,
        mock_update,
        _mock_has_column,
        _mock_graph_configured,
    ):
        mock_get_assenza.return_value = {
            "id": 42,
            "email_esterna": "",
            "consenso": "In attesa",
            "moderation_status": 2,
        }

        before = timezone.now()
        response = self.client.post(
            reverse("assenze_api_car_consenso", args=[42]),
            content_type="application/json",
            data='{"consenso":"Approvato"}',
        )
        after = timezone.now()

        self.assertEqual(response.status_code, 200)
        updates = mock_update.call_args.args[1]
        self.assertEqual(updates["consenso"], "Approvato")
        self.assertEqual(updates["moderation_status"], 0)
        self.assertIn("approvazione_datetime", updates)
        self.assertGreaterEqual(updates["approvazione_datetime"], before)
        self.assertLessEqual(updates["approvazione_datetime"], after)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MiaAssenzaUpdateTests(TestCase):
    def setUp(self):
        # Superuser per bypassare ACLMiddleware; i permessi applicativi e
        # l'identita' sono pilotati via mock nei singoli test.
        self.user = get_user_model().objects.create_superuser(
            username="assenze-update-user", email="assenze-update@example.com", password="pass12345"
        )

    @patch("assenze.views._graph_configured", return_value=False)
    @patch("assenze.views._update_assenza", return_value=True)
    @patch("assenze.views._validate_business_rules", return_value=(None, ""))
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._get_assenza")
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True})
    def test_my_update_saves_certificato_medico_for_malattia(
        self,
        _mock_perms,
        mock_get_assenza,
        _mock_identity,
        _mock_validate,
        mock_update,
        _mock_graph_configured,
    ):
        mock_get_assenza.return_value = {
            "id": 42,
            "copia_nome": "Mario Rossi",
            "email_esterna": "mario@example.com",
            "tipo_assenza": "Malattia",
            "data_inizio": None,
            "data_fine": None,
            "motivazione_richiesta": "",
            "certificato_medico": "",
            "consenso": "In attesa",
            "moderation_status": 2,
        }
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assenze_api_mia_update", args=[42]),
            content_type="application/json",
            data='{"tipo":"Malattia","inizio":"2026-03-12T08:00:00.000Z","fine":"2026-03-12T17:00:00.000Z","motivazione":"Influenza","certificato_medico":"CERT-777"}',
        )

        self.assertEqual(response.status_code, 200)
        updates = mock_update.call_args.args[1]
        self.assertEqual(updates["tipo_assenza"], "Malattia")
        self.assertEqual(updates["certificato_medico"], "CERT-777")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssenzeCsvExportAuditTests(TestCase):
    def setUp(self):
        super().setUp()
        # Superuser per bypassare ACLMiddleware; scope/permessi CAR pilotati via mock.
        self.user = get_user_model().objects.create_superuser(
            username="assenze-export-user",
            email="assenze-export@example.com",
            password="pass12345",
        )
        self.client.force_login(self.user)

    @patch("assenze.views.log_action")
    @patch("assenze.views._load_gestite_for_manager", return_value=[])
    @patch(
        "assenze.views._load_pending_for_manager",
        return_value=[
            {
                "dipendente": "Mario Rossi",
                "tipo": "Permesso",
                "inizio_label": "10/03/2026 08:00",
                "fine_label": "10/03/2026 12:00",
                "consenso": "In attesa",
                "certificato_medico": "",
                "note_gestione": "",
            }
        ],
    )
    @patch("assenze.views._assenze_permissions", return_value={"can_update_owned": True, "can_update_any": False})
    @patch("assenze.views.get_legacy_user", return_value=SimpleNamespace(id=77, nome="Mario CAR", email="car@example.com"))
    def test_car_export_logs_audit_with_rows_and_filters(
        self,
        _mock_legacy_user,
        _mock_perms,
        _mock_pending,
        _mock_gestite,
        mock_log_action,
    ):
        response = self.client.get(reverse("assenze_car_export_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_log_action.call_count, 1)
        action_args = mock_log_action.call_args.args
        self.assertEqual(action_args[1], "export_csv")
        self.assertEqual(action_args[2], "assenze")
        self.assertEqual(action_args[3]["rows"], 1)
        self.assertEqual(action_args[3]["filters"]["scope"], "owned_manager")
        self.assertEqual(action_args[3]["filters"]["legacy_user_id"], 77)

    @patch("assenze.views.log_action")
    @patch(
        "assenze.views._load_personal",
        return_value=[
            {
                "tipo": "Permesso",
                "inizio": "10/03/2026 08:00",
                "fine": "10/03/2026 12:00",
                "stato": "In attesa",
                "motivazione": "Motivo",
                "certificato_medico": "",
                "note_gestione": "",
            }
        ],
    )
    @patch("assenze.views.get_legacy_user", return_value=SimpleNamespace(nome="Mario Rossi", email="mario@example.com"))
    def test_personal_export_logs_audit_with_rows_and_filters(
        self,
        _mock_legacy_user,
        _mock_load_personal,
        mock_log_action,
    ):
        response = self.client.get(reverse("assenze_export_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_log_action.call_count, 1)
        action_args = mock_log_action.call_args.args
        self.assertEqual(action_args[1], "export_csv")
        self.assertEqual(action_args[2], "assenze")
        self.assertEqual(action_args[3]["rows"], 1)
        self.assertEqual(action_args[3]["filters"]["scope"], "personal")
        self.assertEqual(action_args[3]["filters"]["email"], "mario@example.com")


class AssenzeAllineaTipoFlessibilitaCommandTests(SimpleTestCase):
    @patch("assenze.management.commands.allinea_tipo_assenza_flessibilita.connections")
    def test_dry_run_reports_counts_without_altering_constraint(self, mock_connections):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [("dbo",), (4,), (1,), (2,)]
        cursor_manager = MagicMock()
        cursor_manager.__enter__.return_value = cursor
        connection = MagicMock()
        connection.vendor = "microsoft"
        connection.cursor.return_value = cursor_manager
        mock_connections.__getitem__.return_value = connection

        stdout = StringIO()
        call_command("allinea_tipo_assenza_flessibilita", "--dry-run", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("record 'Infortunio': 4", output)
        self.assertIn("Dry-run: nessuna modifica applicata", output)
        executed_sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertNotIn("DROP CONSTRAINT", executed_sql)
        self.assertEqual(cursor.execute.call_count, 4)

    @patch("assenze.management.commands.allinea_tipo_assenza_flessibilita.connections")
    def test_command_rebuilds_check_constraint_with_flessibilita(self, mock_connections):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [("dbo",), (2,), (0,), (3,)]
        cursor_manager = MagicMock()
        cursor_manager.__enter__.return_value = cursor
        connection = MagicMock()
        connection.vendor = "microsoft"
        connection.cursor.return_value = cursor_manager
        mock_connections.__getitem__.return_value = connection

        stdout = StringIO()
        call_command("allinea_tipo_assenza_flessibilita", stdout=stdout)

        executed_sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn("DROP CONSTRAINT [CK_assenze_tipo]", executed_sql)
        self.assertIn("SET [tipo_assenza] = N'Flessibilità'", executed_sql)
        self.assertIn("WHERE [tipo_assenza] = N'Infortunio'", executed_sql)
        self.assertIn("([tipo_assenza]=N'Flessibilità')", executed_sql)
        self.assertIn("SET [tipo_assenza] = N'Certifica presenza'", executed_sql)
        self.assertIn("WHERE [tipo_assenza] = N'Altro'", executed_sql)
        self.assertIn("([tipo_assenza]=N'Certifica presenza')", executed_sql)
        self.assertNotIn("([tipo_assenza]=N'Infortunio')", executed_sql)
        self.assertIn("riallineato", stdout.getvalue())


class AssenzeInsertForOthersScopeTests(TestCase):
    """Scope reparto per l'inserimento richieste 'per conto di' (CAR)."""

    def _make_aziendale(self, *, anagrafica_id, capo_anagrafica_id=None, area=""):
        from anagrafica.models import DipendenteAnagraficaAziendale

        return DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=anagrafica_id,
            caporeparto_legacy_id=capo_anagrafica_id,
            area=area,
        )

    def test_includes_employees_with_matching_caporeparto(self):
        capo_id = 100
        self._make_aziendale(anagrafica_id=11, capo_anagrafica_id=capo_id)
        self._make_aziendale(anagrafica_id=12, capo_anagrafica_id=capo_id)
        self._make_aziendale(anagrafica_id=13, capo_anagrafica_id=999)  # altro reparto

        ids = _anagrafica_employee_ids_for_capo(capo_id)

        self.assertEqual(ids, {11, 12})

    def test_includes_employees_via_reparto_area_fallback(self):
        from anagrafica.models import Reparto

        capo_id = 200
        Reparto.objects.create(nome="Verniciatura", caporeparto_legacy_id=capo_id, is_active=True)
        # Dipendente senza capo diretto ma nell'area gestita dal capo.
        self._make_aziendale(anagrafica_id=21, area="Verniciatura")
        # Dipendente in area diversa: escluso.
        self._make_aziendale(anagrafica_id=22, area="Magazzino")

        ids = _anagrafica_employee_ids_for_capo(capo_id)

        self.assertIn(21, ids)
        self.assertNotIn(22, ids)

    def test_returns_empty_when_no_capo_id(self):
        self.assertEqual(_anagrafica_employee_ids_for_capo(None), set())


class RiconciliazionePresenzeLogicTests(SimpleTestCase):
    """RA1 — logica pura di matching presenza ↔ assenza (senza DB)."""

    def _presenza(self, **kw):
        base = dict(
            id=1, nome_dipendente="Mario Rossi", data=date(2026, 6, 10),
            ore_totali=8.0, assenza_id=None,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def _assenza(self, **kw):
        base = dict(
            id=100, copia_nome="Mario Rossi", data_inizio=date(2026, 6, 8),
            data_fine=date(2026, 6, 12), tipo_assenza="ferie",
        )
        base.update(kw)
        return base

    def test_presenza_in_ferie_e_conflitto(self):
        from assenze.riconciliazione import trova_conflitti
        c = trova_conflitti([self._presenza()], [self._assenza()])
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].tipo_assenza, "ferie")
        self.assertEqual(c[0].presenza_id, 1)
        self.assertEqual(c[0].assenza_id, 100)

    def test_permesso_non_e_conflitto(self):
        from assenze.riconciliazione import trova_conflitti
        c = trova_conflitti([self._presenza()], [self._assenza(tipo_assenza="permesso")])
        self.assertEqual(c, [])

    def test_link_assenza_id_sopprime_conflitto(self):
        from assenze.riconciliazione import trova_conflitti
        c = trova_conflitti([self._presenza(assenza_id=100)], [self._assenza(id=100)])
        self.assertEqual(c, [])

    def test_presenza_fuori_range_nessun_conflitto(self):
        from assenze.riconciliazione import trova_conflitti
        c = trova_conflitti([self._presenza(data=date(2026, 7, 1))], [self._assenza()])
        self.assertEqual(c, [])

    def test_nome_diverso_nessun_conflitto(self):
        from assenze.riconciliazione import trova_conflitti
        c = trova_conflitti([self._presenza(nome_dipendente="Luigi Verdi")], [self._assenza()])
        self.assertEqual(c, [])

    def test_malattia_match_normalizzato(self):
        from assenze.riconciliazione import trova_conflitti
        c = trova_conflitti(
            [self._presenza(nome_dipendente="  mario   rossi ")],
            [self._assenza(tipo_assenza="MALATTIA")],
        )
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].tipo_label, "Malattia")

    def test_parse_periodo_swap_e_default(self):
        from assenze.riconciliazione import parse_periodo
        da, a = parse_periodo(
            "2026-06-30", "2026-06-01",
            default_da=date(2026, 1, 1), default_a=date(2026, 12, 31),
        )
        self.assertEqual((da, a), (date(2026, 6, 1), date(2026, 6, 30)))
        da2, a2 = parse_periodo(
            "", None, default_da=date(2026, 1, 1), default_a=date(2026, 12, 31),
        )
        self.assertEqual((da2, a2), (date(2026, 1, 1), date(2026, 12, 31)))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RiconciliazioneViewTests(TestCase):
    """RA1 — gating e rendering della vista riconciliazione."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="ric-admin", email="ric-admin@example.com", password="pwd12345",
        )
        UserOnboarding.objects.create(user=self.admin, completed=True, completed_at=timezone.now())
        self.basic = User.objects.create_user(
            username="ric-basic", email="ric-basic@example.com", password="pwd12345",
        )
        UserOnboarding.objects.create(user=self.basic, completed=True, completed_at=timezone.now())

    def test_basic_user_forbidden(self):
        self.client.force_login(self.basic)
        response = self.client.get(reverse("assenze_riconciliazione"))
        self.assertEqual(response.status_code, 403)

    def test_admin_page_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assenze_riconciliazione"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Riconciliazione presenze")

    def test_csv_export(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assenze_riconciliazione"), {"export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("Dipendente", response.content.decode("utf-8-sig"))


class AssenzeCaporepartoEscalationTests(TestCase):
    """Fase 3: caporeparto autoritativo + escalation al superiore se assente."""

    def _capi(self):
        return [
            {"Value": "Capo A", "Email": "capoa@example.com", "LookupId": "legacy_user:77",
             "LegacyUserId": "77", "AnagraficaLegacyId": "501"},
            {"Value": "Super B", "Email": "superb@example.com", "LookupId": "legacy_user:88",
             "LegacyUserId": "88", "AnagraficaLegacyId": "999"},
        ]

    def test_superior_capo_option_resolves_capo_of_capo(self):
        from anagrafica.models import DipendenteAnagraficaAziendale
        from assenze.views import _superior_capo_option

        # Il caporeparto (anagrafica 501) ha come proprio caporeparto l'anagrafica 999.
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=501, caporeparto_legacy_id=999)
        self.assertEqual(_superior_capo_option(501, self._capi()), "superb@example.com")

    @patch("assenze.views._resolve_default_capo_for_user", return_value="capoa@example.com")
    @patch("assenze.views._capo_absent_on", return_value=False)
    def test_no_escalation_when_capo_present(self, _mock_absent, _mock_base):
        from datetime import date
        from assenze.views import _effective_capo_option

        opt, escalated = _effective_capo_option(
            name="X", email="x@e.com", username="x", legacy_user_id=1,
            capi=self._capi(), request_day=date(2026, 7, 15),
        )
        self.assertEqual(opt, "capoa@example.com")
        self.assertFalse(escalated)

    @patch("assenze.views._resolve_default_capo_for_user", return_value="capoa@example.com")
    @patch("assenze.views._capo_absent_on", return_value=True)
    def test_escalates_to_superior_when_capo_absent(self, _mock_absent, _mock_base):
        from datetime import date
        from anagrafica.models import DipendenteAnagraficaAziendale
        from assenze.views import _effective_capo_option

        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=501, caporeparto_legacy_id=999)
        opt, escalated = _effective_capo_option(
            name="X", email="x@e.com", username="x", legacy_user_id=1,
            capi=self._capi(), request_day=date(2026, 7, 15),
        )
        self.assertEqual(opt, "superb@example.com")
        self.assertTrue(escalated)

    @patch("assenze.views._resolve_default_capo_for_user", return_value="capoa@example.com")
    @patch("assenze.views._capo_absent_on", return_value=True)
    def test_fallback_no_escalation_when_superior_missing(self, _mock_absent, _mock_base):
        from datetime import date
        from assenze.views import _effective_capo_option

        # Nessun DipendenteAnagraficaAziendale per il capo → superiore non risolvibile
        # → fail-safe: resta il caporeparto assegnato, nessuna escalation.
        opt, escalated = _effective_capo_option(
            name="X", email="x@e.com", username="x", legacy_user_id=1,
            capi=self._capi(), request_day=date(2026, 7, 15),
        )
        self.assertEqual(opt, "capoa@example.com")
        self.assertFalse(escalated)


class AssenzeRegoleDurataTests(SimpleTestCase):
    def _dt(self, s):
        return datetime.strptime(s, "%Y-%m-%d %H:%M")

    # --- Permesso: 30min-8h, stesso giorno -------------------------------
    def test_permesso_oltre_8h_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 08:00"),
            dt_end=self._dt("2026-03-10 17:00"),  # 9h
        )
        self.assertTrue(err)
        self.assertIn("8 ore", err)

    def test_permesso_sotto_30min_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 08:00"),
            dt_end=self._dt("2026-03-10 08:20"),  # 20min
        )
        self.assertTrue(err)

    def test_permesso_4h_ok(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 08:00"),
            dt_end=self._dt("2026-03-10 12:00"),
        )
        self.assertEqual(err, "")

    def test_permesso_multi_giorno_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 08:00"),
            dt_end=self._dt("2026-03-11 09:00"),
        )
        self.assertTrue(err)

    # --- Ferie: piu di 1 giorno -----------------------------------------
    def test_ferie_un_giorno_respinta(self):
        err, _ = _validate_business_rules(
            tipo="Ferie",
            dt_start=self._dt("2026-03-12 00:00"),
            dt_end=self._dt("2026-03-12 23:59"),
        )
        self.assertTrue(err)
        self.assertIn("un giorno", err)

    def test_ferie_due_giorni_ok(self):
        err, _ = _validate_business_rules(
            tipo="Ferie",
            dt_start=self._dt("2026-03-12 00:00"),
            dt_end=self._dt("2026-03-13 23:59"),
        )
        self.assertEqual(err, "")

    # --- Durata rapida: solo la data ------------------------------------
    def test_durata_rapida_orario_alterato_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 06:00"),
            dt_end=self._dt("2026-03-10 15:00"),  # preset mattina = 06:00-14:00
            shortcut="mattina",
        )
        self.assertTrue(err)
        self.assertIn("solo la data", err)

    def test_durata_rapida_solo_data_ok(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 06:00"),
            dt_end=self._dt("2026-03-10 14:00"),  # combacia col preset mattina (8h)
            shortcut="mattina",
        )
        self.assertEqual(err, "")

    def test_durata_rapida_multi_giorno_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 06:00"),
            dt_end=self._dt("2026-03-11 14:00"),
            shortcut="mattina",
        )
        self.assertTrue(err)

    def test_custom_permesso_orario_libero_ok(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 09:15"),
            dt_end=self._dt("2026-03-10 13:45"),  # 4h30
            shortcut="custom",
        )
        self.assertEqual(err, "")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssenzeInvioRegoleDurataTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-regole-user", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())

    def _token(self):
        session = self.client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        return _build_submit_token(request, "assenze_invio")

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("error"))
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_durata_rapida_orario_manomesso_respinto(
        self, _mock_perms, _mock_table_exists, mock_insert, mock_render,
    ):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("assenze_invio"), {
            "submit_token": self._token(),
            "tipoassenza": "Permesso",
            "motivazione": "Motivo",
            "shortcut": "mattina",          # preset 06:00-14:00
            "date_start": "2026-03-10",
            "date_end": "2026-03-10",
            "time_start": "06:00",
            "time_end": "15:00",            # orario alterato
            "caporeparto": "",
        })
        self.assertEqual(resp.status_code, 200)
        mock_insert.assert_not_called()
        self.assertIn("solo la data", mock_render.call_args.kwargs["error"])

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("error"))
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_permesso_oltre_8h_respinto(
        self, _mock_perms, _mock_table_exists, mock_insert, mock_render,
    ):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("assenze_invio"), {
            "submit_token": self._token(),
            "tipoassenza": "Permesso",
            "motivazione": "Motivo",
            "shortcut": "custom",
            "date_start": "2026-03-10",
            "date_end": "2026-03-10",
            "time_start": "08:00",
            "time_end": "17:00",            # 9h
            "caporeparto": "",
        })
        self.assertEqual(resp.status_code, 200)
        mock_insert.assert_not_called()
        self.assertIn("8 ore", mock_render.call_args.kwargs["error"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssenzeRichiestaShortcutRenderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-ui-user", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())

    @patch("assenze.views._template_perm_context", return_value={})
    @patch("assenze.views._load_motivazioni_local", return_value=["Motivo"])
    @patch("assenze.views._graph_get_motivazioni", return_value=[])
    @patch("assenze.views._load_capi_options", return_value=[])
    @patch("assenze.views._resolve_default_capo_for_user", return_value="")
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_form_espone_shortcut_e_campi_orario(self, *_mocks):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assenze_richiesta"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="shortcut"')
        self.assertContains(resp, 'id="time_start"')
        self.assertContains(resp, 'id="time_end"')
