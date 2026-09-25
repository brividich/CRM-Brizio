"""Registro dei report di conformita' (ISO 9001, EN 9100, ISO 45001, ISO 27001).

Ogni report e' una funzione *di sola lettura* che riceve un :class:`ReportParams`
e restituisce un :class:`ReportResult` (indicatori + tabella + note). La stessa
struttura alimenta la vista web, il PDF e l'XLSX: un solo calcolo, tre formati,
cosi' i numeri non possono divergere fra schermo e file scaricato.

Il registro non conosce l'ACL: ogni report dichiara la sua *area*, e l'area
porta il permesso canonico (vedi :mod:`report_conformita.acl_bootstrap`). La
decisione resta server-side nella view.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

from django.utils import timezone

# ── Norme ──────────────────────────────────────────────────────────────────
ISO_9001 = "ISO 9001"
EN_9100 = "EN 9100"
ISO_45001 = "ISO 45001"
ISO_27001 = "ISO 27001"
NORME = (ISO_9001, EN_9100, ISO_45001, ISO_27001)

# ── Aree (una per permesso canonico) ───────────────────────────────────────
AREA_QUALITA = "qualita"
AREA_PERSONE = "persone"
AREA_SICUREZZA = "sicurezza"
AREA_IT = "it"

AREE = {
    AREA_QUALITA: "Qualità e processi",
    AREA_PERSONE: "Competenze e qualifiche",
    AREA_SICUREZZA: "Salute e sicurezza sul lavoro",
    AREA_IT: "Sicurezza delle informazioni",
}
AREE_ORDINE = (AREA_QUALITA, AREA_PERSONE, AREA_SICUREZZA, AREA_IT)

# Toni ammessi per indicatori e righe (mappati su classi CSS/colori PDF).
TONE_OK = "ok"
TONE_WARN = "warn"
TONE_DANGER = "danger"


@dataclass(frozen=True)
class Clausola:
    norma: str
    punto: str

    def __str__(self) -> str:
        return f"{self.norma} §{self.punto}" if self.punto[:1].isdigit() else f"{self.norma} {self.punto}"


@dataclass(frozen=True)
class Filtro:
    """Filtro aggiuntivo (select) dichiarato da un report."""

    name: str
    label: str
    choices: tuple[tuple[str, str], ...]


@dataclass
class ReportParams:
    date_from: date
    date_to: date
    today: date
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_querydict(cls, data, *, filtri: tuple[Filtro, ...] = ()) -> "ReportParams":
        today = timezone.localdate()
        date_to = _parse_date(data.get("a")) or today
        date_from = _parse_date(data.get("da")) or (date_to - timedelta(days=365))
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        extra: dict[str, str] = {}
        for filtro in filtri:
            value = str(data.get(filtro.name) or "").strip()
            if value in {code for code, _label in filtro.choices}:
                extra[filtro.name] = value
        return cls(date_from=date_from, date_to=date_to, today=today, extra=extra)

    @property
    def periodo_label(self) -> str:
        return f"{self.date_from:%d/%m/%Y} – {self.date_to:%d/%m/%Y}"

    def as_query(self) -> dict[str, str]:
        return {"da": self.date_from.isoformat(), "a": self.date_to.isoformat(), **self.extra}


@dataclass
class Kpi:
    label: str
    value: object
    tone: str = ""
    hint: str = ""


@dataclass
class ReportResult:
    kpis: list[Kpi] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_tones: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Link "dove si gestisce": (etichetta, url) verso la pagina del modulo sorgente.
    links: list[tuple[str, str]] = field(default_factory=list)

    def add_row(self, values: list, tone: str = "") -> None:
        self.rows.append(values)
        self.row_tones.append(tone)


@dataclass(frozen=True)
class ReportDef:
    slug: str
    title: str
    area: str
    description: str
    clausole: tuple[Clausola, ...]
    builder: Callable[[ReportParams], ReportResult]
    usa_periodo: bool = True
    filtri: tuple[Filtro, ...] = ()
    fonte: str = ""

    @property
    def norme(self) -> list[str]:
        seen: list[str] = []
        for clausola in self.clausole:
            if clausola.norma not in seen:
                seen.append(clausola.norma)
        return [n for n in NORME if n in seen]

    def build(self, params: ReportParams) -> ReportResult:
        return self.builder(params)


_REGISTRY: dict[str, ReportDef] = {}


def register(report: ReportDef) -> ReportDef:
    if report.slug in _REGISTRY:
        raise ValueError(f"Report duplicato: {report.slug}")
    if report.area not in AREE:
        raise ValueError(f"Area sconosciuta per {report.slug}: {report.area}")
    _REGISTRY[report.slug] = report
    return report


def _ensure_loaded() -> None:
    if not _REGISTRY:
        from . import reports  # noqa: F401  (registra i report all'import)


def all_reports() -> list[ReportDef]:
    _ensure_loaded()
    ordine = {area: i for i, area in enumerate(AREE_ORDINE)}
    return sorted(_REGISTRY.values(), key=lambda r: (ordine.get(r.area, 99), list(_REGISTRY).index(r.slug)))


def get_report(slug: str) -> ReportDef | None:
    _ensure_loaded()
    return _REGISTRY.get(slug)


def _parse_date(value) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def c(norma: str, punto: str) -> Clausola:
    return Clausola(norma, punto)
