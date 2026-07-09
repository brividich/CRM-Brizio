"""Test delle azioni FSM via HTTP (sessione 3b)."""
from __future__ import annotations

import datetime

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
class AzioniFsmTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.team = User.objects.create_user(username="team", password="x")
        self.inc = User.objects.create_user(username="inc", password="x")
        self.ctrl = User.objects.create_user(username="ctrl", password="x")
        self.ext = User.objects.create_user(username="ext", password="x")
        for u in (self.team, self.inc, self.ctrl, self.ext):
            _onboard(u)
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.team.groups.add(g)
        self.seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Migliorare.",
        )

    def _post(self, user, name, **data):
        self.client.force_login(user)
        return self.client.post(reverse(f"suggestion_corner:{name}", args=[self.seg.pk]), data)

    def _reload(self):
        # FSMField(protected) vieta refresh_from_db(); re-fetch fresco.
        return SuggestionCorner.objects.get(pk=self.seg.pk)

    def _a_da_classificare(self):
        self.seg.notifica_sms_team(); self.seg.save()

    def test_team_classifica(self):
        self._a_da_classificare()
        resp = self._post(self.team, "classifica", stato_sms="SMS_SI")
        self.assertEqual(resp.status_code, 302)
        s = self._reload()
        self.assertEqual(s.stato, "CLASSIFICATA")
        self.assertEqual(s.stato_sms, "SMS_SI")

    def test_estraneo_non_puo_classificare(self):
        self._a_da_classificare()
        resp = self._post(self.ext, "classifica", stato_sms="SMS_SI")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._reload().stato, "DA_CLASSIFICARE")

    def test_plan_incaricato_uguale_controllore_rifiutato(self):
        # porto a CLASSIFICATA
        self.seg.notifica_sms_team(); self.seg.classifica("SMS_SI"); self.seg.save()
        resp = self._post(
            self.team, "definisci_plan",
            incaricato=self.inc.pk, controllore=self.inc.pk,
            data_limite_esecuzione="2026-08-01", data_limite_controllo="2026-08-10",
        )
        self.assertEqual(resp.status_code, 302)  # redirect con messaggio d'errore
        self.assertEqual(self._reload().stato, "CLASSIFICATA")  # invariato

    def _fino_a_do_in_corso(self):
        self.seg.notifica_sms_team(); self.seg.classifica("SMS_SI")
        d1 = datetime.date.today() + datetime.timedelta(days=10)
        d2 = datetime.date.today() + datetime.timedelta(days=20)
        self.seg.definisci_plan(incaricato=self.inc, controllore=self.ctrl,
                                data_limite_esecuzione=d1, data_limite_controllo=d2)
        self.seg.avvia_do(); self.seg.save()

    def test_incaricato_completa_do(self):
        self._fino_a_do_in_corso()
        resp = self._post(self.inc, "completa_do", esito_do="SI", do_testo="Fatto")
        self.assertEqual(resp.status_code, 302)
        s = self._reload()
        self.assertEqual(s.stato, "DO_COMPLETATO")
        self.assertEqual(s.esito_do, "SI")

    def test_estraneo_non_completa_do(self):
        self._fino_a_do_in_corso()
        resp = self._post(self.ext, "completa_do", esito_do="SI")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._reload().stato, "DO_IN_CORSO")

    def test_controllore_check_positivo(self):
        self._fino_a_do_in_corso()
        self.seg.completa_do("SI"); self.seg.avvia_check(); self.seg.save()
        resp = self._post(self.ctrl, "check_positivo", check_testo="ok")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._reload().stato, "CHECK_COMPLETATO")

    def test_transizione_non_consentita_gestita(self):
        # avvia_check quando lo stato non lo consente → messaggio, stato invariato
        self._fino_a_do_in_corso()  # DO_IN_CORSO, non DO_COMPLETATO
        resp = self._post(self.team, "avvia_check")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._reload().stato, "DO_IN_CORSO")

    def test_ciclo_completo_via_http_fino_a_chiusa(self):
        self._a_da_classificare()  # INSERITA→DA_CLASSIFICARE (automatico alla creazione)
        self.client.force_login(self.team)

        def post(name, **d):
            return self.client.post(reverse(f"suggestion_corner:{name}", args=[self.seg.pk]), d)

        post("classifica", stato_sms="SMS_SI")
        d1 = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
        post("definisci_plan", incaricato=self.inc.pk, controllore=self.ctrl.pk,
             data_limite_esecuzione=d1, data_limite_controllo=d1)
        post("avvia_do")
        post("completa_do", esito_do="SI")
        post("avvia_check")
        post("check_positivo")
        post("chiudi")
        self.assertEqual(self._reload().stato, "CHIUSA")
