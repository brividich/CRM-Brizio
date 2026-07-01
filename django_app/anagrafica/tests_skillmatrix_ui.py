"""F4/F7 — test matrice macchina (UI), export CSV, accesso e voci di menu."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

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

    def test_export_csv_include_disponibilita(self):
        a = Asset.objects.create(asset_tag="CNC-DM3-3", name="DM3", asset_type="CNC", reparto="Off")
        CompetenzaSkm.objects.create(competenza_key="DM3", display="DM3", tipo="macchina", asset=a)
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=7, asset=a, livello=LivelloSkm.AUTONOMO)
        fake = {7: [{"data_inizio": date(2026, 7, 1), "data_fine": date(2026, 7, 1),
                     "tipo": "Ferie", "nome": "Rossi Mario", "stato": "confermata", "parziale": False}]}
        with patch("assenze.availability.disponibilita_per_anagrafica", return_value=fake):
            resp = self.client.get(self.url, {"format": "csv", "data": "2026-07-01"})
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Disponibilità 01/07/2026", body)
        self.assertIn("assente (Ferie)", body)

    def test_accesso_negato_senza_permesso(self):
        self.client.logout()
        nobody = User.objects.create_user("nobody2", "n2@example.com", "pass12345")
        self.client.force_login(nobody)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)  # redirect a index


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class SkillMatrixImpostazioniViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("skcfg", "skcfg@example.com", "pass12345")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:skm_impostazioni")

    def _payload(self, **over):
        data = {
            "soglia_operativa": "U",
            "regola_multivoce": "MIN",
            "soglia_uomo_solo": 2,
            "finestra_continuita_mesi": 12,
            "preavviso_continuita_mesi": 9,
            "periodicita_refresh_mesi": 6,
            "etichetta_i": "In formazione",
            "etichetta_l": "Intermedio",
            "etichetta_u": "Autonomo",
            "etichetta_o": "Formatore/Esperto",
        }
        data.update(over)
        return data

    def test_get_render(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Impostazioni")
        self.assertContains(resp, "Soglia operativa")

    def test_post_salva(self):
        from .models import SkillMatrixConfig
        resp = self.client.post(self.url, self._payload(soglia_operativa="L", soglia_uomo_solo=3,
                                                        includi_car_come_riserva="on"))
        self.assertEqual(resp.status_code, 302)
        c = SkillMatrixConfig.get_instance()
        self.assertEqual(c.soglia_operativa, "L")
        self.assertEqual(c.soglia_uomo_solo, 3)
        self.assertTrue(c.includi_car_come_riserva)

    def test_post_invalido_non_salva(self):
        from .models import SkillMatrixConfig
        # soglia_uomo_solo < 1 -> errore di clean, niente salvataggio
        resp = self.client.post(self.url, self._payload(soglia_operativa="L", soglia_uomo_solo=0))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(SkillMatrixConfig.get_instance().soglia_operativa, "U")

    def test_accesso_negato_senza_permesso(self):
        self.client.logout()
        nobody = User.objects.create_user("nocfg", "nocfg@example.com", "pass12345")
        self.client.force_login(nobody)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)


class SkillMatrixNavTests(TestCase):
    def test_voci_menu_create_dalla_migration(self):
        # La data migration 0072 semina le 2 voci sotto "Competenze" / "Skill Matrix".
        for url_value in ("anagrafica:skill_matrix_macchina", "anagrafica:skm_match_validazione"):
            link = SubnavLinkAnagrafica.objects.filter(url_value=url_value).first()
            self.assertIsNotNone(link, f"voce subnav mancante: {url_value}")
            self.assertTrue(link.is_active)
            self.assertEqual(link.gruppo, "Skill Matrix")
            self.assertEqual(link.categoria.nome, "Competenze")
