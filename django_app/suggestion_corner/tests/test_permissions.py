from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig
from suggestion_corner.permissions import is_sms_team, visible_segnalazioni

User = get_user_model()


class PermissionsTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.membro = User.objects.create_user(username="team", password="x")
        self.estraneo = User.objects.create_user(username="ext", password="x")
        self.incaricato = User.objects.create_user(username="inc", password="x")
        cfg = SuggestionCornerConfig.load()
        self.group = Group.objects.create(name=cfg.sms_team_group_name)
        self.membro.groups.add(self.group)
        # una segnalazione dell'estraneo, una con incaricato
        self.sc_ext = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Ext.", created_by=self.estraneo,
        )
        self.sc_inc = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Inc.", incaricato=self.incaricato,
        )

    def test_is_sms_team_membro(self):
        self.assertTrue(is_sms_team(self.membro))

    def test_is_sms_team_superuser(self):
        su = User.objects.create_superuser(username="su", password="x")
        self.assertTrue(is_sms_team(su))

    def test_is_sms_team_estraneo_false(self):
        self.assertFalse(is_sms_team(self.estraneo))

    def test_team_vede_tutto(self):
        self.assertEqual(visible_segnalazioni(self.membro).count(), 2)

    def test_estraneo_vede_solo_le_proprie(self):
        vis = visible_segnalazioni(self.estraneo)
        self.assertEqual(list(vis), [self.sc_ext])

    def test_incaricato_vede_il_proprio_incarico(self):
        vis = visible_segnalazioni(self.incaricato)
        self.assertIn(self.sc_inc, vis)
        self.assertNotIn(self.sc_ext, vis)
