"""
home_portale/views.py
=====================
View della Home portale di NOVICROM HUB (Django SSR + HTMX).
Da collocare in `django_app/home_portale/views.py` o equivalente.

Note di integrazione:
- Usa ACL v2 (`core.acl_v2`) e Module Registry esistente.
- I conteggi KPI/anomalie/ticket vanno cablati ai modelli reali del progetto.
- Tutte le endpoint HTMX rispondono con un frammento HTML (partial).
"""

from __future__ import annotations
from datetime import date, datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

# --- moduli del progetto -----------------------------------------------------
from core.acl_v2 import user_can_access_module, get_user_role
from core.module_registry import iter_modules  # presunto, adatta al tuo registry
from core.context_processors import get_app_version


# ───────────────────────────── HELPERS ────────────────────────────────────────

def _greeting(now: datetime) -> str:
    h = now.hour
    if h < 12:  return "Buongiorno"
    if h < 18:  return "Buon pomeriggio"
    return "Buonasera"


def _date_label(now: datetime) -> str:
    giorni = ["lunedì", "martedì", "mercoledì", "giovedì",
              "venerdì", "sabato", "domenica"]
    mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
            "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    return f"{giorni[now.weekday()]} {now.day} {mesi[now.month - 1]} {now.year}"


# ───────────────────────────── DATA LAYER (skeleton) ──────────────────────────
# Sostituisci ogni funzione con la query reale ai tuoi modelli.

def _priority_kpis(request) -> list[dict]:
    # TODO: query reali
    return [
        {"id": "anomalie", "tone": "red",    "icon": "core/icons/_warning.svg",
         "value": 3,  "label": "Anomalie aperte", "sub": "2 critiche · 1 alta",
         "url": reverse("anomalie:list")},
        {"id": "ticket", "tone": "orange",   "icon": "core/icons/_ticket.svg",
         "value": 14, "label": "Ticket attivi",   "sub": "3 in scadenza oggi",
         "url": reverse("ticket:list")},
        {"id": "task", "tone": "blue",       "icon": "core/icons/_task.svg",
         "value": 27, "label": "Task in corso",   "sub": "5 assegnate a te",
         "url": reverse("task:list")},
        {"id": "appr", "tone": "green",      "icon": "core/icons/_check.svg",
         "value": 8,  "label": "Approvazioni",    "sub": "4 CAR · 4 automazioni",
         "url": reverse("assenze:gestione")},
    ]


# Catalogo statico → fonte canonica dei moduli mostrati in home.
# Per essere DRY puoi rigenerarlo da iter_modules() filtrando per
# l'attributo `show_in_home_portale`.
_MODULE_CATALOG: list[dict] = [
    # OPS
    {"id": "anomalie",   "cat": "ops", "icon": "core/icons/_warning.svg",   "label": "Anomalie",            "sub": "Eventi e segnalazioni",     "url": "anomalie:list",   "tone": "danger",  "kpi_qs": "anomalie_aperte",      "kpi_unit": "aperte",      "acl": "anomalie.view"},
    {"id": "ticket",     "cat": "ops", "icon": "core/icons/_ticket.svg",    "label": "Ticket",              "sub": "Interventi e richieste",    "url": "ticket:list",     "tone": "warning", "kpi_qs": "ticket_attivi",        "kpi_unit": "attivi",      "acl": "ticket.view"},
    {"id": "task",       "cat": "ops", "icon": "core/icons/_task.svg",      "label": "Task / Kick-off",     "sub": "Attività di reparto",       "url": "task:list",       "tone": "info",    "kpi_qs": "task_in_corso",        "kpi_unit": "in corso",    "acl": "task.view"},
    {"id": "diario",     "cat": "ops", "icon": "core/icons/_clipboard.svg", "label": "Diario preposto",     "sub": "Giornale di sicurezza",     "url": "diario:list",     "tone": "warning", "kpi_qs": "diario_da_firmare",    "kpi_unit": "da firmare",  "acl": "diario.view"},
    {"id": "incidenti",  "cat": "ops", "icon": "core/icons/_flag.svg",      "label": "Rilevazione incidenti","sub": "Near miss e infortuni",    "url": "incidenti:list",  "tone": "danger",  "kpi_qs": "incidenti_in_analisi", "kpi_unit": "in analisi",  "acl": "incidenti.view"},
    {"id": "procedure",  "cat": "ops", "icon": "core/icons/_refresh.svg",   "label": "Procedure refresh",   "sub": "Procedure CN aggiornate",   "url": "procedure:list",  "tone": "info",    "kpi_qs": "procedure_review",     "kpi_unit": "da rivedere", "acl": "procedure.view"},
    # HR
    {"id": "anagrafica", "cat": "hr", "icon": "core/icons/_people.svg",     "label": "Anagrafica HR",       "sub": "Dipendenti attivi",         "url": "anagrafica:list",  "tone": "info",   "kpi_qs": "anagrafica_count",     "kpi_unit": "dipendenti",  "acl": "anagrafica.view"},
    {"id": "assenze",    "cat": "hr", "icon": "core/icons/_calendar.svg",   "label": "Assenze",             "sub": "Ferie, malattia, permessi", "url": "assenze:home",     "tone": "warning","kpi_qs": "assenze_oggi",         "kpi_unit": "oggi assenti","acl": "assenze.view"},
    {"id": "timbri",     "cat": "hr", "icon": "core/icons/_clock.svg",      "label": "Timbri",              "sub": "Presenze e timbrature",     "url": "timbri:list",      "tone": "success","kpi_qs": "timbri_in_turno",      "kpi_unit": "in turno",    "acl": "timbri.view"},
    {"id": "formazione", "cat": "hr", "icon": "core/icons/_graduation.svg", "label": "Formazione",          "sub": "Corsi e aggiornamenti",     "url": "formazione:list",  "tone": "warning","kpi_qs": "formazione_scaduti",   "kpi_unit": "scaduti",     "acl": "formazione.view"},
    {"id": "dpi",        "cat": "hr", "icon": "core/icons/_shield.svg",     "label": "DPI",                 "sub": "Consegne e firma",          "url": "dpi:list",         "tone": "danger", "kpi_qs": "dpi_da_firmare",       "kpi_unit": "da firmare",  "acl": "dpi.view"},
    {"id": "sicurezza",  "cat": "hr", "icon": "core/icons/_heart.svg",      "label": "Sorv. sanitaria",     "sub": "Visite mediche",            "url": "sicurezza:home",   "tone": "danger", "kpi_qs": "visite_da_pianificare","kpi_unit": "da pianific.","acl": "sicurezza.view"},
    {"id": "notizie",    "cat": "hr", "icon": "core/icons/_bell.svg",       "label": "Notizie aziendali",   "sub": "Comunicazioni interne",     "url": "notizie:list",     "tone": "info",   "kpi_qs": "notizie_non_lette",    "kpi_unit": "nuove",       "acl": "notizie.view"},
    # PLANT
    {"id": "asset",       "cat": "plant", "icon": "core/icons/_asset.svg",    "label": "Attrezzature",  "sub": "Asset register",        "url": "asset:list",       "tone": "info", "kpi_qs": "asset_count",   "kpi_unit": "asset",     "acl": "asset.view"},
    {"id": "planimetria", "cat": "plant", "icon": "core/icons/_building.svg", "label": "Planimetria",   "sub": "Layout stabilimenti",   "url": "planimetria:home", "tone": "info", "kpi_qs": "reparti_count", "kpi_unit": "reparti",   "acl": "planimetria.view"},
    {"id": "fornitori",   "cat": "plant", "icon": "core/icons/_briefcase.svg","label": "Fornitori",     "sub": "Anagrafica fornitori",  "url": "fornitori:list",   "tone": "info", "kpi_qs": "fornitori_count","kpi_unit": "attivi",   "acl": "fornitori.view"},
    {"id": "monitoring",  "cat": "plant", "icon": "core/icons/_gear.svg",     "label": "Monitoring",    "sub": "Telemetria di linea",   "url": "monitoring:home",  "tone": "success","kpi_qs": "monitoring_alarms","kpi_unit": "allarmi","acl": "monitoring.view"},
    # COMP
    {"id": "rentri",     "cat": "comp", "icon": "core/icons/_folder.svg",   "label": "Rentri",         "sub": "Tracciamento rifiuti",  "url": "rentri:home",      "tone": "warning", "kpi_qs": "fir_da_firmare", "kpi_unit": "FIR da firmare", "acl": "rentri.view"},
    {"id": "documenti",  "cat": "comp", "icon": "core/icons/_doc.svg",      "label": "Documenti",      "sub": "Contratti, ACL, audit", "url": "documenti:list",   "tone": "warning", "kpi_qs": "documenti_attesa","kpi_unit": "in attesa",    "acl": "documenti.view"},
    # SYS
    {"id": "automazioni","cat": "sys", "icon": "core/icons/_refresh.svg",   "label": "Automazioni",   "sub": "Workflow designer",     "url": "automazioni:home", "tone": "success", "kpi_qs": "automazioni_attive","kpi_unit": "flussi attivi","acl": "automazioni.view"},
    {"id": "ai",         "cat": "sys", "icon": "core/icons/_badge_check.svg","label":"Assistente AI", "sub": "Knowledge & helper",    "url": "ai_assistant:chat","tone": "success", "kpi_qs": None,             "kpi_unit": "online",          "acl": "ai.view"},
    {"id": "hubtools",   "cat": "sys", "icon": "core/icons/_gear.svg",      "label": "Hub Tools",     "sub": "Branding & pulsanti",   "url": "hub_tools:hub_index","tone": "info",  "kpi_qs": None,             "kpi_unit": "strumenti",       "acl": "hubtools.view"},
    {"id": "admin",      "cat": "sys", "icon": "core/icons/_lock.svg",      "label": "Admin portale", "sub": "Utenze e impersonificaz.","url": "admin:index",    "tone": "info",  "kpi_qs": None,             "kpi_unit": "riservato",       "acl": "admin.view"},
    {"id": "permessi",   "cat": "sys", "icon": "core/icons/_lock.svg",      "label": "Permessi e ruoli","sub": "ACL v2",             "url": "permessi:list",    "tone": "info",  "kpi_qs": "permessi_ruoli", "kpi_unit": "ruoli",           "acl": "permessi.view"},
]

_CATEGORIES = [
    {"key": "ops",   "label": "Operations",            "hint": "Eventi e ciclo di lavoro"},
    {"key": "hr",    "label": "Persone & sicurezza",   "hint": "Anagrafica, assenze, formazione, DPI"},
    {"key": "plant", "label": "Stabilimento",          "hint": "Asset, planimetria, fornitori"},
    {"key": "comp",  "label": "Compliance",            "hint": "Documenti, rifiuti, audit"},
    {"key": "sys",   "label": "Automazione & sistema", "hint": "Workflow, AI, ACL, amministrazione"},
]


def _kpi_for(request, kpi_qs: str | None) -> dict | None:
    """Mappa il nome KPI ad un valore (cablalo ai tuoi modelli)."""
    if not kpi_qs:
        return None
    # TODO: queryset reali; per ora valori placeholder
    placeholders = {
        "anomalie_aperte": 3, "ticket_attivi": 14, "task_in_corso": 27,
        "diario_da_firmare": 2, "incidenti_in_analisi": 1, "procedure_review": 4,
        "anagrafica_count": 148, "assenze_oggi": 11, "timbri_in_turno": 142,
        "formazione_scaduti": 12, "dpi_da_firmare": 9, "visite_da_pianificare": 7,
        "notizie_non_lette": 3, "asset_count": 512, "reparti_count": 6,
        "fornitori_count": 87, "monitoring_alarms": 0, "fir_da_firmare": 2,
        "documenti_attesa": 21, "automazioni_attive": 18, "permessi_ruoli": 14,
    }
    return placeholders.get(kpi_qs)


def _module_groups(request) -> list[dict]:
    """Costruisce i 5 gruppi del Module Hub con ACL v2."""
    groups: list[dict] = []
    for cat in _CATEGORIES:
        modules = []
        accessible = 0
        for spec in _MODULE_CATALOG:
            if spec["cat"] != cat["key"]:
                continue
            can = user_can_access_module(request.user, spec["acl"])
            try:
                url = reverse(spec["url"]) if spec.get("url") else "#"
            except Exception:
                url = "#"
            kpi_value = _kpi_for(request, spec.get("kpi_qs"))
            modules.append({
                "id":          spec["id"],
                "label":       spec["label"],
                "sub":         spec["sub"],
                "icon":        spec["icon"],
                "icon_image":  spec.get("icon_image"),  # opz. immagine
                "tone":        spec["tone"],
                "url":         url,
                "accessible":  can,
                "kpi_value":   kpi_value,
                "kpi_unit":    spec.get("kpi_unit"),
            })
            if can:
                accessible += 1
        if modules:
            groups.append({
                "key":               cat["key"],
                "label":             cat["label"],
                "hint":              cat["hint"],
                "modules":           modules,
                "total":             len(modules),
                "accessible_count":  accessible,
            })
    return groups


def _my_tasks(request) -> list[dict]:
    # TODO: query reale a ticket/task assegnati a request.user
    return []


def _pending_approvals(request) -> list[dict]:
    # TODO: CAR + automation approvals + FIR rentri
    return []


def _anomalie_aperte(request) -> list[dict]:
    # TODO: AnomaliaQuerySet.filter(stato="aperta").order_by(...)[:5]
    return []


def _calendar_week(request) -> list[dict]:
    today = timezone.localdate()
    start = today - timedelta(days=today.weekday())
    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        days.append({
            "day":           ["Lun","Mar","Mer","Gio","Ven","Sab","Dom"][i],
            "num":           d.day,
            "iso":           d.isoformat(),
            "is_today":      d == today,
            "is_weekend":    i >= 5,
            "absent_count":  0,  # TODO: count assenze.approved per quel giorno
        })
    return days


def _news_items(request) -> list[dict]:    return []   # TODO
def _activity_items(request) -> list[dict]: return []  # TODO
def _safety_kpis(request) -> list[dict]:   return []   # TODO
def _system_status(request) -> list[dict]: return []   # TODO


# ───────────────────────────── VIEWS ──────────────────────────────────────────

@login_required
def home_portale(request: HttpRequest) -> HttpResponse:
    now = timezone.localtime()
    role = get_user_role(request.user)
    show_locked = bool(request.session.get("hp_show_locked", True))

    context = {
        "greeting":           _greeting(now),
        "greeting_name":      request.user.first_name or request.user.get_short_name(),
        "greeting_summary":   "Hai attività in scadenza e richieste in approvazione.",
        "date_label":         _date_label(now),
        "time_label":         now.strftime("%H:%M"),
        "active_role":        {"code": role.code, "label": role.label, "hint": role.description},
        "active_unit":        getattr(request.user, "unit_label", None),
        "header_actions":     _header_actions(request),
        "priority_kpis":      _priority_kpis(request),
        "module_groups":      _module_groups(request),
        "show_locked_modules": show_locked,
        "module_total":       sum(g["total"] for g in _module_groups(request)),
        "my_tasks":           _my_tasks(request),
        "pending_approvals":  _pending_approvals(request),
        "anomalie_aperte":    _anomalie_aperte(request),
        "calendar_week":      _calendar_week(request),
        "news_items":         _news_items(request),
        "activity_items":     _activity_items(request),
        "safety_kpis":        _safety_kpis(request),
        "system_status":      _system_status(request),
        "app_version":        get_app_version(),
    }
    return render(request, "core/pages/home_portale.html", context)


def _header_actions(request) -> list[dict]:
    """CTA dell'hero — personalizzabili da Hub Tools o hardcoded qui."""
    actions = [
        {"label": "Nuovo ticket",     "icon": "core/icons/_plus.svg",
         "href": reverse("ticket:new"),         "variant": "primary"},
        {"label": "Segnala anomalia", "icon": "core/icons/_warning.svg",
         "href": reverse("anomalie:new"),       "variant": "ghost"},
        {"label": "Richiedi permesso","icon": "core/icons/_calendar.svg",
         "href": reverse("assenze:new"),        "variant": "ghost"},
    ]
    return [a for a in actions
            if user_can_access_module(request.user, a.get("acl", "") or "")
            or not a.get("acl")]


# ── HTMX endpoints ────────────────────────────────────────────────────────────

@login_required
@require_POST
def toggle_locked(request):
    request.session["hp_show_locked"] = request.POST.get("show_locked") == "1"
    return HttpResponse(status=204)


@login_required
@require_GET
def activity_recent(request):
    items = _activity_items(request)
    return render(request, "core/partials/_home_activity.html", {"items": items})


@login_required
@require_POST
def approval_decide(request, kind: str, pk: int, action: str):
    """
    Endpoint generico per approvare/rifiutare una richiesta.
    Risponde con riga svuotata (HTMX la rimuove con swap outerHTML).
    """
    if action not in ("approve", "reject"):
        return HttpResponseForbidden()

    # TODO: dispatch su modello per `kind`: car, automation, fir, ...
    # obj = get_object_or_404(...)
    # if not request.user.has_perm(...): return HttpResponseForbidden()
    # obj.approve() if action == "approve" else obj.reject()

    return HttpResponse(
        f'<li class="hp-empty-sm hp-flash">'
        f'  Richiesta {"approvata" if action=="approve" else "rifiutata"}.'
        f'</li>'
    )
