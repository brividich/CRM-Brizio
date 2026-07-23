"""Blocco 2 — quick-win P2. 1.15: matricola senza zeri di padding (display-only).
1.6: colonna data ("Creato il") nel catalogo corsi (scheda e sessioni l'hanno già)."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from anagrafica.templatetags.anagrafica_extras import matricola_fmt

User = get_user_model()


class MatricolaFmtTests(SimpleTestCase):
    def test_numerica_strippa_zeri(self):
        self.assertEqual(matricola_fmt("0001"), "1")
        self.assertEqual(matricola_fmt("120"), "120")

    def test_tutti_zeri_resta_zero(self):
        self.assertEqual(matricola_fmt("000"), "0")

    def test_alfanumerica_invariata(self):
        self.assertEqual(matricola_fmt("CNO 0001"), "CNO 0001")
        self.assertEqual(matricola_fmt("A007"), "A007")

    def test_vuota_o_none(self):
        self.assertEqual(matricola_fmt(""), "")
        self.assertEqual(matricola_fmt(None), "")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FormazioneCorsiDataTests(TestCase):
    def test_catalogo_corsi_mostra_colonna_creato(self):
        from anagrafica.models_formazione import TrainingCourse, TrainingPlan
        admin = User.objects.create_superuser(
            username="corsi_p2", email="corsi_p2@x.local", password="x"
        )
        self.client.force_login(admin)
        piano = TrainingPlan.objects.create(codice="P16", nome="Piano 1.6")
        TrainingCourse.objects.create(
            piano=piano, codice="C16", titolo="Corso 1.6", durata_ore_teorica=2,
        )
        resp = self.client.get(reverse("anagrafica:formazione_corsi_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Creato il", resp.content.decode())
