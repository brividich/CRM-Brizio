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
            {"mail_step": "1", "invia_mail": "1", "recipients": "rspp@azienda.it, hr@azienda.it",
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
            {"mail_step": "1", "invia_mail": "1", "recipients": "", "subject": "", "intro": "", "footer": ""},
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


class RicorrenzaTests(TestCase):
    def test_lettura_dei_calendari(self):
        from automazioni.ricorrenza import da_flusso
        r = da_flusso("C", 1, "30 7 * * 1-5")
        self.assertEqual((r["frequenza"], r["orario"]), ("giorno", "07:30"))
        self.assertEqual(r["giorni"], {"1", "2", "3", "4", "5"})
        self.assertEqual(da_flusso("C", 1, "0 8 1 * *")["frequenza"], "mese")
        self.assertEqual(da_flusso("C", 1, "40 7-19 * * 1-5")["frequenza"], "personalizzato")
        self.assertEqual(da_flusso("I", 15, "")["frequenza"], "minuti")
        self.assertEqual(da_flusso("C", 1, "0 9 * * 7")["giorni"], {"0"})

    def test_scrittura_dei_calendari(self):
        from django.http import QueryDict

        from automazioni.ricorrenza import a_flusso
        q = QueryDict(mutable=True)
        q.update({"frequenza": "giorno", "orario": "06:05"})
        q.setlist("giorni", ["1", "3", "5"])
        self.assertEqual(a_flusso(q), ("C", 1, "5 6 * * 1,3,5"))
        q.setlist("giorni", ["0", "1", "2", "3", "4", "5", "6"])
        self.assertEqual(a_flusso(q), ("C", 1, "5 6 * * *"))
        self.assertEqual(a_flusso({"frequenza": "mese", "orario": "08:00", "giorno_mese": "15"}), ("C", 1, "0 8 15 * *"))
        self.assertEqual(a_flusso({"frequenza": "minuti", "minuti": "20"}), ("I", 20, ""))
        self.assertEqual(a_flusso({"frequenza": "personalizzato", "cron": "40  7-19 * * 1-5"}), ("C", 1, "40 7-19 * * 1-5"))
        for cattivo in ({"frequenza": "minuti", "minuti": "0"}, {"frequenza": "mese", "orario": "25:00", "giorno_mese": "1"},
                        {"frequenza": "personalizzato", "cron": "x"}, {"frequenza": "giorno", "orario": "07:00"}):
            with self.assertRaises(ValueError):
                a_flusso(cattivo)


class PassaggioMailTests(TestCase):
    """Regole del passaggio «Invia mail» applicate da send_hub_mail dentro un flusso gestito."""

    def _invia_nel_flusso(self, codice, **kw):
        from automazioni import managed_flows
        from core.email_utils import send_hub_mail
        token = managed_flows._invocation.set({"code": codice, "call": None, "used": True, "result": None})
        try:
            return send_hub_mail(kw.pop("subject", "[Ticket] 3 da gestire"), kw.pop("body", "Corpo"),
                                 kw.pop("to", ["tecnico@x.local"]), **kw)
        finally:
            managed_flows._invocation.reset(token)

    def test_fuori_dal_flusso_non_cambia_niente(self):
        from core.email_utils import send_hub_mail
        ScheduledMailText.objects.create(task_name="tickets_daily_digest", aggiungi_cc="capo@x.local")
        send_hub_mail("Oggetto", "Corpo", ["a@x.local"])
        self.assertEqual(mail.outbox[0].cc, [])

    def test_aggiunge_cc_toglie_esclusi_e_compone_oggetto(self):
        ScheduledMailText.objects.create(task_name="tickets_daily_digest", aggiungi_a="extra@x.local",
                                         aggiungi_cc="capo@x.local, Tecnico@x.local", escludi="vecchio@x.local",
                                         subject="[HUB] {oggetto}", intro="Buongiorno")
        self._invia_nel_flusso("tickets_daily_digest", to=["tecnico@x.local", "vecchio@x.local"])
        m = mail.outbox[0]
        self.assertEqual(m.to, ["tecnico@x.local", "extra@x.local"])
        self.assertEqual(m.cc, ["capo@x.local"])
        self.assertEqual(m.subject, "[HUB] [Ticket] 3 da gestire")
        self.assertIn("Buongiorno", m.body)

    def test_sostituisci_destinatari(self):
        ScheduledMailText.objects.create(task_name="tickets_daily_digest", aggiungi_a="solo@x.local",
                                         sostituisci_destinatari=True)
        self._invia_nel_flusso("tickets_daily_digest", cc=["cc@x.local"])
        self.assertEqual((mail.outbox[0].to, mail.outbox[0].cc), (["solo@x.local"], []))

    def test_mail_disattivata_non_parte(self):
        ScheduledMailText.objects.create(task_name="tickets_daily_digest", mail_disattivata=True)
        self.assertEqual(self._invia_nel_flusso("tickets_daily_digest"), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_tasks_non_raddoppiano_il_testo(self):
        ScheduledMailText.objects.create(task_name="visite_expiry_reminders", intro="Una volta", aggiungi_cc="cc@x.local")
        s, b, f, foot = apply_mail_overrides("visite_expiry_reminders", subject="S", body_text="Corpo")
        self._invia_nel_flusso("visite_expiry_reminders", subject=s, body=b)
        self.assertEqual(mail.outbox[0].body.count("Una volta"), 1)
        self.assertEqual(mail.outbox[0].cc, ["cc@x.local"])


class FlussoPowerAutomateTests(TestCase):
    """Flusso in stile Power Automate aperto da Pianificati, Notifiche di sistema e designer."""

    def setUp(self):
        from automazioni.managed_flows import install_flows
        install_flows()
        self.admin = User.objects.create_superuser("amp_admin", "amp@x.local", "x")
        self.client.force_login(self.admin)

    def _url(self, name="visite_expiry_reminders", which="automazioni_pianificati_mail"):
        return reverse(f"admin_portale:{which}", kwargs={"name": name})

    def test_htmx_restituisce_solo_il_flusso(self):
        r = self.client.get(self._url(), HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        for testo in ("Ricorrenza", "Esegui processo del modulo", "Invia un messaggio di posta", 'name="frequenza"',
                      'name="recipients"', 'name="aggiungi_cc"', "{oggetto}"):
            self.assertContains(r, testo)
        self.assertNotContains(r, "<html")

    def test_flusso_su_evento(self):
        r = self.client.get(self._url("dpi_pronta_ritiro"), HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Quando accade nel modulo")
        self.assertContains(r, 'name="aggiungi_a"')
        self.assertNotContains(r, 'name="frequenza"')

    def test_salva_ricorrenza_giorni_e_orario(self):
        from automazioni.models import ManagedFlow
        r = self.client.post(self._url(which="automazioni_pianificati_mail_save"),
                             {"frequenza": "giorno", "orario": "06:05", "giorni": ["1", "2", "3", "4", "5"]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ManagedFlow.objects.get(code="visite_expiry_reminders").cron, "5 6 * * 1,2,3,4,5")

    def test_salva_ricorrenza_non_valida_non_cambia(self):
        from automazioni.models import ManagedFlow
        prima = ManagedFlow.objects.get(code="visite_expiry_reminders").cron
        self.client.post(self._url(which="automazioni_pianificati_mail_save"), {"frequenza": "giorno", "orario": "06:05"})
        self.assertEqual(ManagedFlow.objects.get(code="visite_expiry_reminders").cron, prima)

    def test_salva_passaggio_mail_di_un_evento(self):
        self.client.post(self._url("dpi_pronta_ritiro", "automazioni_pianificati_mail_save"),
                         {"mail_step": "1", "invia_mail": "1", "aggiungi_cc": "magazzino@x.local; rspp@x.local",
                          "subject": "[DPI] {oggetto}"})
        cfg = ScheduledMailText.objects.get(task_name="dpi_pronta_ritiro")
        self.assertEqual(cfg.aggiungi_cc, "magazzino@x.local, rspp@x.local")
        self.assertFalse(cfg.mail_disattivata)
        self.client.post(self._url("dpi_pronta_ritiro", "automazioni_pianificati_mail_save"),
                         {"mail_step": "1", "aggiungi_cc": "magazzino@x.local; rspp@x.local", "subject": "[DPI] {oggetto}"})
        self.assertTrue(ScheduledMailText.objects.get(task_name="dpi_pronta_ritiro").mail_disattivata)

    def test_sostituisci_senza_indirizzi_rifiutato(self):
        self.client.post(self._url("tickets_daily_digest", "automazioni_pianificati_mail_save"),
                         {"mail_step": "1", "invia_mail": "1", "sostituisci": "1"})
        self.assertFalse(ScheduledMailText.objects.filter(task_name="tickets_daily_digest").exists())

    def test_salva_solo_ricorrenza_non_tocca_destinatari(self):
        SiteConfig.set("visite_reminder_emails", "a@x.local")
        self.client.post(self._url(which="automazioni_pianificati_mail_save"), {"frequenza": "minuti", "minuti": "30"})
        self.assertEqual(SiteConfig.get("visite_reminder_emails"), "a@x.local")

    def test_next_interno_rispettato_esterno_ignorato(self):
        url = self._url(which="automazioni_pianificati_mail_save")
        r = self.client.post(url, {"next": "/admin-portale/automazioni/regole/1/designer/"})
        self.assertEqual(r["Location"], "/admin-portale/automazioni/regole/1/designer/")
        r = self.client.post(url, {"next": "https://esterno.example/x"})
        self.assertIn(reverse("admin_portale:automazioni_pianificati"), r["Location"])

    def test_pianificati_e_notifiche_hanno_modifica_su_ogni_riga(self):
        from automazioni.event_notifications import EVENT_NOTIFICATIONS
        from automazioni.schedules import SCHEDULES
        r = self.client.get(reverse("admin_portale:automazioni_pianificati"))
        self.assertContains(r, 'id="amp-drawer"')
        self.assertContains(r, 'hx-target="#amp-drawer-body"', count=len(SCHEDULES))
        r = self.client.get(reverse("admin_portale:automazioni_event_notifications"))
        self.assertContains(r, 'hx-target="#amp-drawer-body"', count=len(EVENT_NOTIFICATIONS))

    def test_designer_apre_il_flusso_in_stile_power_automate(self):
        from automazioni.models import ManagedFlow
        SiteConfig.set("visite_reminder_emails", "rspp@x.local")
        binding = ManagedFlow.objects.get(code="visite_expiry_reminders")
        r = self.client.get(reverse("admin_portale:automazioni_rule_designer", kwargs={"rule_id": binding.rule_id}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="pa-embed"')
        self.assertContains(r, 'id="designer-avanzato" hidden')
        self.assertContains(r, "A: rspp@x.local")
        self.assertContains(r, 'id="native-preview"')
