"""
dashboard/views_home_portale.py
================================
Home portale interattiva di NOVICROM HUB — Django SSR + HTMX.

Integrazione: basata sul port Django generato da Claude Design (docs/UI/django_port/).
ACL: usa _visible_pulsanti_for_request() dalla dashboard esistente.
Dati: riusa _board_data_tasks(), _board_data_anomalie(), _board_data_assenze_da_approvare()
      già presenti in dashboard/views.py.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.hub_bacheca import visible_bacheca
from core.models import HubLink

# Riusa helpers già in dashboard/views.py (stessa app, no circular import)
from dashboard.views import (
    _board_data_anomalie,
    _board_data_assenze_da_approvare,
    _board_data_tasks,
    _board_related_tickets_queryset,
    _module_card_image_lookup,
    _module_image_url_for,
    _pulsanti_ui_meta_map,
    _visible_pulsanti_for_request,
)

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _greeting(now) -> str:
    h = now.hour
    if h < 12:
        return "Buongiorno"
    if h < 18:
        return "Buon pomeriggio"
    return "Buonasera"


def _date_label(now) -> str:
    giorni = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    mesi = [
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ]
    return f"{giorni[now.weekday()]} {now.day} {mesi[now.month - 1]} {now.year}"


def _safe_url(name: str) -> str:
    try:
        return reverse(name)
    except NoReverseMatch:
        return "#"


# ── Catalogo moduli ───────────────────────────────────────────────────────────

_CATEGORIES = [
    {"key": "ops",   "label": "Operations",            "hint": "Eventi e ciclo di lavoro"},
    {"key": "hr",    "label": "Persone & sicurezza",   "hint": "Anagrafica, assenze, formazione, DPI"},
    {"key": "plant", "label": "Stabilimento",          "hint": "Asset, planimetria, fornitori"},
    {"key": "comp",  "label": "Compliance",            "hint": "Documenti, rifiuti, audit"},
    {"key": "sys",   "label": "Automazione & sistema", "hint": "Workflow, AI, ACL, amministrazione"},
    {"key": "secit", "label": "SOC IT - CN",           "hint": "Contatori, sicurezza IT"},
]

# url_name: nome URL Django (con namespace se presente), o "#" se non esiste ancora.
_MODULE_CATALOG: list[dict] = [
    # OPS
    {"id": "anomalie",    "cat": "ops",   "label": "Anomalie",              "sub": "Eventi e segnalazioni",      "tone": "danger",  "kpi_unit": "aperte",      "url_name": "gestione_anomalie_page",          "pulsante_aliases": ("anomalie", "gestione-anomalie")},
    {"id": "ticket",      "cat": "ops",   "label": "Ticket",                "sub": "Interventi e richieste",     "tone": "warning", "kpi_unit": "attivi",      "url_name": "tickets:dashboard",               "pulsante_aliases": ("ticket", "tickets", "assistenza")},
    {"id": "task",        "cat": "ops",   "label": "Task / Kick-off",       "sub": "Attività di reparto",        "tone": "info",    "kpi_unit": "in corso",    "url_name": "tasks:list",                      "pulsante_aliases": ("task", "tasks", "vrf-kickoff", "kickoff")},
    {"id": "diario",      "cat": "ops",   "label": "Diario preposto",       "sub": "Giornale di sicurezza",      "tone": "warning", "kpi_unit": "da firmare",  "url_name": "diario_preposto:lista",           "pulsante_aliases": ("diario-preposto",)},
    {"id": "incidenti",   "cat": "ops",   "label": "Rilevazione incidenti", "sub": "Near miss e infortuni",      "tone": "danger",  "kpi_unit": "in analisi",  "url_name": "rilevazione_incidenti:lista",     "pulsante_aliases": ("rilevazione-incidenti", "incidenti")},
    {"id": "procedure",   "cat": "ops",   "label": "Procedure refresh",     "sub": "Procedure aggiornate",       "tone": "info",    "kpi_unit": "da rivedere", "url_name": "procedure_refresh:my_assignments","pulsante_aliases": ("procedure-refresh", "refresh-procedure", "procedure")},
    # HR
    {"id": "anagrafica",  "cat": "hr",    "label": "Anagrafica HR",         "sub": "Dipendenti attivi",          "tone": "info",    "kpi_unit": "dipendenti",  "url_name": "anagrafica:index",                "pulsante_aliases": ("anagrafica", "dipendenti")},
    {"id": "assenze",     "cat": "hr",    "label": "Assenze",               "sub": "Ferie, malattia, permessi",  "tone": "warning", "kpi_unit": "oggi assenti","url_name": "assenze_menu",                    "pulsante_aliases": ("assenze", "assenza")},
    {"id": "timbri",      "cat": "hr",    "label": "Timbri",                "sub": "Presenze e timbrature",      "tone": "success", "kpi_unit": "in turno",    "url_name": "timbri:index",                    "pulsante_aliases": ("timbri",)},
    {"id": "formazione",  "cat": "hr",    "label": "Formazione",            "sub": "Corsi e aggiornamenti",      "tone": "warning", "kpi_unit": "scaduti",     "url_name": "anagrafica:index",                "pulsante_aliases": ("formazione",)},
    {"id": "dpi",         "cat": "hr",    "label": "DPI",                   "sub": "Consegne e firma",           "tone": "danger",  "kpi_unit": "da firmare",  "url_name": "dpi:dashboard",                   "pulsante_aliases": ("dpi", "dispositivi-protezione")},
    {"id": "sicurezza",   "cat": "hr",    "label": "Sorv. sanitaria",       "sub": "Visite mediche",             "tone": "danger",  "kpi_unit": "da pianific.","url_name": "anagrafica:index",                "pulsante_aliases": ("visite", "sicurezza", "sorveglianza-sanitaria")},
    {"id": "notizie",     "cat": "hr",    "label": "Notizie aziendali",     "sub": "Comunicazioni interne",      "tone": "info",    "kpi_unit": "nuove",       "url_name": "notizie_lista",                   "pulsante_aliases": ("notizie", "notizia", "news")},
    # PLANT
    {"id": "asset",       "cat": "plant", "label": "Attrezzature",          "sub": "Asset register",             "tone": "info",    "kpi_unit": "asset",       "url_name": "assets:asset_list",               "pulsante_aliases": ("asset", "assets", "attrezzature", "inventario")},
    {"id": "planimetria", "cat": "plant", "label": "Planimetria",           "sub": "Layout stabilimenti",        "tone": "info",    "kpi_unit": "reparti",     "url_name": "planimetria:mappa",               "pulsante_aliases": ("planimetria",)},
    {"id": "fornitori",   "cat": "plant", "label": "Fornitori",             "sub": "Anagrafica fornitori",       "tone": "info",    "kpi_unit": "attivi",      "url_name": "fornitori:index",                 "pulsante_aliases": ("fornitori", "fornitore")},
    {"id": "monitoring",  "cat": "plant", "label": "Monitoring",            "sub": "Telemetria di linea",        "tone": "success", "kpi_unit": "allarmi",     "url_name": "monitoring:dashboard",            "pulsante_aliases": ("monitoring",)},
    # COMP
    {"id": "rentri",      "cat": "comp",  "label": "Rentri",                "sub": "Tracciamento rifiuti",       "tone": "warning", "kpi_unit": "FIR",         "url_name": "rentri_menu",                     "pulsante_aliases": ("rentri",)},
    {"id": "documenti",   "cat": "comp",  "label": "Documenti",             "sub": "Contratti, ACL, audit",      "tone": "warning", "kpi_unit": "in attesa",   "url_name": "#",                               "pulsante_aliases": ("documenti",)},
    # SYS
    {"id": "automazioni", "cat": "sys",   "label": "Automazioni",           "sub": "Workflow designer",          "tone": "success", "kpi_unit": "flussi attivi","url_name": "automazioni:automazioni_settings","pulsante_aliases": ("automazioni",)},
    {"id": "ai",          "cat": "sys",   "label": "Assistente AI",         "sub": "Knowledge & helper",         "tone": "success", "kpi_unit": "online",      "url_name": "ai_assistant:chat",               "pulsante_aliases": ("ai-assistant", "assistente-ai")},
    {"id": "hubtools",    "cat": "sys",   "label": "Hub Tools",             "sub": "Branding & pulsanti",        "tone": "info",    "kpi_unit": "strumenti",   "url_name": "hub_tools:hub_index",             "pulsante_aliases": ("hub-tools",)},
    {"id": "admin",       "cat": "sys",   "label": "Admin portale",         "sub": "Utenze e impersonificaz.",   "tone": "info",    "kpi_unit": "riservato",   "url_name": "admin_portale:index",             "pulsante_aliases": ("admin", "admin-portale")},
    {"id": "permessi",    "cat": "sys",   "label": "Permessi e ruoli",      "sub": "ACL v2",                     "tone": "info",    "kpi_unit": "ruoli",       "url_name": "admin_portale:index",             "pulsante_aliases": ("permessi", "acl")},
    # SOC IT - CN
    {"id": "contatori",   "cat": "secit", "label": "Contatori MFC",         "sub": "Stampanti, letture, consumabili", "tone": "info", "kpi_unit": "stampanti",   "url_name": "contatori:dashboard",             "pulsante_aliases": ("contatori",)},
    {"id": "security_center", "cat": "secit", "label": "Security Center",   "sub": "Alert, ticket, KPI sicurezza",    "tone": "danger", "kpi_unit": "alert",     "url_name": "security:dashboard",              "pulsante_aliases": ("security-center", "soc")},
]


def _build_accessible_set(request) -> set[str]:
    """Slug set derivato dai pulsanti visibili all'utente — usato per ACL del module hub."""
    pulsanti = _visible_pulsanti_for_request(request)
    slugs: set[str] = set()
    for p in pulsanti:
        for val in (p.modulo, p.codice, p.label, p.url):
            s = str(val or "").lower().strip().strip("/").replace("-", "").replace("_", "").replace(" ", "")
            if s:
                slugs.add(s)
    return slugs


def _mod_is_accessible(mod: dict, user_slugs: set[str], is_admin: bool) -> bool:
    if is_admin:
        return True
    for alias in mod.get("pulsante_aliases", (mod["id"],)):
        normalized = alias.lower().replace("-", "").replace("_", "")
        if normalized in user_slugs:
            return True
    return False


# ── Data layer ────────────────────────────────────────────────────────────────

def _first_kpi_value(tile_kpis: dict, module_id: str) -> int:
    """Estrae il primo conteggio KPI di un modulo da _tile_kpi_counts, 0 se assente."""
    rows = tile_kpis.get(module_id) or []
    if not rows:
        return 0
    value = rows[0].get("value")
    return int(value) if isinstance(value, (int, float)) else 0


def _priority_kpis(request, tile_kpis: dict | None = None) -> list[dict]:
    """4 KPI prioritari in hero. Riusa i conteggi già calcolati da
    _tile_kpi_counts (passati in tile_kpis) per evitare query duplicate.
    Il KPI 'Approvazioni' usa il modulo assenze (in approvazione)."""
    tile_kpis = tile_kpis or {}
    task_stats = (tile_kpis.get("task") or [])

    task_open = _first_kpi_value(tile_kpis, "task")
    # 'task' espone [in corso, scaduti]: lo scaduto è il secondo elemento.
    task_overdue = 0
    if len(task_stats) > 1 and isinstance(task_stats[1].get("value"), (int, float)):
        task_overdue = int(task_stats[1]["value"])

    anomalie_open = _first_kpi_value(tile_kpis, "anomalie")
    ticket_attivi = _first_kpi_value(tile_kpis, "ticket")
    approvazioni = _first_kpi_value(tile_kpis, "assenze")

    ticket_url = _safe_url("tickets:dashboard")
    anomalie_url = _safe_url("gestione_anomalie_page")
    task_url = _safe_url("tasks:list")
    assenze_url = _safe_url("assenze_menu")

    return [
        {"tone": "red",    "icon_char": "⚠", "value": anomalie_open, "label": "Anomalie aperte", "sub": "aggiornato in tempo reale", "url": anomalie_url},
        {"tone": "orange", "icon_char": "🎫", "value": ticket_attivi, "label": "Ticket attivi",   "sub": "aggiornato in tempo reale", "url": ticket_url},
        {"tone": "blue",   "icon_char": "✔", "value": task_open,     "label": "Task in corso",   "sub": f"{task_overdue} scaduti",   "url": task_url},
        {"tone": "green",  "icon_char": "✓", "value": approvazioni,  "label": "Approvazioni",    "sub": "richieste in attesa",       "url": assenze_url},
    ]


def _tile_kpi_counts(legacy_user, is_admin: bool, request_user=None) -> dict:
    """Multi-KPI per tile. Returns dict[module_id, list[{value, unit, tone}]].
    Tutte le query sono lightweight e avvolte in try/except — un errore non blocca la home."""
    from datetime import timedelta
    from django.utils import timezone as tz

    today = tz.localdate()
    year_start = today.replace(month=1, day=1)
    days_30 = today + timedelta(days=30)
    week_ago = today - timedelta(days=7)

    out: dict = {}

    # ── ANOMALIE ──────────────────────────────────────────────────────
    try:
        raw = _board_data_anomalie(legacy_user, is_admin, {"max_items": 500, "solo_aperte": True})
        out["anomalie"] = [
            {"value": len(raw), "unit": "aperte", "tone": "danger"},
        ]
    # Un riquadro che si rompe non deve far cadere la home — ma se sparisce in
    # silenzio e' indistinguibile da "nessun dato", e nessuno lo scopre mai.
    except Exception:
        logger.exception("Home: riquadro «Anomalie» non calcolato")

    # ── TICKET ────────────────────────────────────────────────────────
    try:
        from tickets.models import Ticket, StatoTicket
        legacy_user_id = int(legacy_user.id) if legacy_user else None
        if is_admin:
            qs = Ticket.objects.all()
        else:
            qs = _board_related_tickets_queryset(request_user, legacy_user, legacy_user_id)
        attivi = qs.filter(stato=StatoTicket.APERTA).count()
        out["ticket"] = [
            {"value": attivi, "unit": "attivi", "tone": "warning"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Ticket» non calcolato")

    # ── TASK ──────────────────────────────────────────────────────────
    try:
        uid = int(legacy_user.id) if legacy_user else None
        td = _board_data_tasks(uid, {"filter_status": "open", "max_items": 1})
        s = td.get("stats", {})
        scaduti = s.get("overdue", 0)
        out["task"] = [
            {"value": s.get("todo", 0) + s.get("in_progress", 0), "unit": "in corso", "tone": "info"},
            {"value": scaduti, "unit": "scaduti", "tone": "danger" if scaduti else "info"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Task» non calcolato")

    # ── DIARIO PREPOSTO ───────────────────────────────────────────────
    try:
        from diario_preposto.models import SegnalazionePreposto
        out["diario"] = [
            {"value": SegnalazionePreposto.objects.filter(data_segnalazione__date=today).count(),
             "unit": "oggi", "tone": "info"},
            {"value": SegnalazionePreposto.objects.filter(data_segnalazione__date__gte=week_ago).count(),
             "unit": "questa settimana", "tone": "warning"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Diario preposto» non calcolato")

    # ── INCIDENTI ─────────────────────────────────────────────────────
    try:
        from rilevazione_incidenti.models import RilevazioneIncidente
        aperti = RilevazioneIncidente.objects.filter(chiusura_rspp=False).count()
        anno = RilevazioneIncidente.objects.filter(
            data_segnalazione__date__gte=year_start
        ).count()
        out["incidenti"] = [
            {"value": aperti, "unit": "in analisi", "tone": "danger"},
            {"value": anno, "unit": str(today.year), "tone": "warning"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Incidenti» non calcolato")

    # ── PROCEDURE REFRESH ─────────────────────────────────────────────
    try:
        from procedure_refresh.models import ProcedureAssignment, ProcedureCampaign
        da_rivedere = ProcedureAssignment.objects.filter(
            status__in=["assigned", "overdue"]
        ).count()
        campagne = ProcedureCampaign.objects.filter(status="published").count()
        out["procedure"] = [
            {"value": da_rivedere, "unit": "da rivedere", "tone": "warning"},
            {"value": campagne, "unit": "campagne attive", "tone": "info"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Procedure» non calcolato")

    # ── ANAGRAFICA HR ─────────────────────────────────────────────────
    # Solo admin: conta tutti i dipendenti attivi. Per non-admin il tile
    # mostra il valore placeholder dal catalogo (value=None).
    if is_admin:
        try:
            from django.db import connections
            with connections["default"].cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM anagrafica_dipendenti WHERE COALESCE(attivo,1) = 1")
                row = cur.fetchone()
            out["anagrafica"] = [
                {"value": row[0] if row else None, "unit": "in forza", "tone": "info"},
            ]
        except Exception:
            logger.exception("Home: riquadro «Anagrafica» non calcolato")

    # ── ASSENZE ───────────────────────────────────────────────────────
    try:
        pending = _board_data_assenze_da_approvare(legacy_user, is_admin, {"max_items": 500})
        out["assenze"] = [
            {"value": len(pending), "unit": "in approvazione", "tone": "warning"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Assenze» non calcolato")

    # ── TIMBRI ────────────────────────────────────────────────────────
    try:
        from timbri.models import RegistroTimbro
        out["timbri"] = [
            {"value": RegistroTimbro.objects.filter(is_attivo=True, is_archived=False).count(),
             "unit": "badge attivi", "tone": "success"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Timbri» non calcolato")

    # ── FORMAZIONE ────────────────────────────────────────────────────
    # Solo admin: dati HR aggregati (qualifiche scadute di tutti i dipendenti).
    if is_admin:
        try:
            from anagrafica.models import DipendenteQualifica
            scadute = DipendenteQualifica.objects.filter(data_scadenza__lt=today).count()
            in_scad = DipendenteQualifica.objects.filter(
                data_scadenza__gte=today, data_scadenza__lte=days_30
            ).count()
            out["formazione"] = [
                {"value": scadute, "unit": "qualifiche scadute", "tone": "danger"},
                {"value": in_scad, "unit": "in scadenza 30gg", "tone": "warning"},
            ]
        except Exception:
            logger.exception("Home: riquadro «Formazione» non calcolato")

    # ── VISITE MEDICHE (sicurezza) ────────────────────────────────────
    # Solo admin: dati sanitari aggregati su tutti i dipendenti.
    if is_admin:
        try:
            from anagrafica.models import VisitaMedica
            scadute_v = VisitaMedica.objects.filter(data_scadenza__lt=today).count()
            in_scad_v = VisitaMedica.objects.filter(
                data_scadenza__gte=today, data_scadenza__lte=days_30
            ).count()
            out["sicurezza"] = [
                {"value": scadute_v, "unit": "visite scadute", "tone": "danger"},
                {"value": in_scad_v, "unit": "in scadenza 30gg", "tone": "warning"},
            ]
        except Exception:
            logger.exception("Home: riquadro «Visite mediche» non calcolato")

    # ── NOTIZIE ───────────────────────────────────────────────────────
    try:
        from notizie.models import Notizia
        pubblicate = Notizia.objects.filter(pubblicata=True).count()
        nuove = Notizia.objects.filter(pubblicata=True, data_pubblicazione__gte=week_ago).count()
        out["notizie"] = [
            {"value": pubblicate, "unit": "pubblicate", "tone": "info"},
            {"value": nuove, "unit": "ultima settimana", "tone": "success" if nuove else "info"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Notizie» non calcolato")

    # ── ASSET (attrezzature) ──────────────────────────────────────────
    try:
        from assets.models import Asset
        _uid = int(legacy_user.id) if legacy_user else None
        if is_admin:
            out["asset"] = [
                {"value": Asset.objects.filter(status="IN_USE").count(), "unit": "in uso", "tone": "info"},
                {"value": Asset.objects.filter(status="IN_REPAIR").count(), "unit": "in riparazione", "tone": "warning"},
            ]
        elif _uid:
            qs_mine = Asset.objects.filter(assigned_legacy_user_id=_uid)
            out["asset"] = [
                {"value": qs_mine.count(), "unit": "assegnati", "tone": "info"},
                {"value": qs_mine.filter(status="IN_USE").count(), "unit": "in uso", "tone": "info"},
            ]
    except Exception:
        logger.exception("Home: riquadro «Asset» non calcolato")

    # ── FORNITORI ─────────────────────────────────────────────────────
    try:
        from anagrafica.models import Fornitore
        out["fornitori"] = [
            {"value": Fornitore.objects.filter(is_active=True).count(), "unit": "attivi", "tone": "info"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Fornitori» non calcolato")

    # ── AUTOMAZIONI ───────────────────────────────────────────────────
    try:
        from automazioni.models import AutomationRule, AutomationRunLog
        attive = AutomationRule.objects.filter(is_active=True, is_draft=False).count()
        eseguiti = AutomationRunLog.objects.filter(
            started_at__date=today, is_test=False, status="success"
        ).count()
        out["automazioni"] = [
            {"value": attive, "unit": "flussi attivi", "tone": "success"},
            {"value": eseguiti, "unit": "eseguiti oggi", "tone": "info"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Automazioni» non calcolato")

    # ── RENTRI ────────────────────────────────────────────────────────
    try:
        from rentri.models import RegistroRifiuti
        da_rentri = RegistroRifiuti.objects.filter(rentri_si_no=False, salva=True).count()
        # arrivo_fir è una CharField (riferimento FIR): "FIR mancante" = stringa vuota
        # sui soli scarichi (O/M/R). Il vecchio filtro `arrivo_fir=False` non matchava
        # le stringhe vuote.
        fir = RegistroRifiuti.objects.filter(arrivo_fir="", tipo__in=["O", "M", "R"]).count()
        out["rentri"] = [
            {"value": da_rentri, "unit": "da comunicare RENTRI", "tone": "warning"},
            {"value": fir, "unit": "FIR mancanti", "tone": "danger" if fir else "info"},
        ]
    except Exception:
        logger.exception("Home: riquadro «RENTRI» non calcolato")

    # ── PLANIMETRIA ───────────────────────────────────────────────────
    try:
        from anagrafica.models import Reparto
        out["planimetria"] = [
            {"value": Reparto.objects.count(), "unit": "reparti", "tone": "info"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Planimetria» non calcolato")

    # ── UTENTI (admin) ────────────────────────────────────────────────
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        out["admin"] = [
            {"value": User.objects.filter(is_active=True).count(), "unit": "utenti attivi", "tone": "info"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Utenti» non calcolato")

    # ── PULSANTI (hubtools) ───────────────────────────────────────────
    try:
        from hub_tools.models import NavigationItem
        out["hubtools"] = [
            {"value": NavigationItem.objects.filter(is_visible=True).count(),
             "unit": "pulsanti attivi", "tone": "info"},
        ]
    except Exception:
        logger.exception("Home: riquadro «Pulsanti» non calcolato")

    return out


def _module_groups(request, accessible_set: set[str], is_admin: bool,
                   image_lookup: dict, kpi_counts: dict | None = None) -> list[dict]:
    kpi_counts = kpi_counts or {}
    groups = []
    for cat in _CATEGORIES:
        modules = []
        accessible_count = 0
        for spec in _MODULE_CATALOG:
            if spec["cat"] != cat["key"]:
                continue
            can = _mod_is_accessible(spec, accessible_set, is_admin)
            if not can:
                continue
            url = _safe_url(spec["url_name"]) if spec["url_name"] != "#" else "#"
            icon_image = _module_image_url_for(image_lookup, *spec["pulsante_aliases"])
            # kpis: list[{value, unit, tone}] — multi-KPI per tile
            raw_kpis: list = kpi_counts.get(spec["id"]) or []
            if not raw_kpis and spec.get("kpi_unit"):
                raw_kpis = [{"value": None, "unit": spec["kpi_unit"], "tone": spec.get("tone", "info")}]
            first = raw_kpis[0] if raw_kpis else {}
            modules.append({
                "id":         spec["id"],
                "label":      spec["label"],
                "sub":        spec["sub"],
                "icon":       None,
                "icon_image": icon_image,
                "tone":       spec["tone"],
                "url":        url,
                "accessible": can,
                "kpis":       raw_kpis,
                "kpi_value":  first.get("value"),
                "kpi_unit":   first.get("unit"),
            })
            if can:
                accessible_count += 1
        if modules:
            groups.append({
                "key":             cat["key"],
                "label":          cat["label"],
                "hint":           cat["hint"],
                "modules":        modules,
                "total":          len(modules),
                "accessible_count": accessible_count,
            })
    return groups


def _my_tasks(request) -> list[dict]:
    """Task assegnati all'utente — ticket aperti con scadenza."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    legacy_user_id = int(legacy_user.id) if legacy_user else None
    data = _board_data_tasks(legacy_user_id, {"filter_status": "open", "max_items": 5})
    out = []
    for t in data.get("items", []):
        tone = "danger" if t.get("is_overdue") else ("warning" if t.get("priority") in ("H", "high", "Alta") else "info")
        url = _safe_url("tickets:dashboard")
        out.append({
            "code":     f"T-{t['id']}",
            "title":    t["title"],
            "due":      t.get("due_date") or "—",
            "priority": t.get("priority_label") or t.get("priority") or "—",
            "tone":     tone,
            "url":      url,
        })
    return out


def _pending_approvals(request) -> list[dict]:
    """Assenze in attesa di approvazione (CAR / admin)."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    raw = _board_data_assenze_da_approvare(legacy_user, is_admin, {"max_items": 6})
    out = []
    for i, a in enumerate(raw):
        out.append({
            "id":        i,
            "code":      f"CAR-{i:04d}",
            "title":     f"{a.get('tipo', '')} · {a.get('inizio', '')}",
            "requester": a.get("dipendente", ""),
            "category":  "Assenze",
            "url":       _safe_url("assenze_gestione"),
            "approve_url": None,
            "reject_url":  None,
        })
    return out


def _anomalie_aperte(request) -> list[dict]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    raw = _board_data_anomalie(legacy_user, is_admin, {"max_items": 5, "solo_aperte": True})
    url_base = _safe_url("gestione_anomalie_page")
    out = []
    for a in raw:
        out.append({
            "code":    f"A-{a['id']}",
            "title":   a.get("seriale") or "Anomalia",
            "area":    a.get("operatore") or "—",
            "elapsed": "—",
            "tone":    "warning",
            "status":  a.get("avanzamento") or "Aperta",
            "url":     url_base,
        })
    return out


def _calendar_week(request) -> list[dict]:
    today = timezone.localdate()
    start = today - timedelta(days=today.weekday())
    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        days.append({
            "day":          ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"][i],
            "num":          d.day,
            "iso":          d.isoformat(),
            "is_today":     d == today,
            "is_weekend":   i >= 5,
            "absent_count": 0,  # TODO: count assenze approvate per il giorno
        })
    return days


def _news_items(request) -> list[dict]:
    """Ultime notizie dal modulo notizie."""
    try:
        from notizie.models import Notizia
        qs = Notizia.objects.filter(pubblicata=True).order_by("-data_pubblicazione")[:5]
        url_base = _safe_url("notizie_lista")
        out = []
        for n in qs:
            out.append({
                "title":  str(n.titolo or ""),
                "source": str(getattr(n, "reparto", "") or getattr(n, "autore", "") or ""),
                "ago":    "—",
                "url":    url_base,
            })
        return out
    except Exception:
        return []


def _activity_items(request) -> list[dict]:
    """Attività recenti — placeholder (TODO: audit trail)."""
    return []


def _safety_kpis(request) -> list[dict]:
    """KPI sicurezza — placeholder (TODO: da rilevazione_incidenti)."""
    return []


def _system_status(request) -> list[dict]:
    """Stato servizi — placeholder (TODO: ping ACL/Graph/LDAP)."""
    return []


def _active_role(legacy_user) -> dict:
    ruolo = str(getattr(legacy_user, "ruolo", "") or "").strip()
    _map = {
        "AMMINISTRAZIONE": ("IT", "Amministratore"),
        "ADMIN":           ("IT", "Amministratore"),
        "CAR":             ("CR", "Capo Reparto"),
        "CAPO REPARTO":    ("CR", "Capo Reparto"),
        "DIRETTORE":       ("DIR", "Direzione"),
        "HR":              ("HR", "HR Specialist"),
        "PREPOSTO":        ("PR", "Preposto"),
        "OPERATORE":       ("OP", "Operatore"),
    }
    code, label = _map.get(ruolo.upper(), (ruolo[:3].upper() or "?", ruolo or "Utente"))
    return {"code": code, "label": label}


def _active_unit(legacy_user_id) -> str | None:
    try:
        from core.models import UserExtraInfo
        extra = UserExtraInfo.objects.filter(legacy_user_id=legacy_user_id).first()
        return str(extra.reparto or "") or None if extra else None
    except Exception:
        return None


def _header_actions(request) -> list[dict]:
    return [
        {"label": "Le mie attività",   "href": _safe_url("mie_attivita"),          "variant": "primary"},
        {"label": "Scadenzario",       "href": _safe_url("scadenze_globali"),      "variant": "ghost"},
        {"label": "Nuovo ticket",      "href": _safe_url("tickets:nuovo"),       "variant": "ghost"},
        {"label": "Segnala anomalia",  "href": _safe_url("apertura_segnalazione"), "variant": "ghost"},
        {"label": "Richiedi permesso", "href": _safe_url("assenze_richiesta"),     "variant": "ghost"},
    ]


# ── Bacheca "Documenti & Collegamenti" ────────────────────────────────────────

BACHECA_PREVIEW_PER_CATEGORY = 4

_KIND_LABEL = {HubLink.KIND_FILE: "File", HubLink.KIND_URL: "Link", HubLink.KIND_INTERNAL: "Interna"}


def _documenti_collegamenti(request, preview: bool = True) -> list[dict]:
    """Sezione Documenti & Collegamenti per la home / pagina bacheca."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    role_id = getattr(legacy_user, "ruolo_id", None)
    limit = BACHECA_PREVIEW_PER_CATEGORY if preview else None
    groups = visible_bacheca(role_id, is_admin=is_admin, preview_limit=limit)
    out: list[dict] = []
    for g in groups:
        cat = g["category"]
        out.append({
            "name": cat.name,
            "icon": cat.icon,
            "slug": cat.slug,
            "more": g["more"],
            "items": [{
                "title": l.title,
                "description": l.description,
                "kind": l.kind,
                "kind_label": _KIND_LABEL.get(l.kind, ""),
                "icon": l.icon,
                "href": l.resolve_href(),
                "open_in_new_tab": bool(l.open_in_new_tab or l.kind == HubLink.KIND_URL),
            } for l in g["items"]],
        })

    # Gruppo virtuale «Procedure SGI»: documenti procedura consultabili (esclusi i
    # sensibili). Costruito al volo da procedure_refresh, non da HubLink.
    try:
        from procedure_refresh.bacheca import build_procedure_group

        proc = build_procedure_group(role_id, is_admin=is_admin, preview_limit=limit)
        if proc:
            out.append({
                "name": proc["category"].name,
                "icon": proc["category"].icon,
                "slug": proc["category"].slug,
                "more": proc["more"],
                "items": [{**it, "icon": ""} for it in proc["items"]],
            })
    except Exception:
        logger.exception("Home: gruppo bacheca Procedure SGI non disponibile")
    return out


def _module_launcher(groups: list[dict]) -> list[dict]:
    """Appiattisce i module_groups in un'unica lista di card 'home modulo' (dedup)."""
    seen: set[str] = set()
    flat: list[dict] = []
    for grp in groups:
        for mod in grp.get("modules", []):
            key = str(mod.get("id") or mod.get("label") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            flat.append(mod)
    return flat


# ── Views ─────────────────────────────────────────────────────────────────────

@login_required
def home_portale(request: HttpRequest) -> HttpResponse:
    now = timezone.localtime()
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    legacy_user_id = int(legacy_user.id) if legacy_user else None
    display_name = (request.user.first_name
                    or getattr(legacy_user, "nome", "")
                    or request.user.get_username())

    image_lookup = _module_card_image_lookup()
    accessible_set = _build_accessible_set(request)

    my_tasks_list = _my_tasks(request)
    pending = _pending_approvals(request)

    parts = []
    if my_tasks_list:
        parts.append(f"{len(my_tasks_list)} attività assegnate")
    if pending:
        parts.append(f"{len(pending)} richieste in approvazione")
    greeting_summary = " e ".join(parts) + "." if parts else "Benvenuto nel portale."

    tile_kpis = _tile_kpi_counts(legacy_user, is_admin, request_user=request.user)
    groups = _module_groups(request, accessible_set, is_admin, image_lookup, tile_kpis)

    # "Cose da gestire": aggregato cross-modulo delle azioni che spettano all'utente.
    from dashboard.views_mie_attivita import build_cose_da_gestire
    cose_da_gestire = build_cose_da_gestire(request)

    context: dict[str, Any] = {
        "greeting":           _greeting(now),
        "greeting_name":      display_name,
        "greeting_summary":   greeting_summary,
        "date_label":         _date_label(now),
        "time_label":         now.strftime("%H:%M"),
        "active_role":        _active_role(legacy_user),
        "active_unit":        _active_unit(legacy_user_id),
        "header_actions":     _header_actions(request),
        "priority_kpis":      _priority_kpis(request, tile_kpis),
        "module_groups":      groups,
        "module_total":       sum(g["total"] for g in groups),
        # my_tasks/pending alimentano il riepilogo del saluto; i singoli pannelli
        # d'azione sono stati sostituiti dal cockpit "Le mie attività" (cose_da_gestire).
        "my_tasks":           my_tasks_list,
        "pending_approvals":  pending,
        "cose_da_gestire":        cose_da_gestire["sections"],
        "cose_da_gestire_total":  cose_da_gestire["total"],
        "bacheca_groups":     _documenti_collegamenti(request),
        "module_launcher":    _module_launcher(groups),
        "news_items":         _news_items(request),
        "activity_items":     _activity_items(request),
        "app_version":        str(getattr(settings, "APP_VERSION", "") or ""),
        "ai_daily_brief_enabled": bool(
            getattr(settings, "OLLAMA_CHAT_ENABLED", True)
            and getattr(settings, "OLLAMA_DAILY_BRIEF_ENABLED", True)
        ),
    }
    return render(request, "dashboard/pages/home_portale.html", context)


# ── HTMX endpoints ────────────────────────────────────────────────────────────

@login_required
@require_POST
def toggle_locked(request: HttpRequest) -> HttpResponse:
    request.session["hp_show_locked"] = False
    return HttpResponse(status=204)


@login_required
@require_GET
def activity_recent(request: HttpRequest) -> HttpResponse:
    items = _activity_items(request)
    return render(request, "core/partials/_home_activity.html", {"items": items})
