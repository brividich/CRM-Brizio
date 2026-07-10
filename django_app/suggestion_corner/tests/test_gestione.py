"""Test della console di gestione del modulo (SMS_TEAM)."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Reparto
from core.models import UserOnboarding
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig

User = get_user_model()


def _onboard(user):
    UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())


@override_settings(LEGACY_AUTH_ENABLED=False)
class GestioneConsoleTest(TestCase):
    def setUp(self):
        self.rep = Reparto.objects.create(nome="TORNI")
        self.team = User.objects.create_user(username="team", password="x")
        self.ext = User.objects.create_user(username="ext", password="x")
        for u in (self.team, self.ext):
            _onboard(u)
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.team.groups.add(g)
        SuggestionCorner.objects.create(reparto_provenienza=self.rep, opportunity="A.")
        b = SuggestionCorner.objects.create(reparto_provenienza=self.rep, opportunity="B.")
        SuggestionCorner.objects.filter(pk=b.pk).update(stato="DA_CLASSIFICARE")
        self.url = reverse("suggestion_corner:gestione")

    def test_estraneo_403(self):
        self.client.force_login(self.ext)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_team_vede_console_e_kpi(self):
        self.client.force_login(self.team)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["kpi"]["totali"], 2)
        self.assertEqual(resp.context["kpi"]["da_classificare"], 1)
        self.assertIn(self.team, list(resp.context["team"]))

    def test_team_salva_configurazione(self):
        self.client.force_login(self.team)
        resp = self.client.post(self.url, {
            "giorni_sollecito_1": 25, "giorni_sollecito_2": 12,
            "giorni_sollecito_3": 4, "giorni_escalation_oltre_scadenza": 5,
            "email_responsabile_escalation": "", "sms_team_group_name": "SMS_TEAM",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(SuggestionCornerConfig.load().giorni_sollecito_1, 25)

    def _group(self):
        return Group.objects.get(name=SuggestionCornerConfig.load().sms_team_group_name)

    def test_candidati_esclude_membri(self):
        self.client.force_login(self.team)
        candidati = list(self.client.get(self.url).context["candidati"])
        self.assertIn(self.ext, candidati)       # non è nel team → candidato
        self.assertNotIn(self.team, candidati)   # è già nel team → escluso

    def test_team_aggiunge_membro(self):
        self.client.force_login(self.team)
        resp = self.client.post(reverse("suggestion_corner:gestione_team_add"),
                                {"user_id": self.ext.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.ext.groups.filter(pk=self._group().pk).exists())

    def test_team_rimuove_membro(self):
        self.ext.groups.add(self._group())
        self.client.force_login(self.team)
        resp = self.client.post(reverse("suggestion_corner:gestione_team_remove"),
                                {"user_id": self.ext.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(self.ext.groups.filter(pk=self._group().pk).exists())

    def test_estraneo_non_puo_aggiungere(self):
        self.client.force_login(self.ext)
        resp = self.client.post(reverse("suggestion_corner:gestione_team_add"),
                                {"user_id": self.ext.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(self.ext.groups.filter(pk=self._group().pk).exists())
