"""Statistiche di un tipo di verifica periodica (scheda della verifica, «Panoramica»).

Sola lettura. Le statistiche si basano sugli ESITI registrati: le verifiche importate
dallo storico hanno solo il documento (esito «Storico») e contano per date e puntualita',
non per i punti o le voci. La pagina lo dichiara invece di mostrare zeri.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Prefetch
from django.utils import timezone

from ..models import (
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckType,
    WorkOrder,
    _add_months,
)
from . import periodic_checks as checks

RECENT_SESSIONS = 6  # finestra per i punti ricorrenti e le voci piu' spesso non OK
TREND_SESSIONS = 12


@dataclass
class PointState:
    code: str
    x: float
    y: float
    state: str  # "ok" | "cat0" | "cat1" | "fixed" | "unknown"
    category: str = ""
    since: date | None = None
    streak: int = 0
    recent_count: int = 0
    work_order: WorkOrder | None = None
    session_id: int | None = None


@dataclass
class TypeStats:
    today: date
    state: str
    state_label: str
    confirmed: int = 0
    with_results: int = 0
    last_12m: int = 0
    expected_12m: int = 0
    on_time: int = 0
    on_time_total: int = 0
    open_findings: int = 0
    open_work_orders: int = 0
    last_session: PeriodicCheckSession | None = None
    trend: list[dict] = field(default_factory=list)
    trend_series: list[dict] = field(default_factory=list)
    trend_max: int = 0
    # metodo planimetria
    layout: object | None = None
    points: list[PointState] = field(default_factory=list)
    points_total: int = 0
    defective: list[PointState] = field(default_factory=list)
    recurring: list[PointState] = field(default_factory=list)
    efficiency_pct: int | None = None
    layout_session: PeriodicCheckSession | None = None
    # metodo checklist
    item_failures: list[dict] = field(default_factory=list)
    # metodo misure
    measure_session: PeriodicCheckSession | None = None
    measure_ko: list = field(default_factory=list)
    measure_recurring: list[dict] = field(default_factory=list)


def _confirmed_sessions(check_type: PeriodicCheckType):
    return list(
        check_type.sessions.filter(status=PeriodicCheckSession.STATUS_CONFIRMED)
        .prefetch_related(Prefetch("results", queryset=PeriodicCheckResult.objects.select_related("point", "work_order", "item")))
        .order_by("performed_on", "id")
    )


def _on_time(sessions, check_type) -> tuple[int, int]:
    """Verifiche fatte entro la scadenza che la precedente aveva fissato (ultimi 24 mesi)."""
    since = timezone.localdate() - timedelta(days=730)
    ok = total = 0
    for prev, cur in zip(sessions, sessions[1:]):
        if cur.performed_on < since:
            continue
        due = prev.next_due_date or _add_months(prev.performed_on, check_type.frequency_months)
        total += 1
        if cur.performed_on <= due:
            ok += 1
    return ok, total


def _series_key(result, categories: list[str]) -> str:
    if result.kind == PeriodicCheckResult.KIND_POINT:
        return result.category if result.category in categories else (categories[0] if categories else "Punto")
    if result.kind == PeriodicCheckResult.KIND_ITEM:
        return "Voci non OK"
    if result.kind == PeriodicCheckResult.KIND_MEASURE:
        return result.category or "Fuori soglia"
    return "Rilievi"


def type_stats(check_type: PeriodicCheckType, today: date | None = None) -> TypeStats:
    today = today or timezone.localdate()
    state = checks.type_state(check_type, today)
    stats = TypeStats(today=today, state=state, state_label=checks.STATE_LABELS[state])
    sessions = _confirmed_sessions(check_type)
    stats.confirmed = len(sessions)
    stats.last_session = sessions[-1] if sessions else None
    year_ago = today - timedelta(days=365)
    stats.last_12m = sum(1 for s in sessions if s.performed_on >= year_ago)
    stats.expected_12m = max(1, round(12 / max(1, check_type.frequency_months)))
    stats.on_time, stats.on_time_total = _on_time(sessions, check_type)

    # Rilievi aperti: solo quelli dell'ultima verifica con esiti (le precedenti sono superate).
    latest = next((s for s in reversed(sessions) if s.outcome != PeriodicCheckSession.OUTCOME_ARCHIVE), None)
    stats.open_findings = sum(
        1 for r in (latest.results.all() if latest else []) if r.result == PeriodicCheckResult.RESULT_KO and not r.work_order_id
    )
    stats.open_work_orders = WorkOrder.objects.filter(
        periodic_check_results__session__check_type=check_type, status=WorkOrder.STATUS_OPEN
    ).distinct().count()

    # Andamento: rilievi per verifica, divisi per categoria (solo verifiche con esiti)
    categories = check_type.category_list
    with_results = [s for s in sessions if s.outcome != PeriodicCheckSession.OUTCOME_ARCHIVE]
    stats.with_results = len(with_results)
    series_order: list[str] = []
    rows = []
    for session in with_results[-TREND_SESSIONS:]:
        counts = Counter(_series_key(r, categories) for r in session.results.all() if r.result == PeriodicCheckResult.RESULT_KO)
        for key in counts:
            if key not in series_order:
                series_order.append(key)
        rows.append({"session": session, "counts": counts, "total": sum(counts.values())})
    known = [c for c in categories if c in series_order] + [k for k in series_order if k not in categories]
    stats.trend_series = [{"key": key, "slot": index} for index, key in enumerate(known)]
    stats.trend_max = max((r["total"] for r in rows), default=0)
    for row in rows:
        row["segments"] = [{"key": s["key"], "slot": s["slot"], "value": row["counts"].get(s["key"], 0)} for s in stats.trend_series]
    stats.trend = rows

    if check_type.method == PeriodicCheckType.METHOD_LAYOUT:
        _layout_stats(stats, check_type, with_results)
    elif check_type.method == PeriodicCheckType.METHOD_CHECKLIST:
        _checklist_stats(stats, with_results)
    elif check_type.method == PeriodicCheckType.METHOD_MEASURES:
        _measure_stats(stats, with_results)
    return stats


def _measure_stats(stats: TypeStats, sessions) -> None:
    """Ultima verifica con valori: i punti da sistemare adesso; ricorrenti nelle ultime 6."""
    measured = [s for s in sessions if any(r.kind == PeriodicCheckResult.KIND_MEASURE for r in s.results.all())]
    if not measured:
        return
    last = measured[-1]
    stats.measure_session = last
    stats.measure_ko = [r for r in last.results.all()
                        if r.kind == PeriodicCheckResult.KIND_MEASURE and r.result == PeriodicCheckResult.RESULT_KO]
    recent = measured[-RECENT_SESSIONS:]
    counts: Counter = Counter()
    for session in recent:
        counts.update({r.label for r in session.results.all()
                       if r.kind == PeriodicCheckResult.KIND_MEASURE and r.result == PeriodicCheckResult.RESULT_KO})
    stats.measure_recurring = [
        {"label": label, "count": count, "of": len(recent)}
        for label, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if count >= 2
    ]


def _layout_stats(stats: TypeStats, check_type: PeriodicCheckType, sessions) -> None:
    layout = check_type.active_layout
    stats.layout = layout
    if layout is None:
        return
    categories = check_type.category_list
    layout_sessions = [s for s in sessions if s.layout_id is not None]
    points = list(layout.points.all())
    stats.points_total = len(points)
    if not layout_sessions:
        stats.points = [PointState(p.code, p.x, p.y, "unknown") for p in points]
        return
    last = layout_sessions[-1]
    stats.layout_session = last
    recent = layout_sessions[-RECENT_SESSIONS:]
    ko_by_session = [
        {r.point.code: r for r in s.results.all() if r.kind == PeriodicCheckResult.KIND_POINT and r.point_id and r.result == PeriodicCheckResult.RESULT_KO}
        for s in layout_sessions
    ]
    recent_counts: Counter = Counter()
    for found in ko_by_session[-RECENT_SESSIONS:]:
        recent_counts.update(found.keys())
    current = ko_by_session[-1]
    states = []
    for p in points:
        result = current.get(p.code)
        if result is None:
            state = PointState(p.code, p.x, p.y, "ok", recent_count=recent_counts[p.code])
        else:
            streak, since = 0, None
            for session, found in zip(reversed(layout_sessions), reversed(ko_by_session)):
                if p.code not in found:
                    break
                streak += 1
                since = session.performed_on
            fixed = result.work_order_id and result.work_order.status == WorkOrder.STATUS_DONE
            slot = categories.index(result.category) if result.category in categories else 0
            state = PointState(
                p.code, p.x, p.y, "fixed" if fixed else f"cat{min(slot, 1)}", category=result.category,
                since=since, streak=streak, recent_count=recent_counts[p.code],
                work_order=result.work_order, session_id=last.id,
            )
        states.append(state)
    stats.points = states
    stats.defective = sorted((s for s in states if s.state.startswith("cat")), key=lambda s: (s.state, checks._code_key(s.code)))
    ok_now = sum(1 for s in states if s.state in ("ok", "fixed"))
    stats.efficiency_pct = round(100 * ok_now / len(states)) if states else None
    stats.recurring = sorted(
        (s for s in states if s.recent_count >= 2),
        key=lambda s: (-s.recent_count, checks._code_key(s.code)),
    )


def _checklist_stats(stats: TypeStats, sessions) -> None:
    recent = sessions[-RECENT_SESSIONS:]
    counts: dict[str, dict] = defaultdict(lambda: {"ko": 0, "last": None})
    for session in recent:
        for r in session.results.all():
            if r.kind == PeriodicCheckResult.KIND_ITEM and r.result == PeriodicCheckResult.RESULT_KO:
                entry = counts[r.label]
                entry["ko"] += 1
                entry["last"] = session.performed_on
    stats.item_failures = sorted(
        ({"label": label, "ko": v["ko"], "last": v["last"], "of": len(recent)} for label, v in counts.items()),
        key=lambda e: (-e["ko"], e["label"]),
    )
