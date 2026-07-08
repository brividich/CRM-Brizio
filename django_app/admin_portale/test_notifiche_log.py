from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from admin_portale.tests import _ensure_utenti_table
from core.legacy_models import UtenteLegacy
from core.models import Notifica

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NotificheLogViewTests(TestCase):
    """Log notifiche admin (cross-utente): la pagina mostra le notifiche di tutti,
    con nome destinatario risolto, etichetta dal registro, filtri e conteggi."""

    def setUp(self):
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")

        self.admin_user = User.objects.create_superuser(
            username="admin-notif-log", email="a.notif@test.local", password="pass12345"
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Notif", email="a.notif@test.local", password="*AD_MANAGED*",
            ruolo="admin", ruolo_id=1, attivo=True, deve_cambiare_password=False,
        )
        self.dest = UtenteLegacy.objects.create(
            nome="Mario Rossi", email="m.rossi@test.local", password="x",
            ruolo="op", ruolo_id=2, attivo=True, deve_cambiare_password=False,
        )
        Notifica.objects.create(
            legacy_user_id=self.dest.id, tipo="presa_visione",
            messaggio="Documento MT CN 06 da leggere", letta=False,
        )
        Notifica.objects.create(
            legacy_user_id=self.dest.id, tipo="dpi_scadenza",
            messaggio="DPI in scadenza", letta=True,
        )

    def _get(self, url, params=None):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin", return_value=True
        ):
            return self.client.get(url, params or {})

    def test_pagina_mostra_notifiche_cross_utente(self):
        resp = self._get(reverse("admin_portale:notifiche_log"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Documento MT CN 06")
        self.assertContains(resp, "Presa visione")   # etichetta dal registro
        self.assertContains(resp, "Mario Rossi")      # nome risolto da UtenteLegacy
        tipi = {t["tipo"] for t in resp.context["per_tipo"]}
        self.assertIn("presa_visione", tipi)
        self.assertIn("dpi_scadenza", tipi)

    def test_filtro_per_tipo(self):
        resp = self._get(reverse("admin_portale:notifiche_log"), {"tipo": "presa_visione"})
        self.assertEqual(resp.status_code, 200)
        codes = [n.tipo for n in resp.context["page_obj"].object_list]
        self.assertTrue(codes)
        self.assertTrue(all(c == "presa_visione" for c in codes))

    def test_csv_export(self):
        resp = self._get(reverse("admin_portale:notifiche_log"), {"export": "csv"})
        self.assertEqual(resp.status_code, 200)
        blob = (resp.get("Content-Type", "") + resp.get("Content-Disposition", "")).lower()
        self.assertIn("csv", blob)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NotificheConfigViewTests(TestCase):
    """Pannello admin: accende/spegne le categorie globalmente."""

    def setUp(self):
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")
        self.admin_user = User.objects.create_superuser(
            username="admin-notif-cfg", email="a.cfg@test.local", password="pass12345"
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Cfg", email="a.cfg@test.local", password="*AD_MANAGED*",
            ruolo="admin", ruolo_id=1, attivo=True, deve_cambiare_password=False,
        )

    def _as_admin(self, method, url, data=None):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin", return_value=True
        ):
            if method == "post":
                return self.client.post(url, data or {})
            return self.client.get(url)

    def test_pagina_render(self):
        resp = self._as_admin("get", reverse("admin_portale:notifiche_config"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Scadenzari")

    def test_toggle_spegne_categoria(self):
        from core.notifiche_prefs import is_category_enabled_globally

        # POST con solo 'assenze' acceso → le altre categorie si spengono
        self._as_admin("post", reverse("admin_portale:notifiche_config"), {"cat_assenze": "1"})
        self.assertTrue(is_category_enabled_globally("assenze"))
        self.assertFalse(is_category_enabled_globally("scadenzari"))
        self.assertFalse(is_category_enabled_globally("ticket"))
