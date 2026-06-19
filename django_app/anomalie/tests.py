import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
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

    def test_page_loads_precompiled_bundle_and_globals(self):
        """La pagina serve React di produzione + il bundle committato (no Babel
        runtime) e cabla i globals che il bundle legge (incl. ANOMALIE_API e il
        querystring, ora gestito client-side dentro il bundle)."""
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
        html = response.content.decode("utf-8")
        # React di produzione + bundle precompilato, niente traspilazione a runtime.
        self.assertIn("react.production.min.js", html)
        self.assertIn("react-dom.production.min.js", html)
        self.assertIn("gestione_anomalie.bundle.js", html)
        self.assertNotIn("babel", html.lower())
        # I globals letti dal bundle restano resi server-side.
        self.assertIn("window.ANOMALIE_API", html)
        self.assertIn("window.ANOMALIE_ACCESS", html)


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
        # L'export massivo è gated su EDIT_ALL (vedi AnomalieExportPermissionTests):
        # questo utente ha la regola di accesso piena per testare l'audit log.
        AnomalieUserAccessRule.objects.create(user=self.user, access_level=AnomalieAccessLevel.EDIT_ALL)
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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieAllegatiCicloTests(TestCase):
    """Regressione: upload allegato → meta sync → list (gli helper sync-meta
    erano stati persi in un refactor, l'upload andava in 500 e gli allegati
    non comparivano in gestione anomalie)."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-all-user", password="pass12345")
        self.factory = RequestFactory()

    def _post_upload(self, local_id, files):
        request = self.factory.post(reverse("api_anomalie_allegati_upload"), {"local_id": str(local_id)})
        request.user = self.user
        request.legacy_user = None
        request.FILES.setlist("files", files)
        request.POST = request.POST.copy()
        request.POST["local_id"] = str(local_id)
        return request

    def test_upload_then_list_includes_file_and_creates_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_id = 4242
            up = SimpleUploadedFile("foto.png", b"\x89PNG\r\n\x1a\nDATA", content_type="image/png")
            with (
                patch("anomalie.views._anomalie_attachments_root", return_value=root),
                patch("anomalie.views._anomaly_local_row", return_value={"id": local_id, "ex_op_nominativo": "OP/A"}),
                patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
                patch("anomalie.views.log_action"),
            ):
                resp = anomalie_views.api_anomalie_allegati_upload.__wrapped__(self._post_upload(local_id, [up]))
            self.assertEqual(resp.status_code, 200)
            body = json.loads(resp.content)
            self.assertTrue(body["success"])
            self.assertEqual(body["saved"], 1)
            # 1) il file fisico è stato scritto nella cartella dell'anomalia
            folder = root / str(local_id)
            saved_files = [p.name for p in folder.iterdir() if p.is_file()]
            self.assertIn("__sync_meta__.json", saved_files)  # meta creato (no più NameError)
            attach_files = [n for n in saved_files if n != "__sync_meta__.json"]
            self.assertEqual(len(attach_files), 1)
            # 2) il meta marca il file come 'pending'
            meta = json.loads((folder / "__sync_meta__.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["files"][attach_files[0]]["status"], "pending")
            # 3) la list ritorna l'allegato ed ESCLUDE il file meta
            with (
                patch("anomalie.views._anomalie_attachments_root", return_value=root),
                patch("anomalie.views._anomaly_local_row", return_value={"id": local_id, "ex_op_nominativo": "OP/A"}),
                patch("anomalie.views._can_view_anomalie_for_op", return_value=True),
                patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
            ):
                req = self.factory.get(reverse("api_anomalie_allegati"), {"local_id": str(local_id)})
                req.user = self.user
                req.legacy_user = None
                list_resp = anomalie_views.api_anomalie_allegati.__wrapped__(req)
            self.assertEqual(list_resp.status_code, 200)
            listed = json.loads(list_resp.content)
            names = [a["name"] for a in listed["attachments"]]
            self.assertEqual(listed["attachments"][0]["name"], "foto.png")
            self.assertNotIn("__sync_meta__.json", names)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieTimelineTests(TestCase):
    """Copertura logging portale (AnomaliaActionLog) + endpoint timeline per OP."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="anom-timeline-user", password="pass12345"
        )
        self.factory = RequestFactory()

    def test_log_anomalia_portal_action_crea_record(self):
        from anomalie.mail_action_models import AnomaliaActionLog
        from anomalie.mail_action_service import log_anomalia_portal_action

        log_anomalia_portal_action(
            anomalia_id=101,
            op_id="OP/2026/777",
            action="aggiorna",
            user=self.user,
            legacy_user_id=42,
            user_display="Mario Rossi",
            previous_status="In attesa",
            new_status="Finito trattato",
        )

        log = AnomaliaActionLog.objects.get(anomalia_id=101)
        self.assertEqual(log.action, "aggiorna")
        self.assertEqual(log.source, AnomaliaActionLog.Source.PORTAL)
        self.assertEqual(log.previous_status, "In attesa")
        self.assertEqual(log.new_status, "Finito trattato")
        self.assertEqual(log.op_id, "OP/2026/777")

    def test_log_anomalia_portal_action_senza_id_non_scrive(self):
        from anomalie.mail_action_models import AnomaliaActionLog
        from anomalie.mail_action_service import log_anomalia_portal_action

        log_anomalia_portal_action(anomalia_id=None, op_id="OP/X", action="crea")
        self.assertEqual(AnomaliaActionLog.objects.count(), 0)

    def test_gestione_page_wires_timeline_url(self):
        """#2/#4: la pagina cabla l'URL timeline nei globals; i componenti React
        (StatoStepper/TimelineOp) vivono ora nel bundle committato, non più
        inline nell'HTML."""
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(
            user=self.user,
            defaults={"completed": True, "skipped": False},
        )
        self.client.force_login(self.user)
        with (
            patch("anomalie.views.user_can_modulo_action", return_value=True),
            patch("anomalie.views.get_legacy_user", return_value=None),
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views._load_anomalie_lists", return_value={}),
            patch("anomalie.views._current_user_identity",
                  return_value={"name": "", "email": "", "name_norm": "", "email_norm": ""}),
        ):
            response = self.client.get(reverse("gestione_anomalie_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/api/anomalie/timeline", html=False)
        self.assertContains(response, "gestione_anomalie.bundle.js", html=False)

    def test_precompiled_bundle_contains_components(self):
        """Il bundle committato contiene davvero i componenti React attesi
        (stepper, timeline) e il pulsante di export PDF del report."""
        import anomalie

        bundle = (
            Path(anomalie.__file__).parent
            / "static" / "anomalie" / "js" / "gestione_anomalie.bundle.js"
        )
        self.assertTrue(bundle.exists(), f"Bundle mancante: {bundle}")
        text = bundle.read_text(encoding="utf-8")
        self.assertIn("StatoStepper", text)
        self.assertIn("TimelineOp", text)
        # Il PDF del report passa per ?format=pdf (vedi handleOpenReport).
        self.assertIn('"format"', text)
        self.assertIn('"pdf"', text)

    def test_api_timeline_aggrega_per_op(self):
        from anomalie.mail_action_models import AnomaliaActionLog

        # Due anomalie sullo stesso OP + una su OP diverso (esclusa).
        AnomaliaActionLog.objects.create(
            anomalia_id=11, op_id="OP/2026/777", action="crea",
            new_status="In attesa", source=AnomaliaActionLog.Source.PORTAL,
            user_display="Tizio",
        )
        AnomaliaActionLog.objects.create(
            anomalia_id=12, op_id="OP/2026/777", action="chiudi",
            previous_status="In attesa", new_status="Chiusa",
            source=AnomaliaActionLog.Source.MAIL_ACTION, user_display="Caio",
        )
        AnomaliaActionLog.objects.create(
            anomalia_id=99, op_id="OP/2026/OTHER", action="crea",
            source=AnomaliaActionLog.Source.PORTAL, user_display="Estraneo",
        )

        request = self.factory.get(
            reverse("api_anomalie_timeline"), {"op_id": "OP/2026/777"}
        )
        request.user = self.user
        request.legacy_user = None

        with patch("anomalie.views._has_table", return_value=False):
            # _has_table False: niente match per id legacy, ma match per op_id resta.
            response = anomalie_views.api_anomalie_timeline.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        ids = {item["anomalia_id"] for item in data["items"]}
        self.assertEqual(ids, {11, 12})
        labels = {item["action_label"] for item in data["items"]}
        self.assertIn("Anomalia creata", labels)
        self.assertIn("Anomalia chiusa", labels)

    def test_api_timeline_richiede_op(self):
        request = self.factory.get(reverse("api_anomalie_timeline"))
        request.user = self.user
        request.legacy_user = None
        response = anomalie_views.api_anomalie_timeline.__wrapped__(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"items": []})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieExportPermissionTests(TestCase):
    """#2: l'export massivo CSV è riservato a chi ha EDIT_ALL (superuser, admin
    legacy o regola di accesso piena). Gli altri ricevono 403."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-noexport-user", password="pass12345")
        self.client.force_login(self.user)

    def test_export_csv_forbidden_without_edit_all(self):
        with patch("anomalie.views._has_table", return_value=True):
            response = self.client.get(reverse("anomalie_export_csv"))
        self.assertEqual(response.status_code, 403)

    def test_export_csv_filtrato_forbidden_without_edit_all(self):
        with patch("anomalie.views._has_table", return_value=True):
            response = self.client.get(reverse("anomalie_export_csv_filtrato"))
        self.assertEqual(response.status_code, 403)

    def test_export_csv_allowed_with_edit_all_rule(self):
        AnomalieUserAccessRule.objects.create(user=self.user, access_level=AnomalieAccessLevel.EDIT_ALL)
        cols = {"id", "ex_op_nominativo", "seriale", "descrizione", "note_capocommessa",
                "numero_rdc", "avanzamento", "created_datetime", "modified_datetime", "sharepoint_item_id"}
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        conn.ops.quote_name.side_effect = lambda column: column
        with (
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views.legacy_table_columns", return_value=cols),
            patch("anomalie.views.log_action"),
            patch("anomalie.views.connections", {"default": conn}),
        ):
            response = self.client.get(reverse("anomalie_export_csv"))
        self.assertEqual(response.status_code, 200)

    def test_superuser_can_export(self):
        self.client.force_login(get_user_model().objects.create_superuser(
            "anom-su-export", email="su@test.local", password="pass12345"))
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        conn.ops.quote_name.side_effect = lambda column: column
        cols = {"id", "ex_op_nominativo", "seriale", "descrizione", "avanzamento",
                "created_datetime", "modified_datetime", "chiudere"}
        with (
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views.legacy_table_columns", return_value=cols),
            patch("anomalie.views.log_action"),
            patch("anomalie.views.connections", {"default": conn}),
        ):
            response = self.client.get(reverse("anomalie_export_csv_filtrato"))
        self.assertEqual(response.status_code, 200)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieScopeViewTests(TestCase):
    """#2: lo scope ristretto (ASSIGNED/OWN) vale anche in lettura sul singolo
    OP, non solo sull'elenco. Gli endpoint API protetti rispondono 403 JSON."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-scope-user", password="pass12345")
        self.factory = RequestFactory()

    def _request(self, path_name, data=None):
        request = self.factory.get(reverse(path_name), data or {})
        request.user = self.user
        request.legacy_user = None
        return request

    def test_can_view_allows_everyone_in_all_scope(self):
        request = self._request("gestione_anomalie_page")
        with patch("anomalie.views._request_anomalie_list_scope",
                   return_value=anomalie_views.AnomalieListScope.ALL):
            self.assertTrue(anomalie_views._can_view_anomalie_for_op(request, "OP/2026/001"))

    def test_can_view_denies_unentitled_in_restricted_scope(self):
        request = self._request("gestione_anomalie_page")
        with (
            patch("anomalie.views._request_anomalie_list_scope",
                  return_value=anomalie_views.AnomalieListScope.OWN_ANOMALIE),
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=False),
            patch("anomalie.views._op_role_codes_for_current_user", return_value=[]),
            patch("anomalie.views._user_created_anomalia_on_op", return_value=False),
        ):
            self.assertFalse(anomalie_views._can_view_anomalie_for_op(request, "OP/2026/001"))

    def test_can_view_allows_creator_in_own_scope(self):
        request = self._request("gestione_anomalie_page")
        with (
            patch("anomalie.views._request_anomalie_list_scope",
                  return_value=anomalie_views.AnomalieListScope.OWN_ANOMALIE),
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=False),
            patch("anomalie.views._op_role_codes_for_current_user", return_value=[]),
            patch("anomalie.views._user_created_anomalia_on_op", return_value=True),
        ):
            self.assertTrue(anomalie_views._can_view_anomalie_for_op(request, "OP/2026/001"))

    def test_api_anomalie_returns_403_when_not_viewable(self):
        request = self._request("api_anomalie_anomalie", {"op_id": "OP/2026/001"})
        with (
            patch("anomalie.views._resolve_op_lookup_id", return_value=None),
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views.legacy_table_columns", return_value={"id", "numero_rdc"}),
            patch("anomalie.views._can_view_anomalie_for_op", return_value=False),
        ):
            response = anomalie_views.api_anomalie.__wrapped__(request)
        self.assertEqual(response.status_code, 403)

    def test_api_db_anomalie_returns_403_when_restricted_and_not_viewable(self):
        request = self._request("api_anomalie_db_anomalie", {"sp_item_id": "157"})
        with (
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views._request_anomalie_list_scope",
                  return_value=anomalie_views.AnomalieListScope.ASSIGNED),
            patch("anomalie.views._report_op_row", return_value={"title": "OP/2026/001"}),
            patch("anomalie.views._can_view_anomalie_for_op", return_value=False),
        ):
            response = anomalie_views.api_db_anomalie.__wrapped__(request)
        self.assertEqual(response.status_code, 403)

    def test_api_db_anomalie_skips_check_in_all_scope(self):
        """Scope ALL (default): nessuna verifica per-OP, l'endpoint procede."""
        request = self._request("api_anomalie_db_anomalie", {"sp_item_id": "157"})
        with (
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views._request_anomalie_list_scope",
                  return_value=anomalie_views.AnomalieListScope.ALL),
            patch("anomalie.views.legacy_table_columns", return_value={"id", "numero_rdc"}),
            patch("anomalie.views._fetch_all_dict", return_value=[]),
        ):
            response = anomalie_views.api_db_anomalie.__wrapped__(request)
        self.assertEqual(response.status_code, 200)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieReportPdfTests(TestCase):
    """Report PDF dell'OP: variante ?format=pdf della view HTML + generatore."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-pdf-user", password="pass12345")
        self.factory = RequestFactory()

    def test_build_op_report_pdf_bytes_smoke(self):
        from anomalie.services.report_pdf import build_op_report_pdf_bytes

        op = {"id": "OP/2026/123", "item_id": "157", "pn": "0002", "capo": "Tizio",
              "car": "Caio", "stato": "Aperto", "info": "Nota lunga di prova"}
        report = {"anomalie_totali": 2, "anomalie_aperte": 1, "anomalie_chiuse": 1, "allegati_totali": 0}
        anomalie = [
            {"seriale": "SN-001", "descrizione": "Difetto A", "avanzamento": "In attesa",
             "numero_rdc": "RDC-1", "is_closed": False, "note_capocommessa": "Nota A",
             "aprire_rdc_bool": True, "segnalare_cliente_bool": False,
             "pezzo_recuperato_bool": False, "local_id": 1, "attachments": []},
            {"seriale": "SN-002", "descrizione": "Difetto B", "avanzamento": "Finito trattato",
             "numero_rdc": "", "is_closed": True, "local_id": 2, "attachments": []},
        ]
        pdf = build_op_report_pdf_bytes(op, report, anomalie)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)

    def test_build_op_report_pdf_bytes_handles_empty(self):
        from anomalie.services.report_pdf import build_op_report_pdf_bytes

        pdf = build_op_report_pdf_bytes({}, {}, [])
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_report_pdf_variant_returns_application_pdf(self):
        request = self.factory.get(
            reverse("anomalie_report_segnalazione"),
            {"op_item_id": "157", "format": "pdf"},
        )
        request.user = self.user
        request.legacy_user = None

        op_row = [{
            "sharepoint_item_id": "157", "title": "OP/2026/123",
            "part_number": "0002-0003-0004", "incaricato": "Simone Smarrella",
            "capocomessa": "Simone Danesi", "stato": "Aperto", "in1text": "Nota OP",
            "created_datetime": "2026-03-10 08:30:00", "modified_datetime": "2026-03-15 16:45:00",
        }]
        anomaly_rows = [{
            "id": 12, "sharepoint_item_id": "501", "ex_op_nominativo": "OP/2026/123",
            "seriale": "SN-001", "descrizione": "Difetto A", "note_capocommessa": "Nota A",
            "pezzo_recuperato": 1, "aprire_rdc": 0, "segnalare_cliente": 1, "chiudere": 0,
            "avanzamento": "In attesa", "numero_rdc": "RDC-1",
            "created_datetime": "2026-03-10 09:00:00", "modified_datetime": "2026-03-15 11:00:00",
        }]
        cols = {
            "id", "sharepoint_item_id", "ex_op_nominativo", "seriale", "descrizione",
            "note_capocommessa", "pezzo_recuperato", "aprire_rdc", "segnalare_cliente",
            "chiudere", "avanzamento", "numero_rdc", "created_datetime", "modified_datetime",
        }
        with (
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views.legacy_table_columns", return_value=cols),
            patch("anomalie.views._fetch_all_dict", side_effect=[op_row, anomaly_rows]),
            patch("anomalie.views._list_attachments_for_local",
                  side_effect=lambda local_id: [{"name": f"all-{local_id}.pdf", "size": 123, "mime_type": "application/pdf"}]),
            patch("anomalie.views._can_view_anomalie_for_op", return_value=True),
        ):
            response = anomalie_views.report_segnalazione_html.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("report_OP_2026_123.pdf", response["Content-Disposition"])
