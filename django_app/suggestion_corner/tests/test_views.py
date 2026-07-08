from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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
