"""Viste del nuovo dominio manutenzione (Piano / Applicazione / Occorrenza / OdL).

Modulo separato da ``views.py``, che ha superato le 18.000 righe ed e' toccato in
parallelo da piu' rami: tenere qui il nuovo dominio lo rende leggibile e riduce i
conflitti. Gli helper condivisi (shell, gate, parsing) restano importati da
``views.py``, che non importa mai questo modulo: la dipendenza va in un verso solo.

Il linguaggio dell'interfaccia e' quello del documento di specifica: Piano,
Applicazione, Scadenza, Ordine di lavoro, Follow-up. Mai "regola", "override",
"threshold", "scope".
"""

from __future__ import annotations

import logging

import io
import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, F, IntegerField, Max, Q, Value, When
from django.db.models.functions import TruncMonth
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.acl import user_can_modulo_action

from .forms_maintenance import (
    AssetGroupForm,
    AssetPlanCustomizationForm,
    ExecutionDayForm,
    FollowUpForm,
    MaintenancePlanAssignmentForm,
    MaintenanceHistoryImportForm,
    MaintenancePlanForm,
    OccurrenceBulkCompletionForm,
    OccurrenceCompletionForm,
    OccurrenceFilterForm,
    WorkOrderFromOccurrencesForm,
    category_with_descendants,
)
from .models import (
    Asset,
    AssetGroup,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenanceOccurrenceAttachment,
    MaintenancePlanAssignment,
    WorkOrder,
)
from .services import maintenance_domain as domain
from .services import maintenance_history_import as history_import
from .services.recurrence import (
    ANCHOR_FROM_COMPLETION,
    RECURRENCE_PRESETS,
    compute_next_due,
    describe_recurrence,
    first_due_date_for,
)
from .views import _assets_shell_context, _as_int, _clean_string, _copertura_dato, _is_assets_admin

# ---------------------------------------------------------------------------
# Permessi
# ---------------------------------------------------------------------------
# Le tre platee della specifica. I gate non si fermano a "superuser o admin
# legacy": chi ha il permesso ACL granulare deve poter lavorare, altrimenti il
# pannello Accessi non serve a niente.

logger = logging.getLogger(__name__)


def can_manage_maintenance_plans(request: HttpRequest) -> bool:
    """Configura piani, applicazioni, gruppi. Amministratore / responsabile."""
    if _is_assets_admin(request):
        return True
    return bool(user_can_modulo_action(request, "assets", "admin_assets"))


def can_plan_maintenance(request: HttpRequest) -> bool:
    """Organizza il lavoro: crea OdL, distribuisce le giornate, rimuove asset."""
    if can_manage_maintenance_plans(request):
        return True
    return bool(user_can_modulo_action(request, "assets", "maintenance_planning"))


def can_execute_maintenance(request: HttpRequest) -> bool:
    """Esegue: chiude occorrenze, carica rapporti, apre follow-up."""
    if can_plan_maintenance(request):
        return True
    return bool(user_can_modulo_action(request, "assets", "maintenance_execute"))


def _deny(request: HttpRequest, message: str, fallback: str = "assets:maintenance_da_fare"):
    messages.error(request, message)
    return redirect(fallback)


# ---------------------------------------------------------------------------
# Query e presentazione delle occorrenze
# ---------------------------------------------------------------------------

_OCCURRENCE_SELECT = (
    "plan",
    "asset",
    "asset__asset_category",
    "assignment",
    "assignment__asset_group",
    "work_order",
    "work_order__assigned_to",
    "supplier",
)


def _base_occurrence_queryset():
    return (
        MaintenanceOccurrence.objects.select_related(*_OCCURRENCE_SELECT)
        .prefetch_related("attachments")
        .exclude(status=MaintenanceOccurrence.STATUS_CANCELED)
    )


def user_reparti(request: HttpRequest) -> list[str]:
    """Reparti guidati dall'utente, dalla fonte autorevole ``Reparto.caporeparto_legacy_id``.

    Serve a preimpostare il filtro, non a nascondere dati: la pagina lo dichiara e
    basta un click per togliere lo scope. Tutto in try/except perche' passa dalle
    tabelle legacy: un caporeparto non risolto deve dare "nessun filtro", mai un 500.
    """
    try:
        from anagrafica.models import Reparto
        from core.models import Profile

        legacy_id = (
            Profile.objects.filter(user=request.user)
            .values_list("legacy_user_id", flat=True)
            .first()
        )
        if not legacy_id:
            return []
        return sorted(
            {
                str(nome).strip()
                for nome in Reparto.objects.filter(
                    is_active=True, caporeparto_legacy_id=int(legacy_id)
                ).values_list("nome", flat=True)
                if str(nome or "").strip()
            }
        )
    except Exception:  # pragma: no cover - dipende dalle tabelle legacy
        return []


def _apply_caporeparto_scope(queryset, request: HttpRequest) -> tuple[Any, list[str]]:
    """Preimposta lo scope sui reparti dell'utente, se non ha gia' scelto lui.

    ``reparto`` presente in query string (anche vuoto) significa "ho deciso io":
    da quel momento lo scope automatico non si riapplica, altrimenti sarebbe
    impossibile guardare fuori dal proprio reparto.
    """
    if "reparto" in request.GET:
        return queryset, []
    reparti = user_reparti(request)
    if not reparti:
        return queryset, []
    scoped = queryset.filter(asset__reparto__in=reparti)
    if not scoped.exists():
        # Un filtro che azzera la pagina per un disallineamento di nomi (il reparto
        # sull'asset e' testo libero) e' peggio di nessun filtro.
        return queryset, []
    return scoped, reparti


def _manutenzioni_fuori_reparto(request: HttpRequest, occurrences) -> list:
    """Le manutenzioni selezionate che un caporeparto non puo' pianificare.

    Lo scope delle liste e' solo un filtro preimpostato (si toglie con un click):
    guardare fuori dal proprio reparto e' lecito, **scrivere** no. Chi guida uno o
    piu' reparti e non e' responsabile dei piani pianifica solo gli asset di quei
    reparti; senza questo controllo bastava togliere il filtro, o costruire il POST,
    per creare un ordine di lavoro su un asset altrui.

    Nessun vincolo per chi configura i piani e per chi pianifica senza guidare
    alcun reparto (es. l'ufficio manutenzione): il loro perimetro e' l'azienda.
    Il reparto sull'asset e' testo libero: confronto senza maiuscole e spazi.
    """
    if can_manage_maintenance_plans(request):
        return []
    reparti = {r.strip().casefold() for r in user_reparti(request)}
    if not reparti:
        return []
    return [
        occ for occ in occurrences
        if str(getattr(occ.asset, "reparto", "") or "").strip().casefold() not in reparti
    ]


def _nega_fuori_reparto(request: HttpRequest, occurrences) -> None:
    fuori = _manutenzioni_fuori_reparto(request, occurrences)
    if fuori:
        elenco = ", ".join(sorted({occ.asset.asset_tag for occ in fuori})[:10])
        raise PermissionDenied(
            "Puoi pianificare solo le manutenzioni degli asset dei reparti che guidi. "
            f"Fuori dal tuo reparto: {elenco}."
        )


def _apply_occurrence_filters(queryset, form: OccurrenceFilterForm, *, today: date):
    """Filtri della specifica §26, applicati in SQL dove possibile."""
    if not form.is_valid():
        return queryset
    data = form.cleaned_data

    if data.get("q"):
        term = data["q"].strip()
        queryset = queryset.filter(
            Q(plan__label__icontains=term)
            | Q(asset__asset_tag__icontains=term)
            | Q(asset__name__icontains=term)
            | Q(asset__internal_number__icontains=term)
        )
    if data.get("plan"):
        queryset = queryset.filter(plan=data["plan"])
    if data.get("group"):
        queryset = queryset.filter(asset__group_memberships__group=data["group"])
    if data.get("asset"):
        queryset = queryset.filter(asset=data["asset"])
    if data.get("reparto"):
        queryset = queryset.filter(asset__reparto=data["reparto"])
    if data.get("category"):
        try:
            category_id = int(data["category"])
        except (TypeError, ValueError):
            category_id = None
        if category_id:
            queryset = queryset.filter(asset__asset_category_id__in=category_with_descendants(category_id))
    if data.get("assignee"):
        queryset = queryset.filter(work_order__assigned_to=data["assignee"])
    if data.get("supplier"):
        queryset = queryset.filter(supplier=data["supplier"])

    plan_type = data.get("plan_type")
    if plan_type == "administrative":
        queryset = queryset.filter(plan__maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE)
    elif plan_type == "ordinary":
        queryset = queryset.exclude(plan__maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE)

    mode = data.get("execution_mode")
    if mode:
        # La modalita' effettiva puo' venire dall'applicazione o dal piano: si
        # filtra su entrambe, con l'applicazione che vince quando valorizzata.
        queryset = queryset.filter(
            Q(assignment__execution_mode=mode)
            | (Q(assignment__execution_mode="") & Q(plan__execution_mode=mode))
            | (Q(assignment__isnull=True) & Q(plan__execution_mode=mode))
        )

    planning = data.get("planning")
    if planning == "unplanned":
        queryset = queryset.filter(work_order__isnull=True, status=MaintenanceOccurrence.STATUS_OPEN)
    elif planning == "planned":
        queryset = queryset.filter(work_order__isnull=False)

    window = data.get("window")
    # Le finestre temporali sono viste OPERATIVE: dicono cosa resta da gestire, non
    # cosa e' successo. Prima "30 giorni" era il solo ``due_date <= oggi+30``, senza
    # limite inferiore ne' filtro di stato: significava "tutto lo scibile fino a fra
    # 30 giorni", quindi anche manutenzioni concluse nel 2021. Lo storico sta in
    # "Storico"; qui le concluse entrano solo se richieste esplicitamente.
    include_done = bool(data.get("include_done"))
    if window == "overdue":
        queryset = queryset.filter(status=MaintenanceOccurrence.STATUS_OPEN, due_date__lt=today)
    elif window:
        queryset = queryset.filter(
            due_date__gte=today,
            due_date__lte=today + timedelta(days=int(window)),
        )
        if not include_done:
            queryset = queryset.filter(status=MaintenanceOccurrence.STATUS_OPEN)
    elif not include_done:
        # "Tutte future": comunque solo cio' che resta da gestire.
        queryset = queryset.filter(status=MaintenanceOccurrence.STATUS_OPEN)

    return queryset.distinct()


def _decorate(occurrences: list[MaintenanceOccurrence], *, today: date) -> list[dict[str, Any]]:
    """Aggiunge lo stato visuale derivato senza toccare il DB."""
    rows = []
    for occurrence in occurrences:
        payload = domain.occurrence_state_payload(occurrence, today=today)
        days = payload.get("days_until_due")
        # Il ritardo si calcola qui: il template non deve fare aritmetica.
        payload["days_late"] = -days if days is not None and days < 0 else 0
        rows.append({"occurrence": occurrence, **payload})
    rows.sort(key=lambda row: (row["order"], row["occurrence"].due_date, row["occurrence"].id))
    return rows


def _report_missing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["state"] == MaintenanceOccurrence.VIEW_REPORT_MISSING]


def _group_rows(rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Stessa base dati, tre letture: per piano, per famiglia, per asset."""
    buckets: dict[Any, dict[str, Any]] = {}
    for row in rows:
        occurrence = row["occurrence"]
        if mode == "family":
            category = occurrence.asset.asset_category if occurrence.asset.asset_category_id else None
            key = getattr(category, "id", 0)
            label = getattr(category, "label", "") or "Senza famiglia"
            sub = ""
        elif mode == "day":
            key = occurrence.due_date
            label = occurrence.due_date.strftime("%d/%m/%Y")
            sub = ("Lunedi", "Martedi", "Mercoledi", "Giovedi", "Venerdi", "Sabato", "Domenica")[occurrence.due_date.weekday()]
        elif mode == "assignee":
            wo = occurrence.work_order if occurrence.work_order_id else None
            user = getattr(wo, "assigned_to", None)
            key = getattr(user, "id", 0)
            label = (user.get_full_name() or user.get_username()) if user else "Non assegnate"
            sub = ""
        elif mode == "asset":
            key = occurrence.asset_id
            label = occurrence.asset.asset_tag or occurrence.asset.name
            sub = occurrence.asset.name
        elif mode == "group":
            group = occurrence.assignment.asset_group if occurrence.assignment_id else None
            key = getattr(group, "id", 0)
            label = getattr(group, "label", "") or (occurrence.asset.asset_category.label if occurrence.asset.asset_category_id else "Senza famiglia")
            sub = ""
        else:
            key = occurrence.plan_id
            label = occurrence.plan.label
            sub = occurrence.plan.get_maintenance_type_display()
        bucket = buckets.setdefault(key, {"label": label, "sub": sub, "rows": [], "overdue": 0})
        bucket["rows"].append(row)
        if row["state"] == MaintenanceOccurrence.VIEW_OVERDUE:
            bucket["overdue"] += 1
    groups = list(buckets.values())
    if mode == "day":
        # Per giorno conta la sequenza del calendario, non chi ha piu' scadute.
        groups.sort(key=lambda item: item["rows"][0]["occurrence"].due_date)
    else:
        groups.sort(key=lambda item: (-item["overdue"], -len(item["rows"]), item["label"]))
    return groups


# Raggruppamenti offerti in tutte le tabelle delle manutenzioni.
_GROUP_MODES = [
    ("plan", "Piano"),
    ("family", "Famiglia"),
    ("group", "Gruppo asset"),
    ("asset", "Asset"),
    ("day", "Giorno"),
    ("assignee", "Assegnatario"),
]


def _group_mode_links(request: HttpRequest, active: str, *, with_none: bool) -> list[dict[str, Any]]:
    options = ([("", "Nessuno")] if with_none else []) + [
        (key, label) for key, label in _GROUP_MODES
        if key != "group" or AssetGroup.objects.filter(is_active=True).exists()
    ]
    return _tab_links(request, "by", options, active)


# ---------------------------------------------------------------------------
# Pagina "Da fare" — la giornata del manutentore
# ---------------------------------------------------------------------------

@login_required
def maintenance_da_fare(request: HttpRequest) -> HttpResponse:
    """Cosa devo fare, su quali macchine, entro quando.

    Non e' una dashboard di KPI: e' la lista del lavoro, ordinata per urgenza, da
    cui si aprono gli ordini di lavoro.
    """
    today = timezone.localdate()
    form = OccurrenceFilterForm(request.GET or None)
    form.is_valid()

    queryset = _apply_occurrence_filters(
        _base_occurrence_queryset().filter(status=MaintenanceOccurrence.STATUS_OPEN),
        form,
        today=today,
    )
    queryset, scoped_reparti = _apply_caporeparto_scope(queryset, request)

    # "Il mio lavoro": cio' che e' mio piu' cio' che non e' di nessuno (senza OdL o
    # con un OdL senza assegnatario) — la stessa coda di "I miei interventi". E' il
    # default per chi esegue senza pianificare: il manutentore apre la pagina e
    # vede la sua giornata, non l'officina intera. Un click la allarga.
    can_plan = can_plan_maintenance(request)
    can_execute = can_execute_maintenance(request)
    mine_param = _clean_string(request.GET.get("mio"))
    only_mine = mine_param == "1" if mine_param in {"0", "1"} else (can_execute and not can_plan)
    if only_mine:
        queryset = queryset.filter(
            Q(work_order__isnull=True)
            | Q(work_order__assigned_to__isnull=True)
            | Q(work_order__assigned_to=request.user)
        )
    rows = _decorate(list(queryset[:1000]), today=today)

    week_end = today + timedelta(days=7)
    blocks = [
        {
            "key": "overdue",
            "title": "Scadute",
            "tone": "urgent",
            "quiet": "Nessuna manutenzione scaduta",
            "rows": [r for r in rows if r["state"] == MaintenanceOccurrence.VIEW_OVERDUE],
        },
        {
            "key": "week",
            "title": "Da fare entro 7 giorni",
            "tone": "warn",
            "quiet": "Niente in scadenza questa settimana",
            "rows": [
                r
                for r in rows
                if r["state"] in (MaintenanceOccurrence.VIEW_DUE_SOON, MaintenanceOccurrence.VIEW_TO_PLAN)
                and r["occurrence"].due_date <= week_end
            ],
        },
        {
            "key": "planned",
            "title": "Programmate",
            "tone": "",
            "quiet": "Nessuna manutenzione gia' programmata",
            "rows": [
                r
                for r in rows
                if r["state"] in (MaintenanceOccurrence.VIEW_PLANNED, MaintenanceOccurrence.VIEW_IN_PROGRESS)
            ],
        },
        {
            "key": "waiting",
            "title": "In attesa",
            "tone": "",
            "quiet": "Nessun intervento bloccato",
            "rows": [r for r in rows if r["state"] == MaintenanceOccurrence.VIEW_WAITING],
        },
        {
            "key": "external",
            "title": "Esterne",
            "tone": "",
            "quiet": "Nessuna manutenzione affidata a fornitori",
            "rows": [r for r in rows if r["occurrence"].is_external],
        },
    ]

    # Il parametro si chiama "by" e non "group": "group" e' gia' il filtro per gruppo.
    view_mode = _clean_string(request.GET.get("by")) or "plan"
    if view_mode not in {key for key, _label in _GROUP_MODES}:
        view_mode = "plan"

    # I quattro numeri rispondono alla domanda della pagina — "cosa devo fare
    # adesso?" — e non alla salute del modulo, che e' il mestiere del Cruscotto.
    # Contati sulle righe gia' in memoria: nessuna query in piu'.
    user_id = getattr(request.user, "id", None)
    summary = {
        "overdue": sum(1 for r in rows if r["state"] == MaintenanceOccurrence.VIEW_OVERDUE),
        "today": sum(1 for r in rows if r["occurrence"].due_date == today),
        "week": sum(
            1 for r in rows
            if today < r["occurrence"].due_date <= today + timedelta(days=7)
        ),
        "mine": sum(
            1 for r in rows
            if r["occurrence"].work_order_id
            and r["occurrence"].work_order.assigned_to_id == user_id
        ),
    }

    # Gli ordini di lavoro che riguardano chi guarda la pagina. Le occorrenze qui
    # sopra dicono *cosa* e' dovuto; questo blocco dice *cosa e' gia' in mano a
    # qualcuno* — l'unica cosa che "Il mio turno" mostrava e questa pagina no.
    # Coda condivisa: i miei piu' quelli di nessuno, mai quelli di un altro.
    # Solo cio' che chiede attenzione adesso (bloccato, urgente, iniziato): il
    # resto della coda e' gia' rappresentato dalle occorrenze.
    my_workorders = list(
        WorkOrder.objects.select_related("asset", "assigned_to")
        .filter(status=WorkOrder.STATUS_OPEN)
        .filter(Q(assigned_to=request.user) | Q(assigned_to__isnull=True))
        .filter(
            Q(is_waiting=True)
            | Q(started_at__isnull=False)
            | Q(priority=WorkOrder.PRIORITY_URGENT)
        )
        # ``priority`` e' un CharField: ordinarlo alfabeticamente darebbe il
        # risultato giusto per caso, non per costruzione.
        .annotate(
            _urgenza=Case(
                When(priority=WorkOrder.PRIORITY_URGENT, then=Value(0)),
                When(priority=WorkOrder.PRIORITY_NORMAL, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("_urgenza", "started_at", "opened_at", "id")[:40]
    )
    my_workorder_rows = [
        {
            "wo": wo,
            "tone": (
                "grey" if wo.is_waiting
                else "red" if wo.priority == WorkOrder.PRIORITY_URGENT
                else "blue"
            ),
        }
        for wo in my_workorders
    ]

    return render(
        request,
        "assets/pages/maintenance_da_fare.html",
        {
            **_assets_shell_context(request),
            "page_title": "Da fare",
            "today": today,
            "my_workorder_rows": my_workorder_rows,
            "filter_form": form,
            "blocks": blocks,
            "groups": _group_rows(rows, view_mode),
            "view_mode": view_mode,
            "group_links": _group_mode_links(request, view_mode, with_none=False),
            "group_label": dict(_GROUP_MODES).get(view_mode, "").lower(),
            "summary": summary,
            "total": len(rows),
            "can_plan": can_plan,
            "can_execute": can_execute,
            "only_mine": only_mine,
            "mine_tabs": _tab_links(request, "mio", [("1", "Il mio lavoro"), ("0", "Tutto")], "1" if only_mine else "0"),
            "workorder_form": WorkOrderFromOccurrencesForm(),
            "scoped_reparti": scoped_reparti,
        },
    )


# ---------------------------------------------------------------------------
# Pagina "Scadenze" — vista temporale completa
# ---------------------------------------------------------------------------

_SCADENZE_TABS = [
    ("overdue", "Scadute"),
    ("7", "7 giorni"),
    ("30", "30 giorni"),
    ("90", "90 giorni"),
    ("", "Tutte"),
]

_SCADENZE_TYPE_TABS = [
    ("", "Tutte le tipologie"),
    ("ordinary", "Ordinarie"),
    ("administrative", "Amministrative"),
    ("renewals", "Licenze e contratti"),
]


def _tab_links(request: HttpRequest, param: str, options, active: str) -> list[dict[str, Any]]:
    """Link di scheda che cambiano UN solo parametro e conservano gli altri filtri.

    Prima la scheda "Amministrative" azzerava la finestra temporale e ogni scheda
    buttava via ricerca, reparto e assegnatario: cambiare vista voleva dire
    rifare i filtri.
    """
    links = []
    for value, label in options:
        query = request.GET.copy()
        query[param] = value
        links.append({"label": label, "url": f"?{query.urlencode()}", "active": active == value})
    return links


def _renewal_rows(request: HttpRequest, form: OccurrenceFilterForm, *, today: date, scoped_reparti,
                  plan_type: str = "") -> list:
    """Scadenze che non sono occorrenze, dallo stesso servizio del Calendario:
    licenze, contratti e le vecchie scadenze amministrative non ancora migrate.

    Stessa finestra temporale delle occorrenze (le scadute restano finche' sono
    attive), stessi filtri famiglia/reparto/gruppo e ricerca. Licenze e contratti
    solo a chi puo' aprire le loro pagine.
    """
    from .services import deadline_feed as feed

    data = form.cleaned_data if form.is_valid() else {}
    wanted = {
        "": {feed.KIND_LICENSE, feed.KIND_CONTRACT, feed.KIND_ADMINISTRATIVE},
        "renewals": {feed.KIND_LICENSE, feed.KIND_CONTRACT},
        "administrative": {feed.KIND_ADMINISTRATIVE},
    }.get(plan_type, set())
    kinds = feed.allowed_kinds(request) & wanted
    if not kinds or data.get("execution_mode") or data.get("plan") or data.get("supplier"):
        # Filtri che su licenze e contratti non hanno senso: meglio nessuna riga
        # che righe che sembrano rispettarli.
        return []
    window = data.get("window") or ""
    start = end = None
    if window == "overdue":
        end = today - timedelta(days=1)
    elif window:
        start, end = today, today + timedelta(days=int(window))
    category_id = int(data["category"]) if data.get("category") else 0
    filters = feed.FeedFilters(
        kinds=frozenset(kinds),
        category_ids=frozenset(category_with_descendants(category_id)) if category_id else None,
        reparto=data.get("reparto") or "",
        group_id=data["group"].id if data.get("group") else None,
        asset_id=data["asset"].id if data.get("asset") else None,
    )
    # Le occorrenze hanno la loro tabella sopra: qui solo cio' che non lo e'.
    rows = [row for row in feed.collect(start=start, end=end, filters=filters, today=today)
            if not row.key.startswith("occ-")]
    term = (data.get("q") or "").strip().lower()
    if term:
        rows = [r for r in rows if term in f"{r.title} {r.asset_tag} {r.asset_name} {r.supplier}".lower()]
    if scoped_reparti and not data.get("reparto"):
        rows = [r for r in rows if r.reparto in scoped_reparti]
    for row in rows:
        # Il template non fa aritmetica: giorni al netto e ritardo gia' positivo.
        row.days = row.days_until(today)
        row.days_late = -row.days if row.days < 0 else 0
    return rows


def _scadenzario_export(request: HttpRequest, *, rows, renewals, fmt: str, today: date) -> HttpResponse:
    """Scadenzario in Excel o PDF: le righe che la pagina mostra, con gli stessi filtri.

    Occorrenze e poi licenze, contratti e vecchie scadenze, in un'unica tabella
    ordinata per data. I valori passano da ``write_cell`` (niente formula injection).
    """
    from core.excel_export import build_xlsx_bytes
    from core.table_pdf import render_table_pdf

    headers = ["Scadenza", "Tipologia", "Cosa", "Asset", "Descrizione asset", "Categoria", "Reparto", "Stato", "OdL / fornitore"]
    table = []
    admin_type = MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE
    for row in rows:
        occ = row["occurrence"]
        asset = occ.asset
        table.append([
            occ.due_date,
            "Amministrativa" if occ.plan.maintenance_type == admin_type else "Ordinaria",
            occ.plan.label,
            asset.asset_tag or "",
            asset.name or "",
            asset.asset_category.label if asset.asset_category_id else "",
            asset.reparto or "",
            row.get("operational_label") or row.get("label") or "",
            f"OdL #{occ.work_order_id}" if occ.work_order_id else (str(occ.supplier) if occ.supplier_id else ""),
        ])
    for item in renewals:
        table.append([
            item.due_date, item.kind_label, item.title, item.asset_tag, item.asset_name or item.target_label,
            item.category_label, item.reparto, item.state_label, item.supplier,
        ])
    table.sort(key=lambda values: values[0])
    stamp = today.strftime("%Y%m%d")
    filtri = request.GET.copy()
    filtri.pop("format", None)
    filters_label = "Filtri: " + (", ".join(f"{k}={v}" for k, v in filtri.items() if v) or "nessuno")

    if fmt == "pdf":
        body = render_table_pdf(
            title="Scadenzario manutenzione",
            subtitle=filters_label,
            headers=headers,
            rows=[[value.strftime("%d/%m/%Y") if isinstance(value, date) else value for value in values] for values in table],
        )
        response = HttpResponse(body, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="scadenzario_manutenzione_{stamp}.pdf"'
        return response

    body = build_xlsx_bytes(
        columns=headers,
        rows=table,
        sheet_title="Scadenzario",
        title="Scadenzario manutenzione",
        subtitle=f"Estratto il {today:%d/%m/%Y}",
        filters_label=filters_label,
    )
    response = HttpResponse(
        body, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="scadenzario_manutenzione_{stamp}.xlsx"'
    return response


@login_required
def maintenance_scadenze(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    initial = request.GET.copy()
    if "window" not in initial:
        initial["window"] = "30"
    form = OccurrenceFilterForm(initial)
    # Finestra e tipologia sono schede in testa alla pagina, non campi del pannello.
    form.tab_fields = ("window", "plan_type")
    # Solo qui la tipologia comprende anche licenze e contratti: non sono
    # occorrenze e in "Da fare" non c'e' niente da eseguire su di loro.
    form.fields["plan_type"].choices = list(form.fields["plan_type"].choices) + [("renewals", "Licenze e contratti")]
    form.is_valid()
    plan_type = form.cleaned_data.get("plan_type", "") if form.is_valid() else ""

    queryset = _apply_occurrence_filters(_base_occurrence_queryset(), form, today=today)
    queryset, scoped_reparti = _apply_caporeparto_scope(queryset, request)
    if plan_type == "renewals":
        rows = []
    else:
        rows = _decorate(list(queryset[:2000]), today=today)
        if form.cleaned_data.get("report_missing"):
            rows = _report_missing_rows(rows)
    renewals = (
        _renewal_rows(request, form, today=today, scoped_reparti=scoped_reparti, plan_type=plan_type)
        if plan_type in ("", "renewals", "administrative") and not form.cleaned_data.get("report_missing")
        else []
    )

    active_tab = _clean_string(initial.get("window"))
    group_mode = _clean_string(request.GET.get("by"))
    if group_mode not in {key for key, _label in _GROUP_MODES}:
        group_mode = ""
    export_format = _clean_string(request.GET.get("format")).lower()
    if export_format in {"xlsx", "pdf"}:
        return _scadenzario_export(request, rows=rows, renewals=renewals, fmt=export_format, today=today)
    export_query = request.GET.copy()
    export_query.pop("format", None)
    return render(
        request,
        "assets/pages/maintenance_scadenze.html",
        {
            **_assets_shell_context(request),
            "page_title": "Scadenzario",
            "today": today,
            "filter_form": form,
            "rows": rows,
            "total": len(rows) + len(renewals),
            "renewals": renewals,
            "export_query": export_query.urlencode(),
            "group_mode": group_mode,
            "groups": _group_rows(rows, group_mode) if group_mode else [],
            "group_links": _group_mode_links(request, group_mode, with_none=True),
            "show_occurrences": plan_type != "renewals",
            "show_renewals": plan_type in ("", "renewals", "administrative"),
            "window_tabs": _tab_links(request, "window", _SCADENZE_TABS, active_tab),
            "type_tabs": _tab_links(
                request, "plan_type", _SCADENZE_TYPE_TABS, _clean_string(initial.get("plan_type"))
            ),
            "can_plan": can_plan_maintenance(request),
            "workorder_form": WorkOrderFromOccurrencesForm(),
            "scoped_reparti": scoped_reparti,
        },
    )


# ---------------------------------------------------------------------------
# Dashboard responsabile
# ---------------------------------------------------------------------------

def _sintesi_direzione(*, today: date, open_rows: list[dict[str, Any]], done_rows: list[dict[str, Any]],
                       report_missing: int, resolutions: dict) -> dict[str, Any]:
    """Indicatori di andamento per la direzione, costruiti SOLO su campi che
    risultano compilati.

    Costi, fermo macchina e durata degli interventi sono facoltativi in chiusura e
    quasi mai compilati (default ``0``, non ``NULL``): niente MTTR, niente MTBF,
    nessun grafico di spesa. Al loro posto la pagina misura quanto quei campi sono
    coperti e lo dichiara — un grafico piatto a zero sarebbe peggio di un grafico
    assente, perche' sembrerebbe un risultato.
    """
    anno_fa = today - timedelta(days=365)

    # La puntualita' si misura solo dove scadenza ed esecuzione sono due eventi
    # DISTINTI. Nelle occorrenze migrate dal vecchio motore (e in quelle importate
    # dallo storico) la scadenza e' stata dedotta dalla data di esecuzione: sono
    # puntuali per costruzione, e in sviluppo bastavano a produrre un "100% nei
    # tempi" su 164 righe che non misurava nulla. Restano contate, ma a parte.
    concluse_qs = MaintenanceOccurrence.objects.filter(
        status=MaintenanceOccurrence.STATUS_DONE, completed_on__gte=anno_fa
    )
    misurabili_qs = concluse_qs.filter(
        source__in=[MaintenanceOccurrence.SOURCE_SCHEDULER, MaintenanceOccurrence.SOURCE_MANUAL]
    )

    # Una sola aggregazione, confronto fra due colonne della stessa riga.
    # ``order_by()`` esplicito: Meta.ordering con values()+annotate() su SQL Server
    # produce l'errore 8127.
    puntualita = misurabili_qs.aggregate(
        concluse=Count("id"),
        nei_tempi=Count("id", filter=Q(completed_on__lte=F("due_date"))),
    )
    concluse = puntualita["concluse"] or 0
    nei_tempi = puntualita["nei_tempi"] or 0
    concluse_totali = concluse_qs.count()
    # Sotto una decina di righe una percentuale e' aneddotica: si dichiara la base
    # invece di stampare un numero che sembrerebbe una statistica.
    BASE_MINIMA = 10
    puntualita_misurabile = concluse >= BASE_MINIMA

    # Andamento a 12 mesi: stessa base della puntualita', per lo stesso motivo.
    mesi_rows = list(
        misurabili_qs.annotate(mese=TruncMonth("completed_on"))
        .values("mese")
        .annotate(
            concluse=Count("id"),
            nei_tempi=Count("id", filter=Q(completed_on__lte=F("due_date"))),
        )
        .order_by("mese")
    )
    picco = max([row["concluse"] for row in mesi_rows] or [0])
    andamento = [
        {
            "mese": row["mese"],
            "concluse": row["concluse"],
            "nei_tempi": row["nei_tempi"],
            "tardive": row["concluse"] - row["nei_tempi"],
            # Altezza in percentuale: il grafico e' fatto di due div, non serve una libreria.
            "h_nei_tempi": round(100 * row["nei_tempi"] / picco) if picco else 0,
            "h_tardive": round(100 * (row["concluse"] - row["nei_tempi"]) / picco) if picco else 0,
        }
        for row in mesi_rows
    ]

    # Arretrato: non "quante" scadute, ma "da quanto". Una scaduta di ieri e una di
    # due anni fa non sono lo stesso problema.
    scadute = [r for r in open_rows if r["state"] == MaintenanceOccurrence.VIEW_OVERDUE]
    piu_vecchia = min((r["occurrence"].due_date for r in scadute), default=None)

    # Copertura della pianificazione: asset in uso che hanno almeno un piano applicato.
    asset_con_piano = {
        asset_id for (_plan_id, asset_id), resolution in resolutions.items() if resolution.is_applied
    }
    asset_in_uso = Asset.objects.filter(status=Asset.STATUS_IN_USE).count()

    # Copertura dei campi facoltativi sugli interventi chiusi nell'anno.
    chiusi = WorkOrder.objects.filter(status=WorkOrder.STATUS_DONE, closed_at__date__gte=anno_fa).aggregate(
        totale=Count("id"),
        con_durata=Count("id", filter=Q(intervention_duration_minutes__gt=0)),
        con_fermo=Count("id", filter=Q(downtime_minutes__gt=0)),
        con_costo=Count(
            "id",
            filter=Q(cost_eur__gt=0) | Q(labor_cost_eur__gt=0) | Q(materials_cost_eur__gt=0),
        ),
    )
    totale_chiusi = chiusi["totale"] or 0

    # Prossime scadenze amministrative: revisioni, verifiche di legge, contratti.
    # Sono le uniche che la direzione guarda per data e non per carico di lavoro.
    # Nessun campo nuovo: sono occorrenze aperte di piani amministrativi.
    amministrative_qs = MaintenanceOccurrence.objects.filter(
        status=MaintenanceOccurrence.STATUS_OPEN,
        plan__maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
    )
    prossime_amministrative = list(
        amministrative_qs.filter(due_date__gte=today)
        .select_related("plan", "asset", "supplier")
        .order_by("due_date", "id")[:5]
    )
    # Un adempimento gia' scaduto non e' una "prossima scadenza" e non va mescolato
    # alle altre, ma nemmeno taciuto: se ce ne sono, la sezione lo dichiara in una
    # riga sola invece di mostrare un calendario che sembra a posto.
    amministrative_scadute = amministrative_qs.filter(due_date__lt=today).count()

    return {
        "prossime_amministrative": prossime_amministrative,
        "amministrative_scadute": amministrative_scadute,
        "concluse_12m": concluse,
        "concluse_totali_12m": concluse_totali,
        "concluse_non_misurabili_12m": concluse_totali - concluse,
        "puntualita_misurabile": puntualita_misurabile,
        "nei_tempi_12m": nei_tempi,
        "puntualita_pct": round(100 * nei_tempi / concluse) if puntualita_misurabile else None,
        "andamento": andamento,
        "scadute": len(scadute),
        "arretrato_da": piu_vecchia,
        "arretrato_giorni": (today - piu_vecchia).days if piu_vecchia else None,
        "documentale_base": len(done_rows),
        "documentale_mancanti": report_missing,
        "documentale_pct": (
            round(100 * (len(done_rows) - report_missing) / len(done_rows)) if done_rows else None
        ),
        "asset_con_piano": len(asset_con_piano),
        "asset_in_uso": asset_in_uso,
        "asset_pct": round(100 * len(asset_con_piano) / asset_in_uso) if asset_in_uso else None,
        "non_misurabili": [
            {
                "label": "Durata degli interventi",
                "perche": "compilata a mano in chiusura",
                "coverage": _copertura_dato(chiusi["con_durata"] or 0, totale_chiusi),
            },
            {
                "label": "Fermo macchina",
                "perche": "senza questo dato non esiste disponibilita impianti",
                "coverage": _copertura_dato(chiusi["con_fermo"] or 0, totale_chiusi),
            },
            {
                "label": "Costi di manutenzione",
                "perche": "manodopera e materiali non vengono valorizzati",
                "coverage": _copertura_dato(chiusi["con_costo"] or 0, totale_chiusi),
            },
        ],
        "non_misurabili_base": totale_chiusi,
    }


def _panoramica(request: HttpRequest, *, today: date) -> dict[str, Any]:
    """Il colpo d'occhio della Panoramica, sullo stesso servizio di Calendario e
    Scadenzario (``deadline_feed``): per tipologia, prossime quattro settimane,
    prossime scadenze e ripartizione per categoria asset.

    Filtri facoltativi ``category`` (famiglia, con sottocategorie) e ``reparto``:
    restano nell'URL e i link verso Scadenzario e Calendario li portano con se'.
    """
    from urllib.parse import urlencode

    from .forms_maintenance import category_filter_choices
    from .services import deadline_feed as feed

    category_id = 0
    try:
        category_id = int(request.GET.get("category") or 0)
    except (TypeError, ValueError):
        category_id = 0
    reparto = _clean_string(request.GET.get("reparto"))
    kinds = feed.allowed_kinds(request)
    horizon = today + timedelta(days=30)
    week_start = today - timedelta(days=today.weekday())
    heat_end = week_start + timedelta(days=27)
    rows = feed.collect(
        start=None,
        end=max(horizon, heat_end),
        filters=feed.FeedFilters(
            kinds=kinds,
            category_ids=frozenset(category_with_descendants(category_id)) if category_id else None,
            reparto=reparto,
        ),
        today=today,
    )
    open_rows = [row for row in rows if row.state != feed.STATE_DONE]

    shared = {key: value for key, value in (("category", category_id or ""), ("reparto", reparto)) if value}
    scadenzario_url = reverse("assets:maintenance_scadenze")
    calendario_url = reverse("assets:calendario_asset")
    plan_type_for = {feed.KIND_ORDINARY: "ordinary", feed.KIND_ADMINISTRATIVE: "administrative",
                     feed.KIND_LICENSE: "renewals", feed.KIND_CONTRACT: "renewals"}

    types = []
    for kind, label in feed.KIND_LABELS.items():
        if kind not in kinds:
            continue
        of_kind = [row for row in open_rows if row.kind == kind]
        upcoming = [row for row in of_kind if row.due_date >= today]
        types.append({
            "kind": kind,
            "label": {
                feed.KIND_ORDINARY: "Manutenzione ordinaria",
                feed.KIND_ADMINISTRATIVE: "Scadenze amministrative",
                feed.KIND_LICENSE: "Licenze software",
                feed.KIND_CONTRACT: "Contratti di assistenza",
            }[kind],
            "overdue": sum(1 for row in of_kind if row.state == feed.STATE_OVERDUE),
            "due_30": sum(1 for row in upcoming if row.due_date <= horizon),
            "next": upcoming[0] if upcoming else None,
            "url": f"{scadenzario_url}?{urlencode({**shared, 'window': '', 'plan_type': plan_type_for[kind]})}",
            "calendar_url": f"{calendario_url}?{urlencode({**shared, 'kinds': kind})}",
        })

    # Quattro settimane da lunedi': quante scadenze aperte per giorno.
    per_day: dict[date, int] = {}
    for row in open_rows:
        if week_start <= row.due_date <= heat_end:
            per_day[row.due_date] = per_day.get(row.due_date, 0) + 1
    peak = max(per_day.values(), default=0)
    heat = []
    for offset in range(28):
        day = week_start + timedelta(days=offset)
        count = per_day.get(day, 0)
        # Livelli 0-4: il colore dice "quanto", il numero resta nel titolo.
        level = 0 if not count else min(4, 1 + (3 * count) // max(peak, 1))
        heat.append({"day": day, "count": count, "level": level, "is_today": day == today, "past": day < today})

    overdue = [row for row in open_rows if row.state == feed.STATE_OVERDUE]
    upcoming = [row for row in open_rows if row.due_date >= today]
    # Le scadute per prime, ma senza soffocare le prossime.
    prossime = overdue[:4] + upcoming[: 10 - min(len(overdue), 4)]
    for row in prossime:
        row.days = row.days_until(today)
        row.days_late = -row.days if row.days < 0 else 0

    per_category: dict[str, int] = {}
    for row in open_rows:
        if row.due_date <= horizon:
            per_category[row.category_label or "Senza categoria"] = per_category.get(row.category_label or "Senza categoria", 0) + 1
    category_peak = max(per_category.values(), default=0)
    categories = [
        {"label": label, "count": count, "pct": round(100 * count / category_peak) if category_peak else 0}
        for label, count in sorted(per_category.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]

    return {
        "types": types,
        "heat": heat,
        "prossime": prossime,
        "categories": categories,
        "category_choices": category_filter_choices(),
        "category_id": str(category_id or ""),
        "reparto": reparto,
        "reparti": list(
            Asset.objects.exclude(reparto="").values_list("reparto", flat=True).order_by("reparto").distinct()
        ),
        "scadenzario_url": f"{scadenzario_url}?{urlencode({**shared, 'window': ''})}",
        "calendario_url": f"{calendario_url}?{urlencode(shared)}" if shared else calendario_url,
        "filtered": bool(shared),
    }


def _conformita(request: HttpRequest, *, today: date) -> dict[str, Any]:
    """Indicatori di conformita' per la pagina KPI: adempimenti amministrativi in
    regola e rinnovi di licenze e contratti. Stessa fonte della Panoramica."""
    from .services import deadline_feed as feed

    dues = feed.administrative_dues()
    scaduti = sum(1 for due in dues if due.due_date < today)
    kinds = feed.allowed_kinds(request) & {feed.KIND_LICENSE, feed.KIND_CONTRACT}
    rinnovi = feed.collect(
        start=None, end=today + timedelta(days=90), filters=feed.FeedFilters(kinds=frozenset(kinds)), today=today
    ) if kinds else []
    return {
        "adempimenti_aperti": len(dues),
        "adempimenti_scaduti": scaduti,
        "adempimenti_pct": round(100 * (len(dues) - scaduti) / len(dues)) if dues else None,
        "rinnovi_90": sum(1 for row in rinnovi if row.due_date >= today),
        "rinnovi_scaduti": sum(1 for row in rinnovi if row.due_date < today),
        "rinnovi_visibili": bool(kinds),
    }


@login_required
def maintenance_responsabile(request: HttpRequest) -> HttpResponse:
    """Panoramica: cosa e' scaduto, cosa sta per scadere, cosa NON e' ancora
    pianificato. La distinzione fra "dovuta" e "pianificata" e' il punto della pagina.

    La vecchia lettura "Sintesi" (``?vista=sintesi``) e' la pagina KPI: i link
    salvati ci arrivano con gli altri parametri intatti.
    """
    if _clean_string(request.GET.get("vista")).lower() == "sintesi":
        query = request.GET.copy()
        query.pop("vista", None)
        target = reverse("assets:maintenance_kpi")
        return redirect(f"{target}?{query.urlencode()}" if query else target)
    return _responsabile_response(request, kpi_page=False)


@login_required
def maintenance_kpi(request: HttpRequest) -> HttpResponse:
    """KPI: la lettura "come sta andando" (puntualita', arretrato, copertura,
    conformita'). Stesso calcolo della Sintesi, con una voce di menu propria."""
    return _responsabile_response(request, kpi_page=True)


def _responsabile_response(request: HttpRequest, *, kpi_page: bool) -> HttpResponse:
    today = timezone.localdate()
    open_rows = _decorate(
        list(_base_occurrence_queryset().filter(status=MaintenanceOccurrence.STATUS_OPEN)[:3000]),
        today=today,
    )
    done_rows = _decorate(
        list(
            _base_occurrence_queryset()
            .filter(status=MaintenanceOccurrence.STATUS_DONE, completed_on__gte=today - timedelta(days=120))
            .order_by("-completed_on")[:1000]
        ),
        today=today,
    )

    unplanned = [
        row
        for row in open_rows
        if row["occurrence"].work_order_id is None
        and row["state"] in (MaintenanceOccurrence.VIEW_OVERDUE, MaintenanceOccurrence.VIEW_DUE_SOON)
    ]
    report_missing = _report_missing_rows(done_rows)

    # "ODL attivi" sono TUTTI gli ordini aperti, correttivi compresi: il responsabile
    # deve vedere anche il guasto segnalato stamattina, non solo cio' che nasce da un
    # piano. Prima il KPI filtrava ``occurrences__isnull=False`` e mostrava 0 mentre
    # sotto comparivano quattro interventi da gestire: due popolazioni diverse con
    # etichette che sembravano una il sottoinsieme dell'altra.
    open_workorders = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN)
        .select_related("asset", "assigned_to")
        .annotate(occurrence_count=Count("occurrences"))
        .order_by("opened_at")
    )
    # Metrica secondaria, con un nome che dice cosa conta davvero.
    planned_workorders_count = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN, occurrences__isnull=False)
        .distinct()
        .count()
    )
    follow_ups = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN, follow_up_occurrence__isnull=False)
        .select_related("asset", "follow_up_occurrence", "follow_up_occurrence__plan")
        .order_by("-opened_at")[:50]
    )

    # OdL aperti da troppo tempo. NON si chiamano "in ritardo": ``WorkOrder.due_at``
    # esiste ma in pratica non viene valorizzato, quindi non c'e' una scadenza vera da
    # sforare — quello che si misura qui e' l'anzianita', ``opened_at`` oltre la soglia
    # condivisa di SiteConfig (assets_wo_overdue_days), la stessa del promemoria.
    # Presentare come ritardo cio' che e' soltanto vecchio e' una promessa che i dati
    # non mantengono. Sono un SOTTOINSIEME di open_workorders.
    from .maintenance import get_workorder_overdue_days

    wo_overdue_days = get_workorder_overdue_days()
    overdue_workorders = []
    for work_order in (
        WorkOrder.objects.filter(
            status=WorkOrder.STATUS_OPEN,
            opened_at__date__lte=today - timedelta(days=wo_overdue_days),
        )
        .select_related("asset", "assigned_to")
        .order_by("opened_at")[:40]
    ):
        # I giorni si contano qui: il template non deve fare aritmetica, e
        # "1 mese, 1 settimana" e' meno leggibile di "38 giorni" in una colonna.
        work_order.days_open = (today - timezone.localtime(work_order.opened_at).date()).days
        overdue_workorders.append(work_order)

    # --- Carico dei manutentori -------------------------------------------------
    # Una sola query aggregata, GROUP BY server-side: chi ha troppo lavoro e quanto
    # non e' di nessuno. ``order_by`` esplicito perche' Meta.ordering insieme a
    # values()+annotate() su SQL Server produce l'errore 8127.
    week_end = today + timedelta(days=7)
    carico_rows = list(
        MaintenanceOccurrence.objects.filter(status=MaintenanceOccurrence.STATUS_OPEN)
        .values(
            "work_order__assigned_to",
            "work_order__assigned_to__username",
            "work_order__assigned_to__first_name",
            "work_order__assigned_to__last_name",
        )
        .annotate(
            aperte=Count("id"),
            scadute=Count("id", filter=Q(due_date__lt=today)),
            settimana=Count("id", filter=Q(due_date__gte=today, due_date__lte=week_end)),
        )
        .order_by("-aperte")
    )
    carico = []
    non_assegnate = None
    for row in carico_rows:
        user_id = row["work_order__assigned_to"]
        if user_id is None:
            # Non assegnate: sia le occorrenze senza ordine di lavoro sia quelle in un
            # ordine che non ha ancora un assegnatario. Per il responsabile sono la
            # stessa domanda: "chi ci va?".
            non_assegnate = {
                "user_id": None,
                "label": "Non assegnate",
                "aperte": row["aperte"],
                "scadute": row["scadute"],
                "settimana": row["settimana"],
            }
            continue
        nome = " ".join(
            part for part in (row["work_order__assigned_to__first_name"],
                              row["work_order__assigned_to__last_name"]) if part
        ).strip()
        carico.append({
            "user_id": user_id,
            "label": nome or row["work_order__assigned_to__username"],
            "aperte": row["aperte"],
            "scadute": row["scadute"],
            "settimana": row["settimana"],
        })

    resolutions = domain.build_plan_resolutions(asset_queryset=Asset.objects.filter(status=Asset.STATUS_IN_USE))
    conflicts = [resolution for resolution in resolutions.values() if resolution.is_conflict]

    kpi = {
        "overdue": sum(1 for r in open_rows if r["state"] == MaintenanceOccurrence.VIEW_OVERDUE),
        "due_soon": sum(1 for r in open_rows if r["state"] == MaintenanceOccurrence.VIEW_DUE_SOON),
        "unplanned": len(unplanned),
        "workorders_open": open_workorders.count(),
        "workorders_running": sum(1 for wo in open_workorders if wo.started_at and not wo.is_waiting),
        "waiting": sum(1 for wo in open_workorders if wo.is_waiting),
        "workorders_overdue": len(overdue_workorders),
        "report_missing": len(report_missing),
        "follow_ups": follow_ups.count(),
        "conflicts": len(conflicts),
    }

    # Due letture della stessa pagina, non due pagine: l'operativo elenca cosa fare,
    # la sintesi dice come sta andando. Stesso URL, stesso conteggio, un parametro.
    # Due pagine, non uno switch: la Panoramica elenca cosa fare, KPI dice come sta andando.
    vista = "sintesi" if kpi_page else "operativo"
    sintesi = (
        _sintesi_direzione(
            today=today,
            open_rows=open_rows,
            done_rows=done_rows,
            report_missing=len(report_missing),
            resolutions=resolutions,
        )
        if vista == "sintesi"
        else None
    )

    return render(
        request,
        "assets/pages/maintenance_responsabile.html",
        {
            **_assets_shell_context(request),
            "page_title": "KPI manutenzione" if kpi_page else "Panoramica manutenzione",
            "kpi_page": kpi_page,
            "today": today,
            "vista": vista,
            "sintesi": sintesi,
            "panoramica": _panoramica(request, today=today) if vista == "operativo" else None,
            "conformita": _conformita(request, today=today) if vista == "sintesi" else None,
            "kpi": kpi,
            "unplanned": unplanned[:60],
            "report_missing": report_missing[:40],
            "open_workorders": list(open_workorders[:40]),
            "overdue_workorders": overdue_workorders,
            "wo_overdue_days": wo_overdue_days,
            "planned_workorders_count": planned_workorders_count,
            "carico": carico,
            "carico_non_assegnate": non_assegnate,
            "follow_ups": list(follow_ups),
            "conflicts": conflicts[:40],
            "can_plan": can_plan_maintenance(request),
            "workorder_form": WorkOrderFromOccurrencesForm(),
        },
    )


# ---------------------------------------------------------------------------
# Piani
# ---------------------------------------------------------------------------

@login_required
def maintenance_plan_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    plans = list(
        MaintenanceInterventionTemplate.objects.annotate(
            assignment_count=Count("assignments", filter=Q(assignments__is_active=True), distinct=True)
        )
        # Le periodicita' si leggono da plan.assignments dentro il ciclo: senza
        # prefetch e' una query per piano, e con qualche decina di piani la pagina
        # ne faceva oltre cento.
        .prefetch_related("assignments")
        .order_by("sort_order", "label")
    )
    plan_ids = [plan.id for plan in plans]

    resolutions = domain.build_plan_resolutions(
        asset_queryset=Asset.objects.filter(status=Asset.STATUS_IN_USE), plan_ids=plan_ids
    )
    coverage: dict[int, dict[str, int]] = defaultdict(lambda: {"assets": 0, "conflicts": 0, "excluded": 0})
    for (plan_id, _asset_id), resolution in resolutions.items():
        bucket = coverage[plan_id]
        if resolution.is_applied:
            bucket["assets"] += 1
        elif resolution.is_conflict:
            bucket["conflicts"] += 1
        else:
            bucket["excluded"] += 1

    stats: dict[int, dict[str, Any]] = defaultdict(lambda: {"next_due": None, "overdue": 0})
    for plan_id, due_date in (
        MaintenanceOccurrence.objects.filter(plan_id__in=plan_ids, status=MaintenanceOccurrence.STATUS_OPEN)
        .values_list("plan_id", "due_date")
        .order_by("due_date")
    ):
        bucket = stats[plan_id]
        if bucket["next_due"] is None:
            bucket["next_due"] = due_date
        if due_date < today:
            bucket["overdue"] += 1

    # Ultima esecuzione per piano: una query aggregata sola, GROUP BY server-side.
    # ``order_by()`` esplicito perche' Meta.ordering insieme a values()+annotate()
    # su SQL Server produce l'errore 8127.
    last_done = dict(
        MaintenanceOccurrence.objects.filter(
            plan_id__in=plan_ids, status=MaintenanceOccurrence.STATUS_DONE
        )
        .values_list("plan_id")
        .annotate(ultima=Max("completed_on"))
        .order_by()
    )

    rows = []
    for plan in plans:
        cov = coverage.get(plan.id, {"assets": 0, "conflicts": 0, "excluded": 0})
        # Denominatore: gli asset che il piano tocca davvero, non l'intero parco.
        # "32 su 33" dice quanto e' completo il piano; "32 su 400" non direbbe nulla.
        in_scope = cov["assets"] + cov["conflicts"] + cov["excluded"]
        rows.append(
            {
                "plan": plan,
                "coverage": cov,
                "coverage_scope": in_scope,
                "coverage_pct": round(100 * cov["assets"] / in_scope) if in_scope else None,
                "last_done": last_done.get(plan.id),
                "stats": stats.get(plan.id, {"next_due": None, "overdue": 0}),
                "recurrences": sorted(
                    {describe_recurrence(a) for a in plan.assignments.all() if not a.is_excluded}
                ),
            }
        )

    return render(
        request,
        "assets/pages/maintenance_plan_list.html",
        {
            **_assets_shell_context(request),
            "page_title": "Piani di manutenzione",
            "rows": rows,
            "can_manage": can_manage_maintenance_plans(request),
        },
    )


@login_required
def maintenance_plan_detail(request: HttpRequest, plan_id: int) -> HttpResponse:
    today = timezone.localdate()
    plan = get_object_or_404(
        MaintenanceInterventionTemplate.objects.select_related("default_supplier", "default_assignee"),
        pk=plan_id,
    )
    assignments = list(
        plan.assignments.select_related("asset", "asset_group", "asset_category", "supplier", "assigned_to").order_by(
            "-target_type", "id"
        )
    )
    resolutions = domain.build_plan_resolutions(
        asset_queryset=Asset.objects.filter(status=Asset.STATUS_IN_USE), plan_ids=[plan.id]
    )
    per_assignment: dict[int, int] = defaultdict(int)
    conflicts = []
    for resolution in resolutions.values():
        if resolution.is_applied and resolution.assignment is not None:
            per_assignment[resolution.assignment.id] += 1
        elif resolution.is_conflict:
            conflicts.append(resolution)

    assignment_rows = [
        {
            "assignment": assignment,
            "recurrence": describe_recurrence(assignment),
            "asset_count": per_assignment.get(assignment.id, 0),
        }
        for assignment in assignments
    ]

    upcoming = _decorate(
        list(
            _base_occurrence_queryset()
            .filter(plan=plan, status=MaintenanceOccurrence.STATUS_OPEN)
            .order_by("due_date")[:60]
        ),
        today=today,
    )
    history = list(
        _base_occurrence_queryset()
        .filter(plan=plan, status=MaintenanceOccurrence.STATUS_DONE)
        .order_by("-completed_on")[:60]
    )
    open_workorders = list(
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN, occurrences__plan=plan)
        .distinct()
        .select_related("asset", "assigned_to")
        .annotate(occurrence_count=Count("occurrences"))[:30]
    )

    return render(
        request,
        "assets/pages/maintenance_plan_detail.html",
        {
            **_assets_shell_context(request),
            "page_title": plan.label,
            "plan": plan,
            "assignment_rows": assignment_rows,
            "conflicts": conflicts,
            "upcoming": upcoming,
            "history": history,
            "open_workorders": open_workorders,
            "checklist_steps": list(plan.checklist_steps.order_by("step_number", "id")),
            "can_manage": can_manage_maintenance_plans(request),
            "can_plan": can_plan_maintenance(request),
            "workorder_form": WorkOrderFromOccurrencesForm(),
        },
    )


@login_required
def maintenance_plan_form(request: HttpRequest, plan_id: int | None = None) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per configurare i piani di manutenzione.")
    plan = get_object_or_404(MaintenanceInterventionTemplate, pk=plan_id) if plan_id else None

    if request.method == "POST":
        form = MaintenancePlanForm(request.POST, instance=plan)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.full_clean()
            saved.save()
            messages.success(request, f"Piano «{saved.label}» salvato.")
            return redirect("assets:maintenance_plan_detail", plan_id=saved.pk)
    else:
        form = MaintenancePlanForm(instance=plan)

    return render(
        request,
        "assets/pages/maintenance_plan_form.html",
        {
            **_assets_shell_context(request),
            "page_title": "Modifica piano" if plan else "Nuovo piano di manutenzione",
            "form": form,
            "plan": plan,
        },
    )


# ---------------------------------------------------------------------------
# Applicazioni di un piano
# ---------------------------------------------------------------------------

def _assignment_suggestions(plan: MaintenanceInterventionTemplate) -> dict[str, Any]:
    """Cosa sapere prima di applicare un piano: dove vale gia' e chi resta scoperto.

    Solo proposte da leggere: la scelta del bersaglio resta a chi compila.
    """
    from .models import Asset

    existing = list(
        MaintenancePlanAssignment.objects.filter(plan=plan, is_active=True)
        .select_related("asset", "asset_group", "asset_category")
        .order_by("target_type", "id")
    )
    resolutions = domain.build_plan_resolutions(
        plan_ids=[plan.pk], asset_queryset=Asset.objects.exclude(status=Asset.STATUS_RETIRED)
    )
    covered = [res.asset for res in resolutions.values() if not res.is_excluded]
    covered_ids = {asset.id for asset in covered}
    family_gaps = []
    category_ids = {asset.asset_category_id for asset in covered if asset.asset_category_id}
    if category_ids:
        missing = (
            Asset.objects.filter(asset_category_id__in=category_ids)
            .exclude(status=Asset.STATUS_RETIRED)
            .exclude(id__in=covered_ids)
            .select_related("asset_category")
            .order_by("asset_category__label", "asset_tag")
        )
        by_family: dict[int, dict[str, Any]] = {}
        for asset in missing[:200]:
            bucket = by_family.setdefault(
                asset.asset_category_id,
                {"family": asset.asset_category.label, "category_id": asset.asset_category_id, "assets": []},
            )
            bucket["assets"].append(asset)
        family_gaps = list(by_family.values())
    return {"existing_assignments": existing, "covered_count": len(covered_ids), "family_gaps": family_gaps}


def _completion_suggestions(occurrence: MaintenanceOccurrence, back_url: str) -> dict[str, Any]:
    """Informazioni utili mentre si registra un'esecuzione: l'ultima volta, cos'altro
    c'e' da fare sulla stessa macchina, il contratto che la copre."""
    from .maintenance import get_applicable_assistance_contracts

    today = timezone.localdate()
    previous = (
        MaintenanceOccurrence.objects.filter(
            plan_id=occurrence.plan_id, asset_id=occurrence.asset_id, status=MaintenanceOccurrence.STATUS_DONE
        )
        .exclude(pk=occurrence.pk)
        .order_by("-completed_on", "-id")
        .first()
    )
    same_asset = list(
        MaintenanceOccurrence.objects.filter(
            asset_id=occurrence.asset_id,
            status=MaintenanceOccurrence.STATUS_OPEN,
            due_date__lte=today + timedelta(days=30),
        )
        .exclude(pk=occurrence.pk)
        .select_related("plan")
        .order_by("due_date")[:8]
    )
    for other in same_asset:
        other.register_url = f"{reverse('assets:occurrence_complete', args=[other.pk])}?{urlencode({'next': back_url})}"
    contracts = []
    try:
        contracts = list(get_applicable_assistance_contracts(occurrence.asset, today=today)[:1])
    except Exception:
        logger.exception("Contratti applicabili non calcolabili per asset %s", occurrence.asset_id)
    return {"previous": previous, "same_asset_open": same_asset, "contract": contracts[0] if contracts else None}


@login_required
def maintenance_assignment_form(
    request: HttpRequest, plan_id: int, assignment_id: int | None = None
) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per configurare le applicazioni dei piani.")
    plan = get_object_or_404(MaintenanceInterventionTemplate, pk=plan_id)
    assignment = (
        get_object_or_404(MaintenancePlanAssignment, pk=assignment_id, plan=plan) if assignment_id else None
    )

    if request.method == "POST":
        form = MaintenancePlanAssignmentForm(request.POST, instance=assignment, plan=plan)
        if form.is_valid():
            saved = form.save()
            # Prima le scadenze comparivano solo al giro notturno dello scheduler: chi
            # applicava un piano non vedeva nulla e pensava di aver sbagliato. La
            # generazione e' idempotente, quindi la si lancia subito sul solo piano.
            created = 0
            try:
                created = domain.generate_occurrences(plan_ids=[plan.pk]).get("created", 0)
            except Exception:
                logger.exception("Generazione scadenze dopo applicazione piano %s fallita", plan.pk)
            if created:
                messages.success(
                    request,
                    f"Applicazione su «{saved.target_label}» salvata: {created} scadenz"
                    f"{'a creata' if created == 1 else 'e create'} ora. Le successive compariranno "
                    "nel preavviso, e intanto sono visibili come «previste» nel Calendario.",
                )
            else:
                messages.success(
                    request,
                    f"Applicazione su «{saved.target_label}» salvata. Nessuna scadenza e' ancora nel "
                    "preavviso: la vedi come «prevista» nel Calendario e comparira' negli elenchi "
                    "quando si avvicina.",
                )
            return redirect("assets:maintenance_plan_detail", plan_id=plan.pk)
    else:
        form = MaintenancePlanAssignmentForm(instance=assignment, plan=plan)

    return render(
        request,
        "assets/pages/maintenance_assignment_form.html",
        {
            **_assets_shell_context(request),
            "page_title": f"Applicazione — {plan.label}",
            "form": form,
            "plan": plan,
            "assignment": assignment,
            "presets": RECURRENCE_PRESETS,
            "preview_url": reverse("assets:maintenance_assignment_preview"),
            **(_assignment_suggestions(plan) if assignment is None else {}),
        },
    )


@login_required
@require_POST
def maintenance_assignment_delete(request: HttpRequest, plan_id: int, assignment_id: int) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per rimuovere le applicazioni.")
    assignment = get_object_or_404(MaintenancePlanAssignment, pk=assignment_id, plan_id=plan_id)
    if assignment.occurrences.exists():
        # Un'applicazione con storico non si cancella: si disattiva. Altrimenti le
        # occorrenze gia' eseguite perderebbero il riferimento a come erano nate.
        assignment.is_active = False
        assignment.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Applicazione disattivata (ha storico, quindi non viene eliminata).")
    else:
        assignment.delete()
        messages.success(request, "Applicazione rimossa.")
    return redirect("assets:maintenance_plan_detail", plan_id=plan_id)


def _parse_iso_date(raw) -> date | None:
    """Data ISO dai parametri di query (l'anteprima e' un GET, non un form)."""
    try:
        return date.fromisoformat(str(raw or "").strip())
    except ValueError:
        return None


_MESI = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def _preview_first_due(
    request: HttpRequest,
    *,
    plan_id: int,
    asset_ids: list[int],
    skip_asset_ids: set[int],
    conflicting: set[int],
) -> list[dict[str, Any]]:
    """Quando cadrebbero le prime scadenze, raggruppate per mese.

    "Interessera' 14 asset" non dice se il lavoro arriva tutto insieme la settimana
    prossima o spalmato su un anno. La periodicita' viene dai campi del form, non
    dal database: l'applicazione non e' ancora salvata.
    """
    # Il preset vince sui sei campi grezzi: quando l'utente sceglie "ogni trimestre"
    # quei campi restano ai valori iniziali del form, e l'anteprima calcolerebbe le
    # date con una periodicita' che nessuno ha scelto.
    preset_key = _clean_string(request.GET.get("recurrence_preset"))
    preset = next(
        (values for key, _label, values in RECURRENCE_PRESETS if key == preset_key),
        None,
    )
    if preset:
        spec = {
            "frequency": preset.get("frequency", MaintenancePlanAssignment.FREQ_DAYS),
            "interval": preset.get("interval", 1),
            "weekday": preset.get("weekday"),
            "week_of_month": preset.get("week_of_month"),
            "day_of_month": preset.get("day_of_month"),
            "month_of_year": preset.get("month_of_year"),
        }
    else:
        spec = {
            "frequency": _clean_string(request.GET.get("frequency")) or MaintenancePlanAssignment.FREQ_DAYS,
            "interval": _as_int(request.GET.get("interval"), default=1) or 1,
            "weekday": request.GET.get("weekday") or None,
            "week_of_month": request.GET.get("week_of_month") or None,
            "day_of_month": request.GET.get("day_of_month") or None,
            "month_of_year": request.GET.get("month_of_year") or None,
        }
    anchor = _clean_string(request.GET.get("schedule_anchor")) or ANCHOR_FROM_COMPLETION
    today = timezone.localdate()
    start = _parse_iso_date(request.GET.get("first_due_date")) or today

    last_done: dict[int, MaintenanceOccurrence] = {}
    for occurrence in (
        MaintenanceOccurrence.objects.filter(
            plan_id=plan_id, asset_id__in=asset_ids, status=MaintenanceOccurrence.STATUS_DONE
        )
        .only("asset_id", "due_date", "completed_on")
        .order_by("asset_id", "-completed_on", "-due_date")
    ):
        last_done.setdefault(occurrence.asset_id, occurrence)

    buckets: dict[tuple[int, int], int] = {}
    for asset_id in asset_ids:
        if asset_id in skip_asset_ids or asset_id in conflicting:
            continue
        previous = last_done.get(asset_id)
        if previous is not None:
            due = compute_next_due(
                spec,
                anchor=anchor,
                previous_due=previous.due_date,
                completion_date=previous.completed_on,
            )
        else:
            due = first_due_date_for(spec, start_date=start, today=today)
        if due is None:
            continue
        buckets[(due.year, due.month)] = buckets.get((due.year, due.month), 0) + 1

    rows = [
        {"label": f"{_MESI[month - 1]} {year}", "count": count}
        for (year, month), count in sorted(buckets.items())
    ]
    return rows[:6]


@login_required
def maintenance_assignment_preview(request: HttpRequest) -> JsonResponse:
    """Anteprima non persistita: quanti asset tocca, prime scadenze, conflitti.

    Serve a non salvare alla cieca un'applicazione che coinvolge decine di macchine.
    """
    if not can_manage_maintenance_plans(request):
        return JsonResponse({"error": "forbidden"}, status=403)

    plan_id = _as_int(request.GET.get("plan"), default=0)
    target_type = _clean_string(request.GET.get("target_type"))
    target_id = _as_int(request.GET.get("target_id"), default=0)
    if not plan_id or not target_type or not target_id:
        return JsonResponse({"assets": 0, "first_due": [], "conflicts": 0, "already": 0})

    assets = Asset.objects.filter(status=Asset.STATUS_IN_USE)
    if target_type == MaintenancePlanAssignment.TARGET_ASSET:
        assets = assets.filter(pk=target_id)
    elif target_type == MaintenancePlanAssignment.TARGET_GROUP:
        assets = assets.filter(group_memberships__group_id=target_id)
    else:
        assets = assets.filter(asset_category_id=target_id)
    asset_ids = list(assets.values_list("pk", flat=True)[:2000])

    resolutions = domain.build_plan_resolutions(
        asset_queryset=Asset.objects.filter(pk__in=asset_ids), plan_ids=[plan_id]
    )
    conflicts = sum(1 for resolution in resolutions.values() if resolution.is_conflict)
    open_by_asset = set(
        MaintenanceOccurrence.objects.filter(
            plan_id=plan_id, asset_id__in=asset_ids, status=MaintenanceOccurrence.STATUS_OPEN
        ).values_list("asset_id", flat=True)
    )
    already = len(open_by_asset)

    return JsonResponse(
        {
            "assets": len(asset_ids),
            "conflicts": conflicts,
            "already": already,
            "first_due": _preview_first_due(
                request,
                plan_id=plan_id,
                asset_ids=asset_ids,
                skip_asset_ids=open_by_asset,
                conflicting={
                    asset_id
                    for (_plan, asset_id), resolution in resolutions.items()
                    if resolution.is_conflict or resolution.is_excluded
                },
            ),
        }
    )


# ---------------------------------------------------------------------------
# Gruppi di asset
# ---------------------------------------------------------------------------

@login_required
def asset_group_list(request: HttpRequest) -> HttpResponse:
    groups = list(
        AssetGroup.objects.annotate(
            member_count=Count("memberships", distinct=True),
            plan_count=Count("maintenance_plan_assignments", distinct=True),
        ).order_by("sort_order", "label")
    )
    return render(
        request,
        "assets/pages/asset_group_list.html",
        {
            **_assets_shell_context(request),
            "page_title": "Gruppi di asset",
            "groups": groups,
            "can_manage": can_manage_maintenance_plans(request),
        },
    )


@login_required
def asset_group_form(request: HttpRequest, group_id: int | None = None) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per gestire i gruppi di asset.", "assets:asset_group_list")
    group = get_object_or_404(AssetGroup, pk=group_id) if group_id else None

    if request.method == "POST":
        form = AssetGroupForm(request.POST, instance=group)
        if form.is_valid():
            saved = form.save(user=request.user)
            messages.success(request, f"Gruppo «{saved.label}» salvato.")
            return redirect("assets:asset_group_list")
    else:
        form = AssetGroupForm(instance=group)

    return render(
        request,
        "assets/pages/asset_group_form.html",
        {
            **_assets_shell_context(request),
            "page_title": "Modifica gruppo" if group else "Nuovo gruppo di asset",
            "form": form,
            "group": group,
        },
    )


# ---------------------------------------------------------------------------
# Scheda asset: piani applicati
# ---------------------------------------------------------------------------

@login_required
def asset_maintenance_plans(request: HttpRequest, asset_id: int) -> HttpResponse:
    """I piani che riguardano una macchina, con l'origine della regola.

    Niente "override": qui si dice ereditato, personalizzato o escluso.
    """
    asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=asset_id)
    today = timezone.localdate()
    resolutions = domain.resolve_asset_plans(asset)

    next_due_by_plan = {}
    for plan_id, due_date in (
        MaintenanceOccurrence.objects.filter(asset=asset, status=MaintenanceOccurrence.STATUS_OPEN)
        .order_by("due_date")
        .values_list("plan_id", "due_date")
    ):
        next_due_by_plan.setdefault(plan_id, due_date)

    rows = [
        {
            "resolution": resolution,
            "next_due": next_due_by_plan.get(resolution.plan.id),
            "is_overdue": (next_due_by_plan.get(resolution.plan.id) or date.max) < today,
        }
        for resolution in resolutions
    ]

    return render(
        request,
        "assets/pages/asset_maintenance_plans.html",
        {
            **_assets_shell_context(request),
            "page_title": f"Piani di manutenzione — {asset.asset_tag}",
            "asset": asset,
            "rows": rows,
            "history": list(
                _base_occurrence_queryset()
                .filter(asset=asset, status=MaintenanceOccurrence.STATUS_DONE)
                .order_by("-completed_on")[:40]
            ),
            "can_manage": can_manage_maintenance_plans(request),
        },
    )


@login_required
def asset_plan_customize(request: HttpRequest, asset_id: int, plan_id: int) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per personalizzare i piani sugli asset.")
    asset = get_object_or_404(Asset, pk=asset_id)
    plan = get_object_or_404(MaintenanceInterventionTemplate, pk=plan_id)
    assignment = MaintenancePlanAssignment.objects.filter(
        plan=plan, asset=asset, target_type=MaintenancePlanAssignment.TARGET_ASSET
    ).first()
    resolution = domain.resolve_plan_for_asset(plan_id=plan.pk, asset=asset)

    if request.method == "POST":
        form = AssetPlanCustomizationForm(request.POST, instance=assignment, plan=plan, asset=asset)
        if form.is_valid():
            mode = form.cleaned_data.get("mode")
            if mode == AssetPlanCustomizationForm.MODE_INHERIT:
                if assignment is not None:
                    # Tornare al gruppo non cancella lo storico: si toglie solo la
                    # regola specifica, le occorrenze gia' create restano.
                    MaintenanceOccurrence.objects.filter(assignment=assignment).update(assignment=None)
                    assignment.delete()
                messages.success(request, f"«{plan.label}» torna alle impostazioni del gruppo per {asset.asset_tag}.")
            else:
                saved = form.save()
                if saved.is_excluded:
                    messages.success(request, f"{asset.asset_tag} escluso dal piano «{plan.label}».")
                else:
                    messages.success(request, f"Periodicita personalizzata per {asset.asset_tag}.")
            return redirect("assets:asset_maintenance_plans", asset_id=asset.pk)
    else:
        form = AssetPlanCustomizationForm(instance=assignment, plan=plan, asset=asset)
        if assignment is None and resolution is not None and resolution.assignment is not None:
            # Si parte dai valori ereditati: personalizzare significa modificare
            # quello che c'e' gia', non ricominciare da un form vuoto.
            inherited = resolution.assignment
            for name in ("frequency", "interval", "weekday", "week_of_month", "day_of_month", "month_of_year", "warning_days"):
                form.initial.setdefault(name, getattr(inherited, name))
            form.initial["mode"] = AssetPlanCustomizationForm.MODE_INHERIT

    return render(
        request,
        "assets/pages/asset_plan_customize.html",
        {
            **_assets_shell_context(request),
            "page_title": f"{plan.label} — {asset.asset_tag}",
            "form": form,
            "asset": asset,
            "plan": plan,
            "resolution": resolution,
            "presets": RECURRENCE_PRESETS,
        },
    )


# ---------------------------------------------------------------------------
# Occorrenze: pianificazione, chiusura, follow-up
# ---------------------------------------------------------------------------

def _selected_occurrences(request: HttpRequest) -> list[MaintenanceOccurrence]:
    ids = [int(value) for value in request.POST.getlist("occurrence_ids") if str(value).isdigit()]
    if not ids:
        return []
    occurrences = list(
        MaintenanceOccurrence.objects.select_related("plan", "asset", "assignment")
        .filter(pk__in=ids, status=MaintenanceOccurrence.STATUS_OPEN)
        .order_by("due_date", "asset__asset_tag")
    )
    return occurrences


@login_required
@require_POST
def occurrence_reschedule(request: HttpRequest, occurrence_id: int) -> JsonResponse:
    """Sposta la scadenza di una manutenzione aperta (trascinamento nel Calendario).

    Solo chi pianifica, solo occorrenze aperte, nel proprio perimetro di reparto.
    Lo scheduler salta le coppie piano/asset con un'occorrenza gia' aperta, quindi
    spostare la data non genera doppioni. Ogni spostamento va in audit sul record.
    """
    from django.utils.dateparse import parse_date

    from core.audit import log_action

    if not can_plan_maintenance(request):
        return JsonResponse({"ok": False, "error": "Non hai i permessi per pianificare."}, status=403)
    occurrence = get_object_or_404(
        MaintenanceOccurrence.objects.select_related("plan", "asset"), pk=occurrence_id
    )
    if occurrence.status != MaintenanceOccurrence.STATUS_OPEN:
        return JsonResponse({"ok": False, "error": "Si possono spostare solo le manutenzioni aperte."}, status=400)
    try:
        _nega_fuori_reparto(request, [occurrence])
    except PermissionDenied:
        return JsonResponse({"ok": False, "error": "Manutenzione fuori dal tuo reparto."}, status=403)
    new_date = parse_date(_clean_string(request.POST.get("due_date"))[:10] or "")
    if new_date is None:
        return JsonResponse({"ok": False, "error": "Data non valida."}, status=400)
    old_date = occurrence.due_date
    if new_date == old_date:
        return JsonResponse({"ok": True, "due_date": new_date.isoformat(), "old_date": old_date.isoformat()})
    clash = MaintenanceOccurrence.objects.filter(
        plan_id=occurrence.plan_id, asset_id=occurrence.asset_id, due_date=new_date
    ).exclude(pk=occurrence.pk).exists()
    if clash:
        return JsonResponse(
            {"ok": False, "error": "Esiste gia' una manutenzione dello stesso piano su questo asset in quella data."},
            status=409,
        )
    occurrence.due_date = new_date
    occurrence.save(update_fields=["due_date", "updated_at"])
    log_action(
        request,
        "ASSET_OCCORRENZA_SPOSTATA",
        "assets",
        {"da": old_date.isoformat(), "a": new_date.isoformat(), "piano": occurrence.plan.label,
         "asset": occurrence.asset.asset_tag},
        oggetto=occurrence,
    )
    return JsonResponse({"ok": True, "due_date": new_date.isoformat(), "old_date": old_date.isoformat()})


@login_required
@require_POST
def occurrence_create_workorder(request: HttpRequest) -> HttpResponse:
    """Raccoglie le manutenzioni selezionate in un unico ordine di lavoro."""
    back = request.POST.get("next") or reverse("assets:maintenance_da_fare")
    if not can_plan_maintenance(request):
        return _deny(request, "Non hai i permessi per pianificare gli ordini di lavoro.")

    occurrences = _selected_occurrences(request)
    if not occurrences:
        messages.error(request, "Seleziona almeno una manutenzione da pianificare.")
        return redirect(back)
    _nega_fuori_reparto(request, occurrences)

    form = WorkOrderFromOccurrencesForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Dati dell'ordine di lavoro non validi.")
        return redirect(back)

    options = dict(
        user=request.user,
        title=form.cleaned_data.get("title") or "",
        assigned_to=form.cleaned_data.get("assigned_to"),
        supplier=form.cleaned_data.get("supplier"),
        due_at=form.cleaned_data.get("due_at"),
    )
    try:
        if form.cleaned_data.get("split_by_asset"):
            work_orders = domain.create_workorders_by_asset_day(occurrences, **options)
        else:
            work_orders = [domain.create_workorder_from_occurrences(occurrences, **options)]
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(back)

    leader = work_orders[0]
    if len(work_orders) > 1:
        messages.success(
            request,
            f"Creato il gruppo di ordini di lavoro {leader.pk}: "
            + ", ".join(f"#{wo.display_number}" for wo in work_orders)
            + f" — uno per asset e giorno, {len(occurrences)} manutenzioni in tutto.",
        )
    else:
        messages.success(
            request,
            f"Ordine di lavoro #{leader.display_number} creato con {len(occurrences)} manutenzione/i.",
        )
    return redirect("assets:wo_view", id=leader.pk)


@login_required
@require_POST
def workorder_occurrence_add(request: HttpRequest, workorder_id: int) -> HttpResponse:
    if not can_plan_maintenance(request):
        return _deny(request, "Non hai i permessi per modificare gli ordini di lavoro.")
    work_order = get_object_or_404(WorkOrder, pk=workorder_id)
    occurrences = _selected_occurrences(request)
    _nega_fuori_reparto(request, occurrences)
    added = domain.add_occurrences_to_workorder(work_order, occurrences, user=request.user)
    if added:
        messages.success(request, f"Aggiunte {added} manutenzioni all'ordine di lavoro.")
    else:
        messages.info(request, "Nessuna manutenzione aggiunta.")
    return redirect("assets:wo_view", id=work_order.pk)


@login_required
@require_POST
def workorder_occurrence_remove(request: HttpRequest, workorder_id: int, occurrence_id: int) -> HttpResponse:
    """Togliere un asset dall'OdL NON chiude e NON annulla la manutenzione."""
    if not can_plan_maintenance(request):
        return _deny(request, "Non hai i permessi per modificare gli ordini di lavoro.")
    occurrence = get_object_or_404(
        MaintenanceOccurrence.objects.select_related("asset", "work_order"),
        pk=occurrence_id,
        work_order_id=workorder_id,
    )
    domain.remove_occurrence_from_workorder(
        occurrence, user=request.user, reason=_clean_string(request.POST.get("reason"))
    )
    messages.success(
        request,
        f"{occurrence.asset.asset_tag} rimosso dall'ordine di lavoro: la manutenzione resta da pianificare.",
    )
    return redirect("assets:wo_view", id=workorder_id)


@login_required
@require_POST
def workorder_distribute_day(request: HttpRequest, workorder_id: int) -> HttpResponse:
    if not can_plan_maintenance(request):
        return _deny(request, "Non hai i permessi per distribuire il lavoro sulle giornate.")
    work_order = get_object_or_404(WorkOrder, pk=workorder_id)
    form = ExecutionDayForm(request.POST)
    occurrences = _selected_occurrences(request)
    if not form.is_valid() or not occurrences:
        messages.error(request, "Indica la giornata e almeno un asset da spostare.")
        return redirect("assets:wo_view", id=workorder_id)

    day = domain.assign_occurrences_to_day(
        work_order,
        occurrences,
        execution_date=form.cleaned_data["execution_date"],
        user=request.user,
    )
    messages.success(
        request,
        f"{len(occurrences)} asset programmati per il {day.execution_date:%d/%m/%Y}.",
    )
    return redirect("assets:wo_view", id=workorder_id)


@login_required
@require_POST
def workorder_occurrences_complete(request: HttpRequest, workorder_id: int) -> HttpResponse:
    """Registra in un colpo solo le manutenzioni selezionate di QUESTO ordine di lavoro.

    Un intervento massivo si esegue in una sola uscita ma si registrava una riga
    per volta: su un OdL da dieci macchine sono dieci form identici. Qui si
    dichiara una volta sola giorno, note e fermo, mentre la chiusura resta
    **per occorrenza** — ogni asset avanza sul suo piano, e chi non si puo'
    chiudere (manca il documento obbligatorio) viene saltato e detto per nome,
    invece di far fallire tutto il blocco.
    """
    work_order = get_object_or_404(WorkOrder, pk=workorder_id)
    if not can_execute_maintenance(request):
        return _deny(request, "Non hai i permessi per registrare l'esecuzione delle manutenzioni.")

    form = OccurrenceBulkCompletionForm(request.POST, request.FILES)
    # Solo le occorrenze di questo OdL: la selezione arriva dal client e la
    # pagina non e' il posto dove decidere a quale intervento appartengono.
    occurrences = [occ for occ in _selected_occurrences(request) if occ.work_order_id == work_order.pk]

    if not occurrences:
        messages.error(request, "Seleziona almeno una manutenzione da registrare.")
        return redirect("assets:wo_view", id=workorder_id)
    if not form.is_valid():
        errori = "; ".join(
            f"{field}: {' '.join(errs)}" for field, errs in form.errors.items()
        )
        messages.error(request, f"Registrazione non valida. {errori}")
        return redirect("assets:wo_view", id=workorder_id)

    upload = form.cleaned_data.get("attachment")
    completed_on = form.cleaned_data["completed_on"]
    notes = form.cleaned_data.get("notes") or ""
    downtime = form.cleaned_data.get("downtime_minutes")

    registrate: list[str] = []
    saltate: list[str] = []
    for occurrence in occurrences:
        etichetta = occurrence.asset.asset_tag or occurrence.asset.name
        if upload:
            # Lo stesso rapporto vale per tutte: il file viene riletto da capo
            # per ogni allegato, altrimenti dal secondo in poi si salva vuoto.
            upload.seek(0)
            MaintenanceOccurrenceAttachment.objects.create(
                occurrence=occurrence, file=upload, uploaded_by=request.user
            )
        try:
            domain.complete_occurrence(
                occurrence,
                completed_on=completed_on,
                user=request.user,
                notes=notes,
                downtime_minutes=downtime,
            )
        except domain.OccurrenceCompletionError as exc:
            saltate.append(f"{etichetta} ({exc})")
        else:
            registrate.append(etichetta)

    if registrate:
        messages.success(
            request,
            f"{len(registrate)} manutenzion{'e' if len(registrate) == 1 else 'i'} registrat"
            f"{'a' if len(registrate) == 1 else 'e'} il {completed_on:%d/%m/%Y}: {', '.join(registrate)}.",
        )
    if saltate:
        messages.warning(request, f"Non registrate: {'; '.join(saltate)}.")

    rimaste = MaintenanceOccurrence.objects.filter(
        work_order_id=work_order.pk, status=MaintenanceOccurrence.STATUS_OPEN
    ).count()
    if registrate and not rimaste and work_order.status == WorkOrder.STATUS_OPEN:
        messages.info(
            request,
            "Tutte le manutenzioni raccolte sono registrate: l'intervento puo' essere chiuso.",
        )

    return redirect("assets:wo_view", id=workorder_id)


@login_required
def _safe_back_url(request: HttpRequest, fallback: str) -> str:
    """Dove tornare dopo un'azione: ``next`` esplicito, altrimenti la pagina da cui
    si e' arrivati (stesso host). Mai un URL esterno."""
    from django.utils.http import url_has_allowed_host_and_scheme

    for candidate in (request.POST.get("next"), request.GET.get("next"), request.META.get("HTTP_REFERER")):
        candidate = (candidate or "").strip()
        if candidate and url_has_allowed_host_and_scheme(
            candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ) and request.path not in candidate:
            return candidate
    return fallback


def occurrence_complete(request: HttpRequest, occurrence_id: int) -> HttpResponse:
    """Chiusura di una singola manutenzione: ogni asset avanza per conto suo.

    Dopo la registrazione si torna alla pagina di partenza (Calendario,
    Scadenzario, scheda asset...), non sempre a "Da fare"."""
    occurrence = get_object_or_404(
        MaintenanceOccurrence.objects.select_related("plan", "asset", "assignment", "work_order"),
        pk=occurrence_id,
    )
    if not can_execute_maintenance(request):
        return _deny(request, "Non hai i permessi per registrare l'esecuzione delle manutenzioni.")
    back_url = _safe_back_url(request, reverse("assets:maintenance_da_fare"))
    if occurrence.status != MaintenanceOccurrence.STATUS_OPEN:
        messages.info(request, "Questa manutenzione risulta gia chiusa.")
        return redirect(back_url)

    if request.method == "POST":
        form = OccurrenceCompletionForm(request.POST, request.FILES, occurrence=occurrence)
        if form.is_valid():
            upload = form.cleaned_data.get("attachment")
            if upload:
                MaintenanceOccurrenceAttachment.objects.create(
                    occurrence=occurrence, file=upload, uploaded_by=request.user
                )
            report_received = form.cleaned_data.get("report_received_at")
            if report_received:
                occurrence.report_received_at = report_received
                occurrence.save(update_fields=["report_received_at", "updated_at"])
            try:
                following = domain.complete_occurrence(
                    occurrence,
                    completed_on=form.cleaned_data["completed_on"],
                    user=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                    downtime_minutes=form.cleaned_data.get("downtime_minutes"),
                )
            except domain.OccurrenceCompletionError as exc:
                messages.error(request, str(exc))
            else:
                if following is not None:
                    messages.success(
                        request,
                        f"Manutenzione registrata. Prossima scadenza: {following.due_date:%d/%m/%Y}.",
                    )
                else:
                    messages.success(request, "Manutenzione registrata.")
                return redirect(back_url)
    else:
        form = OccurrenceCompletionForm(occurrence=occurrence)

    return render(
        request,
        "assets/pages/occurrence_complete.html",
        {
            **_assets_shell_context(request),
            "page_title": f"Registra — {occurrence.plan.label}",
            "back_url": back_url,
            "form": form,
            "occurrence": occurrence,
            "state": domain.occurrence_state_payload(occurrence),
            **_completion_suggestions(occurrence, back_url),
        },
    )


@login_required
def occurrence_followup_create(request: HttpRequest, occurrence_id: int) -> HttpResponse:
    """Apre un follow-up per l'anomalia trovata su QUESTO asset.

    La manutenzione programmata resta eseguita e la periodicita' avanza lo stesso:
    "eseguita" e "problema risolto" non sono la stessa domanda.
    """
    occurrence = get_object_or_404(
        MaintenanceOccurrence.objects.select_related("plan", "asset", "work_order"), pk=occurrence_id
    )
    if not can_execute_maintenance(request):
        return _deny(request, "Non hai i permessi per aprire un follow-up.")

    checklist_item_id = _as_int(request.GET.get("step"), default=0) or _as_int(
        request.POST.get("checklist_item"), default=0
    )

    if request.method == "POST":
        form = FollowUpForm(request.POST)
        if form.is_valid():
            follow_up = WorkOrder.objects.create(
                asset=occurrence.asset,
                kind=WorkOrder.KIND_CORRECTIVE,
                origin=WorkOrder.ORIGIN_MANUAL,
                status=WorkOrder.STATUS_OPEN,
                title=form.cleaned_data["title"][:255],
                description=form.cleaned_data["reason"],
                assigned_to=form.cleaned_data.get("assigned_to"),
                due_at=form.cleaned_data.get("due_at"),
                follow_up_of=occurrence.work_order,
                follow_up_occurrence=occurrence,
                follow_up_checklist_item_id=checklist_item_id or None,
                follow_up_reason=form.cleaned_data["reason"],
            )
            messages.success(request, f"Follow-up #{follow_up.pk} aperto su {occurrence.asset.asset_tag}.")
            return redirect("assets:wo_view", id=follow_up.pk)
    else:
        form = FollowUpForm(
            initial={
                "title": f"Anomalia rilevata — {occurrence.asset.asset_tag}",
                "assigned_to": occurrence.work_order.assigned_to if occurrence.work_order_id else None,
            }
        )

    return render(
        request,
        "assets/pages/occurrence_followup_form.html",
        {
            **_assets_shell_context(request),
            "page_title": f"Follow-up — {occurrence.asset.asset_tag}",
            "form": form,
            "occurrence": occurrence,
            "checklist_item_id": checklist_item_id,
        },
    )


@login_required
def occurrence_attachment_download(request: HttpRequest, attachment_id: int) -> HttpResponse:
    """I rapporti stanno fuori dalla webroot: si servono solo a utente autenticato."""
    from django.http import FileResponse

    attachment = get_object_or_404(
        MaintenanceOccurrenceAttachment.objects.select_related("occurrence", "occurrence__asset"),
        pk=attachment_id,
    )
    if not attachment.file:
        raise Http404
    return FileResponse(
        attachment.file.open("rb"),
        as_attachment=True,
        filename=attachment.original_name or "allegato",
    )


# ---------------------------------------------------------------------------
# Matrice di copertura
# ---------------------------------------------------------------------------

@login_required
def maintenance_coverage(request: HttpRequest) -> HttpResponse:
    """Asset x Piani: dove il piano e' ereditato, personalizzato, escluso, in conflitto.

    Serve a vedere i buchi senza aprire una macchina alla volta.
    """
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per la matrice di copertura.")

    assets = list(
        Asset.objects.filter(status=Asset.STATUS_IN_USE)
        .select_related("asset_category")
        .order_by("reparto", "asset_tag", "name")[:400]
    )
    plans = list(MaintenanceInterventionTemplate.objects.filter(is_active=True).order_by("sort_order", "label"))
    resolutions = domain.build_plan_resolutions(
        asset_queryset=Asset.objects.filter(pk__in=[a.pk for a in assets]),
        plan_ids=[p.pk for p in plans],
    )

    legend = {
        domain.SOURCE_ASSET: ("P", "Personalizzato"),
        domain.SOURCE_GROUP: ("✓", "Ereditato dal gruppo"),
        domain.SOURCE_CATEGORY: ("✓", "Ereditato dalla categoria"),
    }

    rows = []
    for asset in assets:
        cells = []
        for plan in plans:
            resolution = resolutions.get((plan.pk, asset.pk))
            if resolution is None:
                cells.append({"symbol": "–", "title": "Non applicato", "tone": "none", "plan": plan, "asset": asset})
            elif resolution.is_conflict:
                cells.append({"symbol": "!", "title": "Conflitto fra gruppi", "tone": "conflict", "plan": plan, "asset": asset})
            elif resolution.is_excluded:
                cells.append({"symbol": "X", "title": "Escluso", "tone": "excluded", "plan": plan, "asset": asset})
            else:
                symbol, title = legend.get(resolution.source, ("✓", "Applicato"))
                cells.append(
                    {
                        "symbol": symbol,
                        "title": f"{title} — {resolution.recurrence_label}",
                        "tone": "custom" if resolution.source == domain.SOURCE_ASSET else "inherited",
                        "plan": plan,
                        "asset": asset,
                    }
                )
        rows.append({"asset": asset, "cells": cells})

    return render(
        request,
        "assets/pages/maintenance_coverage.html",
        {
            **_assets_shell_context(request),
            "page_title": "Copertura piani",
            "plans": plans,
            "rows": rows,
        },
    )


# ---------------------------------------------------------------------------
# Import dello storico
# ---------------------------------------------------------------------------

def _import_payload(report) -> str:
    """Righe importabili serializzate per il passo di conferma.

    La conferma ripassa dalla stessa ``analyze``: il payload non e' una scorciatoia
    che salta la validazione, e' solo il modo di non far ricaricare il file.
    """
    return json.dumps(
        [
            [row.asset_tag, row.plan_label, row.last_execution.isoformat(), row.notes]
            for row in report.valid_rows
        ]
    )


def _table_from_payload(raw: str) -> list[list[Any]]:
    try:
        rows = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    table: list[list[Any]] = [list(history_import.TEMPLATE_HEADERS)]
    for row in rows:
        if isinstance(row, list) and len(row) == 4:
            table.append([str(value or "") for value in row])
    return table


@login_required
def maintenance_history_import(request: HttpRequest) -> HttpResponse:
    """Carica lo storico: anteprima riga per riga, poi conferma.

    Senza la data dell'ultima esecuzione il motore considera ogni piano dovuto
    subito: il giorno del passaggio il portale aprirebbe centinaia di scadenze
    false. Questa e' la pagina che evita quel giorno.
    """
    if not can_manage_maintenance_plans(request):
        raise Http404

    form = MaintenanceHistoryImportForm()
    report = None
    payload = ""

    if request.method == "POST" and request.POST.get("confirm") == "1":
        report = history_import.analyze(_table_from_payload(request.POST.get("payload", "")))
        if report.can_apply:
            history_import.apply_report(report, user=request.user)
            avviso = (
                f" {report.kept_open} scadenze gia' aperte sono state lasciate come stavano."
                if report.kept_open
                else ""
            )
            messages.success(
                request,
                f"Storico importato: {report.created_history} esecuzioni registrate, "
                f"{report.created_next} prossime scadenze aperte.{avviso}",
            )
            return redirect("assets:maintenance_scadenze")
        messages.error(request, report.header_error or "Nessuna riga importabile: ricarica il file.")
        payload = _import_payload(report)

    elif request.method == "POST":
        form = MaintenanceHistoryImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                table = history_import.read_table(form.cleaned_data["file"])
            except Exception as exc:  # file corrotto o non leggibile
                messages.error(request, f"File non leggibile: {exc}")
                table = []
            if table:
                report = history_import.analyze(table)
                payload = _import_payload(report)

    return render(
        request,
        "assets/pages/maintenance_history_import.html",
        {
            **_assets_shell_context(request),
            "page_title": "Importa storico manutenzioni",
            "form": form,
            "report": report,
            "payload": payload,
            "headers": history_import.TEMPLATE_HEADERS,
        },
    )


@login_required
def maintenance_history_template(request: HttpRequest) -> HttpResponse:
    """Modello Excel da compilare."""
    if not can_manage_maintenance_plans(request):
        raise Http404

    buffer = io.BytesIO()
    history_import.build_template_workbook().save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="storico_manutenzioni_modello.xlsx"'
    return response


# ---------------------------------------------------------------------------
# Percorso guidato "Imposta la manutenzione"
# ---------------------------------------------------------------------------

@login_required
def maintenance_setup(request: HttpRequest) -> HttpResponse:
    """A che punto e' la configurazione, passo per passo, sui dati veri.

    Ogni passo dice cosa manca, quanto, e porta alla pagina dove si sistema.
    Nessun dato nuovo: solo conteggi su piani, applicazioni, asset e scadenze.
    """
    from .services import deadline_feed as feed

    plans = list(MaintenanceInterventionTemplate.objects.filter(is_active=True).order_by("sort_order", "label"))
    active_assignments = MaintenancePlanAssignment.objects.filter(is_active=True, plan__is_active=True)
    applied_plan_ids = set(
        active_assignments.filter(is_excluded=False).values_list("plan_id", flat=True).order_by().distinct()
    )
    plans_without_target = [plan for plan in plans if plan.id not in applied_plan_ids]
    manual_generation = list(
        active_assignments.filter(is_excluded=False, auto_generate=False).select_related("plan")[:200]
    )
    external_without_supplier = [
        plan for plan in plans
        if plan.execution_mode == MaintenanceInterventionTemplate.MODE_EXTERNAL and not plan.default_supplier_id
    ]

    resolutions = domain.build_plan_resolutions(asset_queryset=Asset.objects.filter(status=Asset.STATUS_IN_USE))
    covered_assets = {asset_id for (_plan_id, asset_id), res in resolutions.items() if res.is_applied}
    conflicts = sum(1 for res in resolutions.values() if res.is_conflict)
    assets_in_use = Asset.objects.filter(status=Asset.STATUS_IN_USE).count()
    coverage_pct = round(100 * len(covered_assets) / assets_in_use) if assets_in_use else None

    legacy_duplicates = feed.migrated_legacy_deadlines_qs().count()
    legacy_open = feed.legacy_deadlines_qs().count()
    groups = AssetGroup.objects.filter(is_active=True).count()

    def step(key, title, status, detail, links, items=None):
        return {"key": key, "title": title, "status": status, "detail": detail, "links": links, "items": items or []}

    steps = [
        step(
            "piani", "Definisci i piani di manutenzione",
            "done" if plans else "todo",
            f"{len(plans)} piani attivi." if plans else "Nessun piano: e' da qui che nascono tutte le scadenze.",
            [("+ Nuovo piano", reverse("assets:maintenance_plan_create")), ("Piani", reverse("assets:maintenance_plan_list"))],
        ),
        step(
            "applicazioni", "Applica ogni piano ad asset, gruppi o categorie",
            "todo" if plans_without_target else ("done" if plans else "blocked"),
            (f"{len(plans_without_target)} piani non sono applicati a nessun asset: non generano scadenze."
             if plans_without_target else "Tutti i piani attivi hanno almeno un'applicazione."),
            [("Piani", reverse("assets:maintenance_plan_list"))],
            [(plan.label, reverse("assets:maintenance_plan_detail", args=[plan.id])) for plan in plans_without_target[:8]],
        ),
        step(
            "generazione", "Conferma le periodicita' da verificare",
            "todo" if manual_generation else "done",
            (f"{len(manual_generation)} applicazioni hanno la generazione automatica spenta: "
             "di solito arrivano dalla migrazione, con periodicita' da confermare."
             if manual_generation else "Tutte le applicazioni generano le scadenze da sole."),
            [],
            [(f"{a.plan.label} — {a.get_target_type_display()}",
              reverse("assets:maintenance_assignment_edit", args=[a.plan_id, a.id])) for a in manual_generation[:8]],
        ),
        step(
            "copertura", "Copri gli asset in uso",
            "done" if coverage_pct == 100 and not conflicts else ("todo" if assets_in_use else "blocked"),
            (f"{len(covered_assets)} asset in uso su {assets_in_use} hanno almeno un piano ({coverage_pct}%)."
             if assets_in_use else "Nessun asset in uso.")
            + (f" {conflicts} conflitti di periodicita' bloccano la generazione." if conflicts else ""),
            [("Copertura", reverse("assets:maintenance_coverage"))],
        ),
        step(
            "fornitori", "Assegna un fornitore ai piani esterni",
            "todo" if external_without_supplier else "done",
            (f"{len(external_without_supplier)} piani esterni senza fornitore predefinito: l'OdL nasce senza ditta."
             if external_without_supplier else "Ogni piano esterno ha il suo fornitore."),
            [("Fornitori", reverse("assets:maintenance_suppliers"))],
            [(plan.label, reverse("assets:maintenance_plan_edit", args=[plan.id])) for plan in external_without_supplier[:8]],
        ),
        step(
            "archivio", "Chiudi l'archivio delle vecchie scadenze",
            "todo" if legacy_duplicates else ("info" if legacy_open else "done"),
            (f"{legacy_duplicates} vecchie scadenze amministrative sono gia' nei piani ma ancora attive: "
             "l'amministratore le chiude con il comando close_migrated_admin_deadlines."
             if legacy_duplicates else
             (f"{legacy_open} vecchie scadenze non sono ancora nei piani: restano visibili, ma conviene trasferirle."
              if legacy_open else "Nessuna scadenza nel vecchio archivio.")),
            [("Archivio precedente", reverse("assets:asset_administrative_deadline_list"))],
        ),
        step(
            "gruppi", "Raggruppa gli asset (facoltativo)",
            "done" if groups else "optional",
            (f"{groups} gruppi attivi." if groups else
             "Le famiglie d'inventario bastano quasi sempre. Un gruppo serve quando un piano riguarda "
             "asset di famiglie diverse (es. «linea 3») o solo alcuni asset di una famiglia."),
            [("Gruppi asset", reverse("assets:asset_group_list"))],
        ),
    ]
    required = [s for s in steps if s["status"] not in {"optional", "info"}]
    done = sum(1 for s in required if s["status"] == "done")
    return render(
        request,
        "assets/pages/maintenance_setup.html",
        {
            **_assets_shell_context(request),
            "page_title": "Imposta la manutenzione",
            "steps": steps,
            "done": done,
            "total": len(required),
            "progress_pct": round(100 * done / len(required)) if required else 100,
        },
    )
