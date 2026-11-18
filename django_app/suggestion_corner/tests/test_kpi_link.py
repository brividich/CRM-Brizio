"""Tessere KPI della console: ognuna apre l'elenco ?filtro=... che conta lo stesso numero."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Reparto
from core.models import UserOnboarding
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class GestioneKpiLinkTest(TestCase):
    def setUp(self):
        rep = Reparto.objects.create(nome="FRESE")
        self.team = User.objects.create_user(username="team-kpi", password="x")
        UserOnboarding.objects.create(user=self.team, completed=True, completed_at=timezone.now())
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.team.groups.add(g)
        ieri = timezone.localdate() - timedelta(days=1)
        S = SuggestionCorner.Stato
        for stato, extra in (
            (S.DA_CLASSIFICARE, {}),
            (S.CHIUSA, {}),
            (S.DO_IN_CORSO, {"data_limite_esecuzione": ieri}),
            (S.CHECK_IN_CORSO, {"data_limite_controllo": ieri}),
        ):
            s = SuggestionCorner.objects.create(reparto_provenienza=rep, opportunity="Idea.")
            SuggestionCorner.objects.filter(pk=s.pk).update(stato=stato, **extra)
        self.client.force_login(self.team)

    def test_tessere_portano_a_elenchi_con_lo_stesso_numero(self):
        r = self.client.get(reverse("suggestion_corner:gestione"))
        self.assertEqual(r.status_code, 200)
        kpi = r.context["kpi"]
        home = reverse("suggestion_corner:home")
        for filtro, chiave in (
            ("tutte", "totali"), ("aperte", "aperte"), ("chiuse", "chiuse"), ("da_gestire", "da_classificare"),
            ("sms_si", "sms_si"), ("sms_no", "sms_no"), ("scaduti_do", "scaduti_do"), ("scaduti_check", "scaduti_check"),
        ):
            self.assertContains(r, f'href="{home}?filtro={filtro}"')
            elenco = self.client.get(home, {"filtro": filtro})
            self.assertEqual(elenco.context["filtro"], filtro)
            self.assertEqual(elenco.context["segnalazioni"].count(), kpi[chiave], filtro)
        self.assertEqual(kpi["scaduti_do"], 1)
        self.assertEqual(kpi["aperte"], 3)
