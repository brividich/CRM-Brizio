"""Test della comunicazione al cliente per le segnalazioni SMS Sì."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Reparto
from core.models import UserOnboarding
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig

User = get_user_model()


def _onboard(user):
    UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())


@override_settings(LEGACY_AUTH_ENABLED=False, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ComunicazioneClienteTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.team = User.objects.create_user(username="team", password="x", email="team@x.it")
        self.ext = User.objects.create_user(username="ext", password="x")
        for u in (self.team, self.ext):
            _onboard(u)
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.team.groups.add(g)
        self.seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Migliorare.",
            stato_sms=SuggestionCorner.StatoSMS.SMS_SI,
        )

    def _url(self):
        return reverse("suggestion_corner:comunica_cliente", args=[self.seg.pk])

    def _reload(self):
        return SuggestionCorner.objects.get(pk=self.seg.pk)

    def test_team_invia_e_traccia(self):
        self.client.force_login(self.team)
        resp = self.client.post(self._url(), {
            "cliente_nome": "ACME SpA", "cliente_email": "qualita@acme.it",
            "messaggio": "In allegato le azioni intraprese.",
        })
        self.assertEqual(resp.status_code, 302)
        s = self._reload()
        self.assertTrue(s.comunicazione_cliente_inviata)
        self.assertIsNotNone(s.data_comunicazione_cliente)
        self.assertEqual(s.cliente_email, "qualita@acme.it")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("qualita@acme.it", mail.outbox[0].to)
        self.assertTrue(s.storico.filter(campo_modificato="comunicazione_cliente").exists())

    def test_non_sms_si_non_invia(self):
        self.seg.stato_sms = SuggestionCorner.StatoSMS.SMS_NO
        self.seg.save()
        self.client.force_login(self.team)
        resp = self.client.post(self._url(), {"cliente_email": "x@y.it"})
        self.assertEqual(resp.status_code, 302)  # redirect con errore
        s = self._reload()
        self.assertFalse(s.comunicazione_cliente_inviata)
        self.assertEqual(len(mail.outbox), 0)

    def test_estraneo_403(self):
        self.client.force_login(self.ext)
        resp = self.client.post(self._url(), {"cliente_email": "x@y.it"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_obbligatoria(self):
        self.client.force_login(self.team)
        resp = self.client.post(self._url(), {"cliente_nome": "ACME"})
        self.assertEqual(resp.status_code, 302)  # form non valido → redirect con messaggio
        s = self._reload()
        self.assertFalse(s.comunicazione_cliente_inviata)
        self.assertEqual(len(mail.outbox), 0)
