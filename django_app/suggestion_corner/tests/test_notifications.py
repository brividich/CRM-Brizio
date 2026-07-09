"""Test notifiche email Suggestion Corner (sessione 5)."""
from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig
from suggestion_corner import notifications as N

User = get_user_model()


class NotificheEmailTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.m1 = User.objects.create_user(username="t1", password="x", email="t1@x.it")
        self.m2 = User.objects.create_user(username="t2", password="x", email="t2@x.it")
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.m1.groups.add(g); self.m2.groups.add(g)

    def test_team_emails(self):
        self.assertCountEqual(N.team_emails(), ["t1@x.it", "t2@x.it"])

    def test_mail_team_nuova(self):
        seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Migliorare.",
        )
        mail.outbox = []
        N.notifica_team_nuova_segnalazione(seg)
        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(mail.outbox[0].to, ["t1@x.it", "t2@x.it"])
        self.assertIn(f"SC#{seg.pk}", mail.outbox[0].subject)


class ReminderCommandTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="CNC")
        self.inc = User.objects.create_user(username="inc", password="x", email="inc@x.it")
        self.ctrl = User.objects.create_user(username="ctrl", password="x", email="ctrl@x.it")

    def _do_in_corso(self, giorni_alla_scadenza):
        seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="X.", incaricato=self.inc,
        )
        seg.notifica_sms_team(); seg.classifica("SMS_SI")
        d = datetime.date.today() + datetime.timedelta(days=giorni_alla_scadenza)
        seg.definisci_plan(incaricato=self.inc, controllore=self.ctrl,
                           data_limite_esecuzione=d, data_limite_controllo=d)
        seg.avvia_do(); seg.save()
        return seg

    def test_sollecito_do_inviato_e_flag_settato(self):
        seg = self._do_in_corso(3)  # entro la soglia 5
        mail.outbox = []
        call_command("send_suggestion_corner_reminders")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["inc@x.it"])
        seg2 = SuggestionCorner.objects.get(pk=seg.pk)
        self.assertTrue(seg2.sollecito_do_5)

    def test_sollecito_non_reinviato(self):
        self._do_in_corso(3)
        call_command("send_suggestion_corner_reminders")
        mail.outbox = []
        call_command("send_suggestion_corner_reminders")  # secondo run
        self.assertEqual(len(mail.outbox), 0)

    def test_escalation_oltre_scadenza(self):
        seg = self._do_in_corso(-20)  # scaduta da 20 giorni (> soglia escalation 7)
        cfg = SuggestionCornerConfig.load()
        cfg.email_responsabile_escalation = "capo@x.it"
        cfg.save()
        mail.outbox = []
        call_command("send_suggestion_corner_reminders")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["capo@x.it"])
        self.assertTrue(SuggestionCorner.objects.get(pk=seg.pk).escalation_do_inviata)
