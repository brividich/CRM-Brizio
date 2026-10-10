"""Promemoria micro-corsi e-learning da completare (send_elearning_reminders).

Verifica il service hook (notifica in-app) e il management command (digest HR +
notifica in-app per discente), sul pattern di send_visite_expiry_reminders.

Prompt 05, rilascio 1: la notifica va all'**utente del portale** collegato
all'anagrafica (prima riceveva l'id anagrafica come se fosse un id utente) e
solo per corsi e-learning pubblicati.
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
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import Notifica


def _corso_elearning(codice="ELE1", titolo="Sicurezza base e-learning", is_active=True):
    from django.utils import timezone
    from anagrafica.models_formazione import TrainingCompletionRule
    piano = TrainingPlan.objects.create(codice=f"P{codice}", nome=f"Piano {codice}")
    corso = TrainingCourse.objects.create(
        piano=piano, codice=codice, titolo=titolo, durata_ore_teorica=2, is_active=is_active,
        is_elearning=True, stato="ATTIVO",
    )
    TrainingCompletionRule.objects.create(corso=corso, confermata_rspp_il=timezone.now())
    return corso


def _dipendente(nome: str) -> tuple[int, int]:
    """(legacy_anagrafica_id, utenti.id) di un dipendente sintetico con account."""
    utente = UtenteLegacy.objects.create(nome=nome, email=f"{nome}@example.invalid", password="x")
    dip = AnagraficaDipendente.objects.create(nome="Nome", cognome=nome, aliasusername=nome, utente=utente)
    return dip.id, utente.id


class ElearningServiceHookTests(TestCase):
    def test_notify_promemoria_crea_notifica_all_utente(self):
        corso = _corso_elearning()
        lid, uid = _dipendente("hook.el")
        notify_promemoria_da_completare(corso.id, lid)
        n = Notifica.objects.filter(legacy_user_id=uid)
        self.assertEqual(n.count(), 1)
        self.assertIn(corso.titolo, n.first().messaggio)


class ElearningReminderCommandTests(TestCase):
    def test_invia_digest_e_notifica_per_iscrizioni_da_completare(self):
        corso = _corso_elearning()
        (l1, u1), (l2, u2), (l3, u3) = _dipendente("a.el"), _dipendente("b.el"), _dipendente("c.el")
        TrainingElearningEnrollment.objects.create(corso=corso, legacy_anagrafica_id=l1, stato="ISCRITTO")
        TrainingElearningEnrollment.objects.create(corso=corso, legacy_anagrafica_id=l2, stato="IN_CORSO")
        # completato: NON deve rientrare
        TrainingElearningEnrollment.objects.create(corso=corso, legacy_anagrafica_id=l3, stato="COMPLETATO")

        out = StringIO()
        call_command("send_elearning_reminders", recipients=["hr@x.local"], stdout=out)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["hr@x.local"])
        self.assertEqual(Notifica.objects.filter(legacy_user_id=u1).count(), 1)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=u2).count(), 1)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=u3).count(), 0)

    def test_noop_senza_iscrizioni_da_completare(self):
        corso = _corso_elearning()
        lid, _uid = _dipendente("noop.el")
        TrainingElearningEnrollment.objects.create(corso=corso, legacy_anagrafica_id=lid, stato="COMPLETATO")
        out = StringIO()
        call_command("send_elearning_reminders", recipients=["hr@x.local"], stdout=out)
        self.assertEqual(len(mail.outbox), 0)
