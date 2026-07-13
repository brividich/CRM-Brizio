"""Test dell'endpoint unico di export delle liste di anagrafica (PDF/Excel)."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from anagrafica.acl_bootstrap import PERM_EXPORT
from anagrafica.exports import EXPORT_SPECS, ExportSpec, acl_gate
from anagrafica.models import Mansione
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Pulsante, UtenteLegacy
from core.models import (
    AuditLog,
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    UserOnboarding,
)
# Riuso degli helper delle tabelle legacy (creazione/pulizia) già usati da core.
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

User = get_user_model()

MANSIONI_LIST_PATH = "/anagrafica/mansioni/"


class ExportEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin_export", "admin@example.invalid", "x")
        # NB: LIVELLO_RISCHIO_CHOICES reali = B/M/A (non ALTO/BASSO come nel brief).
        Mansione.objects.create(
            nome="Addetto verniciatura",
            livello_rischio=Mansione.RISCHIO_ALTO,
            categoria=Mansione.CAT_OPERAIO,
            descrizione="Cabina di verniciatura",
        )
        Mansione.objects.create(
            nome="Impiegato ufficio",
            livello_rischio=Mansione.RISCHIO_BASSO,
            categoria=Mansione.CAT_IMPIEGATO,
        )

    def _url(self, key, **params):
        url = reverse("anagrafica:export", args=[key])
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url

    def test_xlsx_export_returns_spreadsheet(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("mansioni", format="xlsx"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], XLSX_CT)
        self.assertIn("mansioni", resp["Content-Disposition"])

    def test_pdf_export_returns_pdf(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("mansioni", format="pdf"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_filtered_scope_respects_querystring(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            self._url("mansioni", format="xlsx", scope="filtered", q="verniciatura")
        )
        self.assertEqual(resp.status_code, 200)
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("n_righe"), 1)
        self.assertEqual(log.dettaglio.get("scope"), "filtered")
        self.assertIn("verniciatura", log.dettaglio.get("filtri", ""))

    def test_filtered_scope_respects_rischio(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("mansioni", format="xlsx", rischio="A"))
        self.assertEqual(resp.status_code, 200)
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("n_righe"), 1)

    def test_full_scope_ignores_querystring(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            self._url("mansioni", format="xlsx", scope="full", q="verniciatura")
        )
        self.assertEqual(resp.status_code, 200)
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("n_righe"), 2)
        self.assertEqual(log.dettaglio.get("scope"), "full")

    def test_audit_row_written(self):
        self.client.force_login(self.admin)
        self.client.get(self._url("mansioni", format="pdf"))
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.modulo, "anagrafica")
        self.assertEqual(log.dettaglio.get("lista"), "mansioni")
        self.assertEqual(log.dettaglio.get("formato"), "pdf")

    def test_unknown_key_is_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("non-esiste", format="xlsx"))
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get(self._url("mansioni", format="xlsx"))
        self.assertIn(resp.status_code, (302, 403))


class ExportSpecRegistryTests(TestCase):
    def test_permission_gate_is_mandatory_on_every_spec(self):
        """Fail-closed: nessuna spec può essere registrata senza gate ACL."""
        with self.assertRaises(TypeError):
            ExportSpec(  # type: ignore[call-arg]
                key="senza_gate",
                title="Senza gate",
                columns=[("A", "a")],
                dataset=lambda request, scope: [],
            )
        for key, spec in EXPORT_SPECS.items():
            self.assertTrue(callable(spec.permission), f"spec '{key}' senza gate ACL")

    @override_settings(LEGACY_AUTH_ENABLED=True)
    def test_every_spec_gate_denies_user_without_legacy_binding(self):
        """Il gate di ogni spec nega di default (utente senza utente legacy)."""
        request = RequestFactory().get("/anagrafica/esporta/mansioni/")
        request.user = User.objects.create_user("no_legacy", "n@example.invalid", "x")
        for key, spec in EXPORT_SPECS.items():
            self.assertFalse(spec.permission(request), f"spec '{key}' fail-open")

    def test_mansioni_dataset_fills_every_declared_column(self):
        """Le colonne dichiarate esistono davvero nelle righe prodotte dal dataset."""
        Mansione.objects.create(
            nome="Saldatore",
            livello_rischio=Mansione.RISCHIO_ALTO,
            categoria=Mansione.CAT_OPERAIO,
        )
        spec = EXPORT_SPECS["mansioni"]
        request = RequestFactory().get("/anagrafica/esporta/mansioni/")
        rows = spec.dataset(request, "full")
        self.assertTrue(rows)
        accessors = {accessor for _label, accessor in spec.columns}
        for row in rows:
            self.assertEqual(accessors - set(row), set())


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class ExportAclGateTests(TestCase):
    """L'export non deve essere più permissivo della pagina elenco di origine."""

    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (6, 'utente')")

        self.user = User.objects.create_user("export_acl", "e@example.invalid", "x")
        self.legacy_user = UtenteLegacy.objects.create(
            nome="Tizio Test",
            email="tizio@example.invalid",
            password="x",
            ruolo="utente",
            ruolo_id=6,
            attivo=True,
            deve_cambiare_password=False,
        )
        Profile.objects.create(
            user=self.user,
            legacy_user_id=self.legacy_user.id,
            legacy_ruolo_id=6,
            legacy_ruolo="utente",
        )
        UserOnboarding.objects.create(user=self.user, completed=True)

        Mansione.objects.create(nome="Addetto verniciatura", livello_rischio=Mansione.RISCHIO_ALTO)

        # Binding canonico dell'endpoint di export (come da acl_bootstrap): il
        # middleware lascia passare la request, la decisione fine è del gate spec.
        PermissionDefinition.objects.create(
            code=PERM_EXPORT, module="anagrafica", label="Export liste", is_active=True
        )
        RoutePermissionBinding.objects.create(
            route_name="anagrafica:export",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id=PERM_EXPORT,
            source_app="anagrafica",
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=6, permission_id=PERM_EXPORT, enabled=True
        )
        self.client.force_login(self.user)

    # -- helper -------------------------------------------------------------
    def _grant_list_via_legacy(self, allowed: bool = True):
        """Concede/nega la lista mansioni via ACL legacy (nessun binding canonico)."""
        Pulsante.objects.create(
            codice="anagrafica_mansioni",
            nome_visibile="Mansioni",
            modulo="anagrafica",
            url=MANSIONI_LIST_PATH,
        )
        Permesso.objects.create(
            ruolo_id=6,
            modulo="anagrafica",
            azione="anagrafica_mansioni",
            consentito=1 if allowed else 0,
            can_view=1 if allowed else 0,
        )
        cache.clear()
        bump_legacy_cache_version()

    def _grant_list_via_canonical(self, enabled: bool = True):
        """Concede/nega la lista mansioni via binding canonico ACL v2."""
        PermissionDefinition.objects.create(
            code="anagrafica.mansioni.view",
            module="anagrafica",
            label="Mansioni - Visualizza",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="anagrafica:mansioni_list",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="anagrafica.mansioni.view",
            source_app="anagrafica",
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=6, permission_id="anagrafica.mansioni.view", enabled=enabled
        )
        cache.clear()
        bump_legacy_cache_version()

    def _export(self):
        return self.client.get(reverse("anagrafica:export", args=["mansioni"]) + "?format=xlsx")

    # -- test ---------------------------------------------------------------
    def test_export_denied_when_user_cannot_open_the_list(self):
        # Nessun permesso sulla lista (né canonico né legacy) → export negato.
        resp = self._export()
        self.assertEqual(resp.status_code, 403)

    def test_export_denied_when_legacy_permission_explicitly_denies_the_list(self):
        self._grant_list_via_legacy(allowed=False)
        resp = self._export()
        self.assertEqual(resp.status_code, 403)

    def test_export_allowed_when_user_can_open_the_list(self):
        self._grant_list_via_legacy(allowed=True)
        resp = self._export()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], XLSX_CT)

    def test_export_allowed_with_canonical_binding_on_the_list(self):
        self._grant_list_via_canonical(enabled=True)
        resp = self._export()
        self.assertEqual(resp.status_code, 200)

    def test_export_denied_when_canonical_binding_on_the_list_denies(self):
        self._grant_list_via_canonical(enabled=False)
        resp = self._export()
        self.assertEqual(resp.status_code, 403)

    @override_settings(ACL_STRICT_CANONICAL=True)
    def test_strict_mode_denies_export_when_list_has_no_canonical_binding(self):
        """Invariante C1: in strict-mode il middleware nega la lista (fallback
        legacy) → l'export non può essere una porta di servizio."""
        self._grant_list_via_legacy(allowed=True)
        # La pagina elenco, in strict-mode, è negata dal middleware.
        page = self.client.get(MANSIONI_LIST_PATH)
        self.assertEqual(page.status_code, 403)
        # …e l'export deve seguire la stessa sorte.
        resp = self._export()
        self.assertEqual(resp.status_code, 403)

    @override_settings(ACL_STRICT_CANONICAL=True)
    def test_strict_mode_allows_export_when_list_has_canonical_binding(self):
        self._grant_list_via_canonical(enabled=True)
        self.assertEqual(self.client.get(MANSIONI_LIST_PATH).status_code, 200)
        self.assertEqual(self._export().status_code, 200)


class ExportMenuTemplateTests(TestCase):
    """Componente UI «Esporta ▾» nella toolbar della lista mansioni.

    NB rispetto al brief: l'URL atteso è costruito con ``reverse()`` (come fa
    il componente via ``{% url %}``), non concatenando stringhe a mano — il
    componente non deve mai divergere dal path reale dichiarato in urls.py.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin_menu", "admin2@example.invalid", "x")
        cls.export_base = reverse("anagrafica:export", args=["mansioni"])

    def test_mansioni_list_shows_export_menu_with_no_querystring(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:mansioni_list"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Esporta", html)
        # Senza querystring, i link "filtrato" non hanno un "&amp;" a vuoto in coda.
        self.assertIn(f'{self.export_base}?format=xlsx&amp;scope=filtered"', html)
        self.assertIn(f'{self.export_base}?format=pdf&amp;scope=filtered"', html)
        self.assertIn(f'{self.export_base}?format=xlsx&amp;scope=full"', html)
        self.assertIn(f'{self.export_base}?format=pdf&amp;scope=full"', html)

    def test_filtered_links_propagate_current_querystring_html_escaped(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:mansioni_list") + "?q=vernic&rischio=A")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # La querystring corrente va propagata SOLO sui link "filtrato", con
        # '&' correttamente escapato come '&amp;' (HTML valido).
        self.assertIn(
            f'{self.export_base}?format=xlsx&amp;scope=filtered&amp;q=vernic&amp;rischio=A"',
            html,
        )
        self.assertIn(
            f'{self.export_base}?format=pdf&amp;scope=filtered&amp;q=vernic&amp;rischio=A"',
            html,
        )
        # I link "tutto" restano invariati (nessuna propagazione della querystring).
        self.assertIn(f'{self.export_base}?format=xlsx&amp;scope=full"', html)
        self.assertIn(f'{self.export_base}?format=pdf&amp;scope=full"', html)
        self.assertNotIn(
            f'{self.export_base}?format=xlsx&amp;scope=full&amp;q=vernic', html
        )
