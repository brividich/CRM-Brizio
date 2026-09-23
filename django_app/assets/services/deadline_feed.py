"""Scadenze della manutenzione in una forma sola.

Una scadenza della manutenzione puo' venire da tre posti: un'occorrenza di un
piano (ordinaria o amministrativa), la data di scadenza di una licenza software,
la data di fine di un contratto di assistenza. Prima ogni pagina ne leggeva uno —
il calendario addirittura il vecchio motore a regole — e i conteggi non tornavano
fra una pagina e l'altra.

Questo modulo e' in SOLA LETTURA: non crea, non sposta, non chiude niente. Mette
le tre sorgenti nella stessa forma (:class:`Deadline`) e le filtra allo stesso
modo. La gestione resta dove sta: le azioni puntano alle pagine esistenti.

Licenze e contratti hanno i loro permessi ACL: entrano nel risultato solo se chi
guarda puo' aprire le rispettive pagine (stessa decisione del middleware).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from ..models import (
    Asset,
    AssistanceContract,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    SoftwareLicense,
)
from . import maintenance_domain as domain

KIND_ORDINARY = "ordinary"
KIND_ADMINISTRATIVE = "administrative"
KIND_LICENSE = "license"
KIND_CONTRACT = "contract"

KIND_LABELS = {
    KIND_ORDINARY: "Ordinaria",
    KIND_ADMINISTRATIVE: "Amministrativa",
    KIND_LICENSE: "Licenza",
    KIND_CONTRACT: "Contratto",
}
ALL_KINDS = tuple(KIND_LABELS)

# Stati comuni alle tre sorgenti: bastano a colorare e ordinare.
STATE_OVERDUE = "overdue"
STATE_DUE_SOON = "due_soon"
STATE_PLANNED = "planned"
STATE_OPEN = "open"
STATE_DONE = "done"

STATE_LABELS = {
    STATE_OVERDUE: "Scaduta",
    STATE_DUE_SOON: "In scadenza",
    STATE_PLANNED: "Pianificata",
    STATE_OPEN: "Aperta",
    STATE_DONE: "Conclusa",
}

# Licenze e contratti non hanno un preavviso proprio: si usa la stessa soglia
# dello stato contratto esistente (``maintenance.contract_state_payload``).
DEFAULT_WARNING_DAYS = 30

LICENSES_PATH = "/assets/licenze/"
CONTRACTS_PATH = "/assets/manutenzione/contratti/"


@dataclass
class Deadline:
    key: str
    kind: str
    title: str
    due_date: date
    state: str
    asset_id: int | None = None
    asset_tag: str = ""
    asset_name: str = ""
    category_label: str = ""
    reparto: str = ""
    target_label: str = ""
    is_external: bool = False
    assignee: str = ""
    supplier: str = ""
    work_order_id: int | None = None
    detail_url: str = ""
    actions: list[dict[str, str]] = field(default_factory=list)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, "")

    @property
    def state_label(self) -> str:
        return STATE_LABELS.get(self.state, "")

    def days_until(self, today: date) -> int:
        return (self.due_date - today).days

    def as_json(self, today: date) -> dict:
        return {
            "id": self.key,
            "kind": self.kind,
            "kind_label": self.kind_label,
            "title": self.title,
            "start": self.due_date.isoformat(),
            "state": self.state,
            "state_label": self.state_label,
            "days": self.days_until(today),
            "asset_id": self.asset_id,
            "asset_tag": self.asset_tag,
            "asset_name": self.asset_name,
            "category": self.category_label,
            "reparto": self.reparto,
            "target": self.target_label,
            "external": self.is_external,
            "assignee": self.assignee,
            "supplier": self.supplier,
            "work_order_id": self.work_order_id,
            "url": self.detail_url,
            "actions": self.actions,
        }


@dataclass
class FeedFilters:
    kinds: frozenset[str] = frozenset(ALL_KINDS)
    category_ids: frozenset[int] | None = None
    reparto: str = ""
    group_id: int | None = None
    execution_mode: str = ""  # INTERNAL / EXTERNAL, solo per le occorrenze
    include_done: bool = False


def _simple_state(due: date, today: date, warning_days: int) -> str:
    if due < today:
        return STATE_OVERDUE
    if due <= today + timedelta(days=warning_days):
        return STATE_DUE_SOON
    return STATE_OPEN


def _asset_fields(asset: Asset | None) -> dict:
    if asset is None:
        return {}
    category = asset.asset_category if asset.asset_category_id else None
    return {
        "asset_id": asset.id,
        "asset_tag": asset.asset_tag or "",
        "asset_name": asset.name or "",
        "category_label": getattr(category, "label", "") or "",
        "reparto": asset.reparto or "",
    }


def _person(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.get_username() or "").strip()


# ---------------------------------------------------------------------------
# Sorgenti
# ---------------------------------------------------------------------------

def _occurrences(start: date | None, end: date | None, filters: FeedFilters, today: date) -> list[Deadline]:
    wanted = filters.kinds & {KIND_ORDINARY, KIND_ADMINISTRATIVE}
    if not wanted:
        return []
    qs = (
        MaintenanceOccurrence.objects.select_related(
            "plan", "asset", "asset__asset_category", "assignment", "work_order",
            "work_order__assigned_to", "supplier",
        )
        .prefetch_related("attachments")
        .exclude(status=MaintenanceOccurrence.STATUS_CANCELED)
    )
    if not filters.include_done:
        qs = qs.filter(status=MaintenanceOccurrence.STATUS_OPEN)
    if start:
        qs = qs.filter(due_date__gte=start)
    if end:
        qs = qs.filter(due_date__lte=end)
    admin_type = MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE
    if wanted == {KIND_ADMINISTRATIVE}:
        qs = qs.filter(plan__maintenance_type=admin_type)
    elif wanted == {KIND_ORDINARY}:
        qs = qs.exclude(plan__maintenance_type=admin_type)
    if filters.category_ids is not None:
        qs = qs.filter(asset__asset_category_id__in=filters.category_ids)
    if filters.reparto:
        qs = qs.filter(asset__reparto=filters.reparto)
    if filters.group_id:
        qs = qs.filter(asset__group_memberships__group_id=filters.group_id)
    if filters.execution_mode:
        mode = filters.execution_mode
        qs = qs.filter(
            Q(assignment__execution_mode=mode)
            | (Q(assignment__execution_mode="") & Q(plan__execution_mode=mode))
            | (Q(assignment__isnull=True) & Q(plan__execution_mode=mode))
        )

    rows: list[Deadline] = []
    for occ in qs.order_by("due_date", "id").distinct()[:3000]:
        payload = domain.occurrence_state_payload(occ, today=today)
        view_state = payload["state"]
        if occ.status == MaintenanceOccurrence.STATUS_DONE:
            state = STATE_DONE
        elif view_state == MaintenanceOccurrence.VIEW_OVERDUE:
            state = STATE_OVERDUE
        elif occ.work_order_id:
            state = STATE_PLANNED
        elif view_state == MaintenanceOccurrence.VIEW_DUE_SOON:
            state = STATE_DUE_SOON
        else:
            state = STATE_OPEN
        kind = KIND_ADMINISTRATIVE if occ.plan.maintenance_type == admin_type else KIND_ORDINARY
        actions = []
        if occ.status == MaintenanceOccurrence.STATUS_OPEN:
            actions.append({
                "label": "Registra esecuzione",
                "url": reverse("assets:occurrence_complete", args=[occ.id]),
            })
        if occ.work_order_id:
            actions.append({"label": "Apri OdL", "url": reverse("assets:wo_view", args=[occ.work_order_id])})
        elif occ.status == MaintenanceOccurrence.STATUS_OPEN:
            # L'OdL si crea dallo Scadenzario, dove si possono raccogliere piu' asset.
            actions.append({
                "label": "Pianifica nello Scadenzario",
                "url": f"{reverse('assets:maintenance_scadenze')}?window=&q={occ.asset.asset_tag}",
            })
        actions.append({"label": "Apri asset", "url": reverse("assets:asset_view", args=[occ.asset_id])})
        rows.append(Deadline(
            key=f"occ-{occ.id}",
            kind=kind,
            title=occ.plan.label,
            due_date=occ.due_date,
            state=state,
            is_external=bool(occ.is_external),
            assignee=_person(occ.work_order.assigned_to) if occ.work_order_id else "",
            supplier=str(occ.supplier) if occ.supplier_id else "",
            work_order_id=occ.work_order_id,
            detail_url=actions[0]["url"],
            actions=actions,
            **_asset_fields(occ.asset),
        ))
    return rows


def _license_target(lic: SoftwareLicense) -> str:
    """A chi e' intestata una licenza senza asset: la persona, altrimenti il reparto.
    "Da assegnare" solo quando davvero non c'e' nessuno dei due."""
    if lic.asset_id:
        return ""
    if lic.assignment_scope == "user":
        return lic.assignment_label
    if lic.assigned_reparto:
        return f"Reparto {lic.assigned_reparto}"
    return "Da assegnare"


def _licenses(start: date | None, end: date | None, filters: FeedFilters, today: date) -> list[Deadline]:
    if KIND_LICENSE not in filters.kinds or filters.execution_mode:
        return []
    qs = SoftwareLicense.objects.select_related("asset", "asset__asset_category").filter(
        is_active=True, expiry_date__isnull=False
    )
    if start:
        qs = qs.filter(expiry_date__gte=start)
    if end:
        qs = qs.filter(expiry_date__lte=end)
    if filters.category_ids is not None:
        qs = qs.filter(asset__asset_category_id__in=filters.category_ids)
    if filters.reparto:
        qs = qs.filter(Q(assigned_reparto=filters.reparto) | Q(asset__reparto=filters.reparto))
    if filters.group_id:
        qs = qs.filter(asset__group_memberships__group_id=filters.group_id)
    list_url = reverse("assets:software_license_list")
    rows = []
    for lic in qs.order_by("expiry_date", "id").distinct()[:1000]:
        title = " ".join(part for part in (lic.vendor, lic.product_name, lic.edition) if part)
        if lic.seats_total:
            title = f"{title} ({lic.seats_total} posti)"
        fields = _asset_fields(lic.asset) if lic.asset_id else {"reparto": lic.assigned_reparto or ""}
        actions = [{"label": "Apri licenze", "url": f"{list_url}?q={lic.product_name}"}]
        if lic.asset_id:
            actions.append({"label": "Apri asset", "url": reverse("assets:asset_view", args=[lic.asset_id])})
        rows.append(Deadline(
            key=f"lic-{lic.id}",
            kind=KIND_LICENSE,
            title=title,
            due_date=lic.expiry_date,
            state=_simple_state(lic.expiry_date, today, DEFAULT_WARNING_DAYS),
            target_label=_license_target(lic),
            supplier=lic.vendor or "",
            detail_url=actions[0]["url"],
            actions=actions,
            **fields,
        ))
    return rows


def _contracts(start: date | None, end: date | None, filters: FeedFilters, today: date) -> list[Deadline]:
    if KIND_CONTRACT not in filters.kinds or filters.execution_mode:
        return []
    qs = AssistanceContract.objects.select_related(
        "supplier", "asset", "asset__asset_category", "asset_category"
    ).filter(is_active=True, end_date__isnull=False)
    if start:
        qs = qs.filter(end_date__gte=start)
    if end:
        qs = qs.filter(end_date__lte=end)
    if filters.category_ids is not None:
        qs = qs.filter(
            Q(asset__asset_category_id__in=filters.category_ids) | Q(asset_category_id__in=filters.category_ids)
        )
    if filters.reparto:
        qs = qs.filter(asset__reparto=filters.reparto)
    if filters.group_id:
        qs = qs.filter(asset__group_memberships__group_id=filters.group_id)
    list_url = reverse("assets:assistance_contract_list")
    rows = []
    for contract in qs.order_by("end_date", "id").distinct()[:1000]:
        actions = [{"label": "Apri contratti", "url": list_url}]
        if contract.asset_id:
            actions.append({"label": "Apri asset", "url": reverse("assets:asset_view", args=[contract.asset_id])})
        rows.append(Deadline(
            key=f"con-{contract.id}",
            kind=KIND_CONTRACT,
            title=contract.title or contract.code or "Contratto di assistenza",
            due_date=contract.end_date,
            state=_simple_state(contract.end_date, today, DEFAULT_WARNING_DAYS),
            target_label=contract.target_label,
            is_external=True,
            supplier=str(contract.supplier) if contract.supplier_id else "",
            detail_url=list_url,
            actions=actions,
            **_asset_fields(contract.asset if contract.asset_id else None),
        ))
    return rows


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def allowed_kinds(request) -> frozenset[str]:
    """Tipologie che chi guarda puo' vedere: licenze e contratti seguono l'ACL
    delle loro pagine, le occorrenze quella della pagina che chiama."""
    from core.middleware import acl_allows_path

    kinds = {KIND_ORDINARY, KIND_ADMINISTRATIVE}
    user = getattr(request, "user", None)
    for kind, path in ((KIND_LICENSE, LICENSES_PATH), (KIND_CONTRACT, CONTRACTS_PATH)):
        try:
            if acl_allows_path(path, django_user=user, request=request):
                kinds.add(kind)
        except Exception:
            # Nel dubbio non si mostra: fail-closed.
            continue
    return frozenset(kinds)


def collect(
    *,
    start: date | None,
    end: date | None,
    filters: FeedFilters | None = None,
    today: date | None = None,
) -> list[Deadline]:
    """Scadenze delle tre sorgenti fra ``start`` ed ``end`` (inclusi), ordinate per data."""
    today = today or timezone.localdate()
    filters = filters or FeedFilters()
    rows = (
        _occurrences(start, end, filters, today)
        + _licenses(start, end, filters, today)
        + _contracts(start, end, filters, today)
    )
    state_order = {STATE_OVERDUE: 0, STATE_DUE_SOON: 1, STATE_OPEN: 2, STATE_PLANNED: 3, STATE_DONE: 4}
    rows.sort(key=lambda d: (d.due_date, state_order.get(d.state, 9), d.kind, d.title))
    return rows


def parse_kinds(values: Iterable[str], allowed: frozenset[str]) -> frozenset[str]:
    """Nessun parametro = tutte le tipologie consentite. Un parametro presente ma
    senza tipologie di scadenza (tutte spente, o solo "lavori macchina") = nessuna:
    spegnere tutto non deve riaccendere tutto."""
    values = [value for value in values if value]
    if not values:
        return allowed
    return frozenset({value for value in values if value in KIND_LABELS} & allowed)
