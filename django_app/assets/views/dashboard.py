"""Cruscotto Asset e segnalazione guasto.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from core.models import UserExtraInfo
from core.module_branding import (
    get_module_branding_context,
)
from ..forms import (
    IT_DEVICE_TYPES,
)
from ..models import (
    Asset,
    AssetCategory,
    AssetDashboardConfig,
    PeriodicVerification,
    WorkOrder,
)
from ..services.dashboard_kpi import (
    get_downtime_by_family,
    get_families_distribution,
    get_family_dashboard_kpis,
    get_fire_safety_kpis,
    get_maintenance_by_family,
    get_maintenance_performance_kpis,
)

from ._helpers import (  # noqa: F401
    _as_int,
    _clean_string,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
)

def _default_man_category(categorie: list[tuple[str, str]]) -> str:
    """Categoria usata quando chi segnala non ne sceglie una.

    Nessuna impostazione nuova: «Generica» se e' fra le categorie MAN attive, poi
    «Altro Manutenzione», altrimenti la prima attiva (``get_categorie`` ripiega
    comunque sull'elenco predefinito, quindi un valore c'e' sempre).
    """
    codes = [code for code, _label in categorie]
    for preferred in ("GENERICA", "ALTRO_MAN"):
        if preferred in codes:
            return preferred
    return codes[0] if codes else "GENERICA"


# Priorita' proposte a chi segnala dal campo: tre scelte grandi, non quattro.
# «Urgente» resta accettata dal POST (link o form vecchi) ma non si propone: chi
# segnala da telefono dice quanto e' grave, l'urgenza la decide la manutenzione.
QUICK_REPORT_PRIORITIES = (("BASSA", "Bassa"), ("MEDIA", "Media"), ("ALTA", "Alta"))
QUICK_REPORT_MAX_PHOTOS = 3
QUICK_REPORT_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
QUICK_REPORT_PHOTO_MIMES = {"image/jpeg", "image/png"}


@login_required
def asset_quick_report(request: HttpRequest) -> HttpResponse:
    """P3.2 — Segnalazione guasto per operatori non-admin (anche da telefono, dal QR).

    Crea un Ticket MAN con asset, descrizione, priorita' e fino a tre foto. Con
    ``?asset=<id>`` l'asset e' fissato (intestazione, niente elenco); con
    ``?from=qr`` la pagina e' quella minimale della landing QR, senza la shell del
    modulo. Il login resta obbligatorio anche arrivando dal QR pubblico.
    """
    from tickets.allegati import AllegatoError, carica_allegato, qr_rate_limited, registra_caricamento
    from tickets.models import TipoTicket, PrioritaTicket, Ticket, get_categorie

    from_qr = _clean_string(request.GET.get("from") or request.POST.get("from")).lower() == "qr"
    raw_asset = request.GET.get("asset") or request.POST.get("fixed_asset")
    fixed_asset = None
    if raw_asset:
        # Stessa regola della landing QR: un asset inesistente non si segnala.
        fixed_asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=_as_int(raw_asset, default=0))

    asset_choices = []
    if fixed_asset is None:
        # Asset selezionabili: macchine e asset di produzione (no IT puro)
        asset_choices = list(
            Asset.objects
            .filter(status=Asset.STATUS_IN_USE)
            .exclude(asset_type__in=IT_DEVICE_TYPES)
            .order_by("reparto", "name", "asset_tag")
            .values("id", "asset_tag", "name", "reparto")
        )

    categorie_man = get_categorie(TipoTicket.MAN)
    default_categoria = _default_man_category(categorie_man)
    valid_priorities = dict(PrioritaTicket.choices)

    error: str = ""
    success_ticket = None
    photo_notes: list[str] = []

    if request.method == "POST":
        asset_id = fixed_asset.id if fixed_asset is not None else _as_int(request.POST.get("asset_id"), default=0)
        asset_libera = "" if fixed_asset is not None else _clean_string(request.POST.get("asset_descrizione_libera"))
        categoria = _clean_string(request.POST.get("categoria"))
        titolo = _clean_string(request.POST.get("titolo"))
        descrizione = _clean_string(request.POST.get("descrizione"))
        priorita = _clean_string(request.POST.get("priorita")) or PrioritaTicket.MEDIA
        incide_sicurezza = request.POST.get("incide_sicurezza") == "1"
        photos = request.FILES.getlist("foto")

        if not titolo or not descrizione:
            error = "Titolo e descrizione sono obbligatori."
        elif not asset_id and not asset_libera:
            error = "Seleziona un asset o descrivi il punto di intervento."
        elif len(photos) > QUICK_REPORT_MAX_PHOTOS:
            error = f"Puoi allegare al massimo {QUICK_REPORT_MAX_PHOTOS} foto."
        else:
            if priorita not in valid_priorities:
                priorita = PrioritaTicket.MEDIA
            if categoria not in {code for code, _label in categorie_man}:
                categoria = default_categoria

            asset_obj = fixed_asset
            if asset_obj is None and asset_id:
                asset_obj = Asset.objects.filter(pk=asset_id).only("id").first()

            # Identità richiedente dal legacy user o dall'utente Django. UserExtraInfo e'
            # in core.models (importato in testa): l'import da anagrafica.models falliva
            # e ogni invio rispondeva 500.
            legacy_user = getattr(request, "legacy_user", None)
            if legacy_user is None:
                try:
                    extra = UserExtraInfo.objects.filter(user=request.user).select_related("user").first()
                    legacy_user = extra
                except Exception:
                    legacy_user = None

            if legacy_user and hasattr(legacy_user, "nome"):
                req_name = (_clean_string(getattr(legacy_user, "nome", "")) or request.user.get_full_name() or request.user.get_username())
                req_email = (_clean_string(getattr(legacy_user, "email", "")) or request.user.email or "").lower()
                req_legacy_id = getattr(legacy_user, "id", None)
            else:
                req_name = request.user.get_full_name() or request.user.get_username()
                req_email = (request.user.email or "").lower()
                req_legacy_id = None

            ticket = Ticket(
                tipo=TipoTicket.MAN,
                titolo=titolo,
                descrizione=descrizione,
                categoria=categoria,
                priorita=priorita,
                incide_sicurezza=incide_sicurezza,
                asset=asset_obj,
                asset_descrizione_libera=asset_libera if not asset_obj else "",
                richiedente_nome=req_name,
                richiedente_email=req_email,
                richiedente_legacy_user_id=req_legacy_id,
                include_in_maintenance_register=True,
            )
            try:
                ticket.save()
            except Exception as exc:
                error = f"Errore nella creazione del ticket: {exc}"
            else:
                # Foto: il ticket esiste gia'. Una foto rifiutata (formato, peso) si
                # scarta e si dice quale, senza perdere la segnalazione.
                saved_photos = []
                if photos and asset_obj is not None and qr_rate_limited(request, asset_obj.id):
                    photo_notes.append("Troppi invii ravvicinati: le foto non sono state salvate, la segnalazione si'.")
                    photos = []
                for photo in photos:
                    try:
                        saved_photos.append(
                            carica_allegato(
                                ticket,
                                photo,
                                caricato_da_nome=req_name,
                                caricato_da_email=req_email,
                                descrizione="Foto della segnalazione",
                                allowed_extensions=QUICK_REPORT_PHOTO_EXTENSIONS,
                                allowed_mimes=QUICK_REPORT_PHOTO_MIMES,
                            )
                        )
                    except AllegatoError as exc:
                        photo_notes.append(f"Foto «{getattr(photo, 'name', 'senza nome')}» scartata: {exc}")
                if saved_photos:
                    registra_caricamento(ticket, saved_photos)
                log_action(
                    request,
                    "asset_quick_report_create",
                    "assets",
                    {
                        "ticket_id": ticket.id,
                        "ticket_numero": ticket.numero_ticket,
                        "asset_id": asset_id,
                        "categoria": categoria,
                        "priorita": priorita,
                        "foto": len(saved_photos),
                        "da_qr": from_qr,
                    },
                )
                success_ticket = ticket

    landing_url = (
        reverse("assets:asset_qr_landing", kwargs={"asset_tag": fixed_asset.asset_tag}) if fixed_asset is not None else ""
    )
    again_url = reverse("assets:asset_quick_report")
    if fixed_asset is not None:
        again_url += f"?asset={fixed_asset.id}" + ("&from=qr" if from_qr else "")
    context = {
        "page_title": "Segnala un problema",
        "fixed_asset": fixed_asset,
        "asset_choices": asset_choices,
        "categorie_man": categorie_man,
        "default_categoria": default_categoria,
        "priorita_choices": QUICK_REPORT_PRIORITIES,
        "max_photos": QUICK_REPORT_MAX_PHOTOS,
        "error": error,
        "success_ticket": success_ticket,
        "success_ticket_id": success_ticket.id if success_ticket is not None else None,
        "photo_notes": photo_notes,
        "from_qr": from_qr,
        "landing_url": landing_url,
        "again_url": again_url,
    }
    if from_qr:
        # Come la landing QR: pagina minimale, niente sidebar/shell del modulo.
        return render(request, "assets/pages/asset_quick_report_qr.html", context)
    return render(
        request,
        "assets/pages/asset_quick_report.html",
        {**context, **_assets_shell_context(request, rows=25)},
    )


# ---------------------------------------------------------------------------
# Dashboard Assets
# ---------------------------------------------------------------------------

_WIDGET_META: dict[str, dict] = {
    "totale_asset": {"label": "Totale asset", "icon": "package", "color": "blue"},
    "asset_in_uso": {"label": "In uso", "icon": "check-circle", "color": "green"},
    "asset_in_riparazione": {"label": "In riparazione", "icon": "wrench", "color": "orange"},
    "scadenze_scadute": {"label": "Scadenze scadute", "icon": "alert-triangle", "color": "red"},
    "scadenze_30gg": {"label": "Scadenze 30 gg", "icon": "clock", "color": "yellow"},
    "scadenze_90gg": {"label": "Scadenze 90 gg", "icon": "calendar", "color": "slate"},
    "wo_aperte": {"label": "OdL aperte", "icon": "clipboard-list", "color": "blue"},
    "wo_chiuse_mese": {"label": "OdL chiuse (mese)", "icon": "clipboard-check", "color": "green"},
    "verifiche_scadute": {"label": "Piani scaduti", "icon": "shield-alert", "color": "red"},
    "verifiche_30gg": {"label": "Piani in scadenza 30 gg", "icon": "shield-check", "color": "yellow"},
    "asset_per_stato": {"label": "Asset per stato", "icon": "bar-chart", "color": "slate"},
    "asset_per_categoria": {"label": "Asset per categoria", "icon": "layers", "color": "slate"},
}


def _compute_dashboard_kpis(today: date) -> dict:
    """Calcola tutti i valori KPI per la dashboard assets."""

    in_30 = today + timedelta(days=30)
    in_90 = today + timedelta(days=90)
    first_day_month = today.replace(day=1)

    total = Asset.objects.exclude(status=Asset.STATUS_RETIRED).count()
    in_uso = Asset.objects.filter(status=Asset.STATUS_IN_USE).count()
    in_repair = Asset.objects.filter(status=Asset.STATUS_IN_REPAIR).count()

    # Scadenze amministrative: registro separato dai piani, senza le copie
    # migrate (``deadline_feed``).
    from ..services import deadline_feed as feed

    admin_dues = feed.administrative_dues(due_to=in_90, exclude_retired=False)
    dl_scadute = sum(1 for due in admin_dues if due.due_date < today)
    dl_30 = sum(1 for due in admin_dues if today <= due.due_date <= in_30)
    dl_90 = sum(1 for due in admin_dues if in_30 < due.due_date <= in_90)

    # OdL
    wo_aperte = WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN).count()
    wo_chiuse_mese = WorkOrder.objects.filter(
        status=WorkOrder.STATUS_DONE, closed_at__date__gte=first_day_month
    ).count()

    # Verifiche periodiche
    pv_qs = PeriodicVerification.objects.filter(is_active=True, is_legacy=False, next_verification_date__isnull=False)
    pv_scadute = pv_qs.filter(next_verification_date__lt=today).count()
    pv_30 = pv_qs.filter(next_verification_date__gte=today, next_verification_date__lte=in_30).count()

    # Asset per stato
    status_map = dict(Asset.STATUS_CHOICES)
    per_stato_qs = Asset.objects.values("status").annotate(n=Count("id")).order_by("-n")
    per_stato = [
        {"status": r["status"], "label": status_map.get(r["status"], r["status"]), "count": r["n"]}
        for r in per_stato_qs
    ]

    # Asset per categoria (top 10 + "Altro")
    per_cat_qs = list(
        Asset.objects.values("asset_category__id", "asset_category__label")
        .annotate(n=Count("id"))
        .order_by("-n")[:12]
    )
    per_categoria = []
    for r in per_cat_qs:
        per_categoria.append({
            "id": r["asset_category__id"],
            "label": r["asset_category__label"] or "Senza categoria",
            "count": r["n"],
        })

    # Prossime scadenze (lista breve)
    prossime_scadenze = [due for due in admin_dues if today <= due.due_date <= in_30][:8]
    prossime_verifiche = list(
        PeriodicVerification.objects.filter(is_active=True, next_verification_date__gte=today, next_verification_date__lte=in_30)
        .order_by("next_verification_date")[:8]
    )
    scadenze_arretrate = [due for due in admin_dues if due.due_date < today][:8]

    return {
        "totale_asset": total,
        "asset_in_uso": in_uso,
        "asset_in_riparazione": in_repair,
        "scadenze_scadute": dl_scadute,
        "scadenze_30gg": dl_30,
        "scadenze_90gg": dl_90,
        "wo_aperte": wo_aperte,
        "wo_chiuse_mese": wo_chiuse_mese,
        "verifiche_scadute": pv_scadute,
        "verifiche_30gg": pv_30,
        "asset_per_stato": per_stato,
        "asset_per_categoria": per_categoria,
        # dati lista per le card detail
        "prossime_scadenze": prossime_scadenze,
        "prossime_verifiche": prossime_verifiche,
        "scadenze_arretrate": scadenze_arretrate,
    }


def _legacy_asset_dashboard_list_redirect_url(request: HttpRequest) -> str:
    if request.method != "GET" or not request.GET:
        return ""
    legacy_list_query_keys = {"q", "asset_type", "reparto", "vlan", "ip", "rows", "page"}
    if not any(key in request.GET for key in legacy_list_query_keys):
        return ""
    query_string = request.GET.urlencode()
    target_url = reverse("assets:asset_list")
    return f"{target_url}?{query_string}" if query_string else target_url


def _dashboard_workorders(request: HttpRequest, today: date, limit: int = 6) -> dict:
    """OdL aperti per il centro "Da fare": urgenti e in ritardo in testa."""
    from assets.maintenance import get_workorder_overdue_days

    now = timezone.now()
    age_threshold = today - timedelta(days=get_workorder_overdue_days())
    qs = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN)
        .exclude(asset__status=Asset.STATUS_RETIRED)
        .select_related("asset", "assigned_to")
    )
    open_rows = list(qs.order_by("opened_at", "id")[:400])

    def _late(wo) -> bool:
        if wo.due_at and wo.due_at < now:
            return True
        return bool(wo.opened_at and wo.opened_at.date() <= age_threshold)

    def _sort_key(wo):
        return (
            0 if wo.priority == WorkOrder.PRIORITY_URGENT else 1,
            0 if _late(wo) else 1,
            wo.opened_at or now,
        )

    items = []
    for wo in sorted(open_rows, key=_sort_key)[:limit]:
        assignee = ""
        if wo.assigned_to_id:
            assignee = wo.assigned_to.get_full_name() or wo.assigned_to.get_username()
        opened = wo.opened_at.date() if wo.opened_at else None
        items.append({
            "id": wo.id,
            "title": wo.title,
            "asset_tag": wo.asset.asset_tag if wo.asset_id else "",
            "asset_name": wo.asset.name if wo.asset_id else "",
            "kind_label": wo.get_kind_display(),
            "is_urgent": wo.priority == WorkOrder.PRIORITY_URGENT,
            "is_late": _late(wo),
            "state_label": wo.operational_state_label,
            "state": wo.operational_state or "",
            "assignee": assignee,
            "is_mine": wo.assigned_to_id == request.user.id,
            "age_days": (today - opened).days if opened else None,
        })
    return {
        "items": items,
        "total": qs.count(),
        "urgent": sum(1 for wo in open_rows if wo.priority == WorkOrder.PRIORITY_URGENT),
        "late": sum(1 for wo in open_rows if _late(wo)),
        "unassigned": sum(1 for wo in open_rows if not wo.assigned_to_id),
        "mine": sum(1 for wo in open_rows if wo.assigned_to_id == request.user.id),
    }


def _dashboard_deadlines(request: HttpRequest, today: date, limit: int = 8) -> dict:
    """Scadenze (piani, amministrative, licenze, contratti) + verifiche periodiche
    entro 30 giorni o gia' scadute, in una lista sola. Sola lettura: le azioni
    puntano alle pagine che gia' le gestiscono."""
    from ..services import deadline_feed as feed

    horizon = today + timedelta(days=30)
    rows: list[dict] = []
    try:
        deadlines = feed.collect(
            start=None,
            end=horizon,
            filters=feed.FeedFilters(kinds=feed.allowed_kinds(request)),
            today=today,
        )
    except Exception:
        deadlines = []
    for dl in deadlines:
        if dl.state == feed.STATE_DONE:
            continue
        rows.append({
            "source": dl.kind,
            "source_label": dl.kind_label,
            "title": dl.title,
            "due_date": dl.due_date,
            "days": (dl.due_date - today).days,
            "is_overdue": dl.due_date < today,
            "asset_tag": dl.asset_tag,
            "asset_name": dl.asset_name or dl.target_label,
            "url": dl.detail_url,
            "action_label": (dl.actions[0]["label"] if dl.actions else "Apri"),
            "work_order_id": dl.work_order_id,
        })
    verifications = PeriodicVerification.objects.filter(
        is_active=True, is_legacy=False, next_verification_date__isnull=False,
        next_verification_date__lte=horizon,
    ).order_by("next_verification_date")[:200]
    pv_url = reverse("assets:periodic_verifications")
    for pv in verifications:
        rows.append({
            "source": "verification",
            "source_label": "Verifica",
            "title": pv.name,
            "due_date": pv.next_verification_date,
            "days": (pv.next_verification_date - today).days,
            "is_overdue": pv.next_verification_date < today,
            "asset_tag": "",
            "asset_name": "",
            "url": pv_url,
            "action_label": "Gestisci",
            "work_order_id": None,
        })
    rows.sort(key=lambda r: (r["due_date"], r["title"]))
    overdue = [r for r in rows if r["is_overdue"]]
    plan_sources = {feed.KIND_ORDINARY, "verification"}
    return {
        "items": rows[:limit],
        "total": len(rows),
        "overdue": len(overdue),
        "due_soon": len(rows) - len(overdue),
        "maintenance_overdue": sum(1 for r in overdue if r["source"] == feed.KIND_ORDINARY),
        "maintenance_due_soon": sum(
            1 for r in rows if r["source"] == feed.KIND_ORDINARY and not r["is_overdue"]
        ),
        # Scadenze dei piani (regole + eventuali piani periodici non ancora
        # convertiti): alimentano i riquadri "Verifiche" della dashboard.
        "plan_overdue": sum(1 for r in overdue if r["source"] in plan_sources),
        "plan_due_soon": sum(1 for r in rows if r["source"] in plan_sources and not r["is_overdue"]),
        "plan_upcoming": [r for r in rows if r["source"] in plan_sources and not r["is_overdue"]][:8],
    }


def _dashboard_launcher(request: HttpRequest, counters: dict) -> list[dict]:
    """Collegamenti alle parti principali del modulo, filtrati con la stessa
    decisione ACL del middleware (fail-closed): non si mostrano porte chiuse."""
    from core.middleware import acl_allows_path

    tiles = [
        ("inventory", "Inventario", "Tutti gli asset, filtri ed export", reverse("assets:asset_list"), counters.get("assets"), ""),
        ("hub", "Centro manutenzione", "Punto di partenza del manutentore", reverse("assets:maintenance_hub"), None, ""),
        ("todo", "Da fare", "Manutenzioni programmate aperte", reverse("assets:maintenance_da_fare"), counters.get("maintenance_overdue"), "red"),
        ("workorders", "Ordini di lavoro", "Interventi aperti e chiusi", reverse("assets:wo_list"), counters.get("wo_open"), "amber"),
        ("shift", "Il mio lavoro", "Le manutenzioni e gli interventi tuoi e di nessuno", f"{reverse('assets:maintenance_da_fare')}?mio=1", counters.get("wo_mine"), "blue"),
        ("deadlines", "Scadenzario", "Scadenze di piani, adempimenti e contratti", reverse("assets:maintenance_scadenze"), counters.get("deadlines_overdue"), "red"),
        ("plans", "Piani di manutenzione", "Cicli e frequenze per asset", reverse("assets:maintenance_plan_list"), None, ""),
        ("checks", "Verifiche impianti", "Luci di emergenza, estintori, impianti", reverse("assets:periodic_check_list"), None, ""),
        ("map", "Mappa officina", "Stato delle macchine in planimetria", reverse("assets:plant_layout_map"), None, ""),
        ("machines", "Macchine di lavoro", "Cruscotto del parco produttivo", reverse("assets:work_machine_dashboard"), None, ""),
        ("tickets", "Segnalazioni", "Ticket di manutenzione dagli operatori", f"{reverse('tickets:gestione_list')}?tipo=MAN", counters.get("tickets_new"), "amber"),
        ("history", "Storico", "Interventi eseguiti e registro", reverse("assets:maintenance_history"), None, ""),
        ("reports", "Report", "Report e analisi del modulo", reverse("assets:reports"), None, ""),
    ]
    user = getattr(request, "user", None)
    output = []
    for code, label, hint, url, count, tone in tiles:
        try:
            allowed = acl_allows_path(url.split("?", 1)[0], django_user=user, request=request)
        except Exception:
            allowed = False
        if not allowed:
            continue
        output.append({
            "code": code, "label": label, "hint": hint, "url": url,
            "count": count or 0, "tone": tone if count else "",
        })
    return output


@login_required
def asset_dashboard(request: HttpRequest) -> HttpResponse:
    """Dashboard principale del modulo Assets con KPI personalizzabili."""
    legacy_list_redirect = _legacy_asset_dashboard_list_redirect_url(request)
    if legacy_list_redirect:
        return redirect(legacy_list_redirect)

    today = timezone.localdate()
    selected_family_id = None
    selected_family_label = ""
    raw_family_id = request.GET.get("family")
    if raw_family_id:
        try:
            candidate_family_id = int(raw_family_id)
        except (TypeError, ValueError):
            candidate_family_id = None
        if candidate_family_id:
            selected_family = AssetCategory.objects.filter(pk=candidate_family_id, is_active=True).first()
            if selected_family:
                selected_family_id = selected_family.id
                selected_family_label = selected_family.label

    # Configurazione widget utente
    cfg, _ = AssetDashboardConfig.objects.get_or_create(user=request.user)
    enabled = cfg.get_enabled_widgets()

    kpis = _compute_dashboard_kpis(today)
    family_kpis = get_family_dashboard_kpis(selected_family_id, today=today)
    family_distribution = get_families_distribution(today=today)
    maintenance_by_family = get_maintenance_by_family(today=today)
    downtime_by_family = get_downtime_by_family(today=today)
    fire_safety_kpis = get_fire_safety_kpis(today=today)
    try:
        maintenance_perf = get_maintenance_performance_kpis(today=today)
    except Exception:
        maintenance_perf = {
            "mttr_hours": 0, "downtime_hours_month": 0, "maintenance_cost_month": 0,
            "wo_open_by_kind": {}, "wo_open_total": 0, "ticket_man_open": 0,
            "wo_closed_month": 0, "has_data": False,
        }

    # Cruscotto operativo (cose da fare + segnalazioni arrivate), condiviso con il Centro Manutenzione
    from assets.services.dashboard_kpi import get_cose_da_fare_overview, get_segnalazioni_overview
    cose_da_fare = get_cose_da_fare_overview(today=today)
    segnalazioni = get_segnalazioni_overview(today=today)

    # Centro "Da fare": interventi, segnalazioni e scadenze con le azioni rapide
    dash_wo = _dashboard_workorders(request, today)
    dash_deadlines = _dashboard_deadlines(request, today)
    from tickets.views import _can_manage_tickets
    from tickets.models import TipoTicket

    try:
        can_manage_man = _can_manage_tickets(request, TipoTicket.MAN)
    except Exception:
        can_manage_man = False
    attention_total = (
        dash_wo["urgent"] + dash_wo["late"] + segnalazioni["urgenti"] + dash_deadlines["overdue"]
    )
    launcher = _dashboard_launcher(request, {
        "assets": kpis["totale_asset"],
        "maintenance_overdue": dash_deadlines["maintenance_overdue"],
        "wo_open": dash_wo["total"],
        "wo_mine": dash_wo["mine"],
        "deadlines_overdue": dash_deadlines["overdue"],
        "tickets_new": segnalazioni["nuove"],
    })
    # I piani periodici sono convertiti in regole: le "Verifiche" della
    # dashboard contano le scadenze dei piani, non piu' la vecchia tabella.
    kpis["verifiche_scadute"] = dash_deadlines["plan_overdue"]
    kpis["verifiche_30gg"] = dash_deadlines["plan_due_soon"]
    kpis["prossime_verifiche"] = dash_deadlines["plan_upcoming"]
    status_rows = [row for row in kpis["asset_per_stato"] if row["status"] != Asset.STATUS_RETIRED]
    categories = list(AssetCategory.objects.filter(is_active=True).order_by("sort_order", "label"))
    family_options = categories
    # Categorie per la barra "Inventario per categoria": le piu' popolose in vista,
    # le altre dietro "+ altre" (sono decine e coprivano la pagina).
    category_counts = dict(
        Asset.objects.exclude(status=Asset.STATUS_RETIRED)
        .values_list("asset_category_id")
        .annotate(n=Count("id"))
        .order_by()
    )
    for cat in categories:
        cat.asset_count = int(category_counts.get(cat.id) or 0)
    by_count = sorted(categories, key=lambda c: (-c.asset_count, c.label.lower()))
    categories_top = [c for c in by_count if c.asset_count][:10]
    top_ids = {c.id for c in categories_top}
    categories_rest = [c for c in categories if c.id not in top_ids]


    # Metadati widget arricchiti con valore
    widgets_all = []
    for code, meta in _WIDGET_META.items():
        widgets_all.append({
            "code": code,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "enabled": code in enabled,
            "order": enabled.index(code) if code in enabled else 999,
        })
    widgets_all.sort(key=lambda w: (0 if w["enabled"] else 1, w["order"]))

    branding = get_module_branding_context("assets")

    ctx = _assets_shell_context(request, search_action=reverse("assets:asset_list"))
    ctx.update({
        "today": today,
        "kpis": kpis,
        "enabled_widgets": enabled,
        "enabled_widgets_json": json.dumps(enabled),
        "widgets_all": widgets_all,
        "categories": categories,
        "selected_family_id": selected_family_id,
        "selected_family_label": selected_family_label,
        "family_options": family_options,
        "family_kpis": family_kpis,
        "family_distribution": family_distribution,
        "maintenance_by_family": maintenance_by_family,
        "downtime_by_family": downtime_by_family,
        "fire_safety_kpis": fire_safety_kpis,
        "maintenance_perf": maintenance_perf,
        "cose_da_fare": cose_da_fare,
        "segnalazioni": segnalazioni,
        "dash_wo": dash_wo,
        "dash_deadlines": dash_deadlines,
        "can_manage_man": can_manage_man,
        "attention_total": attention_total,
        "launcher": launcher,
        "status_rows": status_rows,
        "categories_top": categories_top,
        "categories_rest": categories_rest,
        "now": timezone.localtime(),
        "branding": branding,
        "page_title": "Dashboard",
    })
    return render(request, "assets/pages/asset_dashboard.html", ctx)


@login_required
def api_asset_dashboard_save_config(request: HttpRequest) -> JsonResponse:
    """Salva la configurazione widget dashboard per l'utente corrente."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Metodo non consentito"}, status=405)
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Payload non valido"}, status=400)

    widgets = payload.get("widgets")
    if not isinstance(widgets, list):
        return JsonResponse({"ok": False, "error": "Campo widgets obbligatorio (lista)"}, status=400)

    valid = set(AssetDashboardConfig.DEFAULT_WIDGETS)
    clean = [w for w in widgets if isinstance(w, str) and w in valid]

    cfg, _ = AssetDashboardConfig.objects.get_or_create(user=request.user)
    cfg.enabled_widgets = clean
    cfg.save(update_fields=["enabled_widgets", "updated_at"])
    return JsonResponse({"ok": True, "saved": len(clean)})
