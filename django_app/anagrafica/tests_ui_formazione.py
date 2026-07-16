"""Render-test leggeri per il restyle UI del modulo Formazione/Compliance/Impostazioni
(stream 3 della punch-list). I test funzionali (chip Processi, Ruoli inline) vivono
in `tests_qualifiche_dashboard.py` risp. in questo file (ImpostazioniRuoliInlineTests).

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi tutto ai
non-superuser (vedi memoria assets_test_legacy_auth_disabled); `SECURE_SSL_REDIRECT=False`
evita i redirect https durante i test.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .tests import _ensure_anagrafica_table, _ensure_utenti_table

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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ElearningManageFormRenderTests(TestCase):
    """Task 5 — il box 'Assegna dipendenti' della cabina e-learning non usa più gli
    inline style grezzi ma classi del design-system. Render-only: il POST è invariato."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, reparto, attivo) "
                "VALUES (1, 'Mario', 'Rossi', 'Produzione', 1)"
            )
        self.su = User.objects.create_superuser("su-el", "su-el@test.local", "x")
        self.client.force_login(self.su)
        from .models import DipendenteAnagraficaAziendale
        from .models_formazione import TrainingCourse, TrainingPlan
        piano = TrainingPlan.objects.create(codice="PEL", nome="Piano e-learning")
        self.corso = TrainingCourse.objects.create(
            piano=piano, codice="EL1", titolo="Corso EL",
            durata_ore_teorica=1, is_elearning=True,
        )
        # Un dipendente attivo → alimenta il pool `assegnabili` (box renderizzato).
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=1)

    def test_form_assegna_pulito(self):
        body = self.client.get(reverse("anagrafica:formazione_elearning_manage",
                                       args=[self.corso.pk])).content.decode()
        self.assertIn("Assegna dipendenti", body)
        self.assertIn("fm-assign-list", body)  # box renderizzato (assegnabili presenti)
        # Marker: gli inline style grezzi del box sono sostituiti da classi
        self.assertNotIn('style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end', body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ImpostazioniRuoliInlineTests(TestCase):
    """Task 6 (stream 3, funzionale): il tab 'Ruoli' in Impostazioni è un pannello
    inline (button data-tab), non più un link a una pagina esterna."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.su = User.objects.create_superuser("su-imp", "su-imp@test.local", "x")
        self.client.force_login(self.su)
        from .models import RuoloOperativo
        RuoloOperativo.objects.create(nome="Preposto")

    def test_tab_ruoli_e_inline_non_link(self):
        body = self.client.get(reverse("anagrafica:impostazioni")).content.decode()
        url_list = reverse("anagrafica:ruoli_operativi_list")
        url_create = reverse("anagrafica:ruolo_operativo_create")
        # Il tab Ruoli è un button data-tab, NON un <a href> verso la pagina esterna
        self.assertIn('data-tab="ruoli"', body)
        self.assertNotIn(f'href="{url_list}"', body)
        # Pannello inline presente col form "+ Nuovo ruolo" e la griglia ruoli
        self.assertIn('data-panel="ruoli"', body)
        self.assertIn(f'action="{url_create}"', body)
        self.assertIn("Preposto", body)

    def test_pagina_standalone_ruoli_ancora_valida(self):
        # Retro-compatibilità: la pagina autonoma continua a rendere il partial
        # (link diretti / bookmark restano validi).
        resp = self.client.get(reverse("anagrafica:ruoli_operativi_list"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Preposto", body)
        self.assertIn(reverse("anagrafica:ruolo_operativo_create"), body)
        self.assertIn('id="ro-modal"', body)
