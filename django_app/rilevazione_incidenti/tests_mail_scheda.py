from datetime import datetime
from io import StringIO

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from automazioni.models import EmailInviata

from .mail_scheda import componi
from .models import RilevazioneIncidente


class MailSchedaSegnalazioneTests(TestCase):
    def setUp(self):
        self.r = RilevazioneIncidente.objects.create(
            nominativo="Persona Prova",
            tipologia_scheda="Early Warning",
            reparto="REPARTO TEST",
            data_segnalazione=timezone.make_aware(datetime(2026, 11, 10, 9, 30)),
            descrizione_avvenimento="Avvenimento <di prova>",
            causa_evento="Causa sintetica",
            why_1="Primo perché",
        )

    def test_componi_scheda_completa(self):
        m = componi(self.r)
        self.assertEqual(m["oggetto"], f"[Sicurezza] Segnalazione di sicurezza #{self.r.pk} (Early Warning) - REPARTO TEST")
        self.assertIn("Persona Prova", m["testo"])
        self.assertIn("Avvenimento &lt;di prova&gt;", m["frammento"])
        self.assertIn("1° perché", m["testo"])
        self.assertIn("Stato: Aperto", m["testo"])

    def test_senza_nominativo_toglie_nome_e_descrizione(self):
        m = componi(self.r, con_nominativo=False)
        self.assertNotIn("Persona Prova", m["testo"] + m["frammento"])
        self.assertNotIn("Avvenimento", m["testo"])
        self.assertIn("Causa sintetica", m["testo"])

    def test_comando_invia_e_registra(self):
        out = StringIO()
        call_command("invia_mail_segnalazione", str(self.r.pk), "--to", "rls@test.local", "--cc", "rspp@test.local", stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["rls@test.local"])
        self.assertEqual(msg.cc, ["rspp@test.local"])
        self.assertIn("NOVICROM", msg.alternatives[0][0])
        self.assertTrue(EmailInviata.objects.filter(oggetto=msg.subject).exists())

    def test_dry_run_non_invia(self):
        out = StringIO()
        call_command("invia_mail_segnalazione", str(self.r.pk), "--to", "rls@test.local", "--dry-run", stdout=out)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("Oggetto: [Sicurezza]", out.getvalue())

    def test_errori_di_input(self):
        with self.assertRaises(CommandError):
            call_command("invia_mail_segnalazione", "999999", "--to", "rls@test.local", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("invia_mail_segnalazione", str(self.r.pk), "--to", "non-una-mail", stdout=StringIO())


class FlussoSchedaSegnalazioneTests(TestCase):
    def setUp(self):
        self.r = RilevazioneIncidente.objects.create(nominativo="Persona Prova", tipologia_scheda="Near Miss", reparto="R1")

    def test_alla_creazione_parte_al_rspp_di_base(self):
        from .mail_scheda import dopo_creazione

        with self.captureOnCommitCallbacks(execute=True):
            dopo_creazione(self.r.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["rspp@costruzioninovicrom.it"])

    def test_destinatari_dal_pannello_e_vuoto_non_parte(self):
        from automazioni.mail_modulo import salva
        from core.models import SiteConfig

        from .mail_scheda import invia_alla_creazione

        salva("sicurezza_scheda_segnalazione", {"mod__sc:sicurezza_scheda_segnalazione_emails": "a@test.local; b@test.local"})
        self.assertEqual(SiteConfig.get("sicurezza_scheda_segnalazione_emails"), "a@test.local, b@test.local")
        invia_alla_creazione(self.r.pk)
        self.assertEqual(mail.outbox[0].to, ["a@test.local", "b@test.local"])
        SiteConfig.set("sicurezza_scheda_segnalazione_emails", "")
        self.assertEqual(invia_alla_creazione(self.r.pk), 0)
        self.assertEqual(len(mail.outbox), 1)
