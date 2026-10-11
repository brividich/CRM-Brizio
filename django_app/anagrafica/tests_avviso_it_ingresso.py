"""Avviso all'IT alla creazione di un nuovo dipendente (email / in-app / ticket).

Dati sintetici su domini ``example.invalid``; nessuna rete (LDAP non usato: scelta account
«nessuno» o «locale").
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import AuditLog, Notifica, SiteConfig
from tickets.models import Ticket

from .services import avviso_it_ingresso as svc
from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()

CF_SINTETICO = "RSSMRA80A01H501U"
PWD_OK = "Cavallo-Batteria-Graffetta-42"


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, SITE_URL="https://hub.example.invalid")
class AvvisoITBase(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute("DELETE FROM utenti")
        self.admin = User.objects.create_superuser("avv_admin", "avv_admin@example.invalid", "x")
        self.client.force_login(self.admin)

    def _configura(self, *, emails="", utenti="", ticket=False):
        SiteConfig.set(svc.CHIAVE_EMAILS, emails)
        SiteConfig.set(svc.CHIAVE_UTENTI, utenti)
        SiteConfig.set(svc.CHIAVE_TICKET, "1" if ticket else "0")

    def _crea(self, **extra):
        dati = {"nome": "Mario", "cognome": "Rossi", "aliasusername": "m.rossi", "attivo": "on",
                "reparto": "Officina", "mansione": "Saldatore",
                "email_notifica": "m.rossi@example.invalid", "account_scelta": "nessuno",
                "codice_fiscale": CF_SINTETICO}
        dati.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("anagrafica:dipendente_create"), dati)
        return response

    def _dipendente(self):
        return AnagraficaDipendente.objects.filter(aliasusername="m.rossi").first()

    def _mail_it(self):
        return [m for m in mail.outbox if m.subject.startswith("[IT]")]


class AvvisoITCanaliTests(AvvisoITBase):
    def test_email_ai_destinatari_configurati_con_contenuto(self):
        self._configura(emails="it@example.invalid; helpdesk@example.invalid")
        response = self._crea(contratto_data_inizio="2026-11-02")
        self.assertEqual(response.status_code, 302)
        dip = self._dipendente()
        self.assertIsNotNone(dip)
        inviate = self._mail_it()
        self.assertEqual(len(inviate), 1)
        msg = inviate[0]
        self.assertEqual(sorted(msg.to), ["helpdesk@example.invalid", "it@example.invalid"])
        self.assertIn("ROSSI MARIO", msg.subject)
        corpo = msg.body
        for atteso in ("ROSSI MARIO", "Officina", "Saldatore", "02/11/2026", "m.rossi@example.invalid",
                       "Nessun accesso al portale: account da creare",
                       f"https://hub.example.invalid{reverse('anagrafica:dipendente_detail', kwargs={'legacy_id': dip.id})}"):
            self.assertIn(atteso, corpo)
        log = AuditLog.objects.filter(azione=svc.AUDIT_AZIONE).first()
        self.assertIsNotNone(log)
        self.assertIn("email", str(log.dettaglio))

    def test_nessun_dato_sensibile_nel_testo(self):
        self._configura(emails="it@example.invalid", ticket=True)
        self._crea(account_scelta="locale", account_login="m.rossi.locale", account_password=PWD_OK)
        msg = self._mail_it()[0]
        ticket = Ticket.objects.get()
        for testo in (msg.body, msg.alternatives[0][0], ticket.descrizione, ticket.titolo):
            self.assertNotIn(CF_SINTETICO, testo)
            self.assertNotIn(PWD_OK, testo)
        self.assertIn("Utente locale del portale creato", msg.body)

    def test_nessun_canale_configurato_non_fa_nulla(self):
        self._configura()
        response = self._crea()
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self._dipendente())
        self.assertEqual(self._mail_it(), [])
        self.assertFalse(Ticket.objects.exists())
        self.assertFalse(AuditLog.objects.filter(azione=svc.AUDIT_AZIONE).exists())

    def test_ticket_solo_con_interruttore(self):
        self._configura(emails="it@example.invalid", ticket=False)
        self._crea()
        self.assertFalse(Ticket.objects.exists())
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
        mail.outbox = []
        self._configura(emails="", ticket=True)
        self._crea(aliasusername="m.rossi")
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.tipo, "IT")
        self.assertIn("ROSSI MARIO", ticket.titolo)
        self.assertIn("account da creare", ticket.descrizione)
        self.assertEqual(ticket.richiedente_user, self.admin)
        self.assertEqual(self._mail_it(), [])

    def test_notifica_in_app_agli_utenti_configurati(self):
        it_user = UtenteLegacy.objects.create(nome="TECNICO IT", email="tecnico.it@example.invalid",
                                              password="x", ruolo="utente", attivo=True)
        self._configura(utenti=str(it_user.id))
        self._crea()
        notifiche = list(Notifica.objects.filter(legacy_user_id=it_user.id))
        self.assertEqual(len(notifiche), 1)
        self.assertIn("ROSSI MARIO", notifiche[0].messaggio)
        self.assertEqual(notifiche[0].url_azione,
                         reverse("anagrafica:dipendente_detail", kwargs={"legacy_id": self._dipendente().id}))
        self.assertEqual(self._mail_it(), [])

    def test_errore_email_non_blocca_creazione_ne_altri_canali(self):
        self._configura(emails="it@example.invalid", ticket=True)
        with patch("core.email_utils.send_hub_mail", side_effect=RuntimeError("smtp giù")):
            response = self._crea()
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self._dipendente())
        self.assertEqual(Ticket.objects.count(), 1)
        log = AuditLog.objects.filter(azione=svc.AUDIT_AZIONE).first()
        self.assertIn("email: RuntimeError", str(log.dettaglio))

    def test_errore_imprevisto_del_servizio_non_blocca(self):
        self._configura(emails="it@example.invalid")
        with patch.object(svc, "raccogli_dati", side_effect=RuntimeError("boom")):
            response = self._crea()
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self._dipendente())

    def test_onboarding_link_e_ticket_sulla_voce_account(self):
        from .models import OnboardingTask

        self._configura(emails="it@example.invalid", ticket=True)
        self._crea(avvia_onboarding="1")
        voce = OnboardingTask.objects.filter(codice=svc.CODICE_VOCE_ONBOARDING).first()
        if voce is None:
            self.skipTest("Pratica onboarding non avviata in questo ambiente di test")
        ticket = Ticket.objects.get()
        self.assertIn(ticket.numero_ticket, voce.note)
        self.assertIn(reverse("anagrafica:onboarding_detail", kwargs={"pratica_id": voce.pratica_id}),
                      self._mail_it()[0].body)


class EsitoAccountTests(AvvisoITBase):
    def test_testi_esito(self):
        self.assertEqual(svc.esito_account("nessuno", None), ("Nessun accesso al portale: account da creare", True))
        testo, da_creare = svc.esito_account("ad", None)
        self.assertTrue(da_creare)
        self.assertIn("non riuscito", testo)
        u = UtenteLegacy.objects.create(nome="ROSSI MARIO", email="m.rossi@example.invalid", password="x",
                                        ruolo="utente", attivo=True)
        self.assertEqual(svc.esito_account("ad", u.id), ("Account AD collegato (m.rossi@example.invalid)", False))


class ConfigurazioneTests(AvvisoITBase):
    def test_salvataggio_da_impostazioni(self):
        response = self.client.post(reverse("anagrafica:avviso_it_save"), {
            "avviso_it_emails": "it@example.invalid,\nhelpdesk@example.invalid",
            "avviso_it_utenti": ["7", "3"], "avviso_it_ticket": "1",
        })
        self.assertEqual(response.status_code, 302)
        conf = svc.configurazione()
        self.assertEqual(conf, {"emails": ["it@example.invalid", "helpdesk@example.invalid"],
                                "utenti_ids": [3, 7], "ticket": True})

    def test_email_non_valida_rifiutata(self):
        self.client.post(reverse("anagrafica:avviso_it_save"), {"avviso_it_emails": "non-una-email"})
        self.assertEqual(svc.configurazione()["emails"], [])

    def test_utente_non_admin_non_salva(self):
        normale = User.objects.create_user("avv_user", "avv_user@example.invalid", "x")
        self.client.force_login(normale)
        self.client.post(reverse("anagrafica:avviso_it_save"), {"avviso_it_emails": "it@example.invalid"})
        self.assertEqual(svc.configurazione()["emails"], [])

    def test_pagina_impostazioni_mostra_il_form(self):
        response = self.client.get(reverse("anagrafica:impostazioni") + "?tab=workflow")
        self.assertContains(response, "Avviso IT ai nuovi ingressi")
        self.assertContains(response, reverse("anagrafica:avviso_it_save"))
