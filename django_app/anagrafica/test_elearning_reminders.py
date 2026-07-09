"""Promemoria micro-corsi e-learning da completare (send_elearning_reminders).

Verifica il service hook (notifica in-app) e il management command (digest HR +
notifica in-app per iscritto), sul pattern di send_visite_expiry_reminders.
"""
from __future__ import annotations

from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from anagrafica.models_formazione import (
    TrainingCourse,
    TrainingElearningEnrollment,
    TrainingPlan,
)
from anagrafica.services.elearning_notifications import notify_promemoria_da_completare
from core.models import Notifica


def _corso_elearning(codice="ELE1", titolo="Sicurezza base e-learning", is_active=True):
    piano = TrainingPlan.objects.create(codice=f"P{codice}", nome=f"Piano {codice}")
    return TrainingCourse.objects.create(
        piano=piano, codice=codice, titolo=titolo,
        durata_ore_teorica=2, is_active=is_active,
    )


class ElearningServiceHookTests(TestCase):
    def test_notify_promemoria_crea_notifica_in_app(self):
        corso = _corso_elearning()
        notify_promemoria_da_completare(corso.id, 711)
        n = Notifica.objects.filter(legacy_user_id=711)
        self.assertEqual(n.count(), 1)
        self.assertIn(corso.titolo, n.first().messaggio)


class ElearningReminderCommandTests(TestCase):
    def test_invia_digest_e_notifica_per_iscrizioni_da_completare(self):
        corso = _corso_elearning()
        TrainingElearningEnrollment.objects.create(
            corso=corso, legacy_anagrafica_id=711, stato="ISCRITTO")
        TrainingElearningEnrollment.objects.create(
            corso=corso, legacy_anagrafica_id=712, stato="IN_CORSO")
        # completato: NON deve rientrare
        TrainingElearningEnrollment.objects.create(
            corso=corso, legacy_anagrafica_id=713, stato="COMPLETATO")

        out = StringIO()
        call_command("send_elearning_reminders", recipients=["hr@x.local"], stdout=out)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["hr@x.local"])
        # notifica in-app ai due iscritti da completare, non al completato
        self.assertEqual(Notifica.objects.filter(legacy_user_id=711).count(), 1)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=712).count(), 1)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=713).count(), 0)

    def test_noop_senza_iscrizioni_da_completare(self):
        corso = _corso_elearning()
        TrainingElearningEnrollment.objects.create(
            corso=corso, legacy_anagrafica_id=713, stato="COMPLETATO")
        out = StringIO()
        call_command("send_elearning_reminders", recipients=["hr@x.local"], stdout=out)
        self.assertEqual(len(mail.outbox), 0)
