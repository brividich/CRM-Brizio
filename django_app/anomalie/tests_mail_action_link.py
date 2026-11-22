"""Link mail delle anomalie: impronta del segreto, link superati, scadenza, tentativi.

Il link resta senza login: questi test fissano le protezioni che lo circondano.
"""
from __future__ import annotations

import hashlib
import importlib
from datetime import timedelta

from django.apps import apps
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie.mail_action_models import AnomaliaMailActionToken, hash_token
from anomalie.mail_action_service import DURATA_LINK_ORE, send_anomalie_action_email
from anomalie.mail_action_views import LIMITE_LINK_ERRATI

OP = "OP-SINT-LINK"
RIGHE = [{"id": 1, "descrizione": "Quota fuori tolleranza", "avanzamento": "In attesa", "seriale": "SN-0001"}]


def _token(**extra):
    dati = {
        "recipient_email": "cc@example.local", "recipient_display": "Capocommessa Prova", "op_id": OP,
        "anomalie_ids": [1], "anomalie_snapshot": RIGHE, "action": "visualizza",
        "expires_at": timezone.now() + timedelta(hours=DURATA_LINK_ORE),
    }
    dati.update(extra)
    return AnomaliaMailActionToken.objects.create(**dati)


def _invia(email="cc@example.local", op=OP, action="visualizza", ore=DURATA_LINK_ORE):
    return send_anomalie_action_email(
        recipient_email=email, recipient_display="Capocommessa Prova", op_id=op, op_nominativo=op,
        anomalie_rows=RIGHE, action=action, expires_hours=ore, site_url="https://hub.example.local",
    )


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ImprontaDelSegretoTests(TestCase):
    def test_nel_database_resta_solo_l_impronta(self):
        token = _token()
        segreto = token.token
        self.assertGreaterEqual(len(segreto), 32)
        salvato = AnomaliaMailActionToken.objects.get(pk=token.pk)
        self.assertEqual(salvato.token_hash, hashlib.sha256(segreto.encode()).hexdigest())
        self.assertEqual(salvato.token, "")
        self.assertNotIn(segreto, str(AnomaliaMailActionToken.objects.filter(pk=token.pk).values().first()))

    def test_il_segreto_dell_url_ritrova_il_token(self):
        token = _token()
        trovato = AnomaliaMailActionToken.per_segreto(token.token)
        self.assertEqual(trovato.pk, token.pk)
        self.assertEqual(trovato.token, token.token)
        self.assertIsNone(AnomaliaMailActionToken.per_segreto(token.token_hash))
        self.assertIsNone(AnomaliaMailActionToken.per_segreto(""))

    def test_la_mail_porta_il_segreto_e_la_pagina_si_apre(self):
        token = _invia()
        self.assertIn(f"/gestione-anomalie/mail-action/{token.token}/", mail.outbox[0].body)
        self.assertNotIn(token.token_hash, mail.outbox[0].body)

    def test_la_migrazione_trasforma_i_segreti_gia_salvati_una_volta_sola(self):
        token = _token()
        vecchio = "segreto-sintetico-di-una-mail-gia-inviata-0123"
        AnomaliaMailActionToken.objects.filter(pk=token.pk).update(token_hash=vecchio)
        migrazione = importlib.import_module("anomalie.migrations.0032_mail_action_token_hash")
        migrazione._impronte(apps, None)
        token.refresh_from_db()
        self.assertEqual(token.token_hash, hash_token(vecchio))
        migrazione._impronte(apps, None)
        token.refresh_from_db()
        self.assertEqual(token.token_hash, hash_token(vecchio))
        self.assertEqual(AnomaliaMailActionToken.per_segreto(vecchio).pk, token.pk)


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ScadenzaERevocaTests(TestCase):
    def test_il_riepilogo_rispetta_scadenza_e_revoca(self):
        token = _token()
        url = reverse("anomalie_mail_action_done", kwargs={"token": token.token})
        self.assertEqual(self.client.get(url).status_code, 200)
        AnomaliaMailActionToken.objects.filter(pk=token.pk).update(is_revoked=True)
        self.assertEqual(self.client.get(url).status_code, 410)
        AnomaliaMailActionToken.objects.filter(pk=token.pk).update(
            is_revoked=False, expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(url).status_code, 410)

    def test_la_mail_nuova_revoca_i_link_non_usati_della_stessa_persona_sullo_stesso_op(self):
        primo = _invia()
        altra_persona = _invia(email="car@example.local")
        altro_op = _invia(op="OP-SINT-ALTRO")
        altra_azione = _invia(action="aggiorna_avanzamento")
        usato = _token(is_used=True)
        secondo = _invia(email="CC@example.local")
        stato = lambda t: AnomaliaMailActionToken.objects.get(pk=t.pk).is_revoked  # noqa: E731
        self.assertTrue(stato(primo))
        for intatto in (altra_persona, altro_op, altra_azione, usato, secondo):
            self.assertFalse(stato(intatto))
        risposta = self.client.get(reverse("anomalie_mail_action", kwargs={"token": primo.token}))
        self.assertEqual(risposta.status_code, 410)
        self.assertContains(risposta, "ultima mail ricevuta", status_code=410)

    def test_senza_op_non_si_revoca_niente(self):
        primo = _invia(op="")
        _invia(op="")
        self.assertFalse(AnomaliaMailActionToken.objects.get(pk=primo.pk).is_revoked)

    def test_il_link_dura_almeno_una_settimana(self):
        self.assertEqual(DURATA_LINK_ORE, 168)
        token = _invia(ore=24)
        self.assertGreater(token.expires_at, timezone.now() + timedelta(hours=167))
        lungo = _invia(op="OP-SINT-LUNGO", ore=336)
        self.assertGreater(lungo.expires_at, timezone.now() + timedelta(hours=335))


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class LinkErratiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _apri(self, segreto, ip):
        return self.client.get(reverse("anomalie_mail_action", kwargs={"token": segreto}), REMOTE_ADDR=ip)

    def test_troppi_link_inesistenti_dallo_stesso_indirizzo_fermano_la_ricerca(self):
        buono = _token()
        for n in range(LIMITE_LINK_ERRATI):
            self.assertEqual(self._apri(f"inesistente-{n}", "10.0.0.9").status_code, 400)
        self.assertEqual(self._apri("inesistente-ancora", "10.0.0.9").status_code, 429)
        self.assertEqual(self._apri(buono.token, "10.0.0.9").status_code, 429)
        self.assertEqual(self._apri(buono.token, "10.0.0.10").status_code, 200)

    def test_i_link_buoni_non_consumano_tentativi(self):
        buono = _token()
        for _ in range(LIMITE_LINK_ERRATI + 5):
            self.assertEqual(self._apri(buono.token, "10.0.0.11").status_code, 200)

    def test_un_indirizzo_che_non_distingue_i_client_non_viene_bloccato(self):
        for n in range(LIMITE_LINK_ERRATI + 2):
            self.assertEqual(self._apri(f"inesistente-{n}", "127.0.0.1").status_code, 400)
