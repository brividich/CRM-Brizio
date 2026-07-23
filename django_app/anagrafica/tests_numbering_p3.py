"""1.7 — codice corso gerarchico `<codice piano>-<N>` (suggest)."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import TrainingCourse, TrainingPlan

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CorsoCodiceSuggestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="cod_p3", email="cod_p3@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_suggest_piano_based_primo(self):
        piano = TrainingPlan.objects.create(codice="SIC", nome="Sicurezza")
        r = self.client.get(
            reverse("anagrafica:formazione_corso_codice_suggest"), {"piano_id": piano.pk}
        )
        self.assertEqual(r.json()["codice"], "SIC-1")

    def test_suggest_piano_based_incrementa(self):
        piano = TrainingPlan.objects.create(codice="SIC", nome="Sicurezza")
        TrainingCourse.objects.create(
            piano=piano, codice="SIC-1", titolo="C1", durata_ore_teorica=1,
        )
        r = self.client.get(
            reverse("anagrafica:formazione_corso_codice_suggest"), {"piano_id": piano.pk}
        )
        self.assertEqual(r.json()["codice"], "SIC-2")

    def test_suggest_fallback_titolo_senza_piano(self):
        # Senza piano si ripiega sulla base derivata dal titolo (comportamento storico).
        r = self.client.get(
            reverse("anagrafica:formazione_corso_codice_suggest"), {"titolo": "Base"}
        )
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["codice"].startswith("BASE"))
