"""Report-only corrections. Source builders always remain read-only."""
from dataclasses import dataclass
from hashlib import sha256
import json

from django.core import signing
from django.db import IntegrityError, transaction

from core.audit import log_action
from .models import ReportCorrection
from .sources import COLUMN_SOURCES


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def as_text(value):
    return "" if value is None else str(value)


def scope_params(definition, params):
    data = {k: v for k, v in params.extra.items() if v}
    if definition.usa_periodo:
        data.update(da=params.date_from.isoformat(), a=params.date_to.isoformat())
    return data


@dataclass
class Cell:
    target: str
    label: str
    original: str
    value: str
    source: str
    row: int | None = None
    column: int | None = None
    kpi: int | None = None
    correction: object = None
    stale: bool = False

    @property
    def corrected(self):
        return bool(self.correction and not self.correction.restored and not self.stale)


class CorrectionData:
    def __init__(self, definition, params, result):
        self.definition = definition
        self.params = scope_params(definition, params)
        self.scope = digest(self.params)
        self.history = ReportCorrection.objects.filter(report_slug=definition.slug, scope=self.scope)
        # No values from the source DB are queried through user-supplied model/field names.
        latest = {}
        for item in self.history:
            latest.setdefault(item.target, item)
        self.cells = {}
        self.rows = []
        self.kpis = []
        sources = COLUMN_SOURCES.get(definition.slug, [])
        for i, values in enumerate(result.rows):
            key = result.row_keys[i] if i < len(result.row_keys) else ""
            if not key:
                raise ValueError(f"Missing stable source identity: {definition.slug}, row {i}")
            cells = []
            for j, value in enumerate(values):
                label = f"{as_text(values[0])[:180]} / {result.columns[j]}"
                cell = Cell(digest(["row", key, result.columns[j]]), label, as_text(value), as_text(value),
                            sources[j] if j < len(sources) else definition.fonte, row=i, column=j)
                self._add(cell, latest)
                cells.append(cell)
            self.rows.append(cells)
        for i, kpi in enumerate(result.kpis):
            cell = Cell(digest(["kpi", kpi.label]), kpi.label, as_text(kpi.value), as_text(kpi.value),
                        f"Indicatore calcolato da {definition.fonte}. {kpi.hint}", kpi=i)
            self._add(cell, latest)
            self.kpis.append(cell)

    def _add(self, cell, latest):
        if cell.target in self.cells:
            raise ValueError("Duplicate report target")
        cell.correction = latest.get(cell.target)
        if cell.correction and not cell.correction.restored:
            cell.stale = cell.original != cell.correction.source_value
            if not cell.stale:
                cell.value = cell.correction.value
        self.cells[cell.target] = cell

    def token(self, cell):
        return signing.dumps(self._state(cell), salt="report-correction")

    def _state(self, cell):
        return [self.definition.slug, self.scope, cell.target, digest(cell.original),
                cell.correction.revision if cell.correction else 0]

    def save(self, request, cell, cleaned):
        try:
            state = signing.loads(cleaned["token"], salt="report-correction", max_age=7200)
        except signing.BadSignature as exc:
            raise ValueError("La pagina e scaduta. Ricarica i dati prima di salvare.") from exc
        if state != self._state(cell):
            raise ValueError("Il dato o la rettifica sono cambiati. Ricarica la pagina prima di salvare.")
        try:
            with transaction.atomic():
                item = ReportCorrection.objects.create(
                    report_slug=self.definition.slug, scope=self.scope, scope_params=self.params,
                    target=cell.target, target_label=cell.label[:500], revision=state[-1] + 1,
                    source_value=cell.original, value=cleaned["value"], reason=cleaned["reason"],
                    restored=cleaned["action"] == "restore", author=request.user,
                    author_label=request.user.get_username()[:150],
                )
                log_action(request, "report_conformita_rettifica", "report_conformita",
                           {"report": self.definition.slug, "rettifica_id": item.pk, "ripristino": item.restored},
                           oggetto_tipo="report", oggetto_id=self.definition.slug)
                return item
        except IntegrityError as exc:
            raise ValueError("Un altro utente ha appena modificato questo dato. Ricarica la pagina.") from exc

    def apply(self, result):
        changed = [c for c in self.cells.values() if c.corrected]
        stale = [c for c in self.cells.values() if c.stale]
        if changed:
            result.notes.append("RETTIFICHE MANUALI DEL REPORT: i dati sorgente restano invariati. "
                                "Indicatori e semafori derivati non vengono ricalcolati dalle rettifiche delle righe.")
        for cell in changed:
            item = cell.correction
            if cell.kpi is not None:
                kpi = result.kpis[cell.kpi]
                kpi.value = cell.value
                kpi.tone = "warn"
                kpi.hint = "Rettifica manuale; originale: " + cell.original
            else:
                result.rows[cell.row][cell.column] = cell.value
                result.corrected_cells.add((cell.row, cell.column))
            note = (f"Rettifica - {cell.label}: {cell.original!r} -> {cell.value!r}. "
                                f"Motivo: {item.reason}. Autore: {item.author_label}; "
                                f"data: {item.created_at:%d/%m/%Y %H:%M %Z}.")
            result.notes.append(note)
            if cell.kpi is not None:
                result.riesame_notes.append(note)
        for cell in stale:
            note = (f"Rettifica sospesa - {cell.label}: il dato sorgente e cambiato; "
                                "mostrato il valore aggiornato. Verificare in Dati e fonti.")
            result.notes.append(note)
            if cell.kpi is not None:
                result.riesame_notes.append(note)
        return result


def corrected_result(definition, params):
    result = definition.build(params)
    return CorrectionData(definition, params, result).apply(result)
