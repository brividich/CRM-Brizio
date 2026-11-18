"""Tessere di lista e statistiche cliccabili: l'elenco filtrato conta lo stesso numero. Dati sintetici."""
from __future__ import annotations

from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import RilevazioneIncidente, TipoEventoSicurezza


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RilevazioniKpiLinkTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(username="ri-kpi", email="ri-kpi@example.com", password="pwd12345")
        UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())
        self.client.force_login(user)
        quando = timezone.make_aware(datetime(2026, 5, 1, 9, 0), timezone.get_current_timezone())
        for nome, tipologia, evento in (
            ("Persona Uno", "Unsafe Condition", TipoEventoSicurezza.UNSAFE_CONDITION),
            ("Persona Due", "Near Miss", TipoEventoSicurezza.NEAR_MISS),
            ("Persona Tre", "Accident", TipoEventoSicurezza.INCIDENTE),
            ("Persona Quattro", "Unsafe Act", TipoEventoSicurezza.UNSAFE_CONDITION),
        ):
            RilevazioneIncidente.objects.create(nominativo=nome, tipologia_scheda=tipologia, tipo_evento=evento,
                                                reparto="CNC", data_segnalazione=quando)
        self.lista = reverse("rilevazione_incidenti:lista")

    def _n(self, params):
        r = self.client.get(self.lista, params)
        self.assertEqual(r.status_code, 200)
        return len(r.context["items"])

    def test_lista_tessere_href_e_conteggi(self):
        r = self.client.get(self.lista)
        stats = r.context["stats"]
        html = r.content.decode()
        casi = [
            ({}, stats["totale"], f"{self.lista}#sic-elenco"),
            ({"stato": "APERTO"}, stats["aperti"], f"{self.lista}?stato=APERTO#sic-elenco"),
            ({"stato": "APPROVATO"}, stats["approvati"], f"{self.lista}?stato=APPROVATO#sic-elenco"),
            ({"stato": "CHIUSO"}, stats["chiusi"], f"{self.lista}?stato=CHIUSO#sic-elenco"),
            ({"tipo": "Unsafe Condition"}, stats["unsafe_condition"], f"{self.lista}?tipo=Unsafe+Condition#sic-elenco"),
            ({"tipo": "Accident"}, stats["accident"], f"{self.lista}?tipo=Accident#sic-elenco"),
            ({"tipo_evento": "unsafe_condition"}, stats["eventi_unsafe_condition"],
             f"{self.lista}?tipo_evento=unsafe_condition#sic-elenco"),
            ({"tipo_evento": "incidente"}, stats["eventi_incidente"], f"{self.lista}?tipo_evento=incidente#sic-elenco"),
        ]
        for params, atteso, href in casi:
            self.assertIn(f'href="{href}"', html, href)
            self.assertEqual(self._n(params), atteso, params)
        self.assertEqual(stats["totale"], 4)
        self.assertEqual(stats["eventi_unsafe_condition"], 2)

    def test_statistiche_tessere_portano_alla_lista(self):
        r = self.client.get(reverse("rilevazione_incidenti:statistiche"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn(f'href="{self.lista}?tipo=Near+Miss#sic-elenco"', html)
        self.assertIn(f'href="{self.lista}?stato=APERTO#sic-elenco"', html)
        self.assertEqual(self._n({"tipo": "Near Miss"}), r.context["n_near_miss"])
        self.assertEqual(self._n({"stato": "APERTO"}), r.context["n_aperto"])
        self.assertEqual(self._n({}), r.context["totale"])
