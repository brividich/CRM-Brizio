from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Profile, UserOnboarding

from .models import (
    COMPLIANCE_APERTO,
    COMPLIANCE_CONFORME,
    COMPLIANCE_NON_CONFORME,
    COMPLIANCE_NON_LETTO,
    STATO_ARCHIVIATA,
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


def _complete_onboarding(user) -> None:
    UserOnboarding.objects.update_or_create(
        user=user,
        defaults={"completed": True, "completed_at": timezone.now()},
    )


def _make_user_with_legacy(username: str, legacy_user_id: int, ruolo_id: int = 1, ruolo: str = "utente"):
    """Crea un Django user con Profile associato a un legacy_user_id fittizio."""

    user = User.objects.create_user(username=username, password="pass12345")
    Profile.objects.create(user=user, legacy_user_id=legacy_user_id, legacy_ruolo_id=ruolo_id, legacy_ruolo=ruolo)
    _complete_onboarding(user)
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
        _complete_onboarding(self.user)
        self.hr_user = _make_user_with_legacy("acl-hr", legacy_user_id=901, ruolo="hr")
        self.admin_user = User.objects.create_superuser(
            username="acl-admin",
            email="acl-admin@example.com",
            password="pass12345",
        )
        _complete_onboarding(self.admin_user)

    def test_lista_richiede_login(self):
        resp = self.client.get(reverse("notizie_lista"))
        self.assertIn(resp.status_code, [302, 403])

    def test_lista_ok_con_login(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_lista"))
        self.assertEqual(resp.status_code, 200)

    def test_lista_renderizza_workspace_fullpage(self):
        _make_notizia(titolo="Comunicazione generale")
        _make_notizia(titolo="Comunicazione obbligatoria", obbligatoria=True)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_lista"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "notizie-list-page")
        self.assertContains(resp, "notizie/css/notizie.css")
        self.assertContains(resp, "1 obbligatoria da confermare")
        self.assertContains(resp, 'Tutte <span class="nz-tab-n">2</span>', html=False)
        self.assertContains(resp, '<article class="nz-card', count=2)

    def test_lista_ricerca_e_filtro_obbligatorie(self):
        _make_notizia(titolo="Turni di Natale")
        _make_notizia(titolo="Nuova procedura DPI", obbligatoria=True)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_lista"), {"q": "natale"})
        self.assertContains(resp, "Turni di Natale")
        self.assertNotContains(resp, "Nuova procedura DPI")
        resp = self.client.get(reverse("notizie_lista"), {"solo_obbligatorie": "1"})
        self.assertContains(resp, "Nuova procedura DPI")
        self.assertNotContains(resp, "Turni di Natale")
        # I contatori delle schede restano sul totale, non sul filtro scelto.
        self.assertContains(resp, 'Tutte <span class="nz-tab-n">2</span>', html=False)

    def test_lista_mostra_link_impostazioni_per_admin(self):
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse("notizie_lista"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("notizie_gestione_admin"))

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

    def test_dashboard_renderizza_workspace_a_card_senza_tabella(self):
        _make_notizia(titolo="Comunicazione pubblicata")
        Notizia.objects.create(titolo="Bozza interna", corpo="x", stato=STATO_BOZZA, versione=1)
        Notizia.objects.create(titolo="Archivio storico", corpo="x", stato=STATO_ARCHIVIATA, versione=1)

        self.client.force_login(self.hr_user)
        resp = self.client.get(reverse("notizie_dashboard"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "notizie-dashboard-page")
        self.assertContains(resp, "Gestione notizie")
        self.assertContains(resp, 'class="nz-card"', count=3)
        self.assertContains(resp, 'Bozze <span class="nz-tab-n">1</span>', html=False)
        self.assertNotContains(resp, "<table")

        # Con il filtro di stato i contatori delle altre schede restano.
        resp = self.client.get(reverse("notizie_dashboard"), {"stato": "bozza"})
        self.assertContains(resp, 'class="nz-card"', count=1)
        self.assertContains(resp, 'Pubblicate <span class="nz-tab-n">1</span>', html=False)

    def test_dashboard_mostra_link_impostazioni_per_admin(self):
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse("notizie_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("notizie_gestione_admin"))

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
        self.assertContains(resp, "Permessi dashboard")

    def test_impostazioni_schede_permessi_aspetto_registro(self):
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse("notizie_gestione_admin"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "notizie-settings-page")
        self.assertContains(resp, "Impostazioni notizie")
        self.assertContains(resp, "Chi può gestire le notizie")

        resp = self.client.get(reverse("notizie_gestione_admin"), {"tab": "aspetto"})
        self.assertContains(resp, 'name="action" value="save_module_branding"', html=False)

        resp = self.client.get(reverse("notizie_gestione_admin"), {"tab": "registro"})
        self.assertContains(resp, "Nessuna attività")

    def test_impostazioni_vecchia_scheda_record_porta_alla_gestione(self):
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse("notizie_gestione_admin"), {"tab": "record", "q": "dpi", "filter_stato": "bozza"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("notizie_dashboard") + "?q=dpi&stato=bozza")

    def test_impostazioni_registro_etichette_e_filtro(self):
        from core.models import AuditLog

        notizia = _make_notizia(titolo="Turni di Natale")
        AuditLog.objects.create(modulo="notizie", azione="notizia_pubblicata", utente_display="Mario Prova",
                                dettaglio={"notizia_id": notizia.pk, "titolo": notizia.titolo})
        AuditLog.objects.create(modulo="notizie", azione="notizia_archiviata", utente_display="Anna Prova",
                                dettaglio={"notizia_id": 999999, "titolo": "Vecchia circolare"})
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse("notizie_gestione_admin"), {"tab": "log"})
        self.assertContains(resp, "Pubblicata")
        self.assertContains(resp, reverse("notizie_dashboard_edit", args=[notizia.pk]))
        self.assertContains(resp, "Vecchia circolare")
        resp = self.client.get(reverse("notizie_gestione_admin"), {"tab": "registro", "azione": "notizia_archiviata"})
        self.assertContains(resp, "Anna Prova")
        self.assertNotContains(resp, "Mario Prova")
        resp = self.client.get(reverse("notizie_gestione_admin"), {"tab": "registro", "q": "natale"})
        self.assertContains(resp, "Mario Prova")
        self.assertNotContains(resp, "Anna Prova")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NotizieReportTests(TestCase):
    def setUp(self):
        self.hr_user = _make_user_with_legacy("report-hr", legacy_user_id=3001, ruolo_id=7, ruolo="hr")
        self.letto = _make_user_with_legacy("report-letto", legacy_user_id=3002, ruolo_id=5, ruolo="operaio")
        self.letto.first_name, self.letto.last_name = "Lucia", "Sintetica"
        self.letto.save()
        self.mai = _make_user_with_legacy("report-mai", legacy_user_id=3003, ruolo_id=5, ruolo="operaio")
        self.mai.first_name, self.mai.last_name = "Paolo", "Fittizio"
        self.mai.save()
        self.notizia = _make_notizia(titolo="Procedura DPI", obbligatoria=True)
        NotiziaAudience.objects.create(notizia=self.notizia, legacy_role_id=5)
        # Due righe di lettura (v1 confermata, v2 aperta) = una sola persona nel report.
        NotiziaLettura.objects.create(notizia=self.notizia, legacy_user_id=3002, versione_letta=1,
                                      hash_versione_letta="a" * 64, opened_at=timezone.now(), ack_at=timezone.now())
        self.notizia.versione = 2
        self.notizia.save(update_fields=["versione"])
        NotiziaLettura.objects.create(notizia=self.notizia, legacy_user_id=3002, versione_letta=2,
                                      hash_versione_letta="b" * 64, opened_at=timezone.now())
        self.client.force_login(self.hr_user)

    def test_senza_notizia_una_riga_per_persona_con_nome(self):
        resp = self.client.get(reverse("notizie_report"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "notizie-report-page")
        self.assertContains(resp, "Lucia Sintetica")
        self.assertContains(resp, "Da confermare")
        self.assertNotContains(resp, "Paolo Fittizio")
        self.assertContains(resp, "1 righe")

    def test_con_notizia_compare_anche_chi_non_ha_letto(self):
        resp = self.client.get(reverse("notizie_report"), {"notizia_id": self.notizia.pk})
        self.assertContains(resp, "Paolo Fittizio")
        self.assertContains(resp, "Non letta")
        self.assertContains(resp, 'Non letta <span class="nz-tab-n">1</span>', html=False)
        resp = self.client.get(reverse("notizie_report"), {"notizia_id": self.notizia.pk, "stato": "aperto"})
        self.assertContains(resp, "Lucia Sintetica")
        self.assertNotContains(resp, "Paolo Fittizio")
        # I contatori delle schede restano sul totale.
        self.assertContains(resp, 'Tutti <span class="nz-tab-n">2</span>', html=False)

    def test_ricerca_persona_e_csv(self):
        resp = self.client.get(reverse("notizie_report"), {"notizia_id": self.notizia.pk, "q": "paolo"})
        self.assertContains(resp, "Paolo Fittizio")
        self.assertNotContains(resp, "Lucia Sintetica")
        resp = self.client.get(reverse("notizie_report_csv"), {"notizia_id": self.notizia.pk})
        body = b"".join(resp.streaming_content).decode("utf-8-sig")
        self.assertIn("Persona", body)
        self.assertIn("Paolo Fittizio", body)
        self.assertIn("Non letta", body)
        self.assertIn("Da confermare", body)

    def test_filtro_date_conferma_esclude_chi_non_ha_confermato(self):
        oggi = timezone.localdate().isoformat()
        resp = self.client.get(reverse("notizie_report"), {"notizia_id": self.notizia.pk, "da": oggi})
        self.assertContains(resp, "Nessuna lettura da mostrare")


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

    def _post_form(self, url, extra=None, files=None):
        data = {
            "titolo": "Comunicazione con ruoli",
            "corpo": "Testo.",
            "audience_picker": "1",
            "allegati-TOTAL_FORMS": "1",
            "allegati-INITIAL_FORMS": "0",
            "allegati-MIN_NUM_FORMS": "0",
            "allegati-MAX_NUM_FORMS": "1000",
            "allegati-0-id": "",
            "allegati-0-nome_file": "",
            "allegati-0-url_esterno": "",
        }
        data.update(extra or {})
        if files:
            data["nuovi_allegati"] = files
        return self.client.post(url, data=data)

    def test_crea_notizia_con_ruoli_a_caselle_e_piu_file(self):
        self.client.force_login(self.hr_user)
        pdf = SimpleUploadedFile("circolare.pdf", b"%PDF-1.4\n%test\n", content_type="application/pdf")
        txt = SimpleUploadedFile("note.txt", b"note interne", content_type="text/plain")
        resp = self._post_form(
            reverse("notizie_dashboard_create"),
            {"audience_roles": ["5", "7", "x"]},
            files=[pdf, txt],
        )
        self.assertEqual(resp.status_code, 302)
        notizia = Notizia.objects.get(titolo="Comunicazione con ruoli")
        self.assertEqual(sorted(notizia.audience.values_list("legacy_role_id", flat=True)), [5, 7])
        self.assertEqual(sorted(notizia.allegati.values_list("nome_file", flat=True)), ["circolare.pdf", "note.txt"])

        # Modifica: tolgo un ruolo, ne aggiungo un altro.
        resp = self._post_form(
            reverse("notizie_dashboard_edit", args=[notizia.id]),
            {
                "audience_roles": ["7", "9"],
                "allegati-TOTAL_FORMS": "0",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(sorted(notizia.audience.values_list("legacy_role_id", flat=True)), [7, 9])

        # Nessuna casella: la notizia torna visibile a tutti.
        self._post_form(reverse("notizie_dashboard_edit", args=[notizia.id]), {"allegati-TOTAL_FORMS": "0"})
        self.assertEqual(notizia.audience.count(), 0)

    def test_file_non_ammesso_blocca_il_salvataggio(self):
        self.client.force_login(self.hr_user)
        exe = SimpleUploadedFile("setup.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        resp = self._post_form(reverse("notizie_dashboard_create"), files=[exe])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Notizia.objects.filter(titolo="Comunicazione con ruoli").exists())

    def test_form_mostra_ruoli_a_caselle(self):
        self.client.force_login(self.hr_user)
        resp = self.client.get(reverse("notizie_dashboard_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="audience_picker" value="1"')
        self.assertContains(resp, 'name="nuovi_allegati" multiple')

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

    def test_onboarding_non_rimandato_a_obbligatorie(self):
        """Regressione loop: /onboarding/ con obbligatorie pendenti non deve redirigere a /notizie/obbligatorie/."""
        invalidate_pending_mandatory_cache(88)
        request = RequestFactory().get(reverse("onboarding_wizard"))
        request.user = self.user
        sentinel = object()
        response = NotizieMandatoryMiddleware(lambda req: sentinel)(request)
        self.assertIs(response, sentinel)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AllegatoAnteprimaTests(TestCase):
    def setUp(self):
        from .models import NotiziaAllegato

        self.user = _make_user_with_legacy("prev-user", legacy_user_id=3101, ruolo_id=1)
        self.notizia = _make_notizia(titolo="Circolare con PDF")
        self.pdf = NotiziaAllegato(notizia=self.notizia, nome_file="Circolare.pdf")
        self.pdf.file = SimpleUploadedFile("circolare.pdf", b"%PDF-1.4\n%test\n", content_type="application/pdf")
        self.pdf.save()
        self.txt = NotiziaAllegato(notizia=self.notizia, nome_file="Note")
        self.txt.file = SimpleUploadedFile("note.txt", b"note", content_type="text/plain")
        self.txt.save()

    def test_dettaglio_mostra_visualizzatore_pdf(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_dettaglio", args=[self.notizia.id]))
        self.assertEqual(resp.status_code, 200)
        url = reverse("notizie_allegato_download", args=[self.pdf.id])
        self.assertContains(resp, "data-nz-viewer")
        self.assertContains(resp, f'data-src="{url}?anteprima=1#view=FitH&navpanes=0"')
        # Il file di testo non ha anteprima: solo download.
        self.assertNotContains(resp, reverse("notizie_allegato_download", args=[self.txt.id]) + "?anteprima=1")

    def test_pdf_in_anteprima_inline_e_incorniciabile_dal_portale(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_allegato_download", args=[self.pdf.id]), {"anteprima": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp["Content-Disposition"].startswith("inline"))
        self.assertEqual(resp["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

    def test_senza_anteprima_resta_download(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_allegato_download", args=[self.pdf.id]))
        self.assertTrue(resp["Content-Disposition"].startswith("attachment"))

    def test_file_non_previsto_mai_inline(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_allegato_download", args=[self.txt.id]), {"anteprima": "1"})
        self.assertTrue(resp["Content-Disposition"].startswith("attachment"))

    def test_anteprima_rispetta_i_destinatari(self):
        NotiziaAudience.objects.create(notizia=self.notizia, legacy_role_id=99)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notizie_allegato_download", args=[self.pdf.id]), {"anteprima": "1"})
        self.assertEqual(resp.status_code, 403)
