from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Reparto

from .models import ProdottoChimico

User = get_user_model()


def _pdf():
    return SimpleUploadedFile("sds.pdf", b"%PDF-1.4\n%finto\n", content_type="application/pdf")


class ReportComplianceViewTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        self.admin = User.objects.create_user(username="admin_report", password="x", is_superuser=True, is_staff=True)

    def test_report_visibile_a_utente_con_permesso(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Senza scheda")

    def test_report_negato_a_utente_senza_permesso(self):
        utente = User.objects.create_user(username="senza_permesso_report", password="x")
        self.client.force_login(utente)
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertNotEqual(resp.status_code, 200)

    def test_report_negato_senza_login(self):
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.url.lower())
