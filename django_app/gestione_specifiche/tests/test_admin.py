"""#6 — Sezione Amministrazione: home + CRUD mappatura cliente→cartella + link condizionato."""
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from django.core import mail

from gestione_specifiche import constants as C
from gestione_specifiche.models import (
    AutoApprovazioneConfig, ClienteCartellaShare, EventoSpecifica, MOD133,
    NotificaConfig, Specifica,
)
from gestione_specifiche.notifiche_gs import notifica_nuova_specifica

User = get_user_model()


class AdminSectionTest(TestCase):
    def setUp(self):
        cache.clear()
        self.su = User.objects.create_superuser("adm_su", "a@x.it", "x")
        self.mso = User.objects.create_user("mso_user", "m@x.it", "x", first_name="Mario", last_name="MSO")
        self.client.force_login(self.su)

    def test_home_render(self):
        r = self.client.get(reverse("gestione_specifiche:admin_home"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Amministrazione")
        self.assertContains(r, "Mappatura cliente")

    def test_cartelle_add_edit_delete(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        os.makedirs(os.path.join(root, "DUCATI"))
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[root]):
            r = self.client.get(reverse("gestione_specifiche:admin_cartelle"))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "DUCATI")  # cartella reale nel menu
            r = self.client.post(reverse("gestione_specifiche:admin_cartelle"),
                                 {"cliente": "Ducati", "cartella": "DUCATI"})
            self.assertEqual(r.status_code, 302)

        m = ClienteCartellaShare.objects.get(cliente="Ducati")
        self.assertEqual(m.cartella, "DUCATI")
        self.assertTrue(m.attivo)

        # modifica: senza "attivo" -> disattivata
        r = self.client.post(reverse("gestione_specifiche:admin_cartella_edit", args=[m.pk]),
                             {"cartella": "DUCATI"})
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertFalse(m.attivo)

        # elimina
        r = self.client.post(reverse("gestione_specifiche:admin_cartella_delete", args=[m.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ClienteCartellaShare.objects.filter(pk=m.pk).exists())

    def test_link_admin_nel_cruscotto(self):
        r = self.client.get(reverse("gestione_specifiche:lista"))
        self.assertContains(r, "Amministrazione")  # superuser -> permesso admin -> link visibile

    # --- #3 auto-approvazione ---
    def test_config_auto_approva_save(self):
        r = self.client.get(reverse("gestione_specifiche:admin_auto_approva"))
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("gestione_specifiche:admin_auto_approva"),
                             {"attiva": "1", "approvatore": str(self.mso.pk), "nota": "delega"})
        self.assertEqual(r.status_code, 302)
        cfg = AutoApprovazioneConfig.get_config()
        self.assertTrue(cfg.attiva)
        self.assertEqual(cfg.approvatore_id, self.mso.pk)

    def test_attiva_senza_approvatore_rifiutata(self):
        r = self.client.post(reverse("gestione_specifiche:admin_auto_approva"), {"attiva": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(AutoApprovazioneConfig.get_config().attiva)

    def _spec_flow_down(self, codice):
        spec = Specifica.objects.create(codice=codice, titolo="T")
        spec.avvia_flow_down(attore=self.su)
        spec.save()
        return spec

    def test_auto_approvazione_al_procedi(self):
        cfg = AutoApprovazioneConfig.get_config()
        cfg.attiva = True
        cfg.approvatore = self.mso
        cfg.save()
        spec = self._spec_flow_down("SP-AUTO")
        r = self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[spec.pk]), {"vai": "approva"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("gestione_specifiche:dettaglio", args=[spec.pk]), r["Location"])
        spec = Specifica.objects.get(pk=spec.pk)
        self.assertEqual(spec.stato, C.STATO_IN_VALIDITA)  # approvato -> S3
        mod = MOD133.objects.get(specifica=spec)
        self.assertEqual(mod.approvatore_id, self.mso.pk)  # a nome dell'MSO
        self.assertTrue(EventoSpecifica.objects.filter(specifica=spec, trigger="auto_approvazione").exists())

    def test_procedi_senza_auto_va_alla_pagina_approva(self):
        spec = self._spec_flow_down("SP-NOAUTO")  # nessuna config attiva
        r = self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[spec.pk]), {"vai": "approva"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("gestione_specifiche:mod133_approva", args=[spec.pk]), r["Location"])
        self.assertEqual(Specifica.objects.get(pk=spec.pk).stato, C.STATO_FLOW_DOWN)  # NON approvato

    # --- #5 notifiche/assegnazione ---
    def test_config_notifiche_save(self):
        r = self.client.get(reverse("gestione_specifiche:admin_notifiche"))
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("gestione_specifiche:admin_notifiche"),
                             {"reparto_in1": "IN2", "email_attiva": "1",
                              "utenti_aggiuntivi": [str(self.mso.pk)]})
        self.assertEqual(r.status_code, 302)
        cfg = NotificaConfig.get_config()
        self.assertEqual(cfg.reparto_in1, "IN2")
        self.assertTrue(cfg.email_attiva)
        self.assertIn(self.mso.pk, set(cfg.utenti_aggiuntivi.values_list("pk", flat=True)))

    def test_form_nuova_ha_assegna_a(self):
        NotificaConfig.get_config().utenti_aggiuntivi.set([self.mso.pk])
        r = self.client.get(reverse("gestione_specifiche:nuova"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Assegna a")
        self.assertContains(r, "Gruppo IN1")
        self.assertContains(r, "Mario MSO")  # utente del pool nel menu

    def test_notifica_nuova_specifica_invia_email(self):
        cfg = NotificaConfig.get_config()
        cfg.email_attiva = True
        cfg.save()
        spec = Specifica.objects.create(codice="SP-INC", titolo="T", incaricato=self.mso)
        n = notifica_nuova_specifica(spec)
        self.assertGreaterEqual(n, 1)
        self.assertGreaterEqual(len(mail.outbox), 1)  # email HTML all'incaricato
        self.assertIn("SP-INC", mail.outbox[0].subject)

    def test_notifica_email_disattivata_non_invia(self):
        cfg = NotificaConfig.get_config()
        cfg.email_attiva = False
        cfg.save()
        spec = Specifica.objects.create(codice="SP-NOEMAIL", titolo="T", incaricato=self.mso)
        notifica_nuova_specifica(spec)
        self.assertEqual(len(mail.outbox), 0)

    # --- Log / Audit ---
    def test_admin_log_render_e_filtro(self):
        self._spec_flow_down("SP-LOG")  # genera un evento di transizione
        r = self.client.get(reverse("gestione_specifiche:admin_log"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SP-LOG")
        r = self.client.get(reverse("gestione_specifiche:admin_log"), {"codice": "SP-LOG"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SP-LOG")
        r = self.client.get(reverse("gestione_specifiche:admin_log"), {"codice": "ZZZ-NONE"})
        self.assertNotContains(r, "SP-LOG")
