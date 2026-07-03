"""F10 — scadenzario abilitazioni macchina + avvio refresh HR->CAR."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset

from .models import (
    AbilitazioneMacchina, CampagnaRefresh, CompetenzaSkm, LivelloSkm,
    Reparto, SkillMatrixConfig, SubnavLinkAnagrafica,
)

User = get_user_model()
OGGI = date(2026, 7, 3)


class ConfigPreavvisoTests(TestCase):
    def test_default_preavviso_refresh_giorni(self):
        cfg = SkillMatrixConfig.get_instance()
        self.assertEqual(cfg.preavviso_refresh_giorni, 60)

    def test_form_salva_preavviso(self):
        from .forms import SkillMatrixConfigForm
        cfg = SkillMatrixConfig.get_instance()
        data = {
            "soglia_operativa": "U", "regola_multivoce": "MIN", "soglia_uomo_solo": 2,
            "finestra_continuita_mesi": 12, "preavviso_continuita_mesi": 9,
            "periodicita_refresh_mesi": 6, "preavviso_refresh_giorni": 45,
            "etichetta_i": "I", "etichetta_l": "L", "etichetta_u": "U", "etichetta_o": "O",
        }
        form = SkillMatrixConfigForm(data, instance=cfg)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        cfg.refresh_from_db()
        self.assertEqual(cfg.preavviso_refresh_giorni, 45)
