from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import RegistroRifiuti

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RentriWriteAuthorizationTests(TestCase):
    """SEC-PREPROD-02 (M3): scrittura del registro RENTRI riservata ai gestori."""

    def setUp(self):
        self.basic = User.objects.create_user(
            username="rentri-basic", email="rentri-basic@example.com", password="pwd12345",
        )
        UserOnboarding.objects.create(
            user=self.basic, completed=True, completed_at=timezone.now(),
        )
        self.admin = User.objects.create_superuser(
            username="rentri-admin", email="rentri-admin@example.com", password="pwd12345",
        )

    def test_basic_user_cannot_create_via_carico(self):
        self.client.force_login(self.basic)
        response = self.client.post(
            reverse("rentri_carico"),
            data='{"data": "2026-05-01"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(RegistroRifiuti.objects.count(), 0)

    def test_admin_can_create_via_carico(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("rentri_carico"),
            data='{"data": "2026-05-01"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RegistroRifiuti.objects.filter(tipo="C").count(), 1)

    def test_basic_user_cannot_modify(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.basic)
        response = self.client.post(
            reverse("rentri_modifica", args=[registro.pk]),
            data='{"data": "2026-06-01"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_basic_user_cannot_delete(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.basic)
        response = self.client.post(reverse("rentri_elimina", args=[registro.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(RegistroRifiuti.objects.filter(pk=registro.pk).exists())

    def test_admin_can_delete(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.admin)
        response = self.client.post(reverse("rentri_elimina", args=[registro.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(RegistroRifiuti.objects.filter(pk=registro.pk).exists())

    def test_delete_rejects_get(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.admin)
        response = self.client.get(reverse("rentri_elimina", args=[registro.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(RegistroRifiuti.objects.filter(pk=registro.pk).exists())

    def test_basic_user_cannot_import_confirm(self):
        self.client.force_login(self.basic)
        response = self.client.post(reverse("rentri_import_confirm"))
        self.assertEqual(response.status_code, 403)

    def test_basic_user_cannot_trigger_sync_pull(self):
        self.client.force_login(self.basic)
        response = self.client.post(reverse("rentri_api_sync_pull"))
        self.assertEqual(response.status_code, 403)
