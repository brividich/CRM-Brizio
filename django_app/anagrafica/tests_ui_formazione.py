"""Render-test leggeri per il restyle UI del modulo Formazione/Compliance/Impostazioni
(stream 3 della punch-list). I test funzionali (chip Processi, Ruoli inline) vivono
in `tests_qualifiche_dashboard.py` risp. in questo file (ImpostazioniRuoliInlineTests).

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi tutto ai
non-superuser (vedi memoria assets_test_legacy_auth_disabled); `SECURE_SSL_REDIRECT=False`
evita i redirect https durante i test.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class IstruttorePopupRenderTests(TestCase):
    """Task 2 — i modali Crea/Modifica istruttore usano il pattern canonico."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-istr", "su-istr@test.local", "x")
        self.client.force_login(self.su)

    def test_popup_istruttore_pattern_canonico(self):
        resp = self.client.get(reverse("anagrafica:formazione_istruttori_list"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # I due modali esistono
        self.assertIn('id="modal-crea-istr"', body)
        self.assertIn('id="modal-edit-istr"', body)
        # Marker della rifinitura: chiusura canonica (× / Annulla) e campi design-system
        self.assertIn("data-close-modal", body)
        self.assertIn("hub-field", body)
        # La vecchia label ad hoc .fm-label non è più usata (fonte campi unificata)
        self.assertNotIn('class="fm-label"', body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MansionePopupRenderTests(TestCase):
    """Task 4 — il popup 'Modifica mansione' è rifinito (header con ×, chiusura
    canonica) senza toccare campi/openEdit/action."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-mn", "su-mn@test.local", "x")
        self.client.force_login(self.su)

    def test_modale_modifica_mansione_rifinito(self):
        body = self.client.get(reverse("anagrafica:mansioni_list")).content.decode()
        self.assertIn('id="mn-modal"', body)
        self.assertIn("Modifica mansione", body)
        self.assertIn("hub-form-stack", body)     # campi design-system (invariati)
        # Marker della rifinitura: chiusura canonica (× header + Annulla) e corpo scrollabile
        self.assertIn("data-close-modal", body)
        self.assertIn("mn-modal-body", body)
