"""Reminder scadenze formazione obbligatoria (send_training_expiry_reminders).

Digest HR + notifica in-app al dipendente per i corsi obbligatori scaduti o in
scadenza, dalla cache TrainingDeadline. Pattern speculare a send_visite_expiry.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from anagrafica.models_formazione import TrainingCourse, TrainingDeadline, TrainingPlan
from core.models import Notifica


def _corso(codice="FORM1", titolo="Antincendio", is_active=True):
    piano = TrainingPlan.objects.create(codice=f"P{codice}", nome=f"Piano {codice}")
    return TrainingCourse.objects.create(
        piano=piano, codice=codice, titolo=titolo, durata_ore_teorica=8, is_active=is_active,
    )


def _deadline(corso, legacy_id, stato, giorni, is_required=True):
    today = timezone.localdate()
    scad = today + timedelta(days=giorni) if giorni is not None else None
    return TrainingDeadline.objects.create(
        corso=corso, legacy_anagrafica_id=legacy_id,
        stato_scadenza=stato, data_scadenza=scad,
        giorni_alla_scadenza=giorni, is_required=is_required,
    )


class TrainingExpiryCommandTests(TestCase):
    def test_digest_e_notifica_per_scadute_e_in_scadenza(self):
        corso = _corso()
        _deadline(corso, 711, "SCADUTO", -10)
        _deadline(corso, 712, "IN_SCADENZA_30", 12)
        _deadline(corso, 713, "VALIDO", 400)          # escluso
        _deadline(corso, 714, "IN_SCADENZA_30", 12, is_required=False)  # non obbligatorio → escluso

        out = StringIO()
        call_command("send_training_expiry_reminders", recipients=["hr@x.local"], stdout=out)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["hr@x.local"])
        self.assertEqual(Notifica.objects.filter(legacy_user_id=711).count(), 1)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=712).count(), 1)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=713).count(), 0)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=714).count(), 0)

    def test_in_scadenza_oltre_finestra_giorni_escluso(self):
        corso = _corso()
        _deadline(corso, 711, "IN_SCADENZA_90", 80)   # oltre --days=30
        out = StringIO()
        call_command("send_training_expiry_reminders", days=30,
                     recipients=["hr@x.local"], stdout=out)
        self.assertEqual(len(mail.outbox), 0)

    def test_noop_senza_scadenze(self):
        corso = _corso()
        _deadline(corso, 713, "VALIDO", 400)
        out = StringIO()
        call_command("send_training_expiry_reminders", recipients=["hr@x.local"], stdout=out)
        self.assertEqual(len(mail.outbox), 0)
