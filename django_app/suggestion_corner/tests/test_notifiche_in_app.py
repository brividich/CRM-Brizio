"""Test notifiche in-app Suggestion Corner (sessione 6, riuso core.Notifica)."""
from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Reparto
from core.models import Notifica, UserOnboarding
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig
from suggestion_corner.notifications import notifica_assegnazione_in_app

User = get_user_model()


class NotificaInAppUnitTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.inc = User.objects.create_user(username="inc", password="x")
        self.ctrl = User.objects.create_user(username="ctrl", password="x")

    def test_crea_notifiche_per_incaricato_e_controllore(self):
        seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="X.",
            incaricato=self.inc, controllore=self.ctrl,
        )
        n = notifica_assegnazione_in_app(seg)
        self.assertEqual(n, 2)
        self.assertTrue(Notifica.objects.filter(
            legacy_user_id=self.inc.id, tipo="sc_assegnazione").exists())
        self.assertTrue(Notifica.objects.filter(
            legacy_user_id=self.ctrl.id, tipo="sc_assegnazione").exists())

    def test_nessun_assegnatario_nessuna_notifica(self):
        seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="X.")
        self.assertEqual(notifica_assegnazione_in_app(seg), 0)
        self.assertEqual(Notifica.objects.count(), 0)


@override_settings(LEGACY_AUTH_ENABLED=False)
class NotificaInAppIntegrationTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="CNC")
        self.team = User.objects.create_user(username="team", password="x")
        self.inc = User.objects.create_user(username="inc", password="x")
        self.ctrl = User.objects.create_user(username="ctrl", password="x")
        UserOnboarding.objects.create(user=self.team, completed=True, completed_at=timezone.now())
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.team.groups.add(g)
        self.seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Migliorare.")
        self.seg.notifica_sms_team(); self.seg.classifica("SMS_SI"); self.seg.save()

    def test_definisci_plan_crea_notifiche(self):
        self.client.force_login(self.team)
        d = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
        self.client.post(
            reverse("suggestion_corner:definisci_plan", args=[self.seg.pk]),
            {"incaricato": self.inc.pk, "controllore": self.ctrl.pk,
             "data_limite_esecuzione": d, "data_limite_controllo": d},
        )
        self.assertTrue(Notifica.objects.filter(legacy_user_id=self.inc.id, tipo="sc_assegnazione").exists())
        self.assertTrue(Notifica.objects.filter(legacy_user_id=self.ctrl.id, tipo="sc_assegnazione").exists())
