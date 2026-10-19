"""Nonce CSP (audit 18/10, fase 4): infrastruttura opt-in, policy invariata a nonce spento."""
from __future__ import annotations

from django.http import HttpResponse
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.context_processors import csp
from core.middleware import ContentSecurityPolicyMiddleware

POLICY = "default-src 'self'; script-src 'self' 'unsafe-inline'"
POLICY_NONCE = "default-src 'self'; script-src 'self' 'nonce-{nonce}'"


def _run(request):
    captured = {}

    def view(req):
        captured["nonce"] = req.csp_nonce
        return HttpResponse("ok")

    response = ContentSecurityPolicyMiddleware(view)(request)
    return response, captured["nonce"]


class CspNonceTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    @override_settings(CSP_ENABLED=True, CSP_REPORT_ONLY=False, CSP_NONCE_ENABLED=False, CSP_POLICY=POLICY, CSP_POLICY_NONCE=POLICY_NONCE)
    def test_nonce_spento_policy_invariata_ma_request_ha_il_nonce(self):
        response, nonce = _run(self.rf.get("/"))
        self.assertEqual(response["Content-Security-Policy"], POLICY)
        self.assertGreaterEqual(len(nonce), 16)
        self.assertNotIn("{nonce}", response["Content-Security-Policy"])

    @override_settings(CSP_ENABLED=True, CSP_REPORT_ONLY=False, CSP_NONCE_ENABLED=True, CSP_POLICY=POLICY, CSP_POLICY_NONCE=POLICY_NONCE)
    def test_nonce_acceso_header_porta_il_nonce_della_richiesta(self):
        response, nonce = _run(self.rf.get("/"))
        self.assertEqual(response["Content-Security-Policy"], f"default-src 'self'; script-src 'self' 'nonce-{nonce}'")
        self.assertNotIn("unsafe-inline", response["Content-Security-Policy"])

    @override_settings(CSP_ENABLED=True, CSP_REPORT_ONLY=True, CSP_NONCE_ENABLED=True, CSP_POLICY=POLICY, CSP_POLICY_NONCE=POLICY_NONCE)
    def test_report_only_con_nonce(self):
        response, nonce = _run(self.rf.get("/"))
        self.assertNotIn("Content-Security-Policy", response)
        self.assertIn(f"'nonce-{nonce}'", response["Content-Security-Policy-Report-Only"])

    @override_settings(CSP_ENABLED=True, CSP_NONCE_ENABLED=True, CSP_POLICY=POLICY, CSP_POLICY_NONCE=POLICY_NONCE)
    def test_nonce_diverso_a_ogni_richiesta(self):
        _, a = _run(self.rf.get("/"))
        _, b = _run(self.rf.get("/"))
        self.assertNotEqual(a, b)

    def test_context_processor_espone_csp_nonce(self):
        request = self.rf.get("/")
        request.csp_nonce = "abc123"
        self.assertEqual(csp(request), {"csp_nonce": "abc123"})
        self.assertEqual(csp(self.rf.get("/")), {"csp_nonce": ""})
        html = Template('<script nonce="{{ csp_nonce }}"></script>').render(Context(csp(request)))
        self.assertEqual(html, '<script nonce="abc123"></script>')

    def test_policy_nonce_di_default_sostituisce_unsafe_inline_solo_negli_script(self):
        from django.conf import settings

        self.assertIn("script-src 'self' 'nonce-{nonce}'", settings.CSP_POLICY_NONCE)
        self.assertIn("style-src 'self' 'unsafe-inline'", settings.CSP_POLICY_NONCE)
