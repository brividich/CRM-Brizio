"""Digest con elenco fisso: «A» è l'unico elenco e la pagina mostra chi riceve davvero."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from automazioni.mail_config import descrivi_effettivi, destinatari_effettivi
from automazioni.models import ScheduledMailText
from core.models import SiteConfig

User = get_user_model()
TASK = "contratti_expiry_reminders"
CHIAVE = "contratti_reminder_emails"


@override_settings(ADMINS=[("IT", "it@test.local")])
class DestinatariEffettiviTests(TestCase):
    def setUp(self):
        from automazioni.managed_flows import install_flows

        install_flows()
        self.admin = User.objects.create_superuser("de_admin", "de@test.local", "x")
        self.client.force_login(self.admin)

    def test_elenco_vuoto_mostra_il_ripiego_amministratori(self):
        eff = destinatari_effettivi(TASK)
        self.assertEqual(eff["to"], ["it@test.local"])
        self.assertIn("amministratori di sistema", descrivi_effettivi(eff))

    def test_regola_rimasta_da_prima_si_vede(self):
        SiteConfig.set(CHIAVE, "amministrazione@test.local")
        ScheduledMailText.objects.create(task_name=TASK, aggiungi_a="it@test.local", sostituisci_destinatari=True)
        self.assertEqual(destinatari_effettivi(TASK)["to"], ["it@test.local"])
        r = self.client.get(reverse("admin_portale:automazioni_pianificati"))
        self.assertContains(r, "it@test.local")

    def test_salvare_a_toglie_indirizzi_nascosti_e_sostituzione(self):
        ScheduledMailText.objects.create(task_name=TASK, aggiungi_a="it@test.local", sostituisci_destinatari=True,
                                         aggiungi_cc="cc@test.local")
        r = self.client.post(reverse("admin_portale:automazioni_pianificati_mail_save", kwargs={"name": TASK}),
                             {"mail_step": "1", "invia_mail": "1", "recipients": "amministrazione@test.local",
                              "aggiungi_cc": "cc@test.local"})
        self.assertLess(r.status_code, 400)
        self.assertEqual(SiteConfig.get(CHIAVE), "amministrazione@test.local")
        txt = ScheduledMailText.objects.get(task_name=TASK)
        self.assertEqual((txt.aggiungi_a, txt.sostituisci_destinatari), ("", False))
        eff = destinatari_effettivi(TASK)
        self.assertEqual((eff["to"], eff["cc"]), (["amministrazione@test.local"], ["cc@test.local"]))

    def test_invio_va_all_elenco_salvato(self):
        from django.core import mail
        from django.core.management import call_command

        from anagrafica.models import DipendenteAnagraficaAziendale

        SiteConfig.set(CHIAVE, "amministrazione@test.local")
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=990001, tipologia_contratto=DipendenteAnagraficaAziendale.CONTRATTO_DETERMINATO)
        call_command("send_contratti_expiry_reminders", verbosity=0)
        self.assertEqual(mail.outbox[-1].to, ["amministrazione@test.local"])

    def test_flusso_senza_elenco_fisso(self):
        self.assertIsNone(destinatari_effettivi("dpi_pronta_ritiro"))
