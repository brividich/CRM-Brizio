"""Configurazione mail per-task (destinatari SiteConfig + testo ScheduledMailText)."""
from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from automazioni.mail_config import apply_mail_overrides
from automazioni.models import ScheduledMailText
from core.models import SiteConfig

User = get_user_model()


class ApplyMailOverridesTests(TestCase):
    def test_nessun_override_lascia_invariato(self):
        s, b, f, foot = apply_mail_overrides("visite_expiry_reminders",
                                             subject="Sub", body_text="Body", fragment="<p>x</p>")
        self.assertEqual((s, b, f, foot), ("Sub", "Body", "<p>x</p>", ""))

    def test_override_applica_oggetto_intro_footer(self):
        ScheduledMailText.objects.create(
            task_name="visite_expiry_reminders",
            subject="Oggetto custom", intro="Ciao team", footer="Cordiali saluti")
        s, b, f, foot = apply_mail_overrides("visite_expiry_reminders",
                                             subject="Sub", body_text="Body", fragment="<p>x</p>")
        self.assertEqual(s, "Oggetto custom")
        self.assertEqual(foot, "Cordiali saluti")
        self.assertIn("Ciao team", b)
        self.assertIn("Ciao team", f)  # intro anteposta al frammento HTML
        self.assertIn("<p>x</p>", f)


class MailConfigPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("mc_admin", "mc@x.local", "x")
        self.client.force_login(self.admin)

    def test_pagina_configurabile(self):
        r = self.client.get(reverse("admin_portale:automazioni_pianificati_mail",
                                    kwargs={"name": "visite_expiry_reminders"}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Destinatari")

    def test_task_non_configurabile_redirige(self):
        r = self.client.get(reverse("admin_portale:automazioni_pianificati_mail",
                                    kwargs={"name": "cleanup_run_logs"}))
        self.assertEqual(r.status_code, 302)

    def test_salva_destinatari_e_testo(self):
        r = self.client.post(
            reverse("admin_portale:automazioni_pianificati_mail_save",
                    kwargs={"name": "visite_expiry_reminders"}),
            {"recipients": "rspp@azienda.it, hr@azienda.it",
             "subject": "Nuovo oggetto", "intro": "Intro", "footer": ""},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SiteConfig.get("visite_reminder_emails"), "rspp@azienda.it, hr@azienda.it")
        txt = ScheduledMailText.objects.get(task_name="visite_expiry_reminders")
        self.assertEqual(txt.subject, "Nuovo oggetto")
        self.assertEqual(txt.intro, "Intro")

    def test_salva_testo_vuoto_rimuove_record(self):
        ScheduledMailText.objects.create(task_name="visite_expiry_reminders", subject="x")
        self.client.post(
            reverse("admin_portale:automazioni_pianificati_mail_save",
                    kwargs={"name": "visite_expiry_reminders"}),
            {"recipients": "", "subject": "", "intro": "", "footer": ""},
        )
        self.assertFalse(ScheduledMailText.objects.filter(task_name="visite_expiry_reminders").exists())


class MailTestPreviewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("mt_admin", "mt@x.local", "x")
        self.client.force_login(self.admin)

    def test_invia_anteprima_al_proprio_indirizzo(self):
        r = self.client.post(reverse("admin_portale:automazioni_pianificati_mail_test",
                                     kwargs={"name": "visite_expiry_reminders"}))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["mt@x.local"])
        self.assertIn("ANTEPRIMA", mail.outbox[0].subject)

    def test_anteprima_usa_override_oggetto(self):
        ScheduledMailText.objects.create(task_name="visite_expiry_reminders", subject="Oggetto mio")
        self.client.post(reverse("admin_portale:automazioni_pianificati_mail_test",
                                 kwargs={"name": "visite_expiry_reminders"}))
        self.assertEqual(mail.outbox[0].subject, "Oggetto mio")


class MailOverridesNoFragmentTests(TestCase):
    def test_intro_senza_frammento_va_nel_testo_non_nel_fragment(self):
        # dpi/assets non passano un fragment: l'intro deve finire nel body_text,
        # lasciando fragment vuoto (send_hub_mail lo auto-converte).
        ScheduledMailText.objects.create(task_name="dpi_expiry_reminders", intro="Nota DPI")
        s, b, f, foot = apply_mail_overrides("dpi_expiry_reminders",
                                             subject="Sub", body_text="Corpo", fragment="")
        self.assertIn("Nota DPI", b)
        self.assertEqual(f, "")  # nessun fragment iniettato
