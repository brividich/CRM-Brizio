"""Costruzione delle righe e delle opzioni del Gantt di commessa."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from django.utils import timezone


from ..models import (
    Task,
)
from .absences import (
    _build_task_absence_day_map,
)
from .calendar_it import (
    _build_holidays_set,
    _count_working_days,
)

logger = logging.getLogger(__name__)

MONTH_LABELS_IT = {
    1: "Gennaio",
    2: "Febbraio",
    3: "Marzo",
    4: "Aprile",
    5: "Maggio",
    6: "Giugno",
    7: "Luglio",
    8: "Agosto",
    9: "Settembre",
    10: "Ottobre",
    11: "Novembre",
    12: "Dicembre",
}

GANTT_WINDOW_OPTIONS = (
    (31, "1 mese"),
    (62, "2 mesi"),
    (93, "3 mesi"),
    (124, "4 mesi"),
    (0, "Auto"),
)
GANTT_CELL_OPTIONS = (
    ("s", "Compatta"),
    ("m", "Standard"),
    ("l", "Ampia"),
)
GANTT_NAME_WIDTH_OPTIONS = (
    (280, "Compatta"),
    (360, "Media"),
    (460, "Ampia"),
)


def _query_bool(query_data, key: str, *, default: bool = True) -> bool:
    raw = query_data.get(key)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() not in {"0", "false", "off", "no", ""}


def _parse_gantt_options(request):
    query_data = request.GET

    valid_windows = {row[0] for row in GANTT_WINDOW_OPTIONS}
    valid_cells = {row[0] for row in GANTT_CELL_OPTIONS}
    valid_name_widths = {row[0] for row in GANTT_NAME_WIDTH_OPTIONS}

    try:
        window_days = int(query_data.get("window_days", 31))
    except (TypeError, ValueError):
        window_days = 31
    if window_days not in valid_windows:
        window_days = 31

    cell_size = str(query_data.get("cell_size", "m") or "m").strip().lower()
    if cell_size not in valid_cells:
        cell_size = "m"

    try:
        name_width = int(query_data.get("name_width", 360))
    except (TypeError, ValueError):
        name_width = 360
    if name_width not in valid_name_widths:
        name_width = 360

    day_cell_px_map = {"s": 22, "m": 30, "l": 38}

    return {
        "window_days": window_days,
        "cell_size": cell_size,
        "name_width": name_width,
        "show_wbs": _query_bool(query_data, "show_wbs", default=True),
        "show_duration": _query_bool(query_data, "show_duration", default=True),
        "show_start": _query_bool(query_data, "show_start", default=True),
        "show_end": _query_bool(query_data, "show_end", default=True),
        "day_cell_px": day_cell_px_map[cell_size],
        "window_choices": GANTT_WINDOW_OPTIONS,
        "cell_choices": GANTT_CELL_OPTIONS,
        "name_width_choices": GANTT_NAME_WIDTH_OPTIONS,
        "return_qs": query_data.urlencode(),
    }


def _project_gantt_rows(tasks: list[Task], *, min_window_days: int = 31) -> dict:
    today = timezone.localdate()
    timeline_points: list[date] = [today]
    base_rows: list[dict] = []

    for index, task in enumerate(tasks, start=1):
        start = task.next_step_due or task.created_at.date()
        end = task.due_date or task.next_step_due or start
        active_start = min(start, end)
        active_end = max(start, end)
        invalid_range = bool(task.next_step_due and task.due_date and task.due_date <= task.next_step_due)

        timeline_points.extend([active_start, active_end])
        base_rows.append(
            {
                "task": task,
                "wbs": str(index),
                "start": start,
                "end": end,
                "active_start": active_start,
                "active_end": active_end,
                "invalid_range": invalid_range,
                "duration_days": max(1, (active_end - active_start).days + 1),
            }
        )

    if base_rows:
        timeline_start = min(timeline_points) - timedelta(days=1)
        timeline_end = max(timeline_points) + timedelta(days=1)
    else:
        timeline_start = today - timedelta(days=3)
        timeline_end = today + timedelta(days=10)

    if min_window_days and min_window_days > 0:
        current_days = max(1, (timeline_end - timeline_start).days + 1)
        if current_days < min_window_days:
            extra_days = min_window_days - current_days
            left_extra = extra_days // 2
            right_extra = extra_days - left_extra
            timeline_start -= timedelta(days=left_extra)
            timeline_end += timedelta(days=right_extra)

    total_days = max(1, (timeline_end - timeline_start).days + 1)
    days = [timeline_start + timedelta(days=offset) for offset in range(total_days)]
    holidays = _build_holidays_set(timeline_start, timeline_end)
    day_columns = [
        {
            "date": day_value,
            "is_weekend": day_value.weekday() >= 5,
            "is_holiday": day_value in holidays and day_value.weekday() < 5,
            "is_today": day_value == today,
        }
        for day_value in days
    ]

    month_spans = []
    if days:
        current_month = (days[0].year, days[0].month)
        span_start = 0
        for index, day_value in enumerate(days):
            key = (day_value.year, day_value.month)
            if key != current_month:
                month_spans.append(
                    {
                        "label": f"{MONTH_LABELS_IT.get(current_month[1], current_month[1])} {current_month[0]}",
                        "span": index - span_start,
                    }
                )
                current_month = key
                span_start = index
        month_spans.append(
            {
                "label": f"{MONTH_LABELS_IT.get(current_month[1], current_month[1])} {current_month[0]}",
                "span": len(days) - span_start,
            }
        )

    task_absence_days = _build_task_absence_day_map(tasks, timeline_start=timeline_start, timeline_end=timeline_end)

    rows: list[dict] = []
    for row in base_rows:
        start_index = max(0, (row["active_start"] - timeline_start).days)
        end_index = min(len(days) - 1, (row["active_end"] - timeline_start).days)
        row_absence_days = task_absence_days.get(row["task"].id, {})
        conflict_dates: list[date] = [
            day_value
            for day_value in sorted(row_absence_days.keys())
            if row["active_start"] <= day_value <= row["active_end"]
        ]
        cells = []
        for day_index, day_value in enumerate(days):
            classes = []
            marker = ""
            title = ""
            is_wknd = day_value.weekday() >= 5
            is_hol = day_value in holidays and not is_wknd
            if is_wknd:
                classes.append("is-weekend")
            if is_hol:
                classes.append("is-holiday")
            if day_value == today:
                classes.append("is-today")
            if start_index <= day_index <= end_index:
                classes.append("is-active")
                classes.append(f"status-{row['task'].status.lower()}")
                if row["invalid_range"]:
                    classes.append("is-invalid-range")
            absence_entries = row_absence_days.get(day_value, [])
            if absence_entries and start_index <= day_index <= end_index:
                classes.append("is-absence")
                marker = "X"
                labels = [f"{entry['tipo']} ({entry['status']})" for entry in absence_entries]
                title = "; ".join(dict.fromkeys(labels))
            cells.append(
                {
                    "classes": " ".join(classes),
                    "marker": marker,
                    "title": title,
                }
            )
        row["cells"] = cells
        row["start_index"] = start_index
        row["end_index"] = end_index
        row["span"] = max(1, end_index - start_index + 1)
        row["absence_days"] = len(conflict_dates)
        row["absence_dates"] = conflict_dates[:6]
        row["has_absence_conflicts"] = bool(conflict_dates)
        row["duration_working_days"] = _count_working_days(row["active_start"], row["active_end"], holidays)
        rows.append(row)

    # Predecessore implicito (WBS order): ogni task conosce l'end_index del task precedente
    # per consentire il vincolo "task N non può iniziare prima della fine di task N-1" nel Gantt.
    for i, row in enumerate(rows):
        row["prev_end_index"] = rows[i - 1]["end_index"] if i > 0 else -1

    # Indice colonna di "oggi" (per la linea verticale) e bande settimana (stile
    # Gantt Carichi Macchina): -1 se oggi è fuori finestra.
    today_index = (today - timeline_start).days
    if today_index < 0 or today_index >= len(days):
        today_index = -1

    week_spans = []
    if days:
        cur_week = days[0].isocalendar()[1]
        cnt = 0
        for day_value in days:
            wk = day_value.isocalendar()[1]
            if wk != cur_week:
                week_spans.append({"label": f"Sett. {cur_week:02d}", "span": cnt})
                cur_week, cnt = wk, 0
            cnt += 1
        week_spans.append({"label": f"Sett. {cur_week:02d}", "span": cnt})

    return {
        "rows": rows,
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
        "today": today,
        "today_index": today_index,
        "days": day_columns,
        "month_spans": month_spans,
        "week_spans": week_spans,
    }
