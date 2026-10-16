"""Blocco B (UX operativa): «Fatta oggi», segnalazione guasto da QR, meno home,
glossario visibile, lista asset dentro la shell. Dati sintetici."""

from __future__ import annotations

import re
import shutil
import tempfile
from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
)

User = get_user_model()


def _complete_onboarding(user) -> None:
    from core.models import UserOnboarding

    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()}
    )


def _png_bytes() -> bytes:
    """PNG 1x1 valido (firma reale: il controllo MIME guarda il contenuto)."""
    try:
        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (1, 1), (200, 30, 30)).save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:  # pragma: no cover - Pillow e' una dipendenza del progetto
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
        )


class _MediaMixin:
    @classmethod
    def setUpClass(cls):
        cls._tmp_root = tempfile.mkdtemp(prefix="assets-blocco-b-")
        cls._override = override_settings(MEDIA_ROOT=cls._tmp_root, ASSETS_PRIVATE_ROOT=cls._tmp_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._tmp_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# B2 — «Fatta oggi»
# ---------------------------------------------------------------------------


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FattaOggiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="b2-admin", password="x", email="b2@example.com")
        cls.category = AssetCategory.objects.create(code="b2-cat", label="B2")
        cls.asset = Asset.objects.create(asset_tag="B2-1", name="Pressa B2", asset_category=cls.category)
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="b2-plan", label="Ingrassaggio B2")
        cls.doc_plan = MaintenanceInterventionTemplate.objects.create(
            code="b2-doc", label="Verifica con verbale", attachment_required=True
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self.assignment = MaintenancePlanAssignment.objects.create(
            plan=self.plan,
            target_type=MaintenancePlanAssignment.TARGET_ASSET,
            asset=self.asset,
            frequency=MaintenancePlanAssignment.FREQ_DAYS,
            interval=30,
            first_due_date=timezone.localdate(),
        )
        self.occurrence = MaintenanceOccurrence.objects.create(
            plan=self.plan, assignment=self.assignment, asset=self.asset,
            due_date=timezone.localdate() - timedelta(days=1), warning_days=10,
        )

    def _url(self, occurrence):
        return reverse("assets:occurrence_quick_complete", args=[occurrence.pk])

    def test_ammissibile_registra_oggi_e_crea_la_successiva(self):
        response = self.client.post(self._url(self.occurrence), HTTP_REFERER="/assets/manutenzione/da-fare/")
        self.assertEqual(response.status_code, 302)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, MaintenanceOccurrence.STATUS_DONE)
        self.assertEqual(self.occurrence.completed_on, timezone.localdate())
        self.assertEqual(self.occurrence.completion_notes, "Registrata con «Fatta oggi»")
        self.assertTrue(
            MaintenanceOccurrence.objects.filter(
                plan=self.plan, asset=self.asset, status=MaintenanceOccurrence.STATUS_OPEN
            ).exists()
        )

    def test_risposta_htmx_con_riga_e_trigger(self):
        response = self.client.post(self._url(self.occurrence), {"cols": "5"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Trigger"], "occurrenceCompleted")
        self.assertContains(response, "Fatta oggi")
        self.assertContains(response, 'colspan="5"')
        self.assertContains(response, "prossima scadenza")

    def test_con_allegato_obbligatorio_409_e_nessuna_modifica(self):
        occ = MaintenanceOccurrence.objects.create(
            plan=self.doc_plan, asset=self.asset, due_date=timezone.localdate(), warning_days=10
        )
        response = self.client.post(self._url(occ), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 409)
        occ.refresh_from_db()
        self.assertEqual(occ.status, MaintenanceOccurrence.STATUS_OPEN)
        # Senza HTMX si passa al form completo.
        response = self.client.post(self._url(occ))
        self.assertRedirects(response, reverse("assets:occurrence_complete", args=[occ.pk]), fetch_redirect_response=False)

    def test_senza_permesso_403(self):
        operatore = User.objects.create_user(username="b2-operatore", password="x", email="op@example.com")
        _complete_onboarding(operatore)
        self.client.force_login(operatore)
        response = self.client.post(self._url(self.occurrence))
        self.assertEqual(response.status_code, 403)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, MaintenanceOccurrence.STATUS_OPEN)

    def test_anonimo_va_al_login(self):
        self.client.logout()
        response = self.client.post(self._url(self.occurrence))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_pulsante_solo_sulle_righe_ammissibili(self):
        doc = MaintenanceOccurrence.objects.create(
            plan=self.doc_plan, asset=self.asset, due_date=timezone.localdate(), warning_days=10
        )
        response = self.client.get(reverse("assets:maintenance_da_fare"), {"mio": "0"})
        self.assertContains(response, f'data-md-quick="{self._url(self.occurrence)}"', html=False)
        # Con documento obbligatorio niente «Fatta oggi»: la riga resta con «Registra».
        self.assertNotContains(response, f'data-md-quick="{self._url(doc)}"', html=False)
        self.assertContains(response, reverse("assets:occurrence_complete", args=[doc.pk]), html=False)
        self.assertContains(response, 'hx-trigger="occurrenceCompleted from:body"', html=False)

    def test_partial_kpi(self):
        response = self.client.get(reverse("assets:maintenance_da_fare"), {"mio": "0", "partial": "kpi"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="md-da-fare-kpis"', html=False)
        self.assertNotContains(response, "<html")

    def test_massiva_con_mix_ammissibili(self):
        other = Asset.objects.create(asset_tag="B2-2", name="Tornio B2", asset_category=self.category)
        ok2 = MaintenanceOccurrence.objects.create(plan=self.plan, asset=other, due_date=timezone.localdate(), warning_days=10)
        doc = MaintenanceOccurrence.objects.create(plan=self.doc_plan, asset=other, due_date=timezone.localdate(), warning_days=10)
        response = self.client.post(
            reverse("assets:occurrence_quick_complete_bulk"),
            {"occurrence_ids": [self.occurrence.pk, ok2.pk, doc.pk], "next": reverse("assets:maintenance_da_fare")},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        for occ, expected in ((self.occurrence, "DONE"), (ok2, "DONE"), (doc, "OPEN")):
            occ.refresh_from_db()
            self.assertEqual(occ.status, expected)
        self.assertContains(response, "2 registrate oggi, 1 esclusa (richiedono allegato o sono esterne)")


# ---------------------------------------------------------------------------
# B3 — segnalazione guasto da QR
# ---------------------------------------------------------------------------


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SegnalaGuastoTests(_MediaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(username="b3-user", password="x", email="b3@example.com")
        cls.asset = Asset.objects.create(
            asset_tag="B3-1", name="Centro di lavoro B3", reparto="Officina B3", status=Asset.STATUS_IN_USE,
            asset_type=Asset.TYPE_CNC,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("assets:asset_quick_report")

    def _post(self, extra=None, query="", **kwargs):
        data = {"titolo": "Perdita olio", "descrizione": "Macchia sotto il basamento"}
        data.update(extra or {})
        return self.client.post(self.url + query, data, **kwargs)

    def test_con_asset_niente_select_e_asset_giusto(self):
        response = self.client.get(self.url, {"asset": self.asset.pk})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="asset_id"', html=False)
        self.assertContains(response, 'name="fixed_asset" value="%d"' % self.asset.pk, html=False)
        self.assertContains(response, "Centro di lavoro B3")
        self.assertContains(response, "Officina B3")

    def test_asset_inesistente_404(self):
        response = self.client.get(self.url, {"asset": 999999})
        self.assertEqual(response.status_code, 404)

    def test_senza_categoria_usa_la_categoria_di_default(self):
        from tickets.models import Ticket

        response = self._post({"fixed_asset": self.asset.pk}, query=f"?asset={self.asset.pk}")
        self.assertEqual(response.status_code, 200)
        ticket = Ticket.objects.get(asset=self.asset)
        self.assertEqual(ticket.categoria, "GENERICA")
        self.assertEqual(ticket.priorita, "MEDIA")
        self.assertContains(response, ticket.numero_ticket)
        self.assertContains(response, "Segnala un altro problema")

    def test_foto_valida_crea_allegato(self):
        from tickets.models import Ticket, TicketAllegato

        foto = SimpleUploadedFile("guasto.png", _png_bytes(), content_type="image/png")
        self._post({"fixed_asset": self.asset.pk, "foto": foto}, query=f"?asset={self.asset.pk}")
        ticket = Ticket.objects.get(asset=self.asset)
        self.assertEqual(TicketAllegato.objects.filter(ticket=ticket).count(), 1)

    def test_foto_con_mime_errato_ticket_creato_allegato_scartato(self):
        from tickets.models import Ticket, TicketAllegato

        finta = SimpleUploadedFile("guasto.png", b"non sono una foto", content_type="image/png")
        response = self._post({"fixed_asset": self.asset.pk, "foto": finta}, query=f"?asset={self.asset.pk}")
        ticket = Ticket.objects.get(asset=self.asset)
        self.assertFalse(TicketAllegato.objects.filter(ticket=ticket).exists())
        self.assertContains(response, "scartata")

    def test_da_qr_niente_sidebar(self):
        response = self.client.get(self.url, {"asset": self.asset.pk, "from": "qr"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="as-side"', html=False)
        self.assertNotContains(response, 'class="as-shell"', html=False)
        self.assertContains(response, "Torna alla macchina")
        self.assertContains(response, 'capture="environment"', html=False)

    def test_landing_qr_porta_alla_segnalazione_minimale(self):
        response = self.client.get(reverse("assets:asset_qr_landing", kwargs={"asset_tag": self.asset.asset_tag}))
        self.assertContains(response, f"?asset={self.asset.pk}&amp;from=qr", html=False)

    def test_priorita_tre_scelte(self):
        response = self.client.get(self.url, {"asset": self.asset.pk})
        self.assertContains(response, "Quanto è urgente?")
        for code in ("BASSA", "MEDIA", "ALTA"):
            self.assertContains(response, f'value="{code}"', html=False)
        self.assertNotContains(response, 'value="URGENTE"', html=False)

    def test_anonimo_va_al_login(self):
        self.client.logout()
        response = self.client.get(self.url, {"asset": self.asset.pk, "from": "qr"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])


# ---------------------------------------------------------------------------
# B4 — meno home
# ---------------------------------------------------------------------------


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MenoHomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="b4-admin", password="x", email="b4@example.com")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_kpi_porta_alla_panoramica_con_query(self):
        response = self.client.get(reverse("assets:maintenance_kpi"), {"category": "3"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("assets:maintenance_responsabile") + "?category=3#dettaglio")

    def test_vista_sintesi_porta_al_dettaglio(self):
        response = self.client.get(reverse("assets:maintenance_responsabile"), {"vista": "sintesi", "reparto": "A"})
        self.assertEqual(response["Location"], reverse("assets:maintenance_responsabile") + "?reparto=A#dettaglio")

    def test_panoramica_sei_tessere_in_testa_e_dettaglio(self):
        response = self.client.get(reverse("assets:maintenance_responsabile"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        start = html.index("data-panoramica-headline")
        end = html.index('class="pn-wrap"', start)
        self.assertEqual(len(re.findall(r'<(?:a|div) class="md-kpi[ "]', html[start:end])), 6)
        for label in ("Scadute", "In scadenza 7 giorni", "Non pianificate", "Interventi aperti",
                      "Puntualità ultimi 90 giorni", "Arretrato"):
            self.assertIn(label, html[start:end])
        self.assertContains(response, '<details class="md-section" id="dettaglio"', html=False)
        self.assertContains(response, "Dettaglio indicatori")

    def test_vecchi_url_non_danno_404(self):
        for name in ("maintenance_kpi", "il_mio_turno"):
            response = self.client.get(reverse(f"assets:{name}"), follow=True)
            self.assertEqual(response.status_code, 200, name)


# ---------------------------------------------------------------------------
# B5 — glossario visibile
# ---------------------------------------------------------------------------

from html.parser import HTMLParser  # noqa: E402


class _VisibleText(HTMLParser):
    """Solo il testo che l'utente legge: niente attributi, script, stili, commenti."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "template"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


PAROLE_VIETATE = ("applicazion", "occorrenz", "vista board", "follow-up")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GlossarioVisibileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="b5-admin", password="x", email="b5@example.com")
        cls.category = AssetCategory.objects.create(code="b5-cat", label="B5")
        cls.asset = Asset.objects.create(asset_tag="B5-1", name="Pressa B5", asset_category=cls.category)
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="b5-plan", label="Ingrassaggio B5")
        cls.assignment = MaintenancePlanAssignment.objects.create(
            plan=cls.plan,
            target_type=MaintenancePlanAssignment.TARGET_ASSET,
            asset=cls.asset,
            frequency=MaintenancePlanAssignment.FREQ_DAYS,
            interval=30,
            first_due_date=timezone.localdate(),
        )
        MaintenanceOccurrence.objects.create(
            plan=cls.plan, assignment=cls.assignment, asset=cls.asset,
            due_date=timezone.localdate() - timedelta(days=2), warning_days=10,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def _visible(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        parser = _VisibleText()
        parser.feed(response.content.decode())
        return " ".join(parser.parts)

    def test_le_pagine_principali_parlano_il_glossario(self):
        pagine = [
            reverse("assets:maintenance_da_fare") + "?mio=0",
            reverse("assets:maintenance_scadenze") + "?window=",
            reverse("assets:maintenance_responsabile"),
            reverse("assets:wo_list"),
            reverse("assets:maintenance_plan_detail", args=[self.plan.pk]),
            reverse("assets:maintenance_assignment_create", args=[self.plan.pk]),
            reverse("assets:asset_view", args=[self.asset.pk]),
        ]
        trovate = []
        for url in pagine:
            testo = self._visible(url).casefold()
            for parola in PAROLE_VIETATE:
                if parola in testo:
                    indice = testo.index(parola)
                    trovate.append(f"{url}: «{parola}» … {testo[max(0, indice - 60):indice + 40]!r}")
        self.assertEqual(trovate, [])
        # Controllo positivo: il testo letto e' quello vero della pagina.
        self.assertIn("Assegnazioni", self._visible(reverse("assets:maintenance_plan_detail", args=[self.plan.pk])))
        self.assertIn("Ingrassaggio B5", self._visible(reverse("assets:maintenance_da_fare") + "?mio=0"))


# ---------------------------------------------------------------------------
# B1 — lista asset dentro la shell, Studio inventario in Impostazioni
# ---------------------------------------------------------------------------


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ListaAssetShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="b1-admin", password="x", email="b1@example.com")
        Asset.objects.create(asset_tag="B1-1", name="Pressa B1", status=Asset.STATUS_IN_USE)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_lista_dentro_la_shell_senza_sidebar_propria(self):
        response = self.client.get(reverse("assets:asset_list"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('class="as-shell"', html)
        for vecchia in ('class="dash"', 'class="side"', 'class="menu"', "openAdminStudio"):
            self.assertNotIn(vecchia, html)
        # Voci della vecchia sidebar propria: class="ma" / class="ms" (anche con active).
        self.assertIsNone(re.search(r'class="m[as](?: active)?"', html))
        self.assertIn("Pressa B1", html)

    def test_un_solo_pulsante_nuovo_con_menu(self):
        response = self.client.get(reverse("assets:asset_list"))
        self.assertNotContains(response, 'class="as-new"', html=False)
        self.assertContains(response, "+ Nuovo asset", count=1)
        for name in ("asset_create", "work_machine_create", "chemical_create"):
            self.assertContains(response, f'href="{reverse(f"assets:{name}")}"', html=False)

    def test_studio_inventario_in_impostazioni(self):
        response = self.client.get(reverse("assets:gestione_admin"), {"tab": "studio"})
        self.assertEqual(response.status_code, 200)
        for section in ("admin-custom-fields", "admin-list-options", "admin-action-buttons",
                        "admin-detail-fields", "admin-header-tools"):
            self.assertContains(response, f'id="{section}"', html=False)
        self.assertContains(response, f'action="{reverse("assets:asset_list")}"', html=False)
        self.assertContains(response, 'name="next" value="%s?tab=studio"' % reverse("assets:gestione_admin"), html=False)

    def test_azione_dello_studio_torna_alla_tab(self):
        from assets.models import AssetCustomField

        target = reverse("assets:gestione_admin") + "?tab=studio"
        response = self.client.post(
            reverse("assets:asset_list"),
            {"action": "create_custom_field", "label": "Campo B1", "code": "campo_b1", "field_type": "TEXT",
             "next": target},
        )
        self.assertRedirects(response, target, fetch_redirect_response=False)
        self.assertTrue(AssetCustomField.objects.filter(label="Campo B1").exists())

    def test_next_esterno_ignorato(self):
        response = self.client.post(
            reverse("assets:asset_list"),
            {"action": "create_custom_field", "label": "Campo B1x", "code": "campo_b1x", "field_type": "TEXT",
             "next": "https://example.com/"},
        )
        self.assertRedirects(response, reverse("assets:asset_list"), fetch_redirect_response=False)
