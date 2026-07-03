"""#6 — Sezione Amministrazione: home + CRUD mappatura cliente→cartella + link condizionato."""
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from gestione_specifiche.models import ClienteCartellaShare

User = get_user_model()


class AdminSectionTest(TestCase):
    def setUp(self):
        cache.clear()
        self.su = User.objects.create_superuser("adm_su", "a@x.it", "x")
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
