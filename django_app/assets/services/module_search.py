"""Ricerca trasversale del modulo Assets / Manutenzione.

Il campo di ricerca in testa a ogni pagina del modulo cercava solo negli asset.
Qui una sola domanda interroga tutto quello che il modulo conserva — asset,
piani, scadenze (ordinarie e amministrative), interventi, segnalazioni,
manutenzioni eseguite, contratti, licenze, documenti — e restituisce i risultati
raggruppati per categoria, ciascuno con il link alla sua pagina.

SOLA LETTURA. Ogni categoria entra nel risultato solo se chi cerca puo' aprire
la pagina elenco che la rappresenta (stessa decisione del middleware ACL,
fail-closed): la ricerca non deve diventare una scorciatoia per leggere cio'
che la navigazione non mostrerebbe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from ..models import (
    Asset,
    AssetDocument,
    AssistanceContract,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    SoftwareLicense,
    WorkOrder,
)

MIN_LENGTH = 2
DEFAULT_LIMIT = 8


@dataclass
class SearchHit:
    title: str
    url: str
    subtitle: str = ""
    badge: str = ""
    badge_class: str = "badge-muted"
    when: date | None = None

    def as_json(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "subtitle": self.subtitle,
            "badge": self.badge,
            "badge_class": self.badge_class,
            "when": self.when.strftime("%d/%m/%Y") if self.when else "",
        }


@dataclass
class SearchGroup:
    key: str
    label: str
    hits: list[SearchHit] = field(default_factory=list)
    total: int = 0
    more_url: str = ""

    @property
    def has_more(self) -> bool:
        return self.total > len(self.hits)

    def as_json(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "total": self.total,
            "more_url": self.more_url,
            "hits": [hit.as_json() for hit in self.hits],
        }


def _allows(request, path: str) -> bool:
    from core.middleware import acl_allows_path

    try:
        return bool(acl_allows_path(path, django_user=getattr(request, "user", None), request=request))
    except Exception:
        # Nel dubbio la categoria non si mostra: fail-closed.
        return False


def _with_q(url: str, term: str, **extra) -> str:
    return f"{url}?{urlencode({'q': term, **extra})}"


def _asset_label(asset) -> str:
    if asset is None:
        return ""
    tag = asset.asset_tag or ""
    return f"{tag} · {asset.name}" if tag and asset.name else (tag or asset.name or "")


def _asset_q(term: str, prefix: str = "asset__") -> Q:
    return (
        Q(**{f"{prefix}asset_tag__icontains": term})
        | Q(**{f"{prefix}name__icontains": term})
        | Q(**{f"{prefix}internal_number__icontains": term})
    )


def _occurrence_state(occ: MaintenanceOccurrence, today: date) -> tuple[str, str]:
    if occ.status == MaintenanceOccurrence.STATUS_DONE:
        return "Eseguita", "badge-success"
    if occ.due_date < today:
        return "Scaduta", "badge-danger"
    if occ.work_order_id:
        return "Pianificata", "badge-info"
    if (occ.due_date - today).days <= int(occ.warning_days or 30):
        return "In scadenza", "badge-warning"
    return "Aperta", "badge-muted"


def _group(key: str, label: str, queryset, build, *, limit: int, more_url: str = "") -> SearchGroup:
    total = queryset.count()
    hits = [build(obj) for obj in queryset[:limit]] if total else []
    return SearchGroup(key=key, label=label, hits=hits, total=total, more_url=more_url)


def search(request, term: str, *, limit: int = DEFAULT_LIMIT) -> list[SearchGroup]:
    """Gruppi di risultati per ``term``, nell'ordine in cui servono a chi lavora.

    I gruppi vuoti non si restituiscono. ``limit`` e' per gruppo: il totale reale
    resta in ``SearchGroup.total`` e ``more_url`` porta all'elenco completo quando
    la pagina elenco sa filtrare per testo.
    """
    term = (term or "").strip()
    if len(term) < MIN_LENGTH:
        return []
    today = timezone.localdate()
    groups: list[SearchGroup] = []

    # --- Asset -------------------------------------------------------------
    asset_list = reverse("assets:asset_list")
    if _allows(request, asset_list):
        qs = (
            Asset.objects.filter(
                _asset_q(term, prefix="")
                | Q(serial_number__icontains=term)
                | Q(manufacturer__icontains=term)
                | Q(model__icontains=term)
                | Q(reparto__icontains=term)
                | Q(assignment_to__icontains=term)
            )
            .select_related("asset_category")
            .order_by("asset_tag", "id")
        )
        groups.append(_group(
            "asset", "Asset", qs,
            lambda a: SearchHit(
                title=_asset_label(a),
                url=reverse("assets:asset_view", args=[a.id]),
                subtitle=" · ".join(p for p in (
                    a.asset_category.label if a.asset_category_id else "",
                    a.reparto,
                    f"S/N {a.serial_number}" if a.serial_number else "",
                ) if p),
                badge=a.get_status_display(),
            ),
            limit=limit, more_url=_with_q(asset_list, term),
        ))

    # --- Piani di manutenzione --------------------------------------------
    plan_list = reverse("assets:maintenance_plan_list")
    if _allows(request, plan_list):
        qs = MaintenanceInterventionTemplate.objects.filter(
            Q(label__icontains=term) | Q(code__icontains=term) | Q(description__icontains=term)
        ).select_related("asset_category").order_by("label", "id")
        groups.append(_group(
            "plans", "Piani di manutenzione", qs,
            lambda p: SearchHit(
                title=p.label,
                url=reverse("assets:maintenance_plan_detail", args=[p.id]),
                subtitle=" · ".join(x for x in (
                    p.get_maintenance_type_display(),
                    p.asset_category.label if p.asset_category_id else "",
                ) if x),
            ),
            limit=limit, more_url=_with_q(plan_list, term),
        ))

    # --- Scadenze (occorrenze aperte): ordinarie e amministrative ----------
    scadenzario = reverse("assets:maintenance_scadenze")
    if _allows(request, scadenzario):
        open_occ = (
            MaintenanceOccurrence.objects.filter(status=MaintenanceOccurrence.STATUS_OPEN)
            .filter(Q(plan__label__icontains=term) | _asset_q(term) | Q(asset__reparto__icontains=term))
            .select_related("plan", "asset")
            .order_by("due_date", "id")
        )

        def occ_hit(occ):
            badge, badge_class = _occurrence_state(occ, today)
            return SearchHit(
                title=occ.plan.label,
                url=reverse("assets:occurrence_complete", args=[occ.id]),
                subtitle=" · ".join(x for x in (
                    _asset_label(occ.asset),
                    f"OdL #{occ.work_order_id}" if occ.work_order_id else "da pianificare",
                ) if x),
                badge=badge, badge_class=badge_class, when=occ.due_date,
            )

        admin_type = MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE
        groups.append(_group(
            "deadlines", "Scadenze di manutenzione",
            open_occ.exclude(plan__maintenance_type=admin_type), occ_hit,
            limit=limit, more_url=_with_q(scadenzario, term, window="", plan_type="ordinary"),
        ))
        admin_group = _group(
            "admin", "Scadenze amministrative",
            open_occ.filter(plan__maintenance_type=admin_type), occ_hit,
            limit=limit, more_url=_with_q(scadenzario, term, window="", plan_type="administrative"),
        )
        # Le vecchie scadenze non ancora migrate a occorrenza restano visibili.
        from .deadline_feed import legacy_deadlines_qs

        legacy = (
            legacy_deadlines_qs()
            .filter(Q(title__icontains=term) | Q(reference_code__icontains=term) | Q(issuer__icontains=term)
                    | _asset_q(term))
            .select_related("asset")
            .order_by("due_date", "id")
        )
        legacy_total = legacy.count()
        if legacy_total:
            admin_group.total += legacy_total
            for deadline in legacy[: max(0, limit - len(admin_group.hits))]:
                late = deadline.due_date < today
                admin_group.hits.append(SearchHit(
                    title=deadline.title,
                    url=reverse("assets:asset_administrative_deadline_edit", args=[deadline.id]),
                    subtitle=" · ".join(x for x in (_asset_label(deadline.asset), deadline.issuer) if x),
                    badge="Scaduta" if late else "Aperta",
                    badge_class="badge-danger" if late else "badge-muted",
                    when=deadline.due_date,
                ))
        groups.append(admin_group)

    # --- Interventi (ordini di lavoro) -------------------------------------
    wo_list = reverse("assets:wo_list")
    if _allows(request, wo_list):
        wo_q = (
            Q(title__icontains=term) | Q(description__icontains=term) | Q(resolution__icontains=term)
            | _asset_q(term) | Q(supplier__ragione_sociale__icontains=term)
        )
        if term.lstrip("#").isdigit():
            wo_q |= Q(pk=int(term.lstrip("#")))
        qs = WorkOrder.objects.filter(wo_q).select_related("asset", "assigned_to").order_by("-opened_at", "-id")

        def wo_hit(wo):
            if wo.status == WorkOrder.STATUS_OPEN:
                badge, badge_class = ("In attesa", "badge-muted") if wo.is_waiting else (
                    ("In corso", "badge-primary") if wo.started_at else ("Aperto", "badge-info"))
            elif wo.status == WorkOrder.STATUS_DONE:
                badge, badge_class = "Chiuso", "badge-success"
            else:
                badge, badge_class = wo.get_status_display(), "badge-muted"
            assignee = wo.assigned_to.get_full_name() or wo.assigned_to.username if wo.assigned_to_id else ""
            return SearchHit(
                title=f"#{wo.pk} · {wo.title}",
                url=reverse("assets:wo_view", args=[wo.pk]),
                subtitle=" · ".join(x for x in (_asset_label(wo.asset), wo.get_kind_display(), assignee) if x),
                badge=badge, badge_class=badge_class,
                when=timezone.localtime(wo.opened_at).date() if wo.opened_at else None,
            )

        groups.append(_group("workorders", "Interventi", qs, wo_hit,
                             limit=limit, more_url=_with_q(wo_list, term, view="all")))

    # --- Segnalazioni (ticket di manutenzione) ------------------------------
    try:
        tickets_list = reverse("tickets:gestione_list")
    except Exception:
        tickets_list = ""
    if tickets_list and _allows(request, tickets_list):
        try:
            from tickets.models import Ticket, TipoTicket

            qs = (
                Ticket.objects.filter(tipo=TipoTicket.MAN)
                .filter(Q(titolo__icontains=term) | Q(descrizione__icontains=term)
                        | Q(numero_ticket__icontains=term) | Q(asset_descrizione_libera__icontains=term)
                        | _asset_q(term))
                .select_related("asset")
                .order_by("-created_at", "-id")
            )
            groups.append(_group(
                "tickets", "Segnalazioni", qs,
                lambda t: SearchHit(
                    title=f"{t.numero_ticket} · {t.titolo}",
                    url=reverse("tickets:gestione_detail", kwargs={"pk": t.pk}),
                    subtitle=_asset_label(t.asset) if t.asset_id else (t.asset_descrizione_libera or ""),
                    badge=t.label_stato,
                    when=timezone.localtime(t.created_at).date() if t.created_at else None,
                ),
                limit=limit, more_url=_with_q(tickets_list, term),
            ))
        except Exception:
            pass

    # --- Manutenzioni eseguite (storico) -----------------------------------
    history = reverse("assets:maintenance_history")
    if _allows(request, history):
        qs = (
            MaintenanceOccurrence.objects.filter(status=MaintenanceOccurrence.STATUS_DONE)
            .filter(Q(plan__label__icontains=term) | _asset_q(term) | Q(completion_notes__icontains=term))
            .select_related("plan", "asset")
            .order_by("-completed_on", "-id")
        )
        groups.append(_group(
            "history", "Manutenzioni eseguite", qs,
            lambda occ: SearchHit(
                title=occ.plan.label,
                url=reverse("assets:occurrence_complete", args=[occ.id]),
                subtitle=_asset_label(occ.asset),
                badge="Eseguita", badge_class="badge-success", when=occ.completed_on,
            ),
            limit=limit, more_url=_with_q(history, term),
        ))

    # --- Contratti di assistenza --------------------------------------------
    contracts = reverse("assets:assistance_contract_list")
    if _allows(request, contracts):
        qs = (
            AssistanceContract.objects.filter(
                Q(title__icontains=term) | Q(code__icontains=term) | Q(notes__icontains=term)
                | Q(supplier__ragione_sociale__icontains=term) | _asset_q(term)
            )
            .select_related("supplier", "asset")
            .order_by("end_date", "id")
        )
        groups.append(_group(
            "contracts", "Contratti di assistenza", qs,
            lambda c: SearchHit(
                title=c.title or c.code or "Contratto di assistenza",
                url=f"{contracts}?edit={c.id}",
                subtitle=" · ".join(x for x in (str(c.supplier) if c.supplier_id else "", _asset_label(c.asset)) if x),
                badge="Attivo" if c.is_active else "Non attivo",
                badge_class="badge-success" if c.is_active else "badge-muted",
                when=c.end_date,
            ),
            limit=limit, more_url=_with_q(contracts, term),
        ))

    # --- Licenze software ---------------------------------------------------
    licenses = reverse("assets:software_license_list")
    if _allows(request, licenses):
        qs = (
            SoftwareLicense.objects.filter(
                Q(product_name__icontains=term) | Q(vendor__icontains=term) | Q(edition__icontains=term)
                | Q(license_reference__icontains=term) | _asset_q(term)
            )
            .select_related("asset")
            .order_by("expiry_date", "id")
        )
        groups.append(_group(
            "licenses", "Licenze software", qs,
            lambda lic: SearchHit(
                title=str(lic),
                url=f"{licenses}?edit={lic.id}",
                subtitle=" · ".join(x for x in (lic.vendor, _asset_label(lic.asset) if lic.asset_id else "") if x),
                when=lic.expiry_date,
            ),
            limit=limit, more_url=_with_q(licenses, term),
        ))

    # --- Documenti degli asset ----------------------------------------------
    if _allows(request, asset_list):
        qs = (
            AssetDocument.objects.filter(
                Q(original_name__icontains=term) | Q(notes__icontains=term) | _asset_q(term)
            )
            .select_related("asset")
            .order_by("-id")
        )
        groups.append(_group(
            "documents", "Documenti", qs,
            lambda d: SearchHit(
                title=d.original_name or d.get_category_display(),
                url=reverse("assets:asset_document_download", args=[d.id]),
                subtitle=" · ".join(x for x in (d.get_category_display(), _asset_label(d.asset)) if x),
                when=d.document_date,
            ),
            limit=limit,
        ))

    return [group for group in groups if group.total]
