"""Dominio delle verifiche periodiche sugli impianti.

Tutta la logica che cambia dati passa da qui (viste, import dello storico, test):
registrazione di una verifica, conferma, ricalcolo della prossima scadenza del tipo,
OdL dai rilievi non conformi. Vedi docs/ai/VERIFICHE_PERIODICHE.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from ..models import (
    PeriodicCheckAttachment,
    PeriodicCheckItem,
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckType,
    WorkOrder,
)

STATE_OVERDUE = "overdue"
STATE_DUE_SOON = "due_soon"
STATE_OK = "ok"
STATE_UNSCHEDULED = "unscheduled"

STATE_LABELS = {
    STATE_OVERDUE: "Scaduta",
    STATE_DUE_SOON: "In scadenza",
    STATE_OK: "In regola",
    STATE_UNSCHEDULED: "Da pianificare",
}


def type_state(check_type: PeriodicCheckType, today: date | None = None) -> str:
    today = today or timezone.localdate()
    due = check_type.next_due_date
    if due is None:
        return STATE_UNSCHEDULED
    if due < today:
        return STATE_OVERDUE
    if due <= today + timedelta(days=check_type.warning_days):
        return STATE_DUE_SOON
    return STATE_OK


@dataclass
class ResultInput:
    label: str
    result: str = PeriodicCheckResult.RESULT_OK
    note: str = ""
    item: PeriodicCheckItem | None = None
    kind: str = PeriodicCheckResult.KIND_ITEM
    point: object | None = None
    category: str = ""


@dataclass
class SessionInput:
    check_type: PeriodicCheckType
    performed_on: date
    outcome: str
    technician: str = ""
    supplier_id: int | None = None
    notes: str = ""
    next_due_date: date | None = None
    results: list[ResultInput] = field(default_factory=list)
    source: str = PeriodicCheckSession.SOURCE_MANUAL
    status: str = PeriodicCheckSession.STATUS_CONFIRMED
    import_key: str = ""


def outcome_from_results(results: Iterable[ResultInput], *, fallback: str) -> str:
    """Una voce non OK rende la verifica "con rilievi" se l'utente la dava conforme."""
    if fallback == PeriodicCheckSession.OUTCOME_OK and any(
        r.result == PeriodicCheckResult.RESULT_KO for r in results
    ):
        return PeriodicCheckSession.OUTCOME_REMARKS
    return fallback


@transaction.atomic
def register_session(data: SessionInput, *, user=None, files: Iterable = ()) -> PeriodicCheckSession:
    session = PeriodicCheckSession.objects.create(
        check_type=data.check_type,
        performed_on=data.performed_on,
        technician=data.technician[:120],
        supplier_id=data.supplier_id or data.check_type.supplier_id,
        outcome=outcome_from_results(data.results, fallback=data.outcome),
        status=data.status,
        source=data.source,
        notes=data.notes,
        next_due_date=data.next_due_date,
        import_key=data.import_key[:255],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    for index, row in enumerate(data.results):
        PeriodicCheckResult.objects.create(
            session=session,
            item=row.item,
            kind=row.kind,
            point=row.point,
            category=row.category[:60],
            label=row.label[:255],
            result=row.result,
            note=row.note[:500],
            sort_order=(index + 1) * 10,
        )
    for upload in files:
        add_attachment(session, upload, user=user)
    if session.status == PeriodicCheckSession.STATUS_CONFIRMED:
        _stamp_confirmation(session, user)
        refresh_next_due(session.check_type)
    return session


def add_attachment(session: PeriodicCheckSession, upload, *, user=None, name: str = "") -> PeriodicCheckAttachment:
    return PeriodicCheckAttachment.objects.create(
        session=session,
        file=upload,
        original_name=(name or Path(getattr(upload, "name", "") or "").name)[:255],
        uploaded_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _stamp_confirmation(session: PeriodicCheckSession, user) -> None:
    session.confirmed_by = user if getattr(user, "is_authenticated", False) else None
    session.confirmed_at = timezone.now()
    session.save(update_fields=["confirmed_by", "confirmed_at", "updated_at"])


@transaction.atomic
def confirm_session(session: PeriodicCheckSession, *, user=None) -> None:
    session.status = PeriodicCheckSession.STATUS_CONFIRMED
    session.save(update_fields=["status", "updated_at"])
    _stamp_confirmation(session, user)
    refresh_next_due(session.check_type)


def refresh_next_due(check_type: PeriodicCheckType) -> date | None:
    """Prossima scadenza = dall'ultima verifica confermata (la data indicata a mano
    vince, es. la scadenza scritta sul verbale DPR 462). Senza verifiche confermate
    la scadenza impostata a mano resta com'e'."""
    last = (
        check_type.sessions.filter(status=PeriodicCheckSession.STATUS_CONFIRMED)
        .order_by("-performed_on", "-id")
        .first()
    )
    if last is None:
        return check_type.next_due_date
    due = last.next_due_date or check_type.next_due_from(last.performed_on)
    if check_type.next_due_date != due:
        check_type.next_due_date = due
        check_type.save(update_fields=["next_due_date", "updated_at"])
    return due


def last_session(check_type: PeriodicCheckType) -> PeriodicCheckSession | None:
    return (
        check_type.sessions.filter(status=PeriodicCheckSession.STATUS_CONFIRMED)
        .order_by("-performed_on", "-id")
        .first()
    )


def create_work_order(result: PeriodicCheckResult, *, asset, user=None, title: str = "") -> WorkOrder:
    """OdL correttivo da un rilievo non conforme; il rilievo resta collegato all'OdL."""
    if result.work_order_id:
        return result.work_order
    session = result.session
    check_type = session.check_type
    description = (
        f"Da verifica periodica «{check_type.name}» ({check_type.system.name}) "
        f"del {session.performed_on:%d/%m/%Y}.\n{result.label}"
    )
    if result.note:
        description += f"\n{result.note}"
    work_order = WorkOrder.objects.create(
        asset=asset,
        kind=WorkOrder.KIND_CORRECTIVE,
        origin=WorkOrder.ORIGIN_MANUAL,
        status=WorkOrder.STATUS_OPEN,
        title=(title or f"{check_type.name}: {result.label}")[:255],
        description=description,
        supplier_id=check_type.supplier_id,
    )
    result.work_order = work_order
    result.save(update_fields=["work_order"])
    return work_order


# ---------------------------------------------------------------------------
# Metodo planimetria: planimetrie, foglio con QR, lettura della scansione
# ---------------------------------------------------------------------------

class LayoutError(ValueError):
    """Planimetria o scansione non utilizzabile: il messaggio va mostrato all'utente."""


def create_layout(check_type: PeriodicCheckType, pdf_bytes: bytes, *, name: str = "",
                  exclude_areas: list | None = None, user=None):
    """Nuova versione della planimetria: estrae i punti e la rende quella attiva."""
    from django.core.files.base import ContentFile

    from ..models import PeriodicCheckLayout, PeriodicCheckPoint
    from . import periodic_layout

    try:
        points = periodic_layout.extract_points(pdf_bytes)
    except Exception as exc:  # PDF illeggibile
        raise LayoutError(f"PDF non leggibile: {exc}") from exc
    if len(points) < 3:
        raise LayoutError(
            "Nella planimetria non ho trovato i punti numerati (riquadro rosso con la X e numero rosso)."
        )
    with transaction.atomic():
        version = (check_type.layouts.order_by("-version").values_list("version", flat=True).first() or 0) + 1
        layout = PeriodicCheckLayout(
            check_type=check_type, version=version, original_name=(name or "planimetria.pdf")[:255],
            exclude_areas=[[float(v) for v in area] for area in (exclude_areas or [])],
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )
        layout.source_pdf.save(name or "planimetria.pdf", ContentFile(pdf_bytes), save=False)
        layout.save()
        PeriodicCheckPoint.objects.bulk_create([
            PeriodicCheckPoint(layout=layout, code=p["code"], x=p["x"], y=p["y"], label_x=p["label_x"],
                               label_y=p["label_y"], sort_order=index)
            for index, p in enumerate(points)
        ])
        check_type.layouts.exclude(pk=layout.pk).update(is_active=False)
    return layout


def _layout_bytes(layout) -> bytes:
    with layout.source_pdf.open("rb") as handle:
        return handle.read()


def build_sheet_for(layout, *, token: str = ""):
    """PDF del foglio (con QR se c'e' il token) e la sua geometria."""
    from . import periodic_layout

    check_type = layout.check_type
    subtitle = f"{check_type.system.name} · {check_type.frequency_label.lower()} · planimetria v{layout.version}"
    return periodic_layout.build_sheet(
        _layout_bytes(layout),
        page_index=layout.page_index,
        title=check_type.name,
        subtitle=subtitle,
        token=token,
        categories=check_type.category_list,
        exclude_areas=layout.exclude_areas,
        printed_on=timezone.localdate() if token else None,
    )


@transaction.atomic
def issue_sheet(check_type: PeriodicCheckType, *, user=None) -> PeriodicCheckSession:
    """Verifica in stato «foglio stampato» con il suo token: il QR la ritrova."""
    from . import periodic_layout

    layout = check_type.active_layout
    if layout is None:
        raise LayoutError("Questa verifica non ha ancora una planimetria.")
    token = periodic_layout.generate_token(lambda t: PeriodicCheckSession.objects.filter(sheet_token=t).exists())
    return PeriodicCheckSession.objects.create(
        check_type=check_type,
        performed_on=timezone.localdate(),
        outcome=PeriodicCheckSession.OUTCOME_OK,
        status=PeriodicCheckSession.STATUS_ISSUED,
        source=PeriodicCheckSession.SOURCE_PARSER,
        supplier_id=check_type.supplier_id,
        sheet_token=token,
        layout=layout,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def session_for_token(text: str) -> PeriodicCheckSession | None:
    from . import periodic_layout

    token = periodic_layout.token_from_qr(text)
    if not token:
        return None
    return PeriodicCheckSession.objects.select_related("check_type", "layout").filter(sheet_token=token).first()


def _code_key(code: str):
    return (0, int(code), code) if code.isdigit() else (1, 0, code)


def read_scan_into(session: PeriodicCheckSession, data: bytes, *, name: str = "", user=None) -> dict:
    """Legge la scansione, la allega e propone i punti segnati. Non conferma nulla."""
    from django.core.files.base import ContentFile

    from . import periodic_layout_reader as reader

    if session.is_confirmed:
        raise LayoutError("La verifica e' gia' confermata: la scansione non viene riletta.")
    layout = session.layout or session.check_type.active_layout
    if layout is None:
        raise LayoutError("La verifica non ha una planimetria da confrontare.")
    template, geo = build_sheet_for(layout)
    points = []
    for p in layout.points.all():
        x, y = geo.to_sheet(p.x, p.y)
        lx, ly = geo.to_sheet(p.label_x if p.label_x is not None else p.x, p.label_y if p.label_y is not None else p.y)
        points.append({"code": p.code, "x": x, "y": y, "label_x": lx, "label_y": ly})
    try:
        result = reader.read_scan(
            data, template_pdf=template, points=points, search_rect=geo.plan_rect,
            exclude=[geo.rect_to_sheet(a) for a in layout.exclude_areas], unit=geo.scale, scan_name=name,
        )
    except Exception as exc:
        raise LayoutError(f"Scansione non leggibile: {exc}") from exc

    categories = session.check_type.category_list
    by_code = {p.code: p for p in layout.points.all()}
    file_name = name or "scansione.pdf"
    with transaction.atomic():
        add_attachment(session, ContentFile(data, name=file_name), user=user, name=file_name)
        add_attachment(session, ContentFile(result.overlay_png, name="lettura-automatica.png"), user=user,
                       name="lettura-automatica.png")
        session.results.filter(kind=PeriodicCheckResult.KIND_POINT, work_order__isnull=True).delete()
        for index, (code, kind) in enumerate(sorted(result.proposed.items(), key=lambda kv: _code_key(kv[0]))):
            category = categories[1] if kind == reader.KIND_PEN and len(categories) > 1 else categories[0]
            PeriodicCheckResult.objects.create(
                session=session, kind=PeriodicCheckResult.KIND_POINT, point=by_code.get(code),
                label=f"Punto {code}", category=category, result=PeriodicCheckResult.RESULT_KO,
                note=f"Letto dalla scansione ({kind})", sort_order=(index + 1) * 10,
            )
        session.layout = layout
        session.status = PeriodicCheckSession.STATUS_DRAFT
        session.reading = {
            "ok": result.ok,
            "registrazione": result.registration,
            "proposti": result.proposed,
            "non_associati": [{"colore": m.color, "tipo": m.kind, "vicini": m.candidates} for m in result.unmatched],
            "letta_il": timezone.now().isoformat(timespec="seconds"),
            "file": file_name,
        }
        session.save(update_fields=["layout", "status", "reading", "updated_at"])
    return session.reading


@transaction.atomic
def confirm_layout_session(session: PeriodicCheckSession, *, performed_on, technician: str = "",
                           decisions: dict[int, str], added: dict[str, str], user=None) -> None:
    """Conferma i punti: ``decisions`` = id esito -> categoria, o "" per scartarlo;
    ``added`` = codice punto -> categoria per quelli che la lettura non ha visto."""
    layout = session.layout
    by_code = {p.code: p for p in layout.points.all()} if layout else {}
    for result in session.results.filter(kind=PeriodicCheckResult.KIND_POINT):
        category = decisions.get(result.id)
        if category is None:
            continue
        if not category:
            if result.work_order_id is None:
                result.delete()
            continue
        result.category = category
        result.save(update_fields=["category"])
    existing = set(session.results.filter(kind=PeriodicCheckResult.KIND_POINT).values_list("point__code", flat=True))
    for code, category in added.items():
        if code in existing or code not in by_code:
            continue
        PeriodicCheckResult.objects.create(
            session=session, kind=PeriodicCheckResult.KIND_POINT, point=by_code[code], label=f"Punto {code}",
            category=category, result=PeriodicCheckResult.RESULT_KO, note="Aggiunto a mano alla conferma",
            sort_order=1000 + _code_key(code)[1],
        )
    has_ko = session.results.filter(result=PeriodicCheckResult.RESULT_KO).exists()
    session.performed_on = performed_on
    if technician:
        session.technician = technician[:120]
    session.outcome = PeriodicCheckSession.OUTCOME_REMARKS if has_ko else PeriodicCheckSession.OUTCOME_OK
    session.save(update_fields=["performed_on", "technician", "outcome", "updated_at"])
    confirm_session(session, user=user)
