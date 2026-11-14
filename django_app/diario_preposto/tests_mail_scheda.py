import tempfile
from datetime import datetime
from io import StringIO

from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from automazioni.models import EmailInviata

from .mail_scheda import componi
from .models import SegnalazioneAllegato, SegnalazionePreposto


class MailSchedaPrepostoTests(TestCase):
    def setUp(self):
        self.s = SegnalazionePreposto.objects.create(
            titolo="Titolo di prova",
            data_segnalazione=timezone.make_aware(datetime(2026, 11, 10, 8, 0)),
            descrizione="Descrizione\nsu due righe",
            preposto="Preposto Prova",
            chi_segnala="Segnalante Prova",
        )

    def test_componi_scheda(self):
        m = componi(self.s)
        self.assertEqual(m["oggetto"], f"[Sicurezza] Diario del preposto {self.s.codice_identificativo} - Titolo di prova")
        self.assertIn("Preposto Prova", m["testo"])
        self.assertIn("Descrizione<br>su due righe", m["frammento"])

    def test_comando_per_codice_invia_e_registra(self):
        call_command("invia_mail_preposto", self.s.codice_identificativo, "--to", "rspp@test.local", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["rspp@test.local"])
        self.assertTrue(EmailInviata.objects.filter(oggetto=mail.outbox[0].subject).exists())

    def test_allegati_elencati_e_allegati_su_richiesta(self):
        with tempfile.TemporaryDirectory() as cartella, override_settings(DIARIO_PREPOSTO_PRIVATE_ROOT=cartella):
            a = SegnalazioneAllegato(segnalazione=self.s, nome_file="documento.pdf")
            a.file.save("documento.pdf", ContentFile(b"contenuto sintetico"), save=True)
            self.assertIn("documento.pdf", componi(self.s)["testo"])
            call_command("invia_mail_preposto", str(self.s.pk), "--to", "rspp@test.local", "--allegati", stdout=StringIO())
        allegati = mail.outbox[0].attachments
        self.assertEqual([x[0] for x in allegati], ["documento.pdf"])
        self.assertEqual(allegati[0][1], b"contenuto sintetico")

    def test_dry_run_e_errori(self):
        out = StringIO()
        call_command("invia_mail_preposto", str(self.s.pk), "--to", "rspp@test.local", "--dry-run", stdout=out)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("Oggetto:", out.getvalue())
        with self.assertRaises(CommandError):
            call_command("invia_mail_preposto", "DP-1999-9999", "--to", "rspp@test.local", stdout=StringIO())


class FlussoSchedaPrepostoTests(TestCase):
    def test_alla_creazione_parte_al_rspp_di_base(self):
        from .mail_scheda import dopo_creazione

        s = SegnalazionePreposto.objects.create(
            titolo="T", data_segnalazione=timezone.make_aware(datetime(2026, 11, 10, 8, 0)), descrizione="D")
        with self.captureOnCommitCallbacks(execute=True):
            dopo_creazione(s.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["rspp@costruzioninovicrom.it"])
