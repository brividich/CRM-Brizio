"""Conferma chiara dopo l'invio, blocco dei doppioni e chi vede «Malattia» (03/11/2026)."""

from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import CambioCapoAbilitato, MalattiaAbilitato
from .views.richieste import _CONFERMA_SESSION_KEY, _build_submit_token

PERMS_UTENTE = {"can_insert": True, "can_skip_approval": False, "can_insert_for_others": False, "group": "UTENTI"}


def _render_finto(request, **kw):
    return HttpResponse(kw.get("error") or kw.get("success") or "")


class _Base(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_user(username="conferma-user", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())
        self.client.force_login(self.user)

    def _invia(self, **extra):
        session = self.client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        dati = {
            "submit_token": _build_submit_token(request, "assenze_invio"),
            "tipoassenza": "Permesso", "motivazione": "Motivo",
            "date_start": "2026-11-10", "date_end": "2026-11-10", "time_start": "08:00", "time_end": "10:00",
        }
        dati.update(extra)
        session.save()
        return self.client.post(reverse("assenze_invio"), dati)


_PATCH_INVIO = [
    patch("assenze.views.richieste._registra_inserita_da"),
    patch("assenze.views.richieste._resolve_capo_local_id", return_value=None),
    patch("assenze.views.richieste._resolve_capo_lookup_id", return_value=None),
    patch("assenze.views.richieste._resolve_nome_lookup_id", return_value=77),
    patch("assenze.views.richieste._resolve_request_display_name", return_value="Mario Rossi"),
    patch("assenze.views.richieste._richiedi_calendario"),
    patch("assenze.views._helpers._sp_enqueue_upsert", return_value={"queued": False}),
    patch("assenze.views._helpers._load_capi_options", return_value=[]),
    patch("assenze.views._helpers._validate_business_rules", return_value=(None, "")),
    patch("assenze.views._helpers._table_exists", return_value=True),
    patch("assenze.views._helpers._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77)),
    patch("assenze.views._helpers._resolve_anagrafica_employee_id_for_user", return_value=500),
    patch("assenze.hr.avvisi_richiesta", return_value=[]),
    patch("assenze.hr.registra"),
]


def _con_patch_invio(cls):
    for p in reversed(_PATCH_INVIO):
        cls = p(cls)
    return cls


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
@_con_patch_invio
class ConfermaInvioTests(_Base):
    @patch("assenze.views._helpers._assenze_permissions", return_value=PERMS_UTENTE)
    def test_invio_riuscito_porta_alla_conferma_una_sola_volta(self, *_m):
        with patch("assenze.views.richieste._insert_assenza", return_value=321), \
                patch("assenze.views.richieste._richiesta_gia_inviata", return_value=None):
            resp = self._invia()
        self.assertRedirects(resp, reverse("assenze_richiesta"), fetch_redirect_response=False)
        conferma = self.client.session[_CONFERMA_SESSION_KEY]
        self.assertEqual(conferma["riferimenti"], [321])
        self.assertEqual(conferma["tipo"], "Permesso")
        self.assertEqual(conferma["periodo"], "10/11/2026 dalle 08:00 alle 10:00")
        self.assertIn("In attesa di approvazione", conferma["stato"])

        with patch("assenze.views.richieste._render_richiesta", side_effect=lambda request, **kw: HttpResponse(
            "CONFERMA" if kw.get("conferma") else "FORM"
        )):
            self.assertContains(self.client.get(reverse("assenze_richiesta")), "CONFERMA")
            # Ricaricando la pagina la conferma non torna e niente viene reinviato.
            self.assertContains(self.client.get(reverse("assenze_richiesta")), "FORM")

    @patch("assenze.views._helpers._assenze_permissions", return_value=PERMS_UTENTE)
    def test_doppione_bloccato(self, *_m):
        esistente = {"id": 9, "consenso": "In attesa", "created_datetime": datetime(2026, 11, 3, 9, 15)}
        with patch("assenze.views.richieste._insert_assenza", return_value=321) as ins, \
                patch("assenze.views.richieste._richiesta_gia_inviata", return_value=esistente), \
                patch("assenze.views.richieste._render_richiesta", side_effect=_render_finto):
            resp = self._invia()
        ins.assert_not_called()
        self.assertContains(resp, "già stata inviata il 03/11/2026 alle 09:15")
        self.assertContains(resp, "Le mie richieste")


class RichiestaGiaInviataTests(TestCase):
    def test_ignora_rifiutate_altri_tipi_e_altre_persone(self):
        from .views.richieste import _richiesta_gia_inviata

        righe = [
            {"id": 1, "copia_nome": "Mario Rossi", "tipo_assenza": "Permesso", "consenso": "Rifiutato"},
            {"id": 2, "copia_nome": "Anna Bianchi", "tipo_assenza": "Permesso", "consenso": "In attesa"},
            {"id": 3, "copia_nome": "Mario  Rossi", "tipo_assenza": "Malattia", "consenso": "In attesa"},
        ]
        inizio, fine = datetime(2026, 11, 10, 8), datetime(2026, 11, 10, 10)
        with patch("assenze.views._helpers._fetch_all_dict", return_value=righe):
            self.assertIsNone(_richiesta_gia_inviata(nominativo="Mario Rossi", tipo="Permesso", inizio=inizio, fine=fine))
            trovata = _richiesta_gia_inviata(nominativo="mario rossi", tipo="Malattia", inizio=inizio, fine=fine)
        self.assertEqual(trovata["id"], 3)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
@_con_patch_invio
class MalattiaAbilitatiTests(_Base):
    def test_elenco_vuoto_tutti_vedono_malattia(self, *_m):
        from .views._helpers import _malattia_permessi

        req = type("Req", (), {"user": self.user})()
        self.assertEqual(_malattia_permessi(req), {"elenco_attivo": False, "visibile": True, "per_tutti": False})

    def test_con_elenco_solo_gli_abilitati(self, *_m):
        from .views._helpers import _malattia_permessi

        MalattiaAbilitato.objects.create(legacy_anagrafica_id=999)
        req = type("Req", (), {"user": self.user})()
        self.assertEqual(_malattia_permessi(req), {"elenco_attivo": True, "visibile": False, "per_tutti": False})
        MalattiaAbilitato.objects.create(legacy_anagrafica_id=500)
        req = type("Req", (), {"user": self.user})()
        self.assertEqual(_malattia_permessi(req), {"elenco_attivo": True, "visibile": True, "per_tutti": True})

    @patch("assenze.views._helpers._assenze_permissions", return_value=PERMS_UTENTE)
    def test_non_abilitato_non_puo_inviare_malattia(self, *_m):
        MalattiaAbilitato.objects.create(legacy_anagrafica_id=999)
        with patch("assenze.views.richieste._insert_assenza", return_value=321) as ins, \
                patch("assenze.views.richieste._render_richiesta", side_effect=_render_finto):
            resp = self._invia(tipoassenza="Malattia", date_end="2026-11-11")
        ins.assert_not_called()
        self.assertContains(resp, "Non sei abilitato a inserire la malattia")

    @patch("assenze.views._helpers._assenze_permissions", return_value=PERMS_UTENTE)
    def test_abilitato_inserisce_malattia_per_un_altro_dipendente(self, *_m):
        MalattiaAbilitato.objects.create(legacy_anagrafica_id=500)
        with patch("assenze.views.richieste._insert_assenza", return_value=654) as ins, \
                patch("assenze.views.richieste._richiesta_gia_inviata", return_value=None), \
                patch("assenze.views._helpers._resolve_employee_identity_from_anagrafica",
                      return_value=("Anna Bianchi", "anna@example.com", 88)):
            resp = self._invia(tipoassenza="Malattia", date_end="2026-11-11", dipendente_id="42")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ins.call_args.args[0]["copia_nome"], "Anna Bianchi")
        conferma = self.client.session[_CONFERMA_SESSION_KEY]
        self.assertTrue(conferma["per_conto"])
        self.assertEqual(conferma["dipendente"], "Anna Bianchi")

    @patch("assenze.views._helpers._assenze_permissions", return_value=PERMS_UTENTE)
    def test_abilitato_malattia_non_sceglie_altri_per_i_permessi(self, *_m):
        MalattiaAbilitato.objects.create(legacy_anagrafica_id=500)
        with patch("assenze.views.richieste._insert_assenza", return_value=654) as ins, \
                patch("assenze.views.richieste._richiesta_gia_inviata", return_value=None), \
                patch("assenze.views._helpers._resolve_employee_identity_from_anagrafica",
                      return_value=("Anna Bianchi", "anna@example.com", 88)):
            self._invia(dipendente_id="42")
        # Senza inserimento per altri il dipendente scelto si ignora: resta la propria richiesta.
        self.assertEqual(ins.call_args.args[0]["copia_nome"], "Mario Rossi")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ImpostazioniMalattiaTests(_Base):
    @patch("assenze.views._helpers.puo_impostazioni_assenze", return_value=True)
    @patch("assenze.views._helpers._load_dipendenti_attivi_list", return_value=[
        {"id": 41, "full_name": "Anna Bianchi"}, {"id": 42, "full_name": "Luca Verdi"},
    ])
    def test_salva_elenco_e_lo_svuota(self, *_m):
        url = reverse("assenze_impostazioni")
        resp = self.client.post(url, {"form": "malattia", "malattia_abilitati": ["42"]})
        self.assertRedirects(resp, f"{url}#malattia", fetch_redirect_response=False)
        self.assertEqual(list(MalattiaAbilitato.objects.values_list("legacy_anagrafica_id", "nominativo")),
                         [(42, "Luca Verdi")])
        self.client.post(url, {"form": "malattia"})
        self.assertFalse(MalattiaAbilitato.objects.exists())

    @patch("assenze.views._helpers.puo_impostazioni_assenze", return_value=False)
    def test_senza_permesso_impostazioni_non_salva(self, *_m):
        self.client.post(reverse("assenze_impostazioni"), {"form": "malattia", "malattia_abilitati": ["42"]})
        self.assertFalse(MalattiaAbilitato.objects.exists())


class TemplateCommentiMonorigaTests(TestCase):
    """«{# #}» vale solo su una riga: su due righe il commento finisce a video."""

    def test_nessun_commento_cancelletto_su_piu_righe(self):
        from pathlib import Path

        cartella = Path(__file__).resolve().parent / "templates"
        fughe = [
            f"{f.relative_to(cartella)}:{n}"
            for f in cartella.rglob("*.html")
            for n, riga in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
            if riga.count("{#") > riga.count("#}")
        ]
        self.assertEqual(fughe, [])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CambioCapoAbilitatiTests(_Base):
    def _req(self):
        return type("Req", (), {"user": self.user})()

    def test_elenco_vuoto_tutti_possono(self):
        from .views._helpers import _puo_cambiare_capo

        self.assertTrue(_puo_cambiare_capo(self._req()))

    @patch("assenze.views._helpers._legacy_identity", return_value=("Anna", "anna@example.com", 7))
    @patch("assenze.views._helpers._resolve_anagrafica_employee_id_for_user", return_value=500)
    def test_con_elenco_solo_gli_abilitati(self, *_m):
        from .views._helpers import _puo_cambiare_capo

        CambioCapoAbilitato.objects.create(legacy_anagrafica_id=999)
        self.assertFalse(_puo_cambiare_capo(self._req()))
        CambioCapoAbilitato.objects.create(legacy_anagrafica_id=500)
        self.assertTrue(_puo_cambiare_capo(self._req()))

    @patch("assenze.views._helpers._legacy_identity", return_value=("Anna", "anna@example.com", 7))
    @patch("assenze.views._helpers._resolve_anagrafica_employee_id_for_user", return_value=None)
    def test_con_elenco_senza_anagrafica_non_puo(self, *_m):
        from .views._helpers import _puo_cambiare_capo

        CambioCapoAbilitato.objects.create(legacy_anagrafica_id=999)
        self.assertFalse(_puo_cambiare_capo(self._req()))

    @patch("assenze.views._helpers.puo_impostazioni_assenze", return_value=True)
    @patch("assenze.views._helpers._load_dipendenti_attivi_list", return_value=[
        {"id": 41, "full_name": "Anna Bianchi"}, {"id": 42, "full_name": "Luca Verdi"},
    ])
    def test_salva_elenco_e_lo_svuota(self, *_m):
        url = reverse("assenze_impostazioni")
        resp = self.client.post(url, {"form": "cambio_capo", "cambio_capo_abilitati": ["42"]})
        self.assertRedirects(resp, f"{url}#cambio-capo", fetch_redirect_response=False)
        self.assertEqual(list(CambioCapoAbilitato.objects.values_list("legacy_anagrafica_id", "nominativo")),
                         [(42, "Luca Verdi")])
        self.client.post(url, {"form": "cambio_capo"})
        self.assertFalse(CambioCapoAbilitato.objects.exists())

    @patch("assenze.views._helpers.puo_impostazioni_assenze", return_value=False)
    def test_senza_permesso_impostazioni_non_salva(self, *_m):
        self.client.post(reverse("assenze_impostazioni"), {"form": "cambio_capo", "cambio_capo_abilitati": ["42"]})
        self.assertFalse(CambioCapoAbilitato.objects.exists())
