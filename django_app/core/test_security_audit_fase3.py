"""Guardrail strutturali dell'audit sicurezza 09/10, Fase 3.

1. Route esenti dal login (``MIDDLEWARE_EXEMPT_PREFIXES``): il middleware non
   applica né autenticazione né ACL, quindi la protezione dipende solo dalla view.
   Se una di queste risponde 200 a un anonimo deve essere pubblica per scelta e
   comparire in ``PUBLIC_VIEWS``.
2. IDOR generico: nessuna route con un id numerico deve restituire 200 a un utente
   autenticato senza alcun permesso.

Una nuova voce in ``PUBLIC_VIEWS`` o ``ID_ROUTES_OPEN_TO_ANY_USER`` va motivata
nel commento accanto e rivista come modifica di sicurezza.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.middleware import is_acl_exempt_path
from core.route_probe import iter_route_samples

# View che rispondono 200 a un anonimo pur stando sotto un prefisso esente.
PUBLIC_VIEWS = frozenset({
    "core.accounts.views.LegacyLoginView",  # pagina di login
    "core.views.health",  # liveness (allowlist IP dentro la view)
    "core.views.version",  # numero di versione
    "core.legacy_flask_views.legacy_flask_check",  # health legacy
    "monitoring.views.healthz",  # liveness (HEALTHZ_ALLOWED_IPS)
    "monitoring.views.readyz",  # readiness (HEALTHZ_ALLOWED_IPS, solo nome/stato)
    "suggestion_corner.views.nuova",  # form anonimo per scelta (§5)
    # Aperto solo finche' SETUP_COMPLETED manca dal .env (audit M9): nei test
    # il flag non c'e'; in produzione il wizard risponde redirect/404.
    "setup_wizard.views.wizard_home",
})

# Route con id numerico accessibili a qualunque utente autenticato (nessuna oggi).
ID_ROUTES_OPEN_TO_ANY_USER: frozenset[str] = frozenset()


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=True, ALLOWED_HOSTS=["*"])
class ExemptRoutesAnonymousAccessTests(TestCase):
    def test_exempt_routes_answer_200_only_for_reviewed_public_views(self):
        unexpected = []
        for sample in iter_route_samples():
            if not is_acl_exempt_path(sample.path):
                continue
            try:
                status = self.client.get(sample.path).status_code
            except Exception:  # noqa: BLE001 - una view che esplode non e' "aperta"
                continue
            if status == 200 and sample.view not in PUBLIC_VIEWS:
                unexpected.append(f"{sample.path} -> {sample.view}")
        self.assertEqual(
            unexpected,
            [],
            "Route esenti dal login che rispondono 200 a un anonimo: aggiungere un controllo "
            "di autorizzazione nella view o, se pubbliche per scelta, PUBLIC_VIEWS motivato.",
        )


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=True, ALLOWED_HOSTS=["*"])
class GenericIdorTests(TestCase):
    def test_id_routes_do_not_answer_200_to_user_without_permissions(self):
        from core.models import UserOnboarding

        user = get_user_model().objects.create_user(username="idor-probe", password="x-pass-123")
        UserOnboarding.objects.get_or_create(user=user, defaults={"completed": True})
        self.client.force_login(user)
        exposed = []
        for sample in iter_route_samples():
            if not sample.has_int_param or is_acl_exempt_path(sample.path):
                continue
            try:
                status = self.client.get(sample.path).status_code
            except Exception:  # noqa: BLE001 - errore != accesso concesso
                continue
            if status == 200 and sample.route not in ID_ROUTES_OPEN_TO_ANY_USER:
                exposed.append(f"{sample.path} -> {sample.view}")
        self.assertEqual(
            exposed,
            [],
            "Route con id visibili a un utente senza permessi: verificare l'ACL/ownership "
            "dell'oggetto nella view.",
        )


class RouteProbeTests(TestCase):
    def test_samples_fill_converters(self):
        samples = {s.route: s for s in iter_route_samples()}
        self.assertTrue(any(s.has_int_param for s in samples.values()))
        self.assertTrue(all("<" not in s.path for s in samples.values()))
