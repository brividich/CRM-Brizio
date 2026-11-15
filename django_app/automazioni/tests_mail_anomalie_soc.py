"""Mail Anomalie e canali email SOC come flussi di Automazioni, con impostazioni condivise col modulo."""
from __future__ import annotations

from unittest import mock

from django.core import mail
from django.test import TestCase

from automazioni.event_notifications import ANOMALIE_MAIL_FLUSSI, codice_flusso_anomalie
from automazioni.managed_flows import catalog
from automazioni.models import EmailInviata


def _spegni(codice):
    from automazioni.models import ManagedFlow

    rule = ManagedFlow.objects.get(code=codice).rule
    rule.is_active = False
    rule.save(update_fields=["is_active"])


class CatalogoAnomalieSocTests(TestCase):
    def test_un_flusso_per_tipo_di_mail_e_uno_per_il_soc(self):
        cat = catalog()
        for kind, *_ in ANOMALIE_MAIL_FLUSSI:
            self.assertEqual(cat[codice_flusso_anomalie(kind)]["module"], "anomalie")
        self.assertEqual(codice_flusso_anomalie("tipo_sconosciuto"), "anomalie_mail_altro")
        self.assertIn("soc_notifiche_email", cat)


class MailAnomalieNelFlussoTests(TestCase):
    def setUp(self):
        from automazioni.managed_flows import install_flows

        install_flows()

    def _manda(self, kind="op_completato"):
        from anomalie.mail_action_service import send_and_log_email

        return send_and_log_email(kind=kind, subject="OP SYN-1 completato", body_text="Testo",
                                  body_html="<html><body><p>Testo</p></body></html>",
                                  to=["capo@test.local"], op_id="SYN-1")

    def test_flusso_acceso_manda_e_applica_le_regole(self):
        from automazioni.models import ScheduledMailText

        ScheduledMailText.objects.create(task_name="anomalie_mail_op_completato", aggiungi_cc="qualita@test.local")
        sent, row = self._manda()
        self.assertTrue(sent)
        self.assertIsNotNone(row)
        self.assertEqual(mail.outbox[0].to, ["capo@test.local"])
        self.assertEqual(mail.outbox[0].cc, ["qualita@test.local"])

    def test_flusso_spento_non_manda_e_non_ritenta(self):
        from anomalie.mail_log_models import AnomalieEmailLog

        _spegni("anomalie_mail_op_completato")
        sent, row = self._manda()
        self.assertEqual((sent, row), (True, None))
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(AnomalieEmailLog.objects.exists())
        riga = EmailInviata.objects.get()
        self.assertEqual(riga.esito, EmailInviata.ESITO_ERRORE)
        self.assertIn("flusso spento", riga.errore)
        # Gli altri tipi restano accesi.
        self._manda(kind="segnala_car")
        self.assertEqual(len(mail.outbox), 1)

    def test_errore_smtp_risale_come_prima(self):
        from anomalie.mail_action_service import send_and_log_email

        with mock.patch("django.core.mail.EmailMessage.send", side_effect=OSError("smtp giù")):
            with self.assertRaises(OSError):
                send_and_log_email(kind="conferma_aggiornamenti", subject="S", body_text="T", to=["a@test.local"])

    def test_reinvia_dal_log_non_passa_dal_flusso(self):
        from anomalie.mail_action_service import resend_logged_email

        _, row = self._manda()
        _spegni("anomalie_mail_op_completato")
        resend_logged_email(row)
        self.assertEqual(len(mail.outbox), 2)


class CanaliSocNelFlussoTests(TestCase):
    def setUp(self):
        from automazioni.managed_flows import install_flows
        from security.models import SecurityNotificationChannel

        install_flows()
        self.canale = SecurityNotificationChannel.objects.create(
            name="SOC email", channel_type="email", enabled=True, recipients="soc@test.local", cooldown_minutes=0)

    def _consegna(self):
        from security.services.notifications import _deliver_to_channel

        return _deliver_to_channel(self.canale, event_kind="new_alert", severity="critical", dedup_hash="h1",
                                   subject="Alert", body="Corpo", alert=None, ticket=None)

    def test_flusso_acceso_manda(self):
        log = self._consegna()
        self.assertEqual(log.outcome, "sent")
        self.assertEqual(mail.outbox[0].to, ["soc@test.local"])

    def test_flusso_spento_non_manda(self):
        from security.services.notifications import deliver_once

        _spegni("soc_notifiche_email")
        log = self._consegna()
        self.assertEqual(log.outcome, "cooldown")
        self.assertIn("Automazioni", log.error_message)
        self.assertIsNone(deliver_once(self.canale, event_kind="report", severity="info", dedup_hash="r1",
                                       subject="Report", body="Corpo"))
        self.assertEqual(len(mail.outbox), 0)


class ImpostazioniCondiviseTests(TestCase):
    def test_lista_anomalie_dai_due_lati(self):
        from anomalie.views import _load_anomalie_lists
        from automazioni.mail_modulo import campi, salva

        cambiati = salva("anomalie_mail_digest_settimanale",
                         {"mod__anom:escalation_supervisori": "sup1@test.local\nsup2@test.local"})
        self.assertEqual(cambiati, ["Lista «Supervisori»"])
        self.assertEqual(_load_anomalie_lists()["escalation_supervisori"], ["sup1@test.local", "sup2@test.local"])
        valori = {c["nome"]: c["valore"] for c in campi("anomalie_mail_ricorrenza_pn")["campi"]}
        self.assertEqual(valori["mod__anom:escalation_supervisori"], "sup1@test.local\nsup2@test.local")
        with self.assertRaises(ValueError):
            salva("anomalie_mail_digest_settimanale", {"mod__anom:escalation_supervisori": "non-una-mail"})

    def test_destinatari_canale_soc_dai_due_lati(self):
        from automazioni.mail_modulo import campi, salva
        from security.models import SecurityNotificationChannel

        c = SecurityNotificationChannel.objects.create(name="Canale prova", channel_type="email", recipients="a@test.local")
        SecurityNotificationChannel.objects.create(name="Teams", channel_type="teams_webhook")
        voce = campi("soc_notifiche_email")
        self.assertEqual([x["nome"] for x in voce["campi"]], [f"mod__soc:{c.pk}"])
        salva("soc_notifiche_email", {f"mod__soc:{c.pk}": "a@test.local; b@test.local"})
        c.refresh_from_db()
        self.assertEqual(c.recipients, "a@test.local\nb@test.local")

    def test_senza_canali_email_nessun_pannello(self):
        from automazioni.mail_modulo import campi

        self.assertIsNone(campi("soc_notifiche_email"))
