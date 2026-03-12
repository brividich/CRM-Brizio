from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .views import (
    _build_submit_token,
    _certificazione_presenza_dipendenti_attivi,
    _diagnose_sharepoint_sync_item,
    _fetch_first_row_from_cursor,
    _find_inserted_assenza_id,
    _graph_delete,
    _insert_assenza,
    _insert_row_and_return_id,
    _load_capi_options,
    _norm_tipo,
    _owned_capo_ids_for_legacy_user,
    _reconcile_pending_item_ids_with_sharepoint,
    _resolve_request_display_name,
    _sp_item_to_local,
    _tipo_for_storage,
)


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

        with patch("assenze.views._db_vendor", return_value="microsoft"), patch(
            "assenze.views.connections",
            {"default": MagicMock()},
        ):
            result = _insert_row_and_return_id(cursor, "assenze", ["title", "consenso"], ["Richiesta", "In attesa"])

        self.assertEqual(result, 51)
        first_sql, first_params = cursor.execute.call_args_list[0].args
        self.assertIn("INSERT INTO assenze (title, consenso)", first_sql)
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
        self.assertIn("sharepoint_item_id IS NULL", sql)
        self.assertIn("copia_nome = %s", sql)
        self.assertEqual(params, ["Mario Rossi", "mario@example.com", "Permesso", 2])


class AssenzeTipoMappingTests(SimpleTestCase):
    def test_storage_keeps_flessibilita_as_canonical_value(self):
        self.assertEqual(_tipo_for_storage("Flessibilità"), "Flessibilità")

    def test_legacy_infortunio_is_still_rendered_as_flessibilita(self):
        self.assertEqual(_norm_tipo("Infortunio"), "Flessibilità")


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
    def test_invio_accepts_valid_submit_token_without_csrf_cookie(
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
                "date_start": "2026-03-10",
                "date_end": "2026-03-10",
                "time_start": "08:00",
                "time_end": "12:00",
                "caporeparto": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        mock_insert.assert_called_once()

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
class AssenzeCaporepartoLocalSourceTests(TestCase):
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

    @patch("assenze.views._legacy_capi_table_exists", return_value=False)
    def test_owned_capo_ids_include_current_legacy_user_even_without_legacy_table(self, _mock_legacy_exists):
        local_ids, lookup_ids = _owned_capo_ids_for_legacy_user(77)

        self.assertEqual(local_ids, {77})
        self.assertEqual(lookup_ids, set())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GestioneAssenzeDeleteUrlTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-gestione-user", password="pass12345")

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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GestioneAssenzeDeleteApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-delete-user", password="pass12345")

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
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assenze_api_evento_delete", args=[42]),
            content_type="application/json",
            data="{}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "item_id": 42})
        mock_graph_delete.assert_called_once_with("4018")
        mock_delete_assenza.assert_called_once_with(42)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MiaAssenzaUpdateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-update-user", password="pass12345")

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
