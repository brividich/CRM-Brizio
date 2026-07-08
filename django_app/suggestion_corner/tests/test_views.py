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


class SuggestionCornerUrlsTest(TestCase):
    def test_home_url_risolve(self):
        self.assertEqual(reverse("suggestion_corner:home"), "/suggestion-corner/")

    def test_home_richiede_login(self):
        resp = self.client.get(reverse("suggestion_corner:home"))
        self.assertEqual(resp.status_code, 302)  # redirect al login
        self.assertIn("/login", resp.url.lower())

    def test_home_autenticato_200(self):
        # NB: self.client.login(username=, password=) non e' compatibile con
        # AxesStandaloneBackend (richiede request, che Client.login() non passa);
        # force_login e' il pattern gia' usato in tutto il resto della suite.
        # Superuser per bypassare il redirect onboarding (CoreMiddleware) non
        # pertinente a questo test di sola risoluzione rotta/gating login.
        user = User.objects.create_superuser(username="u1", email="u1@example.test", password="x")
        self.client.force_login(user)
        resp = self.client.get(reverse("suggestion_corner:home"))
        self.assertEqual(resp.status_code, 200)


@override_settings(LEGACY_AUTH_ENABLED=False)
class HomeScopeTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="CNC")
        self.team = User.objects.create_user(username="team", password="x")
        self.estraneo = User.objects.create_user(username="ext", password="x")
        # NB: self.client.login(username=, password=) non e' compatibile con
        # AxesStandaloneBackend (richiede request, che Client.login() non passa);
        # force_login e' il pattern gia' usato in tutto il resto della suite.
        # Inoltre CoreMiddleware redirige a /onboarding/ gli utenti non-superuser
        # senza UserOnboarding completato: qui serve testare utenti NON superuser
        # (per lo scope "vede solo le proprie"), quindi occorre un onboarding
        # completato per ciascuno.
        # Infine: ACLMiddleware negherebbe 403 anche a login riuscito, perche'
        # questi utenti Django di test non hanno un account legacy collegato
        # (get_legacy_user -> None -> "deny_missing_legacy_user") e il modulo
        # suggestion_corner non ha ancora un binding ACL v2 canonico (arriva
        # con l'acl_bootstrap.py di un task successivo). Pattern gia' in uso
        # nel resto della suite (es. notizie/tests.py) per isolare il test di
        # scope-dati dal gating ACL non ancora cablato per questo modulo.
        UserOnboarding.objects.create(user=self.team, completed=True, completed_at=timezone.now())
        UserOnboarding.objects.create(user=self.estraneo, completed=True, completed_at=timezone.now())
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.team.groups.add(g)
        SuggestionCorner.objects.create(reparto_provenienza=self.reparto, opportunity="A.", created_by=self.estraneo)
        SuggestionCorner.objects.create(reparto_provenienza=self.reparto, opportunity="B.", created_by=self.team)

    def test_team_vede_tutte_in_home(self):
        self.client.force_login(self.team)
        resp = self.client.get(reverse("suggestion_corner:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_team"])
        self.assertEqual(len(resp.context["segnalazioni"]), 2)

    def test_estraneo_vede_solo_le_proprie_in_home(self):
        self.client.force_login(self.estraneo)
        resp = self.client.get(reverse("suggestion_corner:home"))
        self.assertFalse(resp.context["is_team"])
        self.assertEqual(len(resp.context["segnalazioni"]), 1)
