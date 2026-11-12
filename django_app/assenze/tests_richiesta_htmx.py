"""Form «Richiesta assenza» con HTMX (revisione UX 12/11/2026).

- Cambio dipendente → il server ridisegna il campo «Capo reparto» (prima lo
  aggiornava uno script sul <select> nativo e la tendina Tom Select restava ferma).
- Saldo, avvisi HR e corsi → riquadro «Controlli» in HTML dal server.
- CSS e JS della pagina sono file statici; l'invio sta nel riepilogo laterale.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

CAPI = [{"Value": f"Capo {i}", "Email": f"capo{i}@example.com", "LookupId": i} for i in range(12)]
PERMS_PER_ALTRI = {"can_insert": True, "can_insert_for_others": True, "can_choose_capo": False}


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CampoCapoHtmxTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-htmx", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())
        self.client.force_login(self.user)
        self.url = reverse("assenze_richiesta_campo_capo")

    @patch("assenze.views._helpers._resolve_default_capo_for_user", return_value="capo5@example.com")
    @patch("assenze.views._helpers._resolve_employee_identity_from_anagrafica", return_value=("Mario Rossi", "m@example.com", 9))
    @patch("assenze.views._helpers._can_insert_for_dipendente", return_value=True)
    @patch("assenze.views._helpers._malattia_permessi", return_value={"per_tutti": False, "visibile": True})
    @patch("assenze.views._helpers._load_capi_options", return_value=CAPI)
    @patch("assenze.views._helpers._assenze_permissions", return_value=PERMS_PER_ALTRI)
    def test_capo_del_dipendente_scelto_e_bloccato(self, *_mocks):
        r = self.client.get(self.url, {"dipendente_id": "7"})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('id="abs-campo-capo"', html)
        self.assertIn('value="capo5@example.com" selected', html)
        self.assertIn("disabled", html)  # non abilitato al cambio: fermo sul capo assegnato

    @patch("assenze.views._helpers._resolve_default_capo_for_user", return_value="")
    @patch("assenze.views._helpers._resolve_employee_identity_from_anagrafica", return_value=("Mario Rossi", "m@example.com", 9))
    @patch("assenze.views._helpers._can_insert_for_dipendente", return_value=True)
    @patch("assenze.views._helpers._malattia_permessi", return_value={"per_tutti": False, "visibile": True})
    @patch("assenze.views._helpers._load_capi_options", return_value=CAPI)
    @patch("assenze.views._helpers._assenze_permissions", return_value=PERMS_PER_ALTRI)
    def test_senza_capo_assegnato_il_campo_resta_libero(self, *_mocks):
        html = self.client.get(self.url, {"dipendente_id": "7"}).content.decode()
        self.assertNotIn(" disabled", html)
        self.assertIn("Non risulta un capo assegnato", html)

    @patch("assenze.views._helpers._can_insert_for_dipendente", return_value=False)
    @patch("assenze.views._helpers._malattia_permessi", return_value={"per_tutti": False, "visibile": True})
    @patch("assenze.views._helpers._load_capi_options", return_value=CAPI)
    @patch("assenze.views._helpers._assenze_permissions", return_value=PERMS_PER_ALTRI)
    def test_dipendente_fuori_reparto_negato(self, *_mocks):
        self.assertEqual(self.client.get(self.url, {"dipendente_id": "7"}).status_code, 403)

    @patch("assenze.views._helpers._assenze_permissions", return_value={"can_insert": False})
    def test_senza_inserimento_negato(self, _mock):
        self.assertEqual(self.client.get(self.url).status_code, 403)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ControlliHtmxTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-controlli", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())
        self.client.force_login(self.user)
        self.url = reverse("assenze_richiesta_controlli")

    @patch("assenze.views.eventi.corsi_nel_periodo", return_value=[{
        "data_inizio": "2026-11-20", "data_fine": "2026-11-20", "url": "/anagrafica/formazione/sessioni/3/",
        "course_code": "C<1>", "title": "Sicurezza <b>base</b>", "stato_display": "Programmata",
    }])
    @patch("assenze.hr.avvisi_richiesta", return_value=["Supera il residuo <ferie>"])
    @patch("assenze.hr.riepilogo_saldo", return_value={"ferie_residue": 12, "permessi_residui": 4, "situazione_al": "31/10/2026"})
    @patch("assenze.views._helpers._resolve_anagrafica_employee_id_for_user", return_value=55)
    @patch("assenze.views._helpers._legacy_identity", return_value=("Mario Rossi", "m@example.com", 9))
    @patch("assenze.views._helpers._assenze_permissions", return_value={"can_insert": True})
    def test_saldo_avvisi_e_corsi_in_html_con_escape(self, _p, _i, _a, _saldo, mock_avvisi, mock_corsi):
        r = self.client.get(self.url, {
            "tipoassenza": "Permesso", "date_start": "2026-11-20", "date_end": "2026-11-20",
            "time_start": "08:00", "time_end": "12:00",
        })
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("Ferie 12 ore", html)
        self.assertIn("Supera il residuo &lt;ferie&gt;", html)
        self.assertIn("il 20/11/2026", html)
        self.assertIn("Sicurezza &lt;b&gt;base&lt;/b&gt;", html)
        # I corsi si cercano con l'id anagrafica del dipendente, non con l'id utente.
        self.assertEqual(mock_corsi.call_args.args[0], 55)
        self.assertEqual(mock_avvisi.call_args.kwargs["anagrafica_id"], 55)

    @patch("assenze.views._helpers._malattia_permessi", return_value={"per_tutti": False, "visibile": True})
    @patch("assenze.views._helpers._can_insert_for_dipendente", return_value=False)
    @patch("assenze.views._helpers._assenze_permissions", return_value={"can_insert": True, "can_insert_for_others": True})
    def test_saldo_di_altri_negato_fuori_reparto(self, *_mocks):
        self.assertEqual(self.client.get(self.url, {"dipendente_id": "7"}).status_code, 403)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PaginaRichiestaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-pagina", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())
        self.client.force_login(self.user)

    @patch("assenze.views.richieste._insertable_dipendenti_for_request", return_value=[{"id": 7, "full_name": "Mario Rossi"}])
    @patch("assenze.views._helpers._template_perm_context", return_value={"assenze_can_insert_for_others": True})
    @patch("assenze.views._helpers._load_motivazioni_local", return_value=["Motivo"])
    @patch("assenze.views._helpers._graph_get_motivazioni", return_value=[])
    @patch("assenze.views._helpers._load_capi_options", return_value=CAPI)
    @patch("assenze.views._helpers._resolve_default_capo_for_user", return_value="capo1@example.com")
    @patch("assenze.views._helpers._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._helpers._assenze_permissions", return_value={"can_insert": True, "can_insert_for_others": True})
    def test_pagina_htmx_statici_e_invio_nel_riepilogo(self, *_mocks):
        r = self.client.get(reverse("assenze_richiesta"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("assenze/css/richiesta.css", html)
        self.assertIn("assenze/js/richiesta.js", html)
        self.assertIn('hx-get="%s"' % reverse("assenze_richiesta_campo_capo"), html)
        self.assertIn('hx-get="%s"' % reverse("assenze_richiesta_controlli"), html)
        self.assertIn('id="abs-campo-capo"', html)
        self.assertIn('type="submit" form="richiestaForm"', html)
        # Niente doppioni: barra dei passi, card durata, «Torna al menu», JS inline.
        for assente in ("abs-flow-strip", "abs-duration-card", "Torna al menu", "window.alert", "onclick=", "onchange="):
            self.assertNotIn(assente, html)
        self.assertNotIn("{#", html)
