import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from anomalie import views as anomalie_views
from anomalie.models import (
    AnomalieAccessLevel,
    AnomalieLegacyRoleAccessRule,
    AnomalieRoleAccessRule,
    AnomalieRoleType,
    AnomalieUserAccessRule,
)
from anagrafica.models import RuoloOperativo
from core.legacy_models import Ruolo


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieOrdiniApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-api-user", password="pass12345")
        self.factory = RequestFactory()

    def test_api_db_ordini_includes_open_count(self):
        request = self.factory.get(reverse("api_anomalie_db_ordini"))
        request.user = self.user
        request.legacy_user = None

        rows = [
            {
                "item_id": "157",
                "op_title": "OP/2026/123",
                "part_number": "0002-0003-0004",
                "incaricato": "Simone Smarrella",
                "capocommessa": "Simone Danesi",
                "stato": "Aperto",
                "anomalie_count": 4,
                "anomalie_aperte_count": 2,
            }
        ]

        with (
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views._fetch_all_dict", return_value=rows),
        ):
            response = anomalie_views.api_db_ordini.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            [
                {
                    "item_id": "157",
                    "id": "OP/2026/123",
                    "pn": "0002-0003-0004",
                    "capo": "Simone Danesi",
                    "car": "Simone Smarrella",
                    "stato": "Aperto",
                    "anomalie_count": 4,
                    "anomalie_aperte_count": 2,
                }
            ],
        )

    def test_page_keeps_filter_querystring_for_frontend(self):
        self.client.force_login(self.user)

        with (
            patch("anomalie.views.user_can_modulo_action", return_value=True),
            patch("anomalie.views.get_legacy_user", return_value=None),
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views._load_anomalie_lists", return_value={}),
            patch("anomalie.views._current_user_identity", return_value={"name": "", "email": ""}),
        ):
            response = self.client.get(reverse("gestione_anomalie_page") + "?filter=in_carico")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "new URLSearchParams(window.location.search || \"\")", html=False)
        self.assertContains(response, 'label: "In carico"', html=False)
        self.assertContains(response, 'label: "Aperte"', html=False)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieConfigPageTests(TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(
            username="anom-admin",
            email="anom-admin@test.local",
            password="pass12345",
        )

    def test_config_page_shows_roles_and_access_tabs(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("anomalie_configurazione_page") + "?tab=accessi")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ruoli operativi")
        self.assertContains(response, "Regole accesso anomalie")
        self.assertContains(response, "Regole per ruolo aziendale")
        self.assertContains(response, "Capocommessa")
        self.assertContains(response, "CAR / Incaricato")

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieAccessRuleTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-access-user", password="pass12345")
        self.factory = RequestFactory()

    def _request(self, legacy_name: str = "Mario Rossi"):
        request = self.factory.get(reverse("gestione_anomalie_page"))
        request.user = self.user
        request.legacy_user = SimpleNamespace(
            id=101,
            nome=legacy_name,
            email="m.rossi@test.local",
            ruolo="utente",
            ruolo_id=2,
        )
        return request

    def test_system_role_rule_controls_op_edit_scope(self):
        anomalie_views._ensure_system_anomalie_roles()
        AnomalieRoleAccessRule.objects.update_or_create(
            role_type=AnomalieRoleType.CAPO_COMMESSA,
            defaults={"access_level": AnomalieAccessLevel.NONE},
        )
        request = self._request("Mario Rossi")

        with (
            patch("anomalie.views._load_anomalie_lists", return_value={"autorizzati_modifica": []}),
            patch("anomalie.views._has_table", return_value=True),
            patch(
                "anomalie.views._fetch_all_dict",
                return_value=[{"capocomessa": "Mario Rossi", "incaricato": ""}],
            ),
        ):
            self.assertFalse(anomalie_views._can_edit_anomalie_for_op(request, "OP/2026/001"))

        AnomalieRoleAccessRule.objects.update_or_create(
            role_type=AnomalieRoleType.CAPO_COMMESSA,
            defaults={"access_level": AnomalieAccessLevel.EDIT_ASSIGNED},
        )
        with (
            patch("anomalie.views._load_anomalie_lists", return_value={"autorizzati_modifica": []}),
            patch("anomalie.views._has_table", return_value=True),
            patch(
                "anomalie.views._fetch_all_dict",
                return_value=[{"capocomessa": "Mario Rossi", "incaricato": ""}],
            ),
        ):
            self.assertTrue(anomalie_views._can_edit_anomalie_for_op(request, "OP/2026/001"))

    def test_custom_role_and_user_override_can_grant_global_edit(self):
        # Ruolo operativo dal catalogo unico anagrafica + regola ri-chiavata su ruolo_operativo.
        ruolo = RuoloOperativo.objects.create(nome="Qualita", descrizione="Ruolo test")
        AnomalieRoleAccessRule.objects.create(
            ruolo_operativo=ruolo, access_level=AnomalieAccessLevel.EDIT_ALL
        )

        request = self._request("Utente Non In OP")
        # L'utente ricopre il ruolo operativo (risolto via anagrafica): mock dell'helper condiviso.
        with (
            patch("anomalie.views._load_anomalie_lists", return_value={"autorizzati_modifica": []}),
            patch("anomalie.views.get_role_ids_for_user", return_value={ruolo.id}),
        ):
            self.assertTrue(anomalie_views._can_edit_anomalie_for_op(request, "OP/2026/999"))

        AnomalieRoleAccessRule.objects.filter(ruolo_operativo=ruolo).update(
            access_level=AnomalieAccessLevel.NONE
        )
        AnomalieUserAccessRule.objects.create(user=self.user, access_level=AnomalieAccessLevel.EDIT_ALL)
        with (
            patch("anomalie.views._load_anomalie_lists", return_value={"autorizzati_modifica": []}),
            patch("anomalie.views.get_role_ids_for_user", return_value={ruolo.id}),
        ):
            self.assertTrue(anomalie_views._can_edit_anomalie_for_op(request, "OP/2026/999"))

    def test_legacy_role_rule_can_grant_global_edit(self):
        AnomalieLegacyRoleAccessRule.objects.create(
            legacy_role_id=2,
            legacy_role_name="utente",
            access_level=AnomalieAccessLevel.EDIT_ALL,
        )

        request = self._request("Utente Non In OP")
        with patch("anomalie.views._load_anomalie_lists", return_value={"autorizzati_modifica": []}):
            self.assertTrue(anomalie_views._can_edit_anomalie_for_op(request, "OP/2026/999"))

    def test_legacy_role_edit_assigned_requires_matching_op_role(self):
        anomalie_views._ensure_system_anomalie_roles()
        AnomalieRoleAccessRule.objects.update_or_create(
            role_type=AnomalieRoleType.CAPO_COMMESSA,
            defaults={"access_level": AnomalieAccessLevel.NONE},
        )
        AnomalieLegacyRoleAccessRule.objects.create(
            legacy_role_id=2,
            legacy_role_name="utente",
            access_level=AnomalieAccessLevel.EDIT_ASSIGNED,
        )
        request = self._request("Mario Rossi")

        with (
            patch("anomalie.views._load_anomalie_lists", return_value={"autorizzati_modifica": []}),
            patch("anomalie.views._has_table", return_value=True),
            patch(
                "anomalie.views._fetch_all_dict",
                return_value=[{"capocomessa": "Mario Rossi", "incaricato": ""}],
            ),
        ):
            self.assertTrue(anomalie_views._can_edit_anomalie_for_op(request, "OP/2026/001"))

        with (
            patch("anomalie.views._load_anomalie_lists", return_value={"autorizzati_modifica": []}),
            patch("anomalie.views._has_table", return_value=True),
            patch(
                "anomalie.views._fetch_all_dict",
                return_value=[{"capocomessa": "Altro Utente", "incaricato": ""}],
            ),
        ):
            self.assertFalse(anomalie_views._can_edit_anomalie_for_op(request, "OP/2026/002"))

    def test_access_post_saves_legacy_role_rule(self):
        Ruolo.objects.create(id=77, nome="Qualita")
        self.client.force_login(get_user_model().objects.create_superuser("anom-admin-roles", password="pass12345"))

        response = self.client.post(
            reverse("anomalie_configurazione_page") + "?tab=accessi",
            {
                "action": "save_access",
                "visible_legacy_role_id": "77",
                "access_legacy_role__77": AnomalieAccessLevel.EDIT_ALL,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AnomalieLegacyRoleAccessRule.objects.filter(
                legacy_role_id=77,
                legacy_role_name="Qualita",
                access_level=AnomalieAccessLevel.EDIT_ALL,
            ).exists()
        )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieReportTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-report-user", password="pass12345")
        self.factory = RequestFactory()

    def test_report_renders_op_summary_for_op_item_id(self):
        request = self.factory.get(reverse("anomalie_report_segnalazione"), {"op_item_id": "157"})
        request.user = self.user
        request.legacy_user = None

        op_row = [
            {
                "sharepoint_item_id": "157",
                "title": "OP/2026/123",
                "part_number": "0002-0003-0004",
                "incaricato": "Simone Smarrella",
                "capocomessa": "Simone Danesi",
                "stato": "Aperto",
                "in1text": "Nota OP",
                "created_datetime": "2026-03-10 08:30:00",
                "modified_datetime": "2026-03-15 16:45:00",
            }
        ]
        anomaly_rows = [
            {
                "id": 12,
                "sharepoint_item_id": "501",
                "ex_op_nominativo": "OP/2026/123",
                "seriale": "SN-001",
                "descrizione": "Difetto A",
                "note_capocommessa": "Nota A",
                "pezzo_recuperato": 1,
                "aprire_rdc": 0,
                "segnalare_cliente": 1,
                "chiudere": 0,
                "avanzamento": "In attesa",
                "numero_rdc": "RDC-1",
                "created_datetime": "2026-03-10 09:00:00",
                "modified_datetime": "2026-03-15 11:00:00",
            },
            {
                "id": 13,
                "sharepoint_item_id": "502",
                "ex_op_nominativo": "OP/2026/123",
                "seriale": "SN-002",
                "descrizione": "Difetto B",
                "note_capocommessa": "Nota B",
                "pezzo_recuperato": 0,
                "aprire_rdc": 1,
                "segnalare_cliente": 0,
                "chiudere": 1,
                "avanzamento": "Finito trattato",
                "numero_rdc": "",
                "created_datetime": "2026-03-11 10:00:00",
                "modified_datetime": "2026-03-15 12:30:00",
            },
        ]

        with (
            patch("anomalie.views._has_table", return_value=True),
            patch(
                "anomalie.views.legacy_table_columns",
                return_value={
                    "id",
                    "sharepoint_item_id",
                    "ex_op_nominativo",
                    "seriale",
                    "descrizione",
                    "note_capocommessa",
                    "pezzo_recuperato",
                    "aprire_rdc",
                    "segnalare_cliente",
                    "chiudere",
                    "avanzamento",
                    "numero_rdc",
                    "created_datetime",
                    "modified_datetime",
                },
            ),
            patch("anomalie.views._fetch_all_dict", side_effect=[op_row, anomaly_rows]),
            patch("anomalie.views._list_attachments_for_local", side_effect=lambda local_id: [{"name": f"all-{local_id}.pdf", "size": 123, "mime_type": "application/pdf"}]),
            patch("anomalie.views._can_view_anomalie_for_op", return_value=True),
            patch("anomalie.views._load_report_template", return_value=None),
        ):
            response = anomalie_views.report_segnalazione_html.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("OP/2026/123", html)
        self.assertIn("SN-001", html)
        self.assertIn("SN-002", html)
        self.assertIn("Difetto A", html)
        self.assertIn("Report Documento OP", html)

    def test_report_can_resolve_op_from_anomaly_id(self):
        request = self.factory.get(reverse("anomalie_report_segnalazione"), {"id": "12"})
        request.user = self.user
        request.legacy_user = None

        focus_row = [{"id": 12, "op_lookup_id": 157, "ex_op_nominativo": "OP/2026/123"}]
        op_row = [
            {
                "sharepoint_item_id": "157",
                "title": "OP/2026/123",
                "part_number": "0002-0003-0004",
                "incaricato": "Simone Smarrella",
                "capocomessa": "Simone Danesi",
                "stato": "Aperto",
                "in1text": "",
                "created_datetime": "",
                "modified_datetime": "2026-03-15 16:45:00",
            }
        ]
        anomaly_rows = [
            {
                "id": 12,
                "sharepoint_item_id": "501",
                "ex_op_nominativo": "OP/2026/123",
                "seriale": "SN-001",
                "descrizione": "Difetto A",
                "note_capocommessa": "",
                "pezzo_recuperato": 1,
                "aprire_rdc": 0,
                "segnalare_cliente": 1,
                "chiudere": 0,
                "avanzamento": "In attesa",
                "numero_rdc": "",
                "created_datetime": "",
                "modified_datetime": "",
            },
            {
                "id": 13,
                "sharepoint_item_id": "502",
                "ex_op_nominativo": "OP/2026/123",
                "seriale": "SN-002",
                "descrizione": "Difetto B",
                "note_capocommessa": "",
                "pezzo_recuperato": 0,
                "aprire_rdc": 0,
                "segnalare_cliente": 0,
                "chiudere": 1,
                "avanzamento": "Finito trattato",
                "numero_rdc": "",
                "created_datetime": "",
                "modified_datetime": "",
            },
        ]

        with (
            patch("anomalie.views._has_table", return_value=True),
            patch(
                "anomalie.views.legacy_table_columns",
                return_value={
                    "id",
                    "sharepoint_item_id",
                    "ex_op_nominativo",
                    "seriale",
                    "descrizione",
                    "note_capocommessa",
                    "pezzo_recuperato",
                    "aprire_rdc",
                    "segnalare_cliente",
                    "chiudere",
                    "avanzamento",
                    "numero_rdc",
                    "created_datetime",
                    "modified_datetime",
                },
            ),
            patch("anomalie.views._fetch_all_dict", side_effect=[focus_row, op_row, anomaly_rows]),
            patch("anomalie.views._list_attachments_for_local", return_value=[]),
            patch("anomalie.views._can_view_anomalie_for_op", return_value=True),
            patch("anomalie.views._load_report_template", return_value=None),
        ):
            response = anomalie_views.report_segnalazione_html.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("SN-001", html)
        self.assertIn("SN-002", html)
        self.assertIn("Record #12", html)

    def test_report_default_template_download(self):
        request = self.factory.get(reverse("anomalie_report_segnalazione"), {"_tpl_default": "1"})
        request.user = self.user
        request.legacy_user = None

        response = anomalie_views.report_segnalazione_html.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Disposition"], 'attachment; filename="report_default_op.html"')
        self.assertIn("Report Documento OP", response.content.decode("utf-8"))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieCsvExportAuditTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-export-user", password="pass12345")
        self.client.force_login(self.user)

    @staticmethod
    def _export_columns() -> set[str]:
        return {
            "id",
            "ex_op_nominativo",
            "seriale",
            "descrizione",
            "note_capocommessa",
            "numero_rdc",
            "avanzamento",
            "created_datetime",
            "modified_datetime",
            "sharepoint_item_id",
            "chiudere",
        }

    @patch("anomalie.views.log_action")
    @patch("anomalie.views.legacy_table_columns")
    @patch("anomalie.views._has_table", return_value=True)
    def test_export_csv_logs_audit_with_rows_and_filters(
        self,
        _mock_has_table,
        mock_legacy_columns,
        mock_log_action,
    ):
        mock_legacy_columns.return_value = self._export_columns()
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (1, "OP/2026/123", "SN-001", "Difetto", "Nota", "RDC-1", "In attesa", "2026-03-10", "2026-03-11", "501")
        ]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        conn.ops.quote_name.side_effect = lambda column: column

        with patch("anomalie.views.connections", {"default": conn}):
            response = self.client.get(reverse("anomalie_export_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_log_action.call_count, 1)
        action_args = mock_log_action.call_args.args
        self.assertEqual(action_args[1], "export_csv")
        self.assertEqual(action_args[2], "anomalie")
        self.assertEqual(action_args[3]["rows"], 1)
        self.assertEqual(action_args[3]["filters"]["mode"], "all")

    @patch("anomalie.views.log_action")
    @patch("anomalie.views.legacy_table_columns")
    @patch("anomalie.views._has_table", return_value=True)
    def test_export_csv_filtrato_logs_audit_with_rows_and_filters(
        self,
        _mock_has_table,
        mock_legacy_columns,
        mock_log_action,
    ):
        mock_legacy_columns.return_value = self._export_columns()
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (1, "OP/2026/123", "SN-001", "Difetto", "Nota", "RDC-1", "In attesa", 0, "2026-03-10", "2026-03-11")
        ]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        conn.ops.quote_name.side_effect = lambda column: column

        with patch("anomalie.views.connections", {"default": conn}):
            response = self.client.get(
                reverse("anomalie_export_csv_filtrato"),
                {
                    "da": "2026-03-01",
                    "a": "2026-03-31",
                    "avanzamento": "In attesa",
                    "capocommessa": "Simone Danesi",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_log_action.call_count, 1)
        action_args = mock_log_action.call_args.args
        self.assertEqual(action_args[1], "export_csv")
        self.assertEqual(action_args[2], "anomalie")
        self.assertEqual(action_args[3]["rows"], 1)
        self.assertEqual(action_args[3]["filters"]["da"], "2026-03-01")
        self.assertEqual(action_args[3]["filters"]["a"], "2026-03-31")
        self.assertEqual(action_args[3]["filters"]["avanzamento"], "In attesa")
        self.assertEqual(action_args[3]["filters"]["capocommessa"], "Simone Danesi")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieStatisticheRicercaTests(TestCase):
    """Verifica KPI estesi e tabella di ricerca paginata."""

    _COLS = {
        "id", "ex_op_nominativo", "seriale", "descrizione", "avanzamento",
        "numero_rdc", "aprire_rdc", "segnalare_cliente", "pezzo_recuperato",
        "chiudere", "created_datetime", "modified_datetime", "note_capocommessa",
    }

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-stat-user", password="pass12345")
        self.factory = RequestFactory()

    def _request(self, path_name, data=None):
        request = self.factory.get(reverse(path_name), data or {})
        request.user = self.user
        request.legacy_user = None
        return request

    @patch("anomalie.views.legacy_table_columns")
    @patch("anomalie.views._has_table", return_value=True)
    @patch("anomalie.views._fetch_all_dict")
    def test_statistiche_espone_kpi_estesi(self, mock_fetch, _mock_has, mock_cols):
        mock_cols.return_value = self._COLS
        # Ogni COUNT(*) ritorna [{"n": ...}]; le GROUP BY ritornano liste.
        mock_fetch.side_effect = lambda sql, params=None: (
            [{"n": 3}] if "COUNT(*)" in sql and "GROUP BY" not in sql
            else [{"avanzamento": "In attesa", "n": 2}] if "GROUP BY avanzamento" in sql
            else [{"mese": "2026-03", "n": 3}] if "FORMAT(created_datetime" in sql
            else [{"op": "OP/A", "n": 3, "chiuse": 1}] if "ex_op_nominativo" in sql and "GROUP BY" in sql and "TOP" in sql
            else [{"h": 48.0}] if "AVG(" in sql
            else [{"avanzamento": "In attesa"}] if "DISTINCT avanzamento" in sql
            else [{"ex_op_nominativo": "OP/A"}] if "DISTINCT ex_op_nominativo" in sql
            else []
        )
        resp = anomalie_views.api_anomalie_statistiche.__wrapped__(self._request("api_anomalie_statistiche"))
        self.assertEqual(resp.status_code, 200)
        d = json.loads(resp.content)
        for key in ("totale", "aperte", "chiuse", "rdc_aperti", "segnalazioni",
                    "recuperati", "in_attesa", "tempo_medio_giorni", "per_op"):
            self.assertIn(key, d)
        self.assertEqual(d["tempo_medio_giorni"], 2.0)  # 48h / 24
        self.assertEqual(d["per_op"], [{"op": "OP/A", "n": 3, "chiuse": 1}])

    @patch("anomalie.views.legacy_table_columns")
    @patch("anomalie.views._has_table", return_value=True)
    @patch("anomalie.views._fetch_all_dict")
    def test_ricerca_paginata_contratto(self, mock_fetch, _mock_has, mock_cols):
        mock_cols.return_value = self._COLS
        riga = {
            "id": 7, "ex_op_nominativo": "OP/A", "seriale": "SN-7",
            "descrizione": "Difetto", "avanzamento": "In attesa", "numero_rdc": "",
            "aprire_rdc": 1, "segnalare_cliente": 0, "chiudere": 0,
            "created_datetime": "2026-03-10", "modified_datetime": "2026-03-11",
        }
        mock_fetch.side_effect = lambda sql, params=None: (
            [{"n": 1}] if "COUNT(*)" in sql else [riga]
        )
        resp = anomalie_views.api_anomalie_ricerca.__wrapped__(
            self._request("api_anomalie_ricerca", {"q": "SN", "rdc": "si"})
        )
        self.assertEqual(resp.status_code, 200)
        d = json.loads(resp.content)
        self.assertEqual(d["totale"], 1)
        self.assertEqual(d["page"], 1)
        self.assertEqual(d["pages"], 1)
        self.assertEqual(len(d["righe"]), 1)
        self.assertEqual(d["righe"][0]["seriale"], "SN-7")
