"""Configurazione mail per-task (destinatari SiteConfig + testo ScheduledMailText)."""
from __future__ import annotations


from django.contrib.auth import get_user_model
from django.core import mail
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

    def test_task_sconosciuto_redirige(self):
        r = self.client.get(reverse("admin_portale:automazioni_pianificati_mail",
                                    kwargs={"name": "non_esiste"}))
        self.assertEqual(r.status_code, 302)

    def test_task_senza_elenco_fisso_mostra_solo_info(self):
        r = self.client.get(reverse("admin_portale:automazioni_pianificati_mail",
                                    kwargs={"name": "tickets_daily_digest"}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Assegnatari dei ticket")
        self.assertNotContains(r, 'name="recipients"')

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


class PannelloLateraleTests(TestCase):
    """Pannello «Mail, destinatari e orario» aperto da Pianificati e dal designer."""

    def setUp(self):
        from automazioni.managed_flows import install_flows
        install_flows()
        self.admin = User.objects.create_superuser("amp_admin", "amp@x.local", "x")
        self.client.force_login(self.admin)

    def _url(self, name="visite_expiry_reminders", which="automazioni_pianificati_mail"):
        return reverse(f"admin_portale:{which}", kwargs={"name": name})

    def test_cron_con_orario_mantiene_i_giorni(self):
        from automazioni.mail_config import cron_con_orario, orario_da_cron
        self.assertEqual(cron_con_orario("30 7 * * 1-5", "08:15"), "15 8 * * 1-5")
        self.assertEqual(orario_da_cron("*/5 * * * *"), "")
        with self.assertRaises(ValueError):
            cron_con_orario("30 7 * * *", "25:00")
        with self.assertRaises(ValueError):
            cron_con_orario("*/5 * * * *", "08:00")

    def test_htmx_restituisce_solo_il_pannello(self):
        r = self.client.get(self._url(), HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "data-amp-panel")
        self.assertContains(r, 'name="orario"')
        self.assertContains(r, 'name="recipients"')
        self.assertNotContains(r, "<html")

    def test_salva_orario_aggiorna_il_flusso(self):
        from automazioni.mail_config import orario_da_cron
        from automazioni.models import ManagedFlow
        binding = ManagedFlow.objects.get(code="visite_expiry_reminders")
        giorni = binding.cron.split()[2:]
        r = self.client.post(self._url(which="automazioni_pianificati_mail_save"), {"orario": "06:05"})
        self.assertEqual(r.status_code, 302)
        binding.refresh_from_db()
        self.assertEqual(orario_da_cron(binding.cron), "06:05")
        self.assertEqual(binding.cron.split()[2:], giorni)

    def test_salva_solo_orario_non_tocca_destinatari(self):
        SiteConfig.set("visite_reminder_emails", "a@x.local")
        self.client.post(self._url(which="automazioni_pianificati_mail_save"), {"orario": "06:05"})
        self.assertEqual(SiteConfig.get("visite_reminder_emails"), "a@x.local")

    def test_next_interno_rispettato_esterno_ignorato(self):
        url = self._url(which="automazioni_pianificati_mail_save")
        r = self.client.post(url, {"next": "/admin-portale/automazioni/regole/1/designer/"})
        self.assertEqual(r["Location"], "/admin-portale/automazioni/regole/1/designer/")
        r = self.client.post(url, {"next": "https://esterno.example/x"})
        self.assertIn(reverse("admin_portale:automazioni_pianificati"), r["Location"])

    def test_pianificati_ha_pulsante_modifica(self):
        r = self.client.get(reverse("admin_portale:automazioni_pianificati"))
        self.assertContains(r, 'id="amp-drawer"')
        self.assertContains(r, 'hx-target="#amp-drawer-body"')

    def test_designer_mostra_mail_e_destinatari_del_processo(self):
        from automazioni.models import ManagedFlow
        SiteConfig.set("visite_reminder_emails", "rspp@x.local")
        binding = ManagedFlow.objects.get(code="visite_expiry_reminders")
        r = self.client.get(reverse("admin_portale:automazioni_rule_designer", kwargs={"rule_id": binding.rule_id}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Modifica mail, destinatari e orario")
        self.assertContains(r, "Destinatari: rspp@x.local")
        self.assertContains(r, 'id="native-preview"')
