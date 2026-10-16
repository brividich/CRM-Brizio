"""Gate del tool AI Anagrafica/ratei: con il sistema ruoli attivo decide la matrice ruoli."""
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from ai_assistant.tools import _can_use_anagrafica_runtime


class AnagraficaRuntimeGateRuoliTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="ratei-gate", password="x")
        self.request = RequestFactory().get("/")
        self.request.user = self.user

    def _esito(self, consentito, ambito):
        return SimpleNamespace(consentito=consentito, ambito=ambito)

    def test_ruoli_attivi_consente_con_dati_riservati_su_tutti(self):
        with mock.patch("core.permessi.sistema_ruoli_attivo", return_value=True), mock.patch(
            "core.permessi.decisione", return_value=self._esito(True, "tutti")
        ) as dec:
            allowed, scope = _can_use_anagrafica_runtime(self.request)
        self.assertTrue(allowed)
        self.assertEqual(scope, "ruoli_dati_riservati")
        dec.assert_called_once_with(self.request, "anagrafica", "dati_riservati")

    def test_ruoli_attivi_nega_se_ambito_solo_team(self):
        with mock.patch("core.permessi.sistema_ruoli_attivo", return_value=True), mock.patch(
            "core.permessi.decisione", return_value=self._esito(True, "team")
        ):
            allowed, scope = _can_use_anagrafica_runtime(self.request)
        self.assertFalse(allowed)
        self.assertEqual(scope, "missing_ruoli_dati_riservati")

    def test_ruoli_attivi_ignora_singleton_aperto_a_tutti(self):
        from anagrafica.models import AnagraficaHRPermission

        perm = AnagraficaHRPermission.get_instance()
        perm.accesso = AnagraficaHRPermission.ACCESSO_TUTTI
        perm.save()
        with mock.patch("core.permessi.sistema_ruoli_attivo", return_value=True), mock.patch(
            "core.permessi.decisione", return_value=self._esito(False, "")
        ):
            allowed, _scope = _can_use_anagrafica_runtime(self.request)
        self.assertFalse(allowed)

    def test_ruoli_spenti_usa_ancora_il_singleton(self):
        from anagrafica.models import AnagraficaHRPermission

        perm = AnagraficaHRPermission.get_instance()
        perm.accesso = AnagraficaHRPermission.ACCESSO_TUTTI
        perm.save()
        with mock.patch("core.permessi.sistema_ruoli_attivo", return_value=False):
            allowed, scope = _can_use_anagrafica_runtime(self.request)
        self.assertTrue(allowed)
        self.assertEqual(scope, "hr_permission_all")
