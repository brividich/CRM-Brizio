"""Vista personale: un amministratore trova in «Le mie attività» solo ciò che aspetta lui."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from core.legacy_utils import is_legacy_admin
from core.vista_personale import attiva, vista_personale


class VistaPersonaleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="syn.admin.it", email="admin.it@example.test", is_superuser=True)
        self.req = RequestFactory().get("/")
        self.req.user = self.user
        self.legacy = SimpleNamespace(id=901, nome="Admin Sintetico", email="admin.it@example.test",
                                      ruolo="admin", ruolo_id=None)
        self.req.legacy_user = self.legacy

    def test_dentro_il_blocco_niente_admin_ne_superuser_poi_tornano(self):
        self.assertTrue(is_legacy_admin(self.legacy))
        with vista_personale(self.req):
            self.assertTrue(attiva())
            self.assertFalse(is_legacy_admin(self.legacy))
            self.assertFalse(self.user.is_superuser)
            ctx = self.user._permessi_contesto
            self.assertFalse(ctx.amministratore or ctx.superuser)
            self.assertFalse(any(r.vede_tutto for r in ctx.ruoli))
        self.assertFalse(attiva())
        self.assertTrue(is_legacy_admin(self.legacy))
        self.assertTrue(self.user.is_superuser)
        self.assertFalse(hasattr(self.user, "_permessi_contesto"))

    def test_ripristina_anche_se_il_calcolo_fallisce(self):
        with self.assertRaises(RuntimeError), vista_personale(self.req):
            raise RuntimeError("fonte rotta")
        self.assertTrue(self.user.is_superuser)
        self.assertTrue(is_legacy_admin(self.legacy))

    def test_le_mie_attivita_non_chiede_le_anomalie_di_tutti(self):
        from dashboard import views_mie_attivita as vm

        visti = []

        def anomalie(legacy_user, is_admin, params):
            visti.append(is_admin)
            return []

        with patch.object(vm, "_board_data_anomalie", side_effect=anomalie):
            vm.build_cose_da_gestire(self.req)
        self.assertEqual(visti, [False])
        self.assertTrue(self.user.is_superuser)

    def test_pulsante_da_approvare_calcolato_in_vista_personale(self):
        from dashboard import da_approvare

        def fonti(request, legacy_user):
            self.assertTrue(attiva())
            self.assertFalse(is_legacy_admin(legacy_user))
            return []

        with patch.object(da_approvare, "_fonti", side_effect=fonti):
            self.assertEqual(da_approvare.riepilogo(self.req, self.legacy)["totale"], 0)
