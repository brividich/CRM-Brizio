from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class NotificaMetaTests(TestCase):
    """(a) Registro di presentazione dei tipi notifica."""

    def test_tipo_noto_ha_label_e_icona(self):
        from core.notifiche_meta import notifica_meta

        m = notifica_meta("dpi_scadenza")
        self.assertEqual(m["label"], "DPI in scadenza")
        self.assertTrue(m["icona"])
        self.assertIn(m["tono"], {"ok", "warn", "danger", "info"})

    def test_presa_visione_registrata(self):
        from core.notifiche_meta import notifica_meta

        self.assertEqual(notifica_meta("presa_visione")["label"], "Presa visione")

    def test_tipo_ignoto_default(self):
        from core.notifiche_meta import notifica_meta

        m = notifica_meta("qualcosa_di_ignoto")
        self.assertEqual(m["label"], "Notifica")
        self.assertTrue(m["icona"])

    def test_filtro_template(self):
        from django.template import Context, Template

        out = Template(
            "{% load notifiche_extras %}{{ 'ticket_sla'|notifica_meta }}"
        ).render(Context({}))
        self.assertIn("SLA ticket", out)


class NotifichePageTests(TestCase):
    """(a) label dal registro nella pagina + (b) aprire NON marca tutto letto."""

    def setUp(self):
        from core.models import Notifica, UserOnboarding

        self.user = User.objects.create_user("notifuser", password="pw", is_superuser=True)
        UserOnboarding.objects.create(user=self.user, skipped=True)
        self.n = Notifica.objects.create(
            legacy_user_id=999, tipo="presa_visione", messaggio="Documento da leggere", letta=False
        )

    def test_pagina_usa_label_registro_e_non_marca_letto(self):
        self.client.force_login(self.user)
        with mock.patch("core.views.get_legacy_user", return_value=SimpleNamespace(id=999)):
            resp = self.client.get(reverse("notifiche"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Presa visione")  # label dal registro, non "generico"
        self.n.refresh_from_db()
        self.assertFalse(self.n.letta)  # (b) aprire la pagina NON marca come letto
