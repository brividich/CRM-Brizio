import configparser
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from anomalie import views as anomalie_views


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieSharePointSyncTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-sync-user", password="pass12345")
        self.factory = RequestFactory()

    def _graph_config(self, list_id: str = "<GRAPH_LIST_ID_ANOMALIE_DB>") -> configparser.ConfigParser:
        cfg = configparser.ConfigParser()
        cfg["AZIENDA"] = {
            "tenant_id": "tenant-test",
            "client_id": "client-test",
            "client_secret": "secret-test",
            "site_id": "site-test",
            "list_id_anomalie_db": list_id,
        }
        return cfg

    def test_graph_config_detects_placeholder_list_id(self):
        with patch("anomalie.views._load_app_config", return_value=self._graph_config()):
            self.assertFalse(anomalie_views._graph_configured())
            self.assertEqual(
                anomalie_views._graph_config_issue(),
                "Configurazione Graph anomalie incompleta: list_id_anomalie_db",
            )

    def test_api_sync_returns_503_when_graph_is_not_configured(self):
        request = self.factory.post(
            reverse("api_anomalie_sync"),
            data=json.dumps({}),
            content_type="application/json",
        )
        request.user = self.user
        request.legacy_user = SimpleNamespace(id=10, ruolo="gestore", ruolo_id=None)

        with patch(
            "anomalie.views._graph_config_issue",
            return_value="Configurazione Graph anomalie incompleta: list_id_anomalie_db",
        ):
            response = anomalie_views.api_sync.__wrapped__(request)

        self.assertEqual(response.status_code, 503)
        self.assertJSONEqual(
            response.content,
            {"error": "Configurazione Graph anomalie incompleta: list_id_anomalie_db"},
        )

    def test_page_exposes_sync_disabled_state_when_graph_config_is_missing(self):
        self.client.force_login(self.user)

        with (
            patch("anomalie.views.user_can_modulo_action", return_value=True),
            patch("anomalie.views.get_legacy_user", return_value=None),
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views._load_app_config", return_value=self._graph_config()),
        ):
            response = self.client.get(reverse("gestione_anomalie_page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "window.ANOMALIE_SYNC_AVAILABLE = false;", html=False)
        self.assertContains(response, "list_id_anomalie_db", html=False)
        self.assertContains(response, "Invia a SP")


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
            patch("anomalie.views._graph_config_issue", return_value=""),
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

    def test_config_page_shows_sharepoint_config_card(self):
        self.client.force_login(self.admin)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.ini"
            config_path.write_text(
                "\n".join(
                    [
                        "[AZIENDA]",
                        "tenant_id = tenant-test",
                        "client_id = client-test",
                        "client_secret = secret-test",
                        "site_id = site-test",
                        "list_id_anomalie_db = list-test",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("anomalie.views._config_ini_path", return_value=config_path):
                response = self.client.get(reverse("anomalie_configurazione_page") + "?tab=config")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SharePoint / Microsoft Graph")
        self.assertContains(response, 'name="sharepoint_list_id_anomalie_db"', html=False)
        self.assertContains(response, "list-test")

    def test_config_page_can_save_sharepoint_config(self):
        self.client.force_login(self.admin)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.ini"
            config_path.write_text("[AZIENDA]\nclient_secret = old-secret\n", encoding="utf-8")

            with patch("anomalie.views._config_ini_path", return_value=config_path):
                response = self.client.post(
                    reverse("anomalie_configurazione_page") + "?tab=config",
                    {
                        "action": "save_sharepoint_config",
                        "sharepoint_tenant_id": "tenant-new",
                        "sharepoint_client_id": "client-new",
                        "sharepoint_client_secret": "",
                        "sharepoint_site_id": "site-new",
                        "sharepoint_list_id_anomalie_db": "list-new",
                    },
                )

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], f"{reverse('anomalie_configurazione_page')}?tab=config")

            cfg = configparser.ConfigParser()
            cfg.read(config_path, encoding="utf-8")
            self.assertEqual(cfg.get("AZIENDA", "tenant_id"), "tenant-new")
            self.assertEqual(cfg.get("AZIENDA", "client_id"), "client-new")
            self.assertEqual(cfg.get("AZIENDA", "site_id"), "site-new")
            self.assertEqual(cfg.get("AZIENDA", "list_id_anomalie_db"), "list-new")
            self.assertEqual(cfg.get("AZIENDA", "client_secret"), "old-secret")
