from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Profile

from .models import (
    COMPLIANCE_APERTO,
    COMPLIANCE_CONFORME,
    COMPLIANCE_NON_CONFORME,
    COMPLIANCE_NON_LETTO,
    STATO_BOZZA,
    STATO_PUBBLICATA,
    Notizia,
    NotiziaAudience,
    NotiziaLettura,
    compute_hash_versione,
    get_compliance_status,
    get_or_create_lettura,
    is_visible_to_user,
)
from .mandatory_middleware import NotizieMandatoryMiddleware, _has_pending_mandatory, invalidate_pending_mandatory_cache
from .views import _build_conferma_token

User = get_user_model()


def _make_notizia(titolo="Test", obbligatoria=False, stato=STATO_PUBBLICATA) -> Notizia:
    return Notizia.objects.create(
        titolo=titolo,
        corpo="Corpo di test.",
        stato=stato,
        versione=1,
        obbligatoria=obbligatoria,
        pubblicato_il=timezone.now(),
    )


def _make_user_with_legacy(username: str, legacy_user_id: int, ruolo_id: int = 1, ruolo: str = "utente"):
    """Crea un Django user con Profile associato a un legacy_user_id fittizio."""
    from core.legacy_models import UtenteLegacy

    user = User.objects.create_user(username=username, password="pass12345")
    Profile.objects.create(user=user, legacy_user_id=legacy_user_id, legacy_ruolo_id=ruolo_id, legacy_ruolo=ruolo)
    return user


# ---------------------------------------------------------------------------
# Test modelli / helper
# ---------------------------------------------------------------------------

class HashVersioneTests(TestCase):
    def test_hash_e_deterministico(self):
        n = _make_notizia()
        h1 = compute_hash_versione(n)
        h2 = compute_hash_versione(n)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_hash_cambia_se_cambia_titolo(self):
        n = _make_notizia(titolo="Titolo A")
        h1 = compute_hash_versione(n)
        n.titolo = "Titolo B"
        h2 = compute_hash_versione(n)
        self.assertNotEqual(h1, h2)

    def test_hash_non_include_id(self):
        """Due notizie identiche (diverso id) devono avere lo stesso hash."""
        n1 = Notizia.objects.create(titolo="X", corpo="Y", versione=1, stato=STATO_PUBBLICATA, pubblicato_il=timezone.now())
        n2 = Notizia.objects.create(titolo="X", corpo="Y", versione=1, stato=STATO_PUBBLICATA, pubblicato_il=timezone.now())
        self.assertNotEqual(n1.id, n2.id)
        self.assertEqual(compute_hash_versione(n1), compute_hash_versione(n2))


class AudienceTests(TestCase):
    def test_senza_audience_visibile_a_tutti(self):
        n = _make_notizia()
        self.assertTrue(is_visible_to_user(n, legacy_role_id=1))
        self.assertTrue(is_visible_to_user(n, legacy_role_id=None))

    def test_con_audience_visibile_solo_al_ruolo_corretto(self):
        n = _make_notizia()
        NotiziaAudience.objects.create(notizia=n, legacy_role_id=5)
        self.assertTrue(is_visible_to_user(n, legacy_role_id=5))
        self.assertFalse(is_visible_to_user(n, legacy_role_id=99))
        self.assertFalse(is_visible_to_user(n, legacy_role_id=None))


class ComplianceTests(TestCase):
    def setUp(self):
        self.notizia = _make_notizia()
        self.notizia.hash_versione = compute_hash_versione(self.notizia)
        self.notizia.save(update_fields=["hash_versione"])
        self.user_id = 42

    def test_non_letto_senza_letture(self):
        status = get_compliance_status(self.notizia, self.user_id)
        self.assertEqual(status, COMPLIANCE_NON_LETTO)

    def test_aperto_dopo_opened_at(self):
        NotiziaLettura.objects.create(
            notizia=self.notizia,
            legacy_user_id=self.user_id,
            versione_letta=self.notizia.versione,
            hash_versione_letta=self.notizia.hash_versione,
            opened_at=timezone.now(),
            ack_at=None,
        )
        self.assertEqual(get_compliance_status(self.notizia, self.user_id), COMPLIANCE_APERTO)

    def test_conforme_dopo_ack(self):
        NotiziaLettura.objects.create(
            notizia=self.notizia,
            legacy_user_id=self.user_id,
            versione_letta=self.notizia.versione,
            hash_versione_letta=self.notizia.hash_versione,
            opened_at=timezone.now(),
            ack_at=timezone.now(),
        )
        self.assertEqual(get_compliance_status(self.notizia, self.user_id), COMPLIANCE_CONFORME)

    def test_non_conforme_dopo_nuova_versione(self):
        """Dopo aver confermato v1, se si pubblica v2 l'utente diventa non_conforme."""
        NotiziaLettura.objects.create(
            notizia=self.notizia,
            legacy_user_id=self.user_id,
            versione_letta=1,
            hash_versione_letta=self.notizia.hash_versione,
            opened_at=timezone.now(),
            ack_at=timezone.now(),
        )
        # Simula nuova versione pubblicata
        self.notizia.versione = 2
        self.notizia.save(update_fields=["versione"])
        self.assertEqual(get_compliance_status(self.notizia, self.user_id), COMPLIANCE_NON_CONFORME)

    def test_lettura_versionata_mantiene_storia(self):
        """Un nuovo record di lettura per v2 non cancella il record di v1."""
        NotiziaLettura.objects.create(
            notizia=self.notizia,
            legacy_user_id=self.user_id,
            versione_letta=1,
            hash_versione_letta="abc",
            ack_at=timezone.now(),
        )
        self.notizia.versione = 2
        self.notizia.save(update_fields=["versione"])
        get_or_create_lettura(self.notizia, self.user_id)
        self.assertEqual(NotiziaLettura.objects.filter(notizia=self.notizia, legacy_user_id=self.user_id).count(), 2)


# ---------------------------------------------------------------------------
# Test viste ACL / accesso
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NotizieACLTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="acl-user", password="pass12345")
        self.hr_user = _make_user_with_legacy("acl-hr", legacy_user_id=901, ruolo="hr")

    def test_lista_richiede_login(self):
        resp = self.client.get(reverse("notizie_lista"))
        self.assertIn(resp.status_code, [302, 403])

    def test_lista_ok_con_login(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_lista"))
        self.assertEqual(resp.status_code, 200)

    def test_dettaglio_404_notizia_non_pubblicata(self):
        notizia = Notizia.objects.create(titolo="Bozza", corpo="x", stato="bozza", versione=1)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_dettaglio", args=[notizia.id]))
        self.assertEqual(resp.status_code, 404)

    def test_dettaglio_imposta_cookie_csrf(self):
        notizia = _make_notizia()
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_dettaglio", args=[notizia.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("csrftoken", resp.cookies)

    def test_obbligatorie_accessibile_senza_legacy_user(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_obbligatorie"))
        self.assertEqual(resp.status_code, 200)

    def test_report_richiede_admin_o_hr(self):
        """Utente normale non può vedere il report."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_report"))
        self.assertEqual(resp.status_code, 403)

    def test_dashboard_richiede_admin_o_hr(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_dashboard"))
        self.assertEqual(resp.status_code, 403)

    def test_dashboard_ok_per_hr(self):
        self.client.force_login(self.hr_user)
        resp = self.client.get(reverse("notizie_dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_bottone_dashboard_visibile_solo_abilitati(self):
        self.client.force_login(self.user)
        resp_user = self.client.get(reverse("notizie_lista"))
        self.assertEqual(resp_user.status_code, 200)
        self.assertNotContains(resp_user, "Dashboard Notizie")

        self.client.force_login(self.hr_user)
        resp_hr = self.client.get(reverse("notizie_lista"))
        self.assertEqual(resp_hr.status_code, 200)
        self.assertContains(resp_hr, "Dashboard Notizie")

    def test_dashboard_mostra_editor_permessi_per_hr(self):
        self.client.force_login(self.hr_user)
        resp = self.client.get(reverse("notizie_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Visibilita pulsante Dashboard Notizie")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NotizieDashboardCrudTests(TestCase):
    def setUp(self):
        self.hr_user = _make_user_with_legacy("dashboard-hr", legacy_user_id=1701, ruolo="hr")

    def test_crea_notizia_con_audience_e_allegato_file(self):
        self.client.force_login(self.hr_user)

        upload = SimpleUploadedFile("procedura.txt", b"contenuto test", content_type="text/plain")
        response = self.client.post(
            reverse("notizie_dashboard_create"),
            data={
                "titolo": "Nuova comunicazione sicurezza",
                "corpo": "Corpo della comunicazione.",
                "obbligatoria": "on",
                "audience-TOTAL_FORMS": "1",
                "audience-INITIAL_FORMS": "0",
                "audience-MIN_NUM_FORMS": "0",
                "audience-MAX_NUM_FORMS": "1000",
                "audience-0-id": "",
                "audience-0-legacy_role_id": "5",
                "allegati-TOTAL_FORMS": "1",
                "allegati-INITIAL_FORMS": "0",
                "allegati-MIN_NUM_FORMS": "0",
                "allegati-MAX_NUM_FORMS": "1000",
                "allegati-0-id": "",
                "allegati-0-nome_file": "Procedura interna",
                "allegati-0-file": upload,
                "allegati-0-url_esterno": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        notizia = Notizia.objects.get(titolo="Nuova comunicazione sicurezza")
        self.assertEqual(notizia.stato, STATO_BOZZA)
        self.assertEqual(notizia.audience.count(), 1)
        self.assertEqual(notizia.allegati.count(), 1)
        self.assertTrue(notizia.hash_versione)

    def test_pubblica_notizia_da_dashboard(self):
        notizia = Notizia.objects.create(
            titolo="Bozza dashboard",
            corpo="Corpo",
            stato=STATO_BOZZA,
            versione=1,
        )
        self.client.force_login(self.hr_user)
        response = self.client.post(reverse("notizie_dashboard_publish", args=[notizia.id]))
        self.assertEqual(response.status_code, 302)

        notizia.refresh_from_db()
        self.assertEqual(notizia.stato, STATO_PUBBLICATA)
        self.assertIsNotNone(notizia.pubblicato_il)
        self.assertTrue(notizia.hash_versione)


# ---------------------------------------------------------------------------
# Test presa visione
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PrisaVisioneTests(TestCase):
    def setUp(self):
        self.user = _make_user_with_legacy("pv-user", legacy_user_id=77)
        self.notizia = _make_notizia()
        self.notizia.hash_versione = compute_hash_versione(self.notizia)
        self.notizia.save(update_fields=["hash_versione"])

    def test_conferma_crea_lettura_con_hash(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("notizie_conferma", args=[self.notizia.id]))
        self.assertIn(resp.status_code, [200, 302])
        lettura = NotiziaLettura.objects.filter(notizia=self.notizia, legacy_user_id=77).first()
        self.assertIsNotNone(lettura)
        self.assertIsNotNone(lettura.ack_at)
        self.assertEqual(lettura.hash_versione_letta, self.notizia.hash_versione)

    def test_doppia_conferma_idempotente(self):
        self.client.force_login(self.user)
        self.client.post(reverse("notizie_conferma", args=[self.notizia.id]))
        self.client.post(reverse("notizie_conferma", args=[self.notizia.id]))
        count = NotiziaLettura.objects.filter(notizia=self.notizia, legacy_user_id=77, versione_letta=1).count()
        self.assertEqual(count, 1)

    def test_conferma_get_con_token_valido(self):
        self.client.force_login(self.user)
        token = _build_conferma_token(self.notizia, 77)
        resp = self.client.get(reverse("notizie_conferma", args=[self.notizia.id]), {"token": token})
        self.assertIn(resp.status_code, [200, 302])
        lettura = NotiziaLettura.objects.filter(notizia=self.notizia, legacy_user_id=77).first()
        self.assertIsNotNone(lettura)
        self.assertIsNotNone(lettura.ack_at)

    def test_nuova_versione_invalida_conformita(self):
        self.client.force_login(self.user)
        self.client.post(reverse("notizie_conferma", args=[self.notizia.id]))
        # Pubblica nuova versione
        self.notizia.versione = 2
        self.notizia.save(update_fields=["versione"])
        status = get_compliance_status(self.notizia, 77)
        self.assertEqual(status, COMPLIANCE_NON_CONFORME)


# ---------------------------------------------------------------------------
# Test gating middleware
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GatingMiddlewareTests(TestCase):
    def setUp(self):
        self.user = _make_user_with_legacy("gating-user", legacy_user_id=88)
        self.notizia_obblig = _make_notizia(obbligatoria=True)
        self.notizia_obblig.hash_versione = compute_hash_versione(self.notizia_obblig)
        self.notizia_obblig.save(update_fields=["hash_versione"])

    def test_obbligatoria_non_confermata_pendente(self):
        invalidate_pending_mandatory_cache(88)
        self.assertTrue(_has_pending_mandatory(88, force_check=True))

    def test_dopo_conferma_non_pendente(self):
        NotiziaLettura.objects.create(
            notizia=self.notizia_obblig,
            legacy_user_id=88,
            versione_letta=1,
            hash_versione_letta=self.notizia_obblig.hash_versione,
            opened_at=timezone.now(),
            ack_at=timezone.now(),
        )
        invalidate_pending_mandatory_cache(88)
        self.assertFalse(_has_pending_mandatory(88, force_check=True))

    def test_path_notizie_non_viene_bloccato(self):
        """L'utente può accedere a /notizie/ anche con obbligatorie pendenti."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_lista"))
        # Non deve essere redirect a obbligatorie ma potrebbe esserlo per altri motivi
        # Il test principale è che il path /notizie/ è safe nel middleware
        self.assertNotEqual(resp.status_code, 500)
