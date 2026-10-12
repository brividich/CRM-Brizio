"""Guida Asset in-app (/assets/guida/). Dati sintetici."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.acl_v2 import _find_canonical_binding
from core.models import RoutePermissionBinding, UserOnboarding

from .models import AssetSidebarButton
from .services import report_catalog

User = get_user_model()


def _user(username, *, superuser=False):
    user = User.objects.create_user(username=username, password="x", email=f"{username}@example.test",
                                    is_superuser=superuser, is_staff=superuser)
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()})
    return user


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GuidaAssetTests(TestCase):
    def test_pagina_con_sezioni_e_report_del_catalogo(self):
        self.client.force_login(_user("guida.admin", superuser=True))
        response = self.client.get(reverse("assets:guida"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for ancora in ("qr", "mfc", "storico", "report", "kpi", "permessi"):
            self.assertIn(f'id="{ancora}"', body)
            self.assertIn(f'href="#{ancora}"', body)
        for d in report_catalog.definizioni().values():
            self.assertIn(reverse("assets:report_catalog_run", args=[d.code]), body)
        self.assertIn("Puoi gestire il link pubblico", body)
        self.assertNotIn("{%", body)

    def test_permessi_mancanti_dichiarati(self):
        self.client.force_login(_user("guida.base"))
        with patch("assets.views_guida.can_manage_public_qr", return_value=False), \
                patch("assets.views_guida.can_schedule_email", return_value=False), \
                patch("assets.views_guida._puo_leggere_ora", return_value=False), \
                patch("core.middleware.acl_allows_path", return_value=True):
            body = self.client.get(reverse("assets:guida")).content.decode()
        self.assertIn("Link pubblico: non abilitato per te", body)
        self.assertIn("«Leggi adesso»: non abilitato per te", body)
        self.assertIn("Invio email: non abilitato per te", body)

    def test_anonimo_va_al_login(self):
        response = self.client.get(reverse("assets:guida"))
        self.assertEqual(response.status_code, 302)

    def test_binding_acl_e_voce_menu(self):
        path = reverse("assets:guida")
        binding = RoutePermissionBinding.objects.get(path_pattern=path)
        self.assertEqual(binding.permission_id, "legacy.assets.assets_view")
        self.assertTrue(binding.is_active)
        risolto, _ = _find_canonical_binding(route_name="assets:guida", path_norm=path)
        self.assertEqual(risolto.permission_id, "legacy.assets.assets_view")
        voce = AssetSidebarButton.objects.get(code="guida_asset")
        self.assertEqual(voce.target_url, "django:assets:guida")

    def test_link_alla_guida_dal_catalogo(self):
        self.client.force_login(_user("guida.cat", superuser=True))
        body = self.client.get(reverse("assets:report_catalog")).content.decode()
        self.assertIn(reverse("assets:guida") + "#report", body)
