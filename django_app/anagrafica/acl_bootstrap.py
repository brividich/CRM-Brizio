from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

# Bump alla v3: aggiunge i permessi canonici Skill Matrix MOD.187.
# Bump alla v4: aggiunge il binding route della pagina Impostazioni Skill Matrix
# (anagrafica:skm_impostazioni → manage), così si ri-registra negli ambienti già a v3.
# Bump alla v5: aggiunge i permessi/binding canonici MOD.128 MPQ (processi qualificati).
# Bump alla v6: aggiunge i binding delle route di gestione (CRUD) MOD.128 → manage.
# Bump alla v7: due filoni paralleli avevano entrambi scelto la v7 —
#   (a) binding route dello Scadenzario abilitazioni (F10, anagrafica:skm_scadenzario → manage);
#   (b) permesso/binding canonico dell'endpoint unico di export (anagrafica:export → anagrafica.export.use).
# Bump alla v8: unione dei due. La chiave DEVE essere NUOVA: un ambiente gia' arrivato
#   a "v7" con uno solo dei due filoni non ri-registrerebbe i binding dell'altro, e in
#   ACL_STRICT_CANONICAL una route non mappata viene NEGATA a tutti i non-superuser (403).
# Bump alla v9: permessi/binding canonici del Recruiting MOD. 05-01.
# Bump alla v10: binding delle azioni per riga sui criteri Recruiting
#   (toggle/elimina/sposta). Chiave NUOVA: un ambiente già a v9 non
#   ri-registrerebbe i binding nuovi e in ACL_STRICT_CANONICAL le tre route
#   verrebbero negate a tutti i non-superuser.
# Bump alla v11: binding delle azioni ciclo di vita scheda (annulla/riapri).
_BOOTSTRAP_CACHE_KEY = "anagrafica_acl_bootstrap_v11"

# ── ACL v2 canonico — Skill Matrix MOD.187 ─────────────────────────────────────
# Rende le route Skill Matrix governabili da /admin-portale/acl-canonico/ (e
# applicabili dal middleware in ACL_STRICT_CANONICAL). Senza questi binding, in
# strict-mode le route sarebbero raggiungibili solo dal superuser.
MODULE = "anagrafica"
PERM_SKM_VIEW = "anagrafica.skillmatrix.view"
PERM_SKM_MANAGE = "anagrafica.skillmatrix.manage"

_SKM_CANONICAL = {
    PERM_SKM_VIEW: {
        "label": "Skill Matrix - Visualizza",
        "description": "Matrice persone×macchine (abilitazioni MOD.187), sola lettura.",
    },
    PERM_SKM_MANAGE: {
        "label": "Skill Matrix - Gestisci",
        "description": "Validazione match asset, refresh semestrale CAR, import baseline.",
    },
}

_SKM_ROUTE_BINDINGS = {
    "anagrafica:skill_matrix_macchina": PERM_SKM_VIEW,
    "anagrafica:skm_match_validazione": PERM_SKM_MANAGE,
    "anagrafica:skm_refresh": PERM_SKM_MANAGE,
    "anagrafica:skm_scadenzario": PERM_SKM_MANAGE,
    "anagrafica:skm_impostazioni": PERM_SKM_MANAGE,
}

# Grant di default (CREATE-ONLY: non sovrascrive le scelte fatte in ACL canonico).
_SKM_ROLE_GRANTS = {
    "admin": {PERM_SKM_VIEW, PERM_SKM_MANAGE},
    "amministrazione": {PERM_SKM_VIEW, PERM_SKM_MANAGE},
    "qualita": {PERM_SKM_VIEW, PERM_SKM_MANAGE},
    "caporeparto": {PERM_SKM_VIEW, PERM_SKM_MANAGE},
}


# ── ACL v2 canonico — MOD.128 MPQ (processi qualificati) ───────────────────────
# Rende governabili da /admin-portale/acl-canonico/ (ed enforce-abili dal
# middleware in ACL_STRICT_CANONICAL) le route della vista MOD.128. Le pagine
# sono di sola lettura → binding su VIEW; MANAGE è definito e pronto per i futuri
# endpoint di data-entry (F5), oggi il data-entry passa da Django admin.
PERM_MPQ_VIEW = "anagrafica.mpq.view"
PERM_MPQ_MANAGE = "anagrafica.mpq.manage"

_MPQ_CANONICAL = {
    PERM_MPQ_VIEW: {
        "label": "Processi qualificati MOD.128 - Visualizza",
        "description": "Cruscotto/vista/dettaglio dei processi qualificati (MPQ), sola lettura.",
    },
    PERM_MPQ_MANAGE: {
        "label": "Processi qualificati MOD.128 - Gestisci",
        "description": "Gestione processi/abilitazioni/certificazioni MPQ (data-entry, F5).",
    },
}

_MPQ_ROUTE_BINDINGS = {
    "anagrafica:mpq_cruscotto": PERM_MPQ_VIEW,
    "anagrafica:mpq_vista": PERM_MPQ_VIEW,
    "anagrafica:mpq_processo_detail": PERM_MPQ_VIEW,
    # Gestione (CRUD) → manage
    "anagrafica:mpq_processo_create": PERM_MPQ_MANAGE,
    "anagrafica:mpq_processo_edit": PERM_MPQ_MANAGE,
    "anagrafica:mpq_processo_delete": PERM_MPQ_MANAGE,
    "anagrafica:mpq_cliente_list": PERM_MPQ_MANAGE,
    "anagrafica:mpq_cliente_create": PERM_MPQ_MANAGE,
    "anagrafica:mpq_cliente_edit": PERM_MPQ_MANAGE,
    "anagrafica:mpq_abilitazione_add": PERM_MPQ_MANAGE,
    "anagrafica:mpq_abilitazione_edit": PERM_MPQ_MANAGE,
    "anagrafica:mpq_abilitazione_delete": PERM_MPQ_MANAGE,
    "anagrafica:mpq_certificazione_add": PERM_MPQ_MANAGE,
    "anagrafica:mpq_certificazione_delete": PERM_MPQ_MANAGE,
    "anagrafica:mpq_riferimento_add": PERM_MPQ_MANAGE,
    "anagrafica:mpq_riferimento_delete": PERM_MPQ_MANAGE,
    "anagrafica:mpq_requisito_add": PERM_MPQ_MANAGE,
    "anagrafica:mpq_requisito_edit": PERM_MPQ_MANAGE,
    "anagrafica:mpq_requisito_delete": PERM_MPQ_MANAGE,
}

# Grant di default (CREATE-ONLY: non sovrascrive le scelte fatte in ACL canonico).
_MPQ_ROLE_GRANTS = {
    "admin": {PERM_MPQ_VIEW, PERM_MPQ_MANAGE},
    "amministrazione": {PERM_MPQ_VIEW, PERM_MPQ_MANAGE},
    "qualita": {PERM_MPQ_VIEW, PERM_MPQ_MANAGE},
    "caporeparto": {PERM_MPQ_VIEW},
}


# ── ACL v2 canonico — Recruiting MOD. 05-01 (selezione risorse) ───────────────
# Le schede candidato contengono età, cittadinanza e note libere che possono
# riportare situazioni familiari o di salute: il grant di default è ristretto
# (nessun ruolo oltre admin/amministrazione), e in view si somma il singleton
# `RecruitingPermission` (default ADMIN), come per le visite mediche.
PERM_RECR_VIEW = "anagrafica.recruiting.view"
PERM_RECR_MANAGE = "anagrafica.recruiting.manage"

_RECR_CANONICAL = {
    PERM_RECR_VIEW: {
        "label": "Recruiting MOD. 05-01 - Visualizza",
        "description": "Schede candidato, valutazioni di selezione e cruscotto KPI, sola lettura.",
    },
    PERM_RECR_MANAGE: {
        "label": "Recruiting MOD. 05-01 - Gestisci",
        "description": "Data-entry schede/valutazioni, secondo colloquio, transizione a onboarding, criteri.",
    },
}

_RECR_ROUTE_BINDINGS = {
    "anagrafica:recruiting_list": PERM_RECR_VIEW,
    "anagrafica:recruiting_detail": PERM_RECR_VIEW,
    "anagrafica:recruiting_dashboard": PERM_RECR_VIEW,
    # Data-entry e decisioni → manage
    "anagrafica:recruiting_create": PERM_RECR_MANAGE,
    "anagrafica:recruiting_edit": PERM_RECR_MANAGE,
    "anagrafica:recruiting_step2": PERM_RECR_MANAGE,
    "anagrafica:recruiting_assumi": PERM_RECR_MANAGE,
    "anagrafica:recruiting_archivia": PERM_RECR_MANAGE,
    "anagrafica:recruiting_annulla": PERM_RECR_MANAGE,
    "anagrafica:recruiting_riapri": PERM_RECR_MANAGE,
    "anagrafica:recruiting_criteri": PERM_RECR_MANAGE,
    "anagrafica:recruiting_criterio_toggle": PERM_RECR_MANAGE,
    "anagrafica:recruiting_criterio_delete": PERM_RECR_MANAGE,
    "anagrafica:recruiting_criterio_move": PERM_RECR_MANAGE,
}

# Grant di default (CREATE-ONLY: non sovrascrive le scelte fatte in ACL canonico).
_RECR_ROLE_GRANTS = {
    "admin": {PERM_RECR_VIEW, PERM_RECR_MANAGE},
    "amministrazione": {PERM_RECR_VIEW, PERM_RECR_MANAGE},
}


# ── ACL v2 canonico — endpoint unico di export liste (PDF/Excel) ──────────────
# `anagrafica:export` (/anagrafica/esporta/<key>/) è una rotta trasversale: senza
# RoutePermissionBinding canonico, con ACL_STRICT_CANONICAL=True il middleware la
# nega a TUTTI i non-superuser (deny del fallback legacy). Le liste di anagrafica
# non hanno permessi canonici in codice (i loro binding vivono in DB), quindi qui
# si registra un permesso dedicato "uso dell'export", abilitato di default a tutti
# i ruoli: il gate FINE resta la lista di origine, verificato dentro la view via
# `exports.acl_gate("/anagrafica/<lista>/")`. Chi non vede la lista non la esporta.
PERM_EXPORT = "anagrafica.export.use"

_EXPORT_CANONICAL = {
    PERM_EXPORT: {
        "label": "Anagrafica - Export liste (PDF/Excel)",
        "description": (
            "Uso dell'endpoint unico di export delle liste di anagrafica. "
            "Il contenuto esportabile resta limitato alle liste che l'utente può già vedere."
        ),
    },
}

_EXPORT_ROUTE_BINDINGS = {
    "anagrafica:export": PERM_EXPORT,
}


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _bootstrap_export_canonical() -> bool:
    """Registra permesso canonico + binding route dell'endpoint di export.

    Grant di default: abilitato per tutti i ruoli legacy (CREATE-ONLY, non
    sovrascrive le scelte fatte in /admin-portale/acl-canonico/).
    """
    from core.legacy_models import Ruolo
    from core.models import (
        PermissionDefinition, RolePermissionGrant, RoutePermissionBinding,
    )

    changed = False
    with transaction.atomic():
        for code, payload in _EXPORT_CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        for route_name, code in _EXPORT_ROUTE_BINDINGS.items():
            binding, created = RoutePermissionBinding.objects.get_or_create(
                route_name=route_name, path_pattern="",
                defaults={"match_strategy": RoutePermissionBinding.MATCH_EXACT,
                          "permission_id": code, "source_app": MODULE,
                          "note": "[EXPORT_BOOTSTRAP] binding endpoint unico export liste",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        for rid in Ruolo.objects.values_list("id", flat=True):
            _, created = RolePermissionGrant.objects.get_or_create(
                legacy_role_id=int(rid), permission_id=PERM_EXPORT,
                defaults={"enabled": True, "note": "[EXPORT_BOOTSTRAP] default"},
            )
            changed = changed or created
    return changed


def _bootstrap_skillmatrix_canonical() -> bool:
    """Registra permessi canonici + binding route→permesso + grant di default."""
    from core.legacy_models import Ruolo
    from core.models import (
        PermissionDefinition, RolePermissionGrant, RoutePermissionBinding,
    )

    changed = False
    with transaction.atomic():
        for code, payload in _SKM_CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        for route_name, code in _SKM_ROUTE_BINDINGS.items():
            binding, created = RoutePermissionBinding.objects.get_or_create(
                route_name=route_name, path_pattern="",
                defaults={"match_strategy": RoutePermissionBinding.MATCH_EXACT,
                          "permission_id": code, "source_app": MODULE,
                          "note": "[SKM_BOOTSTRAP] binding Skill Matrix MOD.187",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        for rid, rname in roles.items():
            grants = _SKM_ROLE_GRANTS.get(rname, set())
            for code in (PERM_SKM_VIEW, PERM_SKM_MANAGE):
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[SKM_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed


def _bootstrap_mpq_canonical() -> bool:
    """Registra permessi canonici MOD.128 MPQ + binding route + grant di default.

    Struttura identica al bootstrap Skill Matrix (stesso pattern conservativo:
    definizioni get_or_create, binding create-only con riattivazione, grant
    create-only che non sovrascrive le scelte fatte in ACL canonico).
    """
    from core.legacy_models import Ruolo
    from core.models import (
        PermissionDefinition, RolePermissionGrant, RoutePermissionBinding,
    )

    changed = False
    with transaction.atomic():
        for code, payload in _MPQ_CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        for route_name, code in _MPQ_ROUTE_BINDINGS.items():
            binding, created = RoutePermissionBinding.objects.get_or_create(
                route_name=route_name, path_pattern="",
                defaults={"match_strategy": RoutePermissionBinding.MATCH_EXACT,
                          "permission_id": code, "source_app": MODULE,
                          "note": "[MPQ_BOOTSTRAP] binding MOD.128 processi qualificati",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        for rid, rname in roles.items():
            grants = _MPQ_ROLE_GRANTS.get(rname, set())
            for code in (PERM_MPQ_VIEW, PERM_MPQ_MANAGE):
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[MPQ_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed


def _bootstrap_recruiting_canonical() -> bool:
    """Registra permessi canonici Recruiting MOD. 05-01 + binding route + grant.

    Stesso pattern conservativo di Skill Matrix/MPQ. I binding sono obbligatori:
    con ``ACL_STRICT_CANONICAL`` una route non mappata viene NEGATA a tutti i
    non-superuser.
    """
    from core.legacy_models import Ruolo
    from core.models import (
        PermissionDefinition, RolePermissionGrant, RoutePermissionBinding,
    )

    changed = False
    with transaction.atomic():
        for code, payload in _RECR_CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        for route_name, code in _RECR_ROUTE_BINDINGS.items():
            binding, created = RoutePermissionBinding.objects.get_or_create(
                route_name=route_name, path_pattern="",
                defaults={"match_strategy": RoutePermissionBinding.MATCH_EXACT,
                          "permission_id": code, "source_app": MODULE,
                          "note": "[RECR_BOOTSTRAP] binding Recruiting MOD. 05-01",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        for rid, rname in roles.items():
            grants = _RECR_ROLE_GRANTS.get(rname, set())
            for code in (PERM_RECR_VIEW, PERM_RECR_MANAGE):
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[RECR_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed


def _bootstrap_anagrafica_canonical() -> bool:
    """Bootstrap canonico delle aree anagrafica governate da ACL v2 (SKM + MPQ + Recruiting + export)."""
    changed_skm = _bootstrap_skillmatrix_canonical()
    changed_mpq = _bootstrap_mpq_canonical()
    changed_recr = _bootstrap_recruiting_canonical()
    changed_export = _bootstrap_export_canonical()
    return bool(changed_skm or changed_mpq or changed_recr or changed_export)

_PULSANTI_DEFINITIONS = [
    {"modulo": "anagrafica", "codice": "anagrafica_index", "label": "Anagrafica - Dashboard", "url": "/anagrafica/", "hide": False},
    {"modulo": "anagrafica", "codice": "anagrafica_dipendenti", "label": "Anagrafica - Lista dipendenti", "url": "/anagrafica/dipendenti/", "hide": False},
    # NOTE: i pulsanti "Fornitori" sono ora gestiti dal modulo `fornitori`
    # (vedere fornitori/acl_bootstrap.py se creato in seguito).
    {"modulo": "anagrafica", "codice": "anagrafica_ruoli_operativi", "label": "Anagrafica - Ruoli operativi", "url": "/anagrafica/ruoli-operativi/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_mansioni", "label": "Anagrafica - Mansioni catalogo", "url": "/anagrafica/mansioni/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_qualifiche", "label": "Anagrafica - Qualifiche catalogo", "url": "/anagrafica/qualifiche/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_widget_layout", "label": "Anagrafica - API widget layout", "url": "/anagrafica/api/widget-layout/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_impostazioni_widget", "label": "Anagrafica - Impostazioni permessi widget", "url": "/anagrafica/impostazioni-widget/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_civile_save", "label": "Anagrafica - Salva anagrafica civile dipendente", "url": "/anagrafica/dipendenti/0/anagrafica-civile/salva/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_aziendale_save", "label": "Anagrafica - Salva anagrafica aziendale dipendente", "url": "/anagrafica/dipendenti/0/anagrafica-aziendale/salva/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_dipendenti_report", "label": "Anagrafica - Report/export dipendenti", "url": "/anagrafica/dipendenti/report/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_aree", "label": "Anagrafica - Reparti catalogo", "url": "/anagrafica/aree/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_ruoli_aziendali", "label": "Anagrafica - Ruoli aziendali catalogo", "url": "/anagrafica/ruoli-aziendali/", "hide": True},
    # ── Formazione HR (PATCH-01 stub — URL definitivi in PATCH-02/03) ──────
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_dashboard", "label": "Formazione - Dashboard", "url": "/anagrafica/formazione/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_piani", "label": "Formazione - Piani formativi", "url": "/anagrafica/formazione/piani/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_corsi", "label": "Formazione - Corsi", "url": "/anagrafica/formazione/corsi/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_sessioni", "label": "Formazione - Sessioni", "url": "/anagrafica/formazione/sessioni/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_istruttori", "label": "Formazione - Istruttori", "url": "/anagrafica/formazione/istruttori/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_scadenzario", "label": "Formazione - Scadenzario", "url": "/anagrafica/formazione/scadenzario/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_export", "label": "Formazione - Export Excel", "url": "/anagrafica/formazione/export/", "hide": True},
]


def bootstrap_anagrafica_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "anagrafica",
        icona="users",
        section="anagrafica_api",
        force=force,
        bootstrap_nav_fn=_bootstrap_anagrafica_canonical,
    )
