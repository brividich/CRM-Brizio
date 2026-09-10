"""Il gate di /assets/impostazioni/ deve leggere l'ACL, non solo il ruolo admin.

Regressione osservata in produzione: il pannello Accessi concedeva il permesso
sulla pagina, la voce di menu si accendeva (``can_gestione_admin`` valuta
``assets``/``admin_assets``), ma la pagina rispondeva 403. Il motivo era
``@legacy_admin_required``, che ammette solo superuser e ruoli legacy admin e
non interroga mai i permessi: la concessione non aveva alcun effetto.
"""
from __future__ import annotations

from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from admin_portale.decorators import is_legacy_admin_bypass_view, legacy_admin_or_acl_required
from assets import views as assets_views
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Ruolo, UtenteLegacy
from core.models import Profile
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

RUOLO_CAPO_ID = 42


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class AssetsImpostazioniGateReadsAclTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        self.factory = RequestFactory()

        Ruolo.objects.create(id=RUOLO_CAPO_ID, nome="caporeparto")
        self.legacy_user = UtenteLegacy.objects.create(
            nome="Capo Reparto",
            email="capo-assets@example.local",
            password="x",
            ruolo="caporeparto",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=RUOLO_CAPO_ID,
        )
        self.user = User.objects.create_user(
            username="capo-assets",
            email="capo-assets@example.local",
            password="pass12345",
        )
        Profile.objects.update_or_create(
            user=self.user,
            defaults={"legacy_user_id": self.legacy_user.id},
        )
        bump_legacy_cache_version()

    def _call_gate(self):
        """Applica il gate a una view innocua e restituisce la risposta."""

        @legacy_admin_or_acl_required("assets", "admin_assets")
        def _view(request):
            return HttpResponse("ok")

        request = self.factory.get("/assets/impostazioni/")
        request.user = self.user
        # forbidden.html passa dai context processor del guscio, che leggono la
        # sessione: RequestFactory non la monta.
        request.session = SessionStore()
        return _view(request)

    def _grant(self, *, consentito: int, can_view: int):
        Permesso.objects.update_or_create(
            ruolo_id=RUOLO_CAPO_ID,
            modulo="assets",
            azione="admin_assets",
            defaults={"consentito": consentito, "can_view": can_view},
        )
        bump_legacy_cache_version()
        cache.clear()

    def test_senza_permesso_il_gate_nega(self):
        self._grant(consentito=0, can_view=0)
        self.assertEqual(self._call_gate().status_code, 403)

    def test_con_permesso_concesso_il_gate_apre(self):
        self._grant(consentito=1, can_view=1)
        response = self._call_gate()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_anonimo_viene_mandato_al_login(self):
        @legacy_admin_or_acl_required("assets", "admin_assets")
        def _view(request):
            return HttpResponse("ok")

        request = self.factory.get("/assets/impostazioni/")
        request.user = AnonymousUser()
        self.assertEqual(_view(request).status_code, 302)

    def test_la_pagina_impostazioni_non_e_piu_un_bypass_admin(self):
        """Se tornasse un gate solo-admin, l'ACL smetterebbe di contare."""
        self.assertFalse(is_legacy_admin_bypass_view(assets_views.gestione_admin))
