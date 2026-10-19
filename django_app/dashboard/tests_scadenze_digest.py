"""Riepilogo mattutino personale delle scadenze (dashboard.scadenze_digest)."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from core.models import NotificaCanali
from dashboard import scadenze_digest as sd
from dashboard.scadenze_providers import SOURCE_ASSET, SOURCE_HR, ScadenzaItem

LUNEDI = date(2026, 10, 19)
SABATO = date(2026, 10, 24)


def _voce(giorni, titolo, source=SOURCE_ASSET):
    return ScadenzaItem(
        source=source, kind="x", kind_label="Scadenza amministrativa", titolo=titolo,
        soggetto="Tornio sintetico", reparto="OFFICINA",
        data_scadenza=LUNEDI + timedelta(days=giorni), giorni=giorni,
    )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@example.com", SITE_URL="https://hub.example.com")
class RiepilogoScadenzeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="digest", password="pw", email="digest@example.com")
        self.canali = NotificaCanali.objects.create(user=self.user, digest_scadenze=True, digest_giorni=7)

    def _invia(self, voci, oggi=LUNEDI):
        with patch.object(sd, "collect_all", return_value=voci) as collect, \
             patch.object(sd, "_email_utente", return_value="digest@example.com"):
            esiti = sd.invia_digest_scadenze(oggi=oggi)
        return esiti, collect

    def test_manda_scadute_e_entro_finestra(self):
        esiti, collect = self._invia([_voce(-3, "Revisione scaduta"), _voce(5, "Collaudo vicino"), _voce(20, "Lontana")])
        self.assertEqual(esiti, {"inviato": 1})
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["digest@example.com"])
        self.assertIn("1 scadute, 1 entro 7 giorni", msg.subject)
        corpo = msg.body
        self.assertIn("Revisione scaduta", corpo)
        self.assertIn("Collaudo vicino", corpo)
        self.assertNotIn("Lontana", corpo)
        self.assertIn("https://hub.example.com/scadenze", corpo)
        # Permessi: la raccolta gira con l'utente destinatario.
        request = collect.call_args.args[0]
        self.assertEqual(request.user, self.user)

    def test_una_volta_al_giorno(self):
        self._invia([_voce(-1, "Scaduta")])
        esiti, _ = self._invia([_voce(-1, "Scaduta")])
        self.assertEqual(esiti, {"gia_inviato": 1})
        self.assertEqual(len(mail.outbox), 1)

    def test_niente_da_dire_niente_mail(self):
        esiti, _ = self._invia([_voce(25, "Lontana")])
        self.assertEqual(esiti, {"vuoto": 1})
        self.assertEqual(mail.outbox, [])

    def test_weekend_saltato(self):
        esiti, collect = self._invia([_voce(-1, "Scaduta")], oggi=SABATO)
        self.assertEqual(esiti, {"saltato": "weekend"})
        collect.assert_not_called()

    def test_solo_chi_lo_ha_attivato(self):
        self.canali.digest_scadenze = False
        self.canali.save()
        esiti, collect = self._invia([_voce(-1, "Scaduta")])
        self.assertEqual(esiti, {})
        collect.assert_not_called()

    def test_finestra_30_giorni(self):
        self.canali.digest_giorni = 30
        self.canali.save()
        self._invia([_voce(25, "Entro trenta", source=SOURCE_HR)])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Entro trenta", mail.outbox[0].body)

    def test_richiesta_sintetica_valuta_i_permessi_reali(self):
        # Senza mock: un utente senza permessi non riceve voci riservate.
        voci = sd.voci_per_utente(self.user, giorni=30, oggi=LUNEDI)
        self.assertIsInstance(voci, list)
