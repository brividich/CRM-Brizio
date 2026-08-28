"""Copertura formativa: restyle a design system 'fmd' + paginazione, stessa
logica di gap condivisa ora con l'export (`services.training_eligibility.righe_gap_formativo`).

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi
tutto ai non-superuser durante i test.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente

from .models_formazione import TrainingCourse, TrainingPlan, TrainingRequirementRule
from .services.training_eligibility import righe_gap_formativo

User = get_user_model()


def _piano():
    piano, _ = TrainingPlan.objects.get_or_create(codice="P-COP", defaults={"nome": "Piano copertura"})
    return piano


def _corso_obbligatorio(codice, titolo, legacy_id):
    corso = TrainingCourse.objects.create(
        piano=_piano(), codice=codice, titolo=titolo, durata_ore_teorica=4,
    )
    TrainingRequirementRule.objects.create(
        corso=corso, legacy_anagrafica_id=legacy_id, is_active=True, is_mandatory=True,
    )
    return corso


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RigheGapFormativoTests(TestCase):
    def setUp(self):
        self.dip = AnagraficaDipendente.objects.create(
            nome="Elio", cognome="Rosa Test", aliasusername="erosa.test",
            reparto="Manutenzione",
        )
        self.corso = _corso_obbligatorio("C-COP", "Corso obbligo copertura", self.dip.id)

    def test_dipendente_senza_completamento_compare_come_gap(self):
        corsi, reparti, righe = righe_gap_formativo()
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["legacy_id"], self.dip.id)
        self.assertEqual(righe[0]["stato"], "MAI_FREQUENTATO")
        self.assertIn("Manutenzione", reparti)

    def test_filtro_reparto_esclude_altri(self):
        _, _, righe = righe_gap_formativo(filtro_reparto="Officina")
        self.assertEqual(righe, [])

    def test_filtro_corso_limita_ai_corsi_scelti(self):
        altro = _corso_obbligatorio("C-COP-2", "Altro obbligo", self.dip.id)
        _, _, righe = righe_gap_formativo(filtro_corso=str(altro.pk))
        self.assertEqual({r["corso"].pk for r in righe}, {altro.pk})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CoperturaViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-cop", "su-cop@test.local", "x")
        self.client.force_login(self.su)
        self.dip = AnagraficaDipendente.objects.create(
            nome="Fabio", cognome="Viola Test", aliasusername="fviola.test",
            reparto="Manutenzione",
        )
        self.corso = _corso_obbligatorio("C-COP-V", "Corso obbligo view", self.dip.id)

    def test_pagina_ok_e_pagina(self):
        resp = self.client.get(reverse("anagrafica:formazione_copertura"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("page_obj", resp.context)
        legacy_ids = [r["legacy_id"] for r in resp.context["page_obj"]]
        self.assertIn(self.dip.id, legacy_ids)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ExportCoperturaTests(TestCase):
    def setUp(self):
        self.dip = AnagraficaDipendente.objects.create(
            nome="Gaia", cognome="Rossi Export", aliasusername="grossi.exp",
            reparto="Officina",
        )
        self.corso = _corso_obbligatorio("C-COP-E", "Corso obbligo export", self.dip.id)

    def test_export_dataset_riporta_il_gap(self):
        from .exports_formazione import _formazione_copertura_rows

        req = type("R", (), {"GET": {}})()
        rows = _formazione_copertura_rows(req, "full")
        self.assertEqual(len(rows), 1)
        self.assertIn("Corso obbligo export", rows[0]["corso"])
        self.assertEqual(rows[0]["reparto"], "Officina")
