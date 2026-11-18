"""Tessere delle giacenze RENTRI cliccabili: stesso insieme e stesso numero nell'elenco filtrato. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import RegistroRifiuti

User = get_user_model()


class GiacenzeKpiLinkTests(TestCase):
    def setUp(self):
        user = User.objects.create_superuser(username="rentri-kpi", email="rentri-kpi@example.com", password="pwd12345")
        UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())
        self.client.force_login(user)
        oggi = timezone.localdate()
        RegistroRifiuti.objects.create(tipo="C", data=oggi - timedelta(days=150), codice="080111", quantita=40)  # rosso
        RegistroRifiuti.objects.create(tipo="C", data=oggi - timedelta(days=2), codice="150106", quantita=10)    # verde
        self.url = reverse("rentri_giacenze")

    def test_tessere_href_e_conteggi(self):
        r = self.client.get(self.url, {"aperte": "1"})
        html = r.content.decode()
        self.assertIn(f'href="{self.url}?aperte=1#gi-elenco"', html)
        self.assertIn(f'href="{self.url}?aperte=1&amp;allerta=1#gi-elenco"', html)
        self.assertIn(f'href="{self.url}?aperte=1&amp;oltre=1#gi-elenco"', html)
        self.assertEqual(len(self.client.get(self.url, {"aperte": "1"}).context["rows"]), r.context["totale"])
        self.assertEqual(len(self.client.get(self.url, {"aperte": "1", "allerta": "1"}).context["rows"]), r.context["n_allerta"])
        oltre = self.client.get(self.url, {"aperte": "1", "oltre": "1"}).context["rows"]
        self.assertEqual(len(oltre), r.context["n_oltre"])
        self.assertEqual([g.codice for g, _ in oltre], ["080111"])
