from __future__ import annotations

import re
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction
from django.urls import URLPattern, URLResolver, get_resolver

from core.acl_v2 import normalize_binding_path_pattern, resolve_acl_access, resolve_canonical_target
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Pulsante, Ruolo, UtenteLegacy
from core.middleware import is_acl_exempt_path, is_acl_shared_path, resolve_acl_gate_target_path
from core.models import (
    LegacyRedirect,
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    UserPermissionGrant,
)


SEED_MARKER = "[UAT_SEED]"
SEED_PASSWORD_DEFAULT = "UatNovicrom!2026"
SEED_LEGACY_BUTTON_CODE = "uat_acl_nav_map"
SEED_LEGACY_BUTTON_MODULE = "admin_portale"
SEED_LEGACY_BUTTON_URL = "/uat/legacy-fallback-map"
SEED_LEGACY_REDIRECT_PATH = "/legacy/schema-dati"

STATUS_CANONICAL_BOUND = "CANONICAL_BOUND"
STATUS_LEGACY_FALLBACK = "LEGACY_FALLBACK"
STATUS_UNBOUND = "UNBOUND"
STATUS_COMING_SOON_EXCLUDED = "COMING_SOON_EXCLUDED"
STATUS_REDIRECT_ONLY = "REDIRECT_ONLY"

_COMING_ROUTE_RE = re.compile(r"(^|:)coming[_-]", re.IGNORECASE)
_DYNAMIC_SEGMENT_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class RoleSeed:
    id: int
    name: str


@dataclass(frozen=True)
class UserSeed:
    key: str
    username: str
    full_name: str
    email: str
    role_id: int
    is_superuser: bool = False
    is_staff: bool = False


@dataclass(frozen=True)
class PermissionSeed:
    code: str
    label: str
    module: str
    description: str


@dataclass(frozen=True)
class BindingSeed:
    route_name: str
    path_pattern: str
    match_strategy: str
    permission_code: str
    source_app: str
    priority: int = 90
    is_active: bool = True
    note: str = ""


@dataclass(frozen=True)
class RoleGrantSeed:
    role_id: int
    permission_code: str
    enabled: bool
    note: str = ""


@dataclass(frozen=True)
class UserOverrideSeed:
    user_key: str
    permission_code: str
    enabled: bool
    note: str = ""


@dataclass(frozen=True)
class RouteSample:
    key: str
    route_name: str
    path: str
    expected_status: str
    note: str = ""


@dataclass(frozen=True)
class ScenarioSeed:
    scenario_id: str
    user_key: str
    role_name: str
    path: str
    expected_permission_code: str
    expected_source: str
    expected_allowed: bool
    decision_type: str
    note: str = ""


ROLE_SEEDS: tuple[RoleSeed, ...] = (
    RoleSeed(id=701, name="utente_base"),
    RoleSeed(id=702, name="responsabile_operativo"),
    RoleSeed(id=703, name="amministratore_portale"),
)

USER_SEEDS: tuple[UserSeed, ...] = (
    UserSeed(
        key="uat.base1",
        username="uat.base1",
        full_name="UAT Base One",
        email="uat.base1@novicrom.local",
        role_id=701,
    ),
    UserSeed(
        key="uat.base2",
        username="uat.base2",
        full_name="UAT Base Two",
        email="uat.base2@novicrom.local",
        role_id=701,
    ),
    UserSeed(
        key="uat.resp1",
        username="uat.resp1",
        full_name="UAT Responsabile One",
        email="uat.resp1@novicrom.local",
        role_id=702,
    ),
    UserSeed(
        key="uat.resp2",
        username="uat.resp2",
        full_name="UAT Responsabile Two",
        email="uat.resp2@novicrom.local",
        role_id=702,
    ),
    UserSeed(
        key="uat.admin1",
        username="uat.admin1",
        full_name="UAT Admin One",
        email="uat.admin1@novicrom.local",
        role_id=703,
        is_superuser=True,
        is_staff=True,
    ),
    UserSeed(
        key="uat.override1",
        username="uat.override1",
        full_name="UAT Override One",
        email="uat.override1@novicrom.local",
        role_id=701,
    ),
)

PERMISSION_SEEDS: tuple[PermissionSeed, ...] = (
    PermissionSeed(
        code="core.profile.view",
        label="Profilo utente",
        module="core",
        description="Visualizzazione pagina profilo.",
    ),
    PermissionSeed(
        code="assets.asset.view",
        label="Elenco asset",
        module="assets",
        description="Accesso alla lista asset.",
    ),
    PermissionSeed(
        code="assets.work_orders.manage",
        label="Gestione work order",
        module="assets",
        description="Gestione operativa work order.",
    ),
    PermissionSeed(
        code="anagrafica.dipendenti.view",
        label="Elenco dipendenti",
        module="anagrafica",
        description="Esempio canonicale aggiuntivo per rotta anagrafica.",
    ),
    PermissionSeed(
        code="tickets.dashboard.view",
        label="Dashboard ticket",
        module="tickets",
        description="Esempio canonicale aggiuntivo per dashboard ticket.",
    ),
    PermissionSeed(
        code="admin_portale.acl.view",
        label="Diagnostica ACL",
        module="admin_portale",
        description="Accesso alla diagnostica ACL.",
    ),
    PermissionSeed(
        code="admin_portale.permissions.manage",
        label="ACL canonico",
        module="admin_portale",
        description="Gestione ACL canonico.",
    ),
    PermissionSeed(
        code="admin_portale.route_coverage.view",
        label="Copertura route ACL",
        module="admin_portale",
        description="Accesso report route coverage ACL.",
    ),
    PermissionSeed(
        code="admin_portale.users.manage",
        label="Gestione utenti portale",
        module="admin_portale",
        description="Accesso pagina utenti admin.",
    ),
    PermissionSeed(
        code="admin_portale.access_matrix.view",
        label="Matrice permessi",
        module="admin_portale",
        description="Permesso usato per scenario grant assente.",
    ),
)

BINDING_SEEDS: tuple[BindingSeed, ...] = (
    BindingSeed(
        route_name="profilo",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="core.profile.view",
        source_app="core",
        note="Profilo utente",
    ),
    BindingSeed(
        route_name="assets:asset_list",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="assets.asset.view",
        source_app="assets",
        note="Lista asset",
    ),
    BindingSeed(
        route_name="assets:wo_list",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="assets.work_orders.manage",
        source_app="assets",
        note="Work order list",
    ),
    BindingSeed(
        route_name="",
        path_pattern="/assets/workorders",
        match_strategy=RoutePermissionBinding.MATCH_PREFIX,
        permission_code="assets.work_orders.manage",
        source_app="assets",
        note="Pattern dinamico work order",
    ),
    BindingSeed(
        route_name="admin_portale:acl_diagnostica",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="admin_portale.acl.view",
        source_app="admin_portale",
        note="Diagnostica ACL",
    ),
    BindingSeed(
        route_name="anagrafica:dipendenti_list",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="anagrafica.dipendenti.view",
        source_app="anagrafica",
        note="Esempio canonicale anagrafica",
    ),
    BindingSeed(
        route_name="tickets:dashboard",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="tickets.dashboard.view",
        source_app="tickets",
        note="Esempio canonicale tickets",
    ),
    BindingSeed(
        route_name="admin_portale:acl_canonico",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="admin_portale.permissions.manage",
        source_app="admin_portale",
        note="ACL canonico",
    ),
    BindingSeed(
        route_name="admin_portale:acl_route_coverage",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="admin_portale.route_coverage.view",
        source_app="admin_portale",
        note="Route coverage",
    ),
    BindingSeed(
        route_name="admin_portale:utenti_list",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="admin_portale.users.manage",
        source_app="admin_portale",
        note="Gestione utenti",
    ),
    BindingSeed(
        route_name="admin_portale:matrice_permessi",
        path_pattern="",
        match_strategy=RoutePermissionBinding.MATCH_EXACT,
        permission_code="admin_portale.access_matrix.view",
        source_app="admin_portale",
        note="Scenario grant assente",
    ),
)

ROLE_GRANT_SEEDS: tuple[RoleGrantSeed, ...] = (
    RoleGrantSeed(701, "core.profile.view", True, "Ruolo base"),
    RoleGrantSeed(701, "assets.asset.view", True, "Ruolo base"),
    RoleGrantSeed(701, "assets.work_orders.manage", False, "Ruolo base"),
    RoleGrantSeed(701, "anagrafica.dipendenti.view", False, "Ruolo base"),
    RoleGrantSeed(701, "tickets.dashboard.view", False, "Ruolo base"),
    RoleGrantSeed(701, "admin_portale.acl.view", False, "Ruolo base"),
    RoleGrantSeed(701, "admin_portale.permissions.manage", False, "Ruolo base"),
    RoleGrantSeed(701, "admin_portale.route_coverage.view", False, "Ruolo base"),
    RoleGrantSeed(701, "admin_portale.users.manage", False, "Ruolo base"),
    RoleGrantSeed(702, "core.profile.view", True, "Responsabile"),
    RoleGrantSeed(702, "assets.asset.view", True, "Responsabile"),
    RoleGrantSeed(702, "assets.work_orders.manage", True, "Responsabile"),
    RoleGrantSeed(702, "anagrafica.dipendenti.view", True, "Responsabile"),
    RoleGrantSeed(702, "tickets.dashboard.view", True, "Responsabile"),
    RoleGrantSeed(702, "admin_portale.acl.view", True, "Responsabile"),
    RoleGrantSeed(702, "admin_portale.permissions.manage", False, "Responsabile"),
    RoleGrantSeed(702, "admin_portale.route_coverage.view", True, "Responsabile"),
    RoleGrantSeed(702, "admin_portale.users.manage", False, "Responsabile"),
    RoleGrantSeed(703, "core.profile.view", True, "Amministratore portale"),
    RoleGrantSeed(703, "assets.asset.view", True, "Amministratore portale"),
    RoleGrantSeed(703, "assets.work_orders.manage", True, "Amministratore portale"),
    RoleGrantSeed(703, "anagrafica.dipendenti.view", True, "Amministratore portale"),
    RoleGrantSeed(703, "tickets.dashboard.view", True, "Amministratore portale"),
    RoleGrantSeed(703, "admin_portale.acl.view", True, "Amministratore portale"),
    RoleGrantSeed(703, "admin_portale.permissions.manage", True, "Amministratore portale"),
    RoleGrantSeed(703, "admin_portale.route_coverage.view", True, "Amministratore portale"),
    RoleGrantSeed(703, "admin_portale.users.manage", True, "Amministratore portale"),
)

USER_OVERRIDE_SEEDS: tuple[UserOverrideSeed, ...] = (
    UserOverrideSeed(
        user_key="uat.override1",
        permission_code="assets.work_orders.manage",
        enabled=True,
        note="Override ALLOW su ruolo base.",
    ),
    UserOverrideSeed(
        user_key="uat.base2",
        permission_code="assets.asset.view",
        enabled=False,
        note="Override DENY su elenco asset.",
    ),
    UserOverrideSeed(
        user_key="uat.resp2",
        permission_code="admin_portale.acl.view",
        enabled=False,
        note="Override DENY su diagnostica ACL.",
    ),
)

ROUTE_SAMPLE_DEFINITIONS: tuple[RouteSample, ...] = (
    RouteSample(
        key="R01",
        route_name="admin_portale:acl_canonico",
        path="/admin-portale/acl-canonico/",
        expected_status=STATUS_CANONICAL_BOUND,
        note="Binding canonico diretto.",
    ),
    RouteSample(
        key="R02",
        route_name="admin_portale:acl_diagnostica",
        path="/admin-portale/acl-diagnostica/",
        expected_status=STATUS_CANONICAL_BOUND,
        note="Binding canonico diretto.",
    ),
    RouteSample(
        key="R03",
        route_name="admin_portale:acl_route_coverage",
        path="/admin-portale/acl-route-coverage/",
        expected_status=STATUS_CANONICAL_BOUND,
        note="Binding canonico diretto.",
    ),
    RouteSample(
        key="R04",
        route_name="assets:asset_list",
        path="/assets/",
        expected_status=STATUS_CANONICAL_BOUND,
        note="Binding canonico su route_name.",
    ),
    RouteSample(
        key="R05",
        route_name="assets:wo_view",
        path="/assets/workorders/view/1",
        expected_status=STATUS_CANONICAL_BOUND,
        note="Binding canonico via path_pattern prefix.",
    ),
    RouteSample(
        key="R06",
        route_name="admin_portale:utenti_list",
        path="/admin-portale/utenti/",
        expected_status=STATUS_CANONICAL_BOUND,
        note="Binding canonico gestione utenti.",
    ),
    RouteSample(
        key="R07",
        route_name="uat:legacy_fallback_probe",
        path=SEED_LEGACY_BUTTON_URL,
        expected_status=STATUS_LEGACY_FALLBACK,
        note="Path sintetico coperto solo da fallback legacy seed.",
    ),
    RouteSample(
        key="R08",
        route_name="admin_portale:schema_dati",
        path="/admin-portale/schema-dati/",
        expected_status=STATUS_REDIRECT_ONLY,
        note="Target di redirect legacy.",
    ),
    RouteSample(
        key="R09",
        route_name="admin:login",
        path="/admin/login/",
        expected_status=STATUS_COMING_SOON_EXCLUDED,
        note="Route esclusa (Django admin interno).",
    ),
    RouteSample(
        key="R10",
        route_name="uat:unbound_probe",
        path="/uat/unbound-probe/",
        expected_status=STATUS_UNBOUND,
        note="Path sintetico senza binding canonico e senza copertura legacy.",
    ),
    RouteSample(
        key="R11",
        route_name="admin_portale:matrice_permessi",
        path="/admin-portale/matrice-permessi/",
        expected_status=STATUS_CANONICAL_BOUND,
        note="Binding canonico con grant assente (warning governance).",
    ),
)

SCENARIO_SEEDS: tuple[ScenarioSeed, ...] = (
    ScenarioSeed(
        scenario_id="S01",
        user_key="uat.base1",
        role_name="utente_base",
        path="/profilo/",
        expected_permission_code="core.profile.view",
        expected_source="canonical",
        expected_allowed=True,
        decision_type="CANONICAL_ROLE_GRANT",
        note="Route canonica consentita per grant ruolo.",
    ),
    ScenarioSeed(
        scenario_id="S02",
        user_key="uat.base1",
        role_name="utente_base",
        path="/assets/workorders/",
        expected_permission_code="assets.work_orders.manage",
        expected_source="canonical",
        expected_allowed=False,
        decision_type="CANONICAL_ROLE_DENY",
        note="Route canonica negata per ruolo base.",
    ),
    ScenarioSeed(
        scenario_id="S03",
        user_key="uat.override1",
        role_name="utente_base",
        path="/assets/workorders/view/1",
        expected_permission_code="assets.work_orders.manage",
        expected_source="canonical",
        expected_allowed=True,
        decision_type="USER_OVERRIDE_ALLOW",
        note="Override utente ALLOW su permesso altrimenti negato dal ruolo.",
    ),
    ScenarioSeed(
        scenario_id="S04",
        user_key="uat.base2",
        role_name="utente_base",
        path="/assets/",
        expected_permission_code="assets.asset.view",
        expected_source="canonical",
        expected_allowed=False,
        decision_type="USER_OVERRIDE_DENY",
        note="Override utente DENY su permesso con grant ruolo True.",
    ),
    ScenarioSeed(
        scenario_id="S05",
        user_key="uat.resp1",
        role_name="responsabile_operativo",
        path="/assets/workorders/view/1",
        expected_permission_code="assets.work_orders.manage",
        expected_source="canonical",
        expected_allowed=True,
        decision_type="CANONICAL_DYNAMIC_PATH",
        note="Route dinamica coperta da binding path_pattern prefix.",
    ),
    ScenarioSeed(
        scenario_id="S06",
        user_key="uat.resp2",
        role_name="responsabile_operativo",
        path="/admin-portale/acl-diagnostica/",
        expected_permission_code="admin_portale.acl.view",
        expected_source="canonical",
        expected_allowed=False,
        decision_type="USER_OVERRIDE_DENY",
        note="Override utente DENY prevale su grant ruolo True.",
    ),
    ScenarioSeed(
        scenario_id="S07",
        user_key="uat.admin1",
        role_name="amministratore_portale",
        path="/admin-portale/acl-canonico/",
        expected_permission_code="admin_portale.permissions.manage",
        expected_source="superuser_bypass",
        expected_allowed=True,
        decision_type="SUPERUSER_BYPASS",
        note="Bypass Django superuser (precedenza massima).",
    ),
    ScenarioSeed(
        scenario_id="S08",
        user_key="uat.base1",
        role_name="utente_base",
        path=SEED_LEGACY_BUTTON_URL,
        expected_permission_code="legacy.admin_portale.uat_acl_nav_map",
        expected_source="legacy_fallback",
        expected_allowed=False,
        decision_type="LEGACY_FALLBACK_DENY",
        note="Fallback legacy con permesso negato per ruolo base.",
    ),
    ScenarioSeed(
        scenario_id="S09",
        user_key="uat.resp1",
        role_name="responsabile_operativo",
        path=SEED_LEGACY_BUTTON_URL,
        expected_permission_code="legacy.admin_portale.uat_acl_nav_map",
        expected_source="legacy_fallback",
        expected_allowed=True,
        decision_type="LEGACY_FALLBACK_ALLOW",
        note="Fallback legacy con permesso consentito per responsabile.",
    ),
    ScenarioSeed(
        scenario_id="S10",
        user_key="uat.base1",
        role_name="utente_base",
        path="/admin-portale/matrice-permessi/",
        expected_permission_code="admin_portale.access_matrix.view",
        expected_source="canonical",
        expected_allowed=False,
        decision_type="CANONICAL_MISSING_GRANT",
        note="Binding canonico presente ma grant ruolo assente.",
    ),
    ScenarioSeed(
        scenario_id="S11",
        user_key="uat.base1",
        role_name="utente_base",
        path="/uat/unbound-probe/",
        expected_permission_code="",
        expected_source="legacy_fallback",
        expected_allowed=False,
        decision_type="UNBOUND_DENY",
        note="Route senza binding e senza legacy coverage.",
    ),
    ScenarioSeed(
        scenario_id="S12",
        user_key="uat.resp1",
        role_name="responsabile_operativo",
        path="/assets/workorders/close/1",
        expected_permission_code="assets.work_orders.manage",
        expected_source="canonical",
        expected_allowed=True,
        decision_type="CANONICAL_PATH_PATTERN",
        note="Route dinamica aggiuntiva coperta dal prefix binding.",
    ),
)


class Command(BaseCommand):
    help = (
        "Carica un pacchetto seed ACL v2 per UAT (ruoli, utenti, permission code, binding, "
        "grant, override, fallback legacy e scenari verificabili)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Pulisce i dati seed precedenti identificati dal marker UAT prima di ricreare il pacchetto.",
        )
        parser.add_argument(
            "--password",
            default=SEED_PASSWORD_DEFAULT,
            help=f"Password comune per gli utenti Django seed (default: {SEED_PASSWORD_DEFAULT}).",
        )

    def handle(self, *args, **options):
        do_reset = bool(options.get("reset"))
        seed_password = str(options.get("password") or SEED_PASSWORD_DEFAULT)
        self._warnings: list[str] = []
        self._stats = {
            "roles_created": 0,
            "roles_updated": 0,
            "legacy_users_created": 0,
            "legacy_users_updated": 0,
            "django_users_created": 0,
            "django_users_updated": 0,
            "profiles_created": 0,
            "profiles_updated": 0,
            "permissions_created": 0,
            "permissions_updated": 0,
            "permissions_reused": 0,
            "bindings_created": 0,
            "bindings_updated": 0,
            "bindings_reused": 0,
            "bindings_conflicts": 0,
            "role_grants_created": 0,
            "role_grants_updated": 0,
            "user_overrides_created": 0,
            "user_overrides_updated": 0,
            "legacy_buttons_created": 0,
            "legacy_buttons_updated": 0,
            "legacy_perms_created": 0,
            "legacy_perms_updated": 0,
            "legacy_redirect_created": 0,
            "legacy_redirect_updated": 0,
        }

        self.stdout.write(self.style.NOTICE("ACL v2 UAT seed: avvio"))
        self._ensure_legacy_tables()

        if do_reset:
            self._reset_seed_data()

        with transaction.atomic():
            self._seed_roles()
            self._seed_permissions()
            self._seed_bindings()
            self._seed_role_grants()
            user_maps = self._seed_users(seed_password=seed_password)
            self._seed_user_overrides(user_legacy_ids=user_maps["legacy_ids"])
            self._seed_legacy_fallback_rows()
            self._seed_legacy_redirect()

        bump_legacy_cache_version()
        route_rows = self._build_route_sample_report()
        scenario_rows = self._evaluate_scenarios(user_maps=user_maps)
        self._print_summary(
            seed_password=seed_password,
            route_rows=route_rows,
            scenario_rows=scenario_rows,
        )

    def _ensure_legacy_tables(self):
        vendor = connection.vendor
        with connection.cursor() as cursor:
            if vendor == "sqlite":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ruoli (
                        id INTEGER PRIMARY KEY,
                        nome VARCHAR(100) NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS utenti (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome VARCHAR(200) NOT NULL,
                        email VARCHAR(200) NULL,
                        password VARCHAR(500) NOT NULL,
                        ruolo VARCHAR(100) NULL,
                        attivo INTEGER NOT NULL DEFAULT 1,
                        deve_cambiare_password INTEGER NOT NULL DEFAULT 0,
                        ruolo_id INTEGER NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pulsanti (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        codice VARCHAR(100) NOT NULL,
                        nome_visibile VARCHAR(200) NULL,
                        icona VARCHAR(20) NULL,
                        modulo VARCHAR(100) NOT NULL,
                        url VARCHAR(500) NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS permessi (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        modulo VARCHAR(100) NOT NULL,
                        azione VARCHAR(100) NOT NULL,
                        ruolo_id INTEGER NOT NULL,
                        consentito INTEGER NULL,
                        can_view INTEGER NULL,
                        can_edit INTEGER NULL,
                        can_delete INTEGER NULL,
                        can_approve INTEGER NULL
                    )
                    """
                )
                return

            cursor.execute(
                """
                IF OBJECT_ID('ruoli', 'U') IS NULL
                CREATE TABLE ruoli (
                    id INT NOT NULL PRIMARY KEY,
                    nome NVARCHAR(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('utenti', 'U') IS NULL
                CREATE TABLE utenti (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    nome NVARCHAR(200) NOT NULL,
                    email NVARCHAR(200) NULL,
                    password NVARCHAR(500) NOT NULL,
                    ruolo NVARCHAR(100) NULL,
                    attivo BIT NOT NULL DEFAULT 1,
                    deve_cambiare_password BIT NOT NULL DEFAULT 0,
                    ruolo_id INT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('pulsanti', 'U') IS NULL
                CREATE TABLE pulsanti (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    codice NVARCHAR(100) NOT NULL,
                    nome_visibile NVARCHAR(200) NULL,
                    icona NVARCHAR(20) NULL,
                    modulo NVARCHAR(100) NOT NULL,
                    url NVARCHAR(500) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('permessi', 'U') IS NULL
                CREATE TABLE permessi (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    modulo NVARCHAR(100) NOT NULL,
                    azione NVARCHAR(100) NOT NULL,
                    ruolo_id INT NOT NULL,
                    consentito INT NULL,
                    can_view INT NULL,
                    can_edit INT NULL,
                    can_delete INT NULL,
                    can_approve INT NULL
                )
                """
            )

    def _reset_seed_data(self):
        self.stdout.write(self.style.WARNING("ACL v2 UAT seed: reset dati seed precedenti"))
        seed_usernames = [row.username for row in USER_SEEDS]
        seed_emails = [row.email for row in USER_SEEDS]
        seed_role_ids = [row.id for row in ROLE_SEEDS]
        seed_codes = [row.code for row in PERMISSION_SEEDS]
        seed_legacy_ids = list(
            UtenteLegacy.objects.filter(email__in=seed_emails).values_list("id", flat=True)
        )

        UserPermissionGrant.objects.filter(
            legacy_user_id__in=seed_legacy_ids,
            permission_id__in=seed_codes,
        ).delete()
        RolePermissionGrant.objects.filter(
            legacy_role_id__in=seed_role_ids,
            permission_id__in=seed_codes,
        ).delete()
        RoutePermissionBinding.objects.filter(note__icontains=SEED_MARKER).delete()
        LegacyRedirect.objects.filter(
            legacy_path=SEED_LEGACY_REDIRECT_PATH,
            note__icontains=SEED_MARKER,
        ).delete()
        Permesso.objects.filter(
            modulo=SEED_LEGACY_BUTTON_MODULE,
            azione=SEED_LEGACY_BUTTON_CODE,
            ruolo_id__in=seed_role_ids,
        ).delete()
        Pulsante.objects.filter(
            modulo=SEED_LEGACY_BUTTON_MODULE,
            codice=SEED_LEGACY_BUTTON_CODE,
        ).delete()

        Profile.objects.filter(user__username__in=seed_usernames).delete()
        user_model = get_user_model()
        user_model.objects.filter(username__in=seed_usernames).delete()
        UtenteLegacy.objects.filter(email__in=seed_emails).delete()

        PermissionDefinition.objects.filter(
            code__in=seed_codes,
            description__icontains=SEED_MARKER,
        ).delete()
        Ruolo.objects.filter(id__in=seed_role_ids, nome__in=[row.name for row in ROLE_SEEDS]).delete()

    def _seed_roles(self):
        for row in ROLE_SEEDS:
            obj = Ruolo.objects.filter(id=row.id).first()
            if obj is None:
                Ruolo.objects.create(id=row.id, nome=row.name)
                self._stats["roles_created"] += 1
                continue
            if str(obj.nome or "").strip() != row.name:
                obj.nome = row.name
                obj.save(update_fields=["nome"])
                self._stats["roles_updated"] += 1

    def _seed_permissions(self):
        for row in PERMISSION_SEEDS:
            obj = PermissionDefinition.objects.filter(code=row.code).first()
            marker_description = f"{SEED_MARKER} {row.description}"
            if obj is None:
                PermissionDefinition.objects.create(
                    code=row.code,
                    label=row.label,
                    module=row.module,
                    description=marker_description,
                    is_active=True,
                )
                self._stats["permissions_created"] += 1
                continue

            if SEED_MARKER in str(obj.description or ""):
                changed = False
                if obj.label != row.label:
                    obj.label = row.label
                    changed = True
                if obj.module != row.module:
                    obj.module = row.module
                    changed = True
                if obj.description != marker_description:
                    obj.description = marker_description
                    changed = True
                if not obj.is_active:
                    obj.is_active = True
                    changed = True
                if changed:
                    obj.full_clean()
                    obj.save()
                    self._stats["permissions_updated"] += 1
                else:
                    self._stats["permissions_reused"] += 1
                continue

            self._stats["permissions_reused"] += 1
            if not obj.is_active:
                self._warnings.append(
                    f"PermissionDefinition '{row.code}' esiste ma is_active=False (riusata senza override)."
                )

    def _seed_bindings(self):
        for row in BINDING_SEEDS:
            path_pattern = normalize_binding_path_pattern(
                row.path_pattern,
                for_regex=(row.match_strategy == RoutePermissionBinding.MATCH_REGEX),
            )
            note = f"{SEED_MARKER} {row.note}".strip()
            obj = RoutePermissionBinding.objects.filter(
                route_name=row.route_name,
                path_pattern=path_pattern,
            ).first()
            if obj is None:
                RoutePermissionBinding.objects.create(
                    route_name=row.route_name,
                    path_pattern=path_pattern,
                    match_strategy=row.match_strategy,
                    permission_id=row.permission_code,
                    source_app=row.source_app,
                    note=note,
                    priority=row.priority,
                    is_active=row.is_active,
                )
                self._stats["bindings_created"] += 1
                continue

            if SEED_MARKER in str(obj.note or ""):
                changed = False
                if obj.match_strategy != row.match_strategy:
                    obj.match_strategy = row.match_strategy
                    changed = True
                if obj.permission_id != row.permission_code:
                    obj.permission_id = row.permission_code
                    changed = True
                if obj.source_app != row.source_app:
                    obj.source_app = row.source_app
                    changed = True
                if obj.note != note:
                    obj.note = note
                    changed = True
                if int(obj.priority or 0) != int(row.priority):
                    obj.priority = int(row.priority)
                    changed = True
                if bool(obj.is_active) != bool(row.is_active):
                    obj.is_active = bool(row.is_active)
                    changed = True
                if changed:
                    obj.full_clean()
                    obj.save()
                    self._stats["bindings_updated"] += 1
                else:
                    self._stats["bindings_reused"] += 1
                continue

            if obj.permission_id == row.permission_code and bool(obj.is_active):
                self._stats["bindings_reused"] += 1
                continue

            self._stats["bindings_conflicts"] += 1
            self._warnings.append(
                "Binding in conflitto su "
                f"route='{row.route_name}' path='{path_pattern}': esistente -> '{obj.permission_id}', seed -> '{row.permission_code}'."
            )

    def _seed_role_grants(self):
        for row in ROLE_GRANT_SEEDS:
            note = f"{SEED_MARKER} {row.note}".strip()
            obj = RolePermissionGrant.objects.filter(
                legacy_role_id=row.role_id,
                permission_id=row.permission_code,
            ).first()
            if obj is None:
                RolePermissionGrant.objects.create(
                    legacy_role_id=row.role_id,
                    permission_id=row.permission_code,
                    enabled=bool(row.enabled),
                    note=note,
                )
                self._stats["role_grants_created"] += 1
                continue

            changed = False
            if bool(obj.enabled) != bool(row.enabled):
                obj.enabled = bool(row.enabled)
                changed = True
            if SEED_MARKER in str(obj.note or "") and obj.note != note:
                obj.note = note
                changed = True
            if changed:
                obj.save(update_fields=["enabled", "note", "updated_at"])
                self._stats["role_grants_updated"] += 1

    def _seed_users(self, *, seed_password: str) -> dict:
        role_name_by_id = {row.id: row.name for row in ROLE_SEEDS}
        user_model = get_user_model()
        legacy_users_by_key: dict[str, UtenteLegacy] = {}
        django_users_by_key: dict[str, object] = {}
        legacy_ids_by_key: dict[str, int] = {}

        for row in USER_SEEDS:
            legacy_user = UtenteLegacy.objects.filter(email__iexact=row.email).order_by("id").first()
            if legacy_user is None:
                legacy_user = UtenteLegacy.objects.create(
                    nome=row.full_name,
                    email=row.email,
                    password="*UAT_SEED*",
                    ruolo=role_name_by_id.get(row.role_id, "utente_base"),
                    ruolo_id=row.role_id,
                    attivo=True,
                    deve_cambiare_password=False,
                )
                self._stats["legacy_users_created"] += 1
            else:
                changed_fields = []
                if legacy_user.nome != row.full_name:
                    legacy_user.nome = row.full_name
                    changed_fields.append("nome")
                if str(legacy_user.ruolo or "") != role_name_by_id.get(row.role_id, ""):
                    legacy_user.ruolo = role_name_by_id.get(row.role_id, "")
                    changed_fields.append("ruolo")
                if int(legacy_user.ruolo_id or 0) != int(row.role_id):
                    legacy_user.ruolo_id = int(row.role_id)
                    changed_fields.append("ruolo_id")
                if not bool(legacy_user.attivo):
                    legacy_user.attivo = True
                    changed_fields.append("attivo")
                if bool(legacy_user.deve_cambiare_password):
                    legacy_user.deve_cambiare_password = False
                    changed_fields.append("deve_cambiare_password")
                if changed_fields:
                    legacy_user.save(update_fields=changed_fields)
                    self._stats["legacy_users_updated"] += 1

            django_user = user_model.objects.filter(username=row.username).first()
            if django_user is None:
                django_user = user_model.objects.create_user(
                    username=row.username,
                    email=row.email,
                    password=seed_password,
                )
                self._stats["django_users_created"] += 1
            else:
                self._stats["django_users_updated"] += 1
                django_user.email = row.email
                django_user.set_password(seed_password)

            django_user.is_active = True
            django_user.is_staff = bool(row.is_staff or row.is_superuser)
            django_user.is_superuser = bool(row.is_superuser)
            django_user.save()

            conflict_profile = (
                Profile.objects.filter(legacy_user_id=legacy_user.id)
                .exclude(user_id=django_user.id)
                .first()
            )
            if conflict_profile is not None:
                self._warnings.append(
                    f"Profile conflict: legacy_user_id={legacy_user.id} gia assegnato a user_id={conflict_profile.user_id}. "
                    f"Profilo seed per '{row.username}' non aggiornato."
                )
            else:
                _profile, created = Profile.objects.update_or_create(
                    user=django_user,
                    defaults={
                        "legacy_user_id": legacy_user.id,
                        "legacy_ruolo_id": row.role_id,
                        "legacy_ruolo": role_name_by_id.get(row.role_id, ""),
                    },
                )
                if created:
                    self._stats["profiles_created"] += 1
                else:
                    self._stats["profiles_updated"] += 1

            legacy_users_by_key[row.key] = legacy_user
            django_users_by_key[row.key] = django_user
            legacy_ids_by_key[row.key] = int(legacy_user.id)

        return {
            "legacy_users": legacy_users_by_key,
            "django_users": django_users_by_key,
            "legacy_ids": legacy_ids_by_key,
        }

    def _seed_user_overrides(self, *, user_legacy_ids: dict[str, int]):
        for row in USER_OVERRIDE_SEEDS:
            legacy_user_id = user_legacy_ids.get(row.user_key)
            if legacy_user_id is None:
                self._warnings.append(
                    f"Override seed saltato: utente '{row.user_key}' non presente."
                )
                continue
            note = f"{SEED_MARKER} {row.note}".strip()
            obj = UserPermissionGrant.objects.filter(
                legacy_user_id=legacy_user_id,
                permission_id=row.permission_code,
            ).first()
            if obj is None:
                UserPermissionGrant.objects.create(
                    legacy_user_id=legacy_user_id,
                    permission_id=row.permission_code,
                    enabled=bool(row.enabled),
                    note=note,
                )
                self._stats["user_overrides_created"] += 1
                continue
            changed = False
            if bool(obj.enabled) != bool(row.enabled):
                obj.enabled = bool(row.enabled)
                changed = True
            if SEED_MARKER in str(obj.note or "") and obj.note != note:
                obj.note = note
                changed = True
            if changed:
                obj.save(update_fields=["enabled", "note", "updated_at"])
                self._stats["user_overrides_updated"] += 1

    def _seed_legacy_fallback_rows(self):
        button = Pulsante.objects.filter(
            modulo=SEED_LEGACY_BUTTON_MODULE,
            codice=SEED_LEGACY_BUTTON_CODE,
        ).order_by("id").first()
        if button is None:
            Pulsante.objects.create(
                codice=SEED_LEGACY_BUTTON_CODE,
                nome_visibile="UAT Legacy Fallback Probe",
                icona="shield",
                modulo=SEED_LEGACY_BUTTON_MODULE,
                url=SEED_LEGACY_BUTTON_URL,
            )
            self._stats["legacy_buttons_created"] += 1
        else:
            changed = False
            if (button.nome_visibile or "") != "UAT Legacy Fallback Probe":
                button.nome_visibile = "UAT Legacy Fallback Probe"
                changed = True
            if (button.icona or "") != "shield":
                button.icona = "shield"
                changed = True
            if (button.url or "") != SEED_LEGACY_BUTTON_URL:
                button.url = SEED_LEGACY_BUTTON_URL
                changed = True
            if changed:
                button.save(update_fields=["nome_visibile", "icona", "url"])
                self._stats["legacy_buttons_updated"] += 1

        for role_id, can_view in ((701, 0), (702, 1), (703, 1)):
            perm = (
                Permesso.objects.filter(
                    modulo=SEED_LEGACY_BUTTON_MODULE,
                    azione=SEED_LEGACY_BUTTON_CODE,
                    ruolo_id=role_id,
                )
                .order_by("-id")
                .first()
            )
            if perm is None:
                Permesso.objects.create(
                    modulo=SEED_LEGACY_BUTTON_MODULE,
                    azione=SEED_LEGACY_BUTTON_CODE,
                    ruolo_id=role_id,
                    consentito=can_view,
                    can_view=can_view,
                    can_edit=0,
                    can_delete=0,
                    can_approve=0,
                )
                self._stats["legacy_perms_created"] += 1
                continue
            changed = False
            if int(perm.can_view or 0) != int(can_view):
                perm.can_view = int(can_view)
                changed = True
            if int(perm.consentito or 0) != int(can_view):
                perm.consentito = int(can_view)
                changed = True
            if changed:
                perm.save(update_fields=["can_view", "consentito"])
                self._stats["legacy_perms_updated"] += 1

    def _seed_legacy_redirect(self):
        redirect = LegacyRedirect.objects.filter(legacy_path=SEED_LEGACY_REDIRECT_PATH).first()
        note = f"{SEED_MARKER} Redirect legacy UAT verso schema dati."
        if redirect is None:
            LegacyRedirect.objects.create(
                legacy_path=SEED_LEGACY_REDIRECT_PATH,
                target_route_name="admin_portale:schema_dati",
                target_url_path="",
                is_enabled=True,
                note=note,
            )
            self._stats["legacy_redirect_created"] += 1
            return

        changed = False
        if (
            redirect.target_route_name
            and redirect.target_route_name != "admin_portale:schema_dati"
            and SEED_MARKER not in str(redirect.note or "")
        ):
            self._warnings.append(
                "LegacyRedirect in conflitto su "
                f"{SEED_LEGACY_REDIRECT_PATH}: target esistente '{redirect.target_route_name}' non sovrascritto."
            )
            return

        if redirect.target_route_name != "admin_portale:schema_dati":
            redirect.target_route_name = "admin_portale:schema_dati"
            changed = True
        if redirect.target_url_path:
            redirect.target_url_path = ""
            changed = True
        if not redirect.is_enabled:
            redirect.is_enabled = True
            changed = True
        if SEED_MARKER in str(redirect.note or "") and redirect.note != note:
            redirect.note = note
            changed = True
        if changed:
            redirect.save(update_fields=["target_route_name", "target_url_path", "is_enabled", "note", "updated_at"])
            self._stats["legacy_redirect_updated"] += 1

    def _build_route_sample_report(self) -> list[dict]:
        route_map = self._collect_named_routes()
        active_bindings = list(
            RoutePermissionBinding.objects.filter(is_active=True)
            .select_related("permission")
            .order_by("priority", "id")
        )
        enabled_permission_codes = set(
            RolePermissionGrant.objects.filter(enabled=True).values_list("permission_id", flat=True)
        )
        legacy_routes, legacy_paths = self._legacy_coverage_catalog()
        redirect_route_targets, redirect_path_targets = self._redirect_target_catalog()

        rows: list[dict] = []
        for sample in ROUTE_SAMPLE_DEFINITIONS:
            route_name = sample.route_name
            sample_path = sample.path
            route_catalog_path = route_map.get(route_name)
            if route_catalog_path:
                sample_path = route_catalog_path
            sample_path = normalize_binding_path_pattern(sample_path)

            status, context = self._classify_route(
                route_name=route_name,
                path_norm=sample_path,
                active_bindings=active_bindings,
                enabled_permission_codes=enabled_permission_codes,
                legacy_route_names=legacy_routes,
                legacy_paths=legacy_paths,
                redirect_route_targets=redirect_route_targets,
                redirect_path_targets=redirect_path_targets,
            )
            rows.append(
                {
                    "key": sample.key,
                    "route_name": route_name,
                    "path": sample_path,
                    "expected_status": sample.expected_status,
                    "actual_status": status,
                    "warnings": context["warnings"],
                    "permissions": context["permissions"],
                    "note": sample.note,
                }
            )
        return rows

    def _evaluate_scenarios(self, *, user_maps: dict) -> list[dict]:
        legacy_users = user_maps["legacy_users"]
        django_users = user_maps["django_users"]

        rows: list[dict] = []
        for scenario in SCENARIO_SEEDS:
            legacy_user = legacy_users.get(scenario.user_key)
            django_user = django_users.get(scenario.user_key)
            if legacy_user is None or django_user is None:
                rows.append(
                    {
                        "scenario": scenario,
                        "allowed": False,
                        "decision_source": "missing_seed_user",
                        "permission_code": "",
                        "passed": False,
                        "detail": "utente seed non trovato",
                    }
                )
                continue

            decision = resolve_acl_access(
                path=scenario.path,
                legacy_user=legacy_user,
                django_user=django_user,
                request=None,
                include_legacy_diagnostic=True,
            )
            permission_code = (
                ((decision.get("canonical") or {}).get("permission") or {}).get("code")
                or ""
            )
            passed = (
                bool(decision.get("allowed")) == bool(scenario.expected_allowed)
                and str(decision.get("decision_source") or "") == scenario.expected_source
            )
            if scenario.expected_permission_code and scenario.expected_source == "canonical":
                passed = passed and permission_code == scenario.expected_permission_code

            rows.append(
                {
                    "scenario": scenario,
                    "allowed": bool(decision.get("allowed")),
                    "decision_source": str(decision.get("decision_source") or ""),
                    "permission_code": permission_code,
                    "passed": passed,
                    "detail": str(decision.get("reason") or ""),
                }
            )
        return rows

    def _print_summary(self, *, seed_password: str, route_rows: list[dict], scenario_rows: list[dict]):
        expected_route_statuses = len(route_rows)
        matched_route_statuses = sum(1 for row in route_rows if row["actual_status"] == row["expected_status"])
        scenario_total = len(scenario_rows)
        scenario_passed = sum(1 for row in scenario_rows if row["passed"])

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== ACL v2 UAT Seed Report ==="))
        self.stdout.write("Credenziali seed:")
        self.stdout.write(f"- Password comune utenti Django: {seed_password}")
        self.stdout.write("- Utenti seed: " + ", ".join([row.username for row in USER_SEEDS]))
        self.stdout.write("- Permission code seed: " + ", ".join([row.code for row in PERMISSION_SEEDS]))
        self.stdout.write("- Scenari seed: " + ", ".join([row.scenario_id for row in SCENARIO_SEEDS]))
        self.stdout.write("")
        self.stdout.write("Ruoli legacy seed:")
        for row in ROLE_SEEDS:
            self.stdout.write(f"- role_id={row.id} nome={row.name}")
        self.stdout.write("")

        self.stdout.write("Statistiche upsert:")
        self.stdout.write(
            f"- roles: create={self._stats['roles_created']} update={self._stats['roles_updated']}"
        )
        self.stdout.write(
            f"- legacy users: create={self._stats['legacy_users_created']} update={self._stats['legacy_users_updated']}"
        )
        self.stdout.write(
            f"- django users: create={self._stats['django_users_created']} update={self._stats['django_users_updated']}"
        )
        self.stdout.write(
            f"- profiles: create={self._stats['profiles_created']} update={self._stats['profiles_updated']}"
        )
        self.stdout.write(
            f"- permissions: create={self._stats['permissions_created']} "
            f"update={self._stats['permissions_updated']} reuse={self._stats['permissions_reused']}"
        )
        self.stdout.write(
            f"- bindings: create={self._stats['bindings_created']} update={self._stats['bindings_updated']} "
            f"reuse={self._stats['bindings_reused']} conflicts={self._stats['bindings_conflicts']}"
        )
        self.stdout.write(
            f"- role grants: create={self._stats['role_grants_created']} update={self._stats['role_grants_updated']}"
        )
        self.stdout.write(
            f"- user overrides: create={self._stats['user_overrides_created']} update={self._stats['user_overrides_updated']}"
        )
        self.stdout.write(
            f"- legacy fallback rows: pulsanti create={self._stats['legacy_buttons_created']} update={self._stats['legacy_buttons_updated']}, "
            f"permessi create={self._stats['legacy_perms_created']} update={self._stats['legacy_perms_updated']}"
        )
        self.stdout.write(
            f"- legacy redirects: create={self._stats['legacy_redirect_created']} update={self._stats['legacy_redirect_updated']}"
        )
        self.stdout.write("")

        self.stdout.write(
            "Route sample coverage: "
            f"{matched_route_statuses}/{expected_route_statuses} con stato atteso."
        )
        for row in route_rows:
            status_flag = "OK" if row["actual_status"] == row["expected_status"] else "MISMATCH"
            permissions = ", ".join(row["permissions"]) if row["permissions"] else "-"
            warnings = ", ".join(row["warnings"]) if row["warnings"] else "-"
            self.stdout.write(
                f"- {row['key']} [{status_flag}] {row['route_name']} -> expected={row['expected_status']} "
                f"actual={row['actual_status']} permission={permissions} warnings={warnings}"
            )

        self.stdout.write("")
        self.stdout.write(
            f"Scenari UAT runtime: {scenario_passed}/{scenario_total} coerenti con l'esito atteso."
        )
        for row in scenario_rows:
            scenario = row["scenario"]
            scenario_flag = "PASS" if row["passed"] else "FAIL"
            self.stdout.write(
                f"- {scenario.scenario_id} [{scenario_flag}] user={scenario.user_key} role={scenario.role_name} "
                f"path={scenario.path} source={row['decision_source']} allowed={'ALLOW' if row['allowed'] else 'DENY'} "
                f"expected_source={scenario.expected_source} expected={'ALLOW' if scenario.expected_allowed else 'DENY'} "
                f"permission={row['permission_code'] or '-'}"
            )

        self.stdout.write("")
        self.stdout.write(
            "Dipendenze legacy ancora attive: fallback path->pulsanti->permessi e redirect legacy "
            f"(seed route '{SEED_LEGACY_REDIRECT_PATH}')."
        )
        if self._warnings:
            self.stdout.write(self.style.WARNING("Warning seed:"))
            for warning in self._warnings:
                self.stdout.write(f"- {warning}")
        else:
            self.stdout.write(self.style.SUCCESS("Nessun warning critico nel seed UAT."))

    def _collect_named_routes(self) -> dict[str, str]:
        resolver = get_resolver()
        route_map: dict[str, str] = {}

        def walk(patterns, prefix: str = "", namespace_prefix: str = ""):
            for pattern in patterns:
                if isinstance(pattern, URLPattern):
                    name = getattr(pattern, "name", None)
                    if not name:
                        continue
                    route_name = f"{namespace_prefix}:{name}" if namespace_prefix else str(name)
                    route_pattern = prefix + str(pattern.pattern)
                    path = "/" + route_pattern.lstrip("/")
                    path = _DYNAMIC_SEGMENT_RE.sub("1", path)
                    path = re.sub(r"/+", "/", path)
                    if path != "/":
                        path = path.rstrip("/")
                    route_map[route_name] = normalize_binding_path_pattern(path)
                    continue
                if isinstance(pattern, URLResolver):
                    ns = getattr(pattern, "namespace", None)
                    next_ns = namespace_prefix
                    if ns:
                        next_ns = f"{namespace_prefix}:{ns}" if namespace_prefix else str(ns)
                    walk(pattern.url_patterns, prefix + str(pattern.pattern), next_ns)

        walk(resolver.url_patterns)
        return route_map

    def _classify_route(
        self,
        *,
        route_name: str,
        path_norm: str,
        active_bindings: list[RoutePermissionBinding],
        enabled_permission_codes: set[str],
        legacy_route_names: set[str],
        legacy_paths: list[str],
        redirect_route_targets: set[str],
        redirect_path_targets: set[str],
    ) -> tuple[str, dict]:
        route_matches: list[RoutePermissionBinding] = []
        path_matches: list[RoutePermissionBinding] = []
        route_name_norm = str(route_name or "").strip().lower()
        gate_target_path = resolve_acl_gate_target_path(path_norm)
        for binding in active_bindings:
            if binding.route_name and binding.route_name.strip().lower() == route_name_norm:
                route_matches.append(binding)
                continue
            if self._binding_matches_path(binding, gate_target_path):
                path_matches.append(binding)

        resolved = resolve_canonical_target(path=gate_target_path, route_name=route_name)
        binding_payload = resolved.get("binding") or {}
        effective_binding_id = binding_payload.get("id")
        effective_permission_code = str(binding_payload.get("permission_code") or "").strip()
        canonical_permissions = [effective_permission_code] if effective_permission_code else []
        canonical_missing_grant = bool(
            effective_permission_code and effective_permission_code not in enabled_permission_codes
        )
        has_legacy = self._route_has_legacy_coverage(
            route_name=route_name,
            path_norm=gate_target_path,
            legacy_route_names=legacy_route_names,
            legacy_paths=legacy_paths,
        )
        has_redirect = bool(
            (route_name and route_name in redirect_route_targets)
            or (gate_target_path and gate_target_path in redirect_path_targets)
        )
        is_excluded, _ = self._is_coming_or_excluded_route(route_name=route_name, path_norm=path_norm)

        if is_excluded:
            status = STATUS_COMING_SOON_EXCLUDED
        elif effective_binding_id:
            status = STATUS_CANONICAL_BOUND
        elif has_legacy:
            status = STATUS_LEGACY_FALLBACK
        elif has_redirect:
            status = STATUS_REDIRECT_ONLY
        else:
            status = STATUS_UNBOUND

        warnings: list[str] = []
        if canonical_missing_grant:
            warnings.append("BINDING_WITHOUT_ENABLED_ROLE_GRANT")
        ambiguous_route_matches = False
        if route_matches:
            min_route_priority = min(int(getattr(binding, "priority", 0) or 0) for binding in route_matches)
            ambiguous_route_matches = sum(
                1 for binding in route_matches if int(getattr(binding, "priority", 0) or 0) == min_route_priority
            ) > 1
        ambiguous_path_matches = False
        if not route_matches and path_matches and effective_binding_id:
            effective_binding = next((binding for binding in path_matches if int(binding.id) == int(effective_binding_id)), None)
            if effective_binding is not None:
                strategy = (effective_binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
                if strategy == RoutePermissionBinding.MATCH_EXACT:
                    strategy_rank = 0
                    pattern = normalize_binding_path_pattern(effective_binding.path_pattern, for_regex=False)
                elif strategy == RoutePermissionBinding.MATCH_PREFIX:
                    strategy_rank = 1
                    pattern = normalize_binding_path_pattern(effective_binding.path_pattern, for_regex=False)
                else:
                    strategy_rank = 2
                    pattern = str(effective_binding.path_pattern or "")
                winner_key = (
                    int(getattr(effective_binding, "priority", 0) or 0),
                    strategy_rank,
                    -len(pattern),
                )
                for binding in path_matches:
                    strategy = (binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
                    if strategy == RoutePermissionBinding.MATCH_EXACT:
                        binding_rank = 0
                        binding_pattern = normalize_binding_path_pattern(binding.path_pattern, for_regex=False)
                    elif strategy == RoutePermissionBinding.MATCH_PREFIX:
                        binding_rank = 1
                        binding_pattern = normalize_binding_path_pattern(binding.path_pattern, for_regex=False)
                    else:
                        binding_rank = 2
                        binding_pattern = str(binding.path_pattern or "")
                    if (
                        int(getattr(binding, "priority", 0) or 0),
                        binding_rank,
                        -len(binding_pattern),
                    ) == winner_key:
                        ambiguous_path_matches = ambiguous_path_matches or int(binding.id) != int(effective_binding_id)
        if ambiguous_route_matches or ambiguous_path_matches:
            warnings.append("AMBIGUOUS_CANONICAL_BINDING")
        return status, {"permissions": canonical_permissions, "warnings": warnings}

    def _binding_matches_path(self, binding: RoutePermissionBinding, path_norm: str) -> bool:
        strategy = (binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
        if strategy == RoutePermissionBinding.MATCH_REGEX:
            try:
                return re.search(binding.path_pattern or "", path_norm) is not None
            except re.error:
                return False

        pattern = normalize_binding_path_pattern(binding.path_pattern, for_regex=False)
        if not pattern:
            return False
        if strategy == RoutePermissionBinding.MATCH_PREFIX:
            return path_norm == pattern or path_norm.startswith(pattern + "/")
        return path_norm == pattern

    def _legacy_coverage_catalog(self) -> tuple[set[str], list[str]]:
        route_names: set[str] = set()
        path_patterns: set[str] = set()
        try:
            rows = list(Pulsante.objects.values("url"))
        except DatabaseError:
            return route_names, []

        for row in rows:
            raw_url = str(row.get("url") or "").strip()
            lower_url = raw_url.lower()
            if lower_url.startswith("route:") or lower_url.startswith("django:"):
                _, route_name = raw_url.split(":", 1)
                route_name = route_name.strip()
                if route_name:
                    route_names.add(route_name)
                continue
            path = normalize_binding_path_pattern(raw_url)
            if path:
                path_patterns.add(path)
        return route_names, sorted(path_patterns, key=len, reverse=True)

    def _redirect_target_catalog(self) -> tuple[set[str], set[str]]:
        route_targets: set[str] = set()
        path_targets: set[str] = set()
        try:
            rows = list(
                LegacyRedirect.objects.filter(is_enabled=True).values("target_route_name", "target_url_path")
            )
        except DatabaseError:
            return route_targets, path_targets
        for row in rows:
            route_name = str(row.get("target_route_name") or "").strip()
            url_path = str(row.get("target_url_path") or "").strip()
            if route_name:
                route_targets.add(route_name)
            if url_path.startswith("/"):
                path_targets.add(normalize_binding_path_pattern(url_path))
        return route_targets, path_targets

    def _route_has_legacy_coverage(
        self,
        *,
        route_name: str,
        path_norm: str,
        legacy_route_names: set[str],
        legacy_paths: list[str],
    ) -> bool:
        if route_name and route_name in legacy_route_names:
            return True
        for legacy_path in legacy_paths:
            if path_norm == legacy_path:
                return True
            if legacy_path and legacy_path != "/" and path_norm.startswith(legacy_path + "/"):
                return True
        return False

    def _is_coming_or_excluded_route(self, *, route_name: str, path_norm: str) -> tuple[bool, str]:
        route_name_norm = str(route_name or "").strip()
        if is_acl_exempt_path(path_norm):
            return True, "EXEMPT_MIDDLEWARE_PATH"
        if is_acl_shared_path(path_norm):
            return True, "AUTH_SHARED_PATH"
        if _COMING_ROUTE_RE.search(route_name_norm):
            return True, "COMING_SOON_ROUTE"
        excluded_route_prefixes = (
            "admin:",
            "django_prometheus:",
            "silk:",
            "debug_toolbar:",
            "admin_portale:api_",
        )
        if any(route_name_norm.startswith(prefix) for prefix in excluded_route_prefixes):
            return True, "EXCLUDED_INTERNAL_ROUTE"
        if route_name_norm in {"login", "logout", "password_change", "password_reset"}:
            return True, "EXCLUDED_AUTH_ROUTE"
        if path_norm in {"/health", "/health/", "/admin-portale/health", "/admin-portale/health/"}:
            return True, "EXCLUDED_HEALTHCHECK_ROUTE"
        return False, ""

