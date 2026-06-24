"""Test F4 — timer/scadenze e notifiche (clock mockato) + pausa/ripresa."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from gestione_specifiche import constants as C
from gestione_specifiche.models import EventoSpecifica, MOD133, Specifica
from gestione_specifiche.scadenze import (
    esegui_verifica_periodica, invia_escalation_mod133, invia_reminder_mod133,
)

User = get_user_model()


class ScadenzeBase(TestCase):
    def setUp(self):
        self.dm = User.objects.create_user("dm", email="dm@x.it", password="x")
        self.comp = User.objects.create_user("comp", email="comp@x.it", password="x")
        self.appr = User.objects.create_user("appr", email="appr@x.it", password="x")

    def _avvia(self, codice="SP-T"):
        spec = Specifica.objects.create(codice=codice, titolo="T")
        spec.avvia_flow_down(attore=self.dm)
        spec.save()
        return spec, MOD133.objects.get(specifica=spec)

    def _in_validita(self, codice="SP-V"):
        spec, mod = self._avvia(codice)
        mod.compilatore = self.comp
        mod.approvatore = self.appr
        mod.esito = C.ESITO_APPROVATO
        mod.save()
        spec.approva_flow_down(attore=self.appr)
        spec.save()
        return spec


class ReminderTests(ScadenzeBase):
    def test_reminder_dopo_7_giorni(self):
        spec, mod = self._avvia("SP-R1")
        future = mod.timer_anchor + timedelta(days=8)
        res = invia_reminder_mod133(now=future)
        self.assertEqual(res["reminder_inviati"], 1)
        mod = MOD133.objects.get(pk=mod.pk)
        self.assertTrue(mod.reminder_inviato)
        self.assertTrue(spec.eventi.filter(trigger="reminder_mod133").exists())
        # idempotente
        self.assertEqual(invia_reminder_mod133(now=future)["reminder_inviati"], 0)

    def test_reminder_non_prima_di_7_giorni(self):
        spec, mod = self._avvia("SP-R2")
        res = invia_reminder_mod133(now=mod.timer_anchor + timedelta(days=3))
        self.assertEqual(res["reminder_inviati"], 0)

    def test_reminder_saltato_se_preso_in_carico(self):
        spec, mod = self._avvia("SP-R3")
        mod.compilatore = self.comp
        mod.save()
        res = invia_reminder_mod133(now=mod.timer_anchor + timedelta(days=10))
        self.assertEqual(res["reminder_inviati"], 0)

    def test_reminder_saltato_se_sospeso(self):
        spec, mod = self._avvia("SP-R4")
        spec.sospendi(attore=self.dm, motivo="x", data=timezone.now().date())
        spec.save()
        res = invia_reminder_mod133(now=mod.timer_anchor + timedelta(days=10))
        self.assertEqual(res["reminder_inviati"], 0)


class EscalationTests(ScadenzeBase):
    def test_escalation_dopo_14_giorni(self):
        spec, mod = self._avvia("SP-E1")
        res = invia_escalation_mod133(now=mod.timer_anchor + timedelta(days=15))
        self.assertEqual(res["escalation_inviate"], 1)
        mod = MOD133.objects.get(pk=mod.pk)
        self.assertTrue(mod.escalation_inviata)
        self.assertTrue(spec.eventi.filter(trigger="escalation_mod133").exists())

    def test_escalation_non_prima_di_14(self):
        spec, mod = self._avvia("SP-E2")
        res = invia_escalation_mod133(now=mod.timer_anchor + timedelta(days=10))
        self.assertEqual(res["escalation_inviate"], 0)


class VerificaPeriodicaTests(ScadenzeBase):
    def test_verifica_scaduta_notifica_e_avanza(self):
        spec = self._in_validita("SP-VP")
        oggi = timezone.now().date()
        spec.data_verifica = oggi
        spec.save(update_fields=["data_verifica"])
        res = esegui_verifica_periodica(now=timezone.now())
        self.assertEqual(res["verifiche_inviate"], 1)
        spec = Specifica.objects.get(pk=spec.pk)
        # avanzata di 6 mesi (ricorrente)
        self.assertGreater(spec.data_verifica, oggi)
        self.assertIsNotNone(spec.verifica_reminder_inviata_at)
        self.assertTrue(spec.eventi.filter(trigger="verifica_periodica").exists())

    def test_verifica_non_scaduta(self):
        spec = self._in_validita("SP-VP2")  # data_verifica = oggi + 6 mesi
        res = esegui_verifica_periodica(now=timezone.now())
        self.assertEqual(res["verifiche_inviate"], 0)


class PausaRipresaTests(ScadenzeBase):
    def test_pausa_sposta_la_scadenza(self):
        spec, mod = self._avvia("SP-P1")
        anchor0 = mod.timer_anchor

        # sospensione al giorno +3 (clock mockato sul modulo models)
        t_pause = anchor0 + timedelta(days=3)
        with patch("gestione_specifiche.models.timezone.now", return_value=t_pause):
            spec.sospendi(attore=self.dm, motivo="riesame", data=anchor0.date())
            spec.save()
        mod = MOD133.objects.get(pk=mod.pk)
        self.assertIsNotNone(mod.timer_pausa_at)

        # ripristino al giorno +10 → l'anchor scivola in avanti di 7 giorni
        t_resume = anchor0 + timedelta(days=10)
        with patch("gestione_specifiche.models.timezone.now", return_value=t_resume):
            spec.ripristina(attore=self.dm, motivo="ok")
            spec.save()
        mod = MOD133.objects.get(pk=mod.pk)
        self.assertIsNone(mod.timer_pausa_at)
        self.assertAlmostEqual(
            (mod.timer_anchor - anchor0).total_seconds(), timedelta(days=7).total_seconds(), delta=2,
        )

        # senza pausa il reminder sarebbe scattato a +9; con la pausa (anchor=+7) non ancora
        self.assertEqual(invia_reminder_mod133(now=anchor0 + timedelta(days=9))["reminder_inviati"], 0)
        # a +15 (elapsed attivo 8gg) scatta
        self.assertEqual(invia_reminder_mod133(now=anchor0 + timedelta(days=15))["reminder_inviati"], 1)
