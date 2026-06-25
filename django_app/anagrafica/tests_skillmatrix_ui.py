"""F4/F7 — test matrice macchina (UI), export CSV, accesso e voci di menu."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset

from .models import (
    AbilitazioneMacchina, CompetenzaSkm, LivelloSkm, SubnavLinkAnagrafica,
)

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class SkillMatrixMacchinaViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("smadmin", "sm@example.com", "pass12345")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:skill_matrix_macchina")

    def test_render_vuoto(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Skill Matrix")
        self.assertContains(resp, "Nessuna abilitazione macchina")

    def test_render_con_abilitazione(self):
        a = Asset.objects.create(asset_tag="CNC-DM3-1", name="DM3", asset_type="CNC", reparto="Off")
        CompetenzaSkm.objects.create(competenza_key="DM3", display="DM3", tipo="macchina", asset=a)
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=1, asset=a, livello=LivelloSkm.AUTONOMO)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "DM3")
        self.assertNotContains(resp, "Nessuna abilitazione macchina")

    def test_export_csv(self):
        a = Asset.objects.create(asset_tag="CNC-DM3-2", name="DM3", asset_type="CNC", reparto="Off")
        CompetenzaSkm.objects.create(competenza_key="DM3", display="DM3", tipo="macchina", asset=a)
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=1, asset=a, livello=LivelloSkm.ESPERTO)
        resp = self.client.get(self.url, {"format": "csv"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("skill_matrix_macchina.csv", resp["Content-Disposition"])

    def test_accesso_negato_senza_permesso(self):
        self.client.logout()
        nobody = User.objects.create_user("nobody2", "n2@example.com", "pass12345")
        self.client.force_login(nobody)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)  # redirect a index


class SkillMatrixNavTests(TestCase):
    def test_voci_menu_create_dalla_migration(self):
        # La data migration 0072 semina le 2 voci sotto "Competenze" / "Skill Matrix".
        for url_value in ("anagrafica:skill_matrix_macchina", "anagrafica:skm_match_validazione"):
            link = SubnavLinkAnagrafica.objects.filter(url_value=url_value).first()
            self.assertIsNotNone(link, f"voce subnav mancante: {url_value}")
            self.assertTrue(link.is_active)
            self.assertEqual(link.gruppo, "Skill Matrix")
            self.assertEqual(link.categoria.nome, "Competenze")
