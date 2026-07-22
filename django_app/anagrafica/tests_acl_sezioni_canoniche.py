"""Le sezioni riservate di anagrafica devono riconoscere l'ACL v2 canonico.

Storia del bug: i cancelli delle sezioni HR (dati riservati, visite mediche,
formazione) e delle sezioni "admin" della scheda dipendente non consultavano
l'ACL. Guardavano solo `is_superuser` oppure `is_legacy_admin()`, che e' vero
soltanto per i ruoli legacy il cui NOME e' in `PORTAL_ADMIN_ROLE_NAMES` (default
`{"admin"}`, e mai valorizzato in nessun settings). Risultato: un ruolo come
DIREZIONE, per quanto abilitato in `/admin-portale/acl-canonico/`, non poteva
in alcun modo vedere quelle sezioni — la pagina dei permessi non le governava.

Stesso difetto gia' corretto per il Security Center in `security/tests_config_acl.py`:
il grant canonico affianca i cancelli storici, non li sostituisce.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import UtenteLegacy
from core.models import Profile, RolePermissionGrant
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

from .acl_bootstrap import (
    PERM_FORMAZIONE_MANAGE,
    PERM_FORMAZIONE_VIEW,
    PERM_HR_VIEW,
    PERM_SCHEDA_MANAGE,
    PERM_VISITE_VIEW,
    bootstrap_anagrafica_acl_endpoints,
)
from .views import (
    _can_edit_formazione,
    _can_view_formazione,
    _can_view_visite_mediche,
    _check_hr_permission,
    _is_anagrafica_admin,
)

User = get_user_model()

RUOLO_DIREZIONE_ID = 7
RUOLO_ADMIN_ID = 1

# Il middleware ACL decide se la ROTTA è raggiungibile; i test qui sotto
# verificano il cancello IN-VIEW, che è il passo successivo.
_MIDDLEWARE_SENZA_ACL = [
    m for m in settings.MIDDLEWARE if m != "core.middleware.ACLMiddleware"
]


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SezioniAnagraficaAclV2Test(TestCase):
    """Un ruolo non-admin abilitato in ACL canonico deve vedere le sezioni."""

    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (%s, 'direzione')", [RUOLO_DIREZIONE_ID])
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (%s, 'admin')", [RUOLO_ADMIN_ID])

        bootstrap_anagrafica_acl_endpoints(force=True)

        self.user = self._make_user("direzione-user", "direzione", RUOLO_DIREZIONE_ID)
        self.factory = RequestFactory()
        bump_legacy_cache_version()

    def _make_user(self, username: str, ruolo: str, ruolo_id: int):
        user = User.objects.create_user(username=username, password="pass12345")
        legacy = UtenteLegacy.objects.create(
            nome=username,
            email=f"{username}@example.local",
            password="x",
            ruolo=ruolo,
            ruolo_id=ruolo_id,
            attivo=True,
            deve_cambiare_password=False,
        )
        Profile.objects.create(
            user=user,
            legacy_user_id=legacy.id,
            legacy_ruolo_id=legacy.ruolo_id,
            legacy_ruolo=legacy.ruolo,
        )
        return user

    def _request(self, user=None):
        request = self.factory.get("/anagrafica/")
        request.user = user or self.user
        return request

    def _grant(self, code: str, *, role_id: int = RUOLO_DIREZIONE_ID, enabled: bool = True):
        RolePermissionGrant.objects.update_or_create(
            legacy_role_id=role_id,
            permission_id=code,
            defaults={"enabled": enabled},
        )
        cache.clear()
        bump_legacy_cache_version()

    # ── bootstrap ────────────────────────────────────────────────────────────
    def test_bootstrap_registra_i_permessi_delle_sezioni(self):
        from core.models import PermissionDefinition

        for code in (PERM_HR_VIEW, PERM_VISITE_VIEW, PERM_FORMAZIONE_VIEW,
                     PERM_FORMAZIONE_MANAGE, PERM_SCHEDA_MANAGE):
            self.assertTrue(
                PermissionDefinition.objects.filter(code=code, is_active=True).exists(),
                f"permesso canonico mancante: {code}",
            )

    # ── dati HR riservati ────────────────────────────────────────────────────
    def test_grant_hr_apre_i_dati_riservati(self):
        self._grant(PERM_HR_VIEW)

        self.assertTrue(_check_hr_permission(self._request()))

    def test_senza_grant_i_dati_riservati_restano_chiusi(self):
        self.assertFalse(_check_hr_permission(self._request()))

    def test_grant_hr_disabilitato_non_apre_i_dati_riservati(self):
        self._grant(PERM_HR_VIEW, enabled=False)

        self.assertFalse(_check_hr_permission(self._request()))

    # ── visite mediche ───────────────────────────────────────────────────────
    def test_grant_visite_apre_le_visite_mediche(self):
        self._grant(PERM_VISITE_VIEW)

        self.assertTrue(_can_view_visite_mediche(self._request()))

    def test_senza_grant_le_visite_mediche_restano_chiuse(self):
        self.assertFalse(_can_view_visite_mediche(self._request()))

    # ── formazione ───────────────────────────────────────────────────────────
    def test_grant_formazione_apre_la_visualizzazione(self):
        self._grant(PERM_FORMAZIONE_VIEW)

        self.assertTrue(_can_view_formazione(self._request()))

    def test_grant_formazione_view_non_apre_la_modifica(self):
        self._grant(PERM_FORMAZIONE_VIEW)

        self.assertFalse(_can_edit_formazione(self._request()))

    def test_grant_formazione_manage_apre_la_modifica(self):
        self._grant(PERM_FORMAZIONE_MANAGE)

        self.assertTrue(_can_edit_formazione(self._request()))

    # ── sezioni admin della scheda dipendente ────────────────────────────────
    def test_grant_scheda_apre_le_sezioni_admin(self):
        self._grant(PERM_SCHEDA_MANAGE)

        self.assertTrue(_is_anagrafica_admin(self._request()))

    def test_senza_grant_le_sezioni_admin_restano_chiuse(self):
        self.assertFalse(_is_anagrafica_admin(self._request()))

    # ── non regressione: i cancelli storici restano ──────────────────────────
    def test_admin_legacy_resta_ammesso_senza_alcun_grant(self):
        admin_user = self._make_user("admin-user", "admin", RUOLO_ADMIN_ID)
        cache.clear()
        bump_legacy_cache_version()
        request = self._request(admin_user)

        self.assertTrue(_check_hr_permission(request))
        self.assertTrue(_can_view_visite_mediche(request))
        self.assertTrue(_can_view_formazione(request))
        self.assertTrue(_can_edit_formazione(request))
        self.assertTrue(_is_anagrafica_admin(request))

    # ── la view reale deve usare il gate, non il vecchio in-line ─────────────
    # NB: si isola il gate IN-VIEW dal middleware ACL (che governa se la rotta è
    # raggiungibile ed è coperto dai propri test). Qui interessa il passo dopo:
    # una volta dentro la pagina, il grant canonico deve accendere le sezioni.
    @override_settings(MIDDLEWARE=_MIDDLEWARE_SENZA_ACL)
    def test_view_catalogo_ruoli_riconosce_il_grant(self):
        """Il grant deve arrivare fino alla view, non fermarsi all'helper."""
        from django.urls import reverse

        self._grant(PERM_SCHEDA_MANAGE)
        self.client.force_login(self.user)

        resp = self.client.get(reverse("anagrafica:ruoli_operativi_list"))

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_admin"])

    @override_settings(MIDDLEWARE=_MIDDLEWARE_SENZA_ACL)
    def test_view_catalogo_ruoli_senza_grant_non_e_admin(self):
        from django.urls import reverse

        self.client.force_login(self.user)

        resp = self.client.get(reverse("anagrafica:ruoli_operativi_list"))

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_admin"])

    def test_superuser_resta_ammesso_senza_alcun_grant(self):
        su = User.objects.create_superuser("anag-su", "anag-su@example.local", "pass12345")
        request = self._request(su)

        self.assertTrue(_check_hr_permission(request))
        self.assertTrue(_can_view_visite_mediche(request))
        self.assertTrue(_can_view_formazione(request))
        self.assertTrue(_can_edit_formazione(request))
        self.assertTrue(_is_anagrafica_admin(request))
