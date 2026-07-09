"""Test copilota AI Suggestion Corner (sessione 9).

- classifica_ai / bozza_plan_ai: AI mockata (nessuna dipendenza da Ollama);
- trova_simili: dati reali (Jaccard token), deterministico;
- endpoint JSON AJAX: 403 JSON per i non-SMS_TEAM, 200 per il team.
"""
from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Reparto
from core.models import UserOnboarding
from suggestion_corner import ai as sc_ai
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig

User = get_user_model()


class ClassificaAiTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto,
            opportunity="Ridurre gli scarti in tornitura con un controllo dimensionale.",
        )

    def test_classifica_valida_suggerimento(self):
        raw = '{"suggerimento": "SMS_SI", "motivazione": "Opportunità concreta."}'
        with mock.patch.object(sc_ai, "_chiama_ai", return_value=raw):
            out = sc_ai.classifica_ai(self.seg)
        self.assertTrue(out["ai_disponibile"])
        self.assertEqual(out["suggerimento"], "SMS_SI")
        self.assertEqual(out["motivazione"], "Opportunità concreta.")

    def test_classifica_scarta_valore_fuori_lista(self):
        raw = '{"suggerimento": "FORSE", "motivazione": "boh"}'
        with mock.patch.object(sc_ai, "_chiama_ai", return_value=raw):
            out = sc_ai.classifica_ai(self.seg)
        self.assertEqual(out["suggerimento"], "")  # non inventa

    def test_classifica_ai_offline_failsafe(self):
        with mock.patch.object(sc_ai, "_chiama_ai", return_value=""):
            out = sc_ai.classifica_ai(self.seg)
        self.assertFalse(out["ai_disponibile"])
        self.assertEqual(out["suggerimento"], "")
        self.assertTrue(out["proposto"])


class BozzaPlanAiTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="CNC")
        self.seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Migliorare illuminazione.",
        )

    def test_bozza_plan_estratta(self):
        raw = '{"bozza_plan": "- Azione 1\\n- Azione 2"}'
        with mock.patch.object(sc_ai, "_chiama_ai", return_value=raw):
            out = sc_ai.bozza_plan_ai(self.seg)
        self.assertTrue(out["ai_disponibile"])
        self.assertIn("Azione 1", out["bozza_plan"])

    def test_bozza_plan_offline_failsafe(self):
        with mock.patch.object(sc_ai, "_chiama_ai", return_value=""):
            out = sc_ai.bozza_plan_ai(self.seg)
        self.assertFalse(out["ai_disponibile"])
        self.assertEqual(out["bozza_plan"], "")


class TrovaSimiliTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.base = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto,
            opportunity="Ridurre gli scarti in tornitura con controllo dimensionale automatico.",
        )
        self.simile = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto,
            opportunity="Controllo dimensionale automatico per ridurre scarti tornitura.",
        )
        self.diversa = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto,
            opportunity="Installare nuova macchinetta del caffè in mensa aziendale.",
        )

    def test_trova_la_simile_non_la_diversa(self):
        out = sc_ai.trova_simili(self.base)
        pks = [r["pk"] for r in out]
        self.assertIn(self.simile.pk, pks)
        self.assertNotIn(self.diversa.pk, pks)
        self.assertNotIn(self.base.pk, pks)  # esclude sé stessa

    def test_ordinamento_per_score(self):
        out = sc_ai.trova_simili(self.base)
        self.assertTrue(out)
        scores = [r["score"] for r in out]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_opportunity_vuota_nessun_risultato(self):
        vuota = SuggestionCorner(reparto_provenienza=self.reparto, opportunity="")
        vuota.save()
        self.assertEqual(sc_ai.trova_simili(vuota), [])


@override_settings(LEGACY_AUTH_ENABLED=False)
class AiEndpointAclTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Ridurre scarti.",
        )
        self.team = User.objects.create_user(username="team", password="x")
        self.altro = User.objects.create_user(username="altro", password="x")
        for u in (self.team, self.altro):
            UserOnboarding.objects.create(user=u, completed=True, completed_at=timezone.now())
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.team.groups.add(g)

    def test_non_team_riceve_403_json(self):
        self.client.force_login(self.altro)
        resp = self.client.post(reverse("suggestion_corner:ai_simili", args=[self.seg.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp["Content-Type"], "application/json")

    def test_team_ai_simili_200(self):
        self.client.force_login(self.team)
        resp = self.client.post(reverse("suggestion_corner:ai_simili", args=[self.seg.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("risultati", resp.json())

    def test_team_ai_classifica_200(self):
        self.client.force_login(self.team)
        with mock.patch.object(sc_ai, "_chiama_ai", return_value='{"suggerimento":"SMS_NO","motivazione":"x"}'):
            resp = self.client.post(reverse("suggestion_corner:ai_classifica", args=[self.seg.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["suggerimento"], "SMS_NO")
