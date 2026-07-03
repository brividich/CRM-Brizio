"""#6 — Sezione Amministrazione: home + CRUD mappatura cliente→cartella + link condizionato."""
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from gestione_specifiche import constants as C
from gestione_specifiche.models import (
    AutoApprovazioneConfig, ClienteCartellaShare, EventoSpecifica, MOD133, Specifica,
)

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
