"""Test della modifica amministrativa interna al modulo (gestione SMS_TEAM)."""
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
class ModificaSegnalazioneTest(TestCase):
    def setUp(self):
        self.rep_a = Reparto.objects.create(nome="TORNI")
        self.rep_b = Reparto.objects.create(nome="CNC")
        self.team = User.objects.create_user(username="team", password="x")
        self.ext = User.objects.create_user(username="ext", password="x")
        for u in (self.team, self.ext):
            _onboard(u)
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.team.groups.add(g)
        self.seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.rep_a, opportunity="Migliorare.",
        )

    def _url(self):
        return reverse("suggestion_corner:modifica", args=[self.seg.pk])

    def test_team_apre_form(self):
        self.client.force_login(self.team)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_team_modifica_reparto(self):
        self.client.force_login(self.team)
        resp = self.client.post(self._url(), {
            "reparto_provenienza": self.rep_b.pk,
            "opportunity": "Migliorare ancora.",
            "stato_sms": "DA_GESTIRE",
        })
        self.assertEqual(resp.status_code, 302)
        s = SuggestionCorner.objects.get(pk=self.seg.pk)
        self.assertEqual(s.reparto_provenienza, self.rep_b)
        self.assertEqual(s.opportunity, "Migliorare ancora.")
        self.assertEqual(s.updated_by, self.team)
        # audit: una voce di storico "modifica_manuale"
        self.assertTrue(s.storico.filter(campo_modificato="modifica_manuale").exists())

    def test_stato_non_modificabile(self):
        # il campo stato non è nel form: resta invariato anche se provo a forzarlo
        self.client.force_login(self.team)
        self.client.post(self._url(), {
            "reparto_provenienza": self.rep_a.pk,
            "opportunity": "x",
            "stato_sms": "DA_GESTIRE",
            "stato": "CHIUSA",
        })
        s = SuggestionCorner.objects.get(pk=self.seg.pk)
        self.assertEqual(s.stato, "INSERITA")

    def test_incaricato_uguale_controllore_rifiutato(self):
        self.client.force_login(self.team)
        resp = self.client.post(self._url(), {
            "reparto_provenienza": self.rep_a.pk,
            "opportunity": "x",
            "stato_sms": "DA_GESTIRE",
            "incaricato": self.ext.pk,
            "controllore": self.ext.pk,
        })
        self.assertEqual(resp.status_code, 200)  # form non valido, ri-render
        s = SuggestionCorner.objects.get(pk=self.seg.pk)
        self.assertIsNone(s.incaricato)

    def test_estraneo_non_puo_modificare(self):
        self.client.force_login(self.ext)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post(self._url(), {
            "reparto_provenienza": self.rep_b.pk, "opportunity": "hack", "stato_sms": "DA_GESTIRE",
        })
        self.assertEqual(resp.status_code, 403)
        s = SuggestionCorner.objects.get(pk=self.seg.pk)
        self.assertEqual(s.reparto_provenienza, self.rep_a)
