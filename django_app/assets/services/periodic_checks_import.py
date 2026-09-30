"""Import dello storico delle verifiche periodiche dall'archivio su share.

Ogni documento diventa un allegato; i documenti dello stesso tipo e della stessa
data diventano UNA verifica (es. «Pacco1.pdf» + «Pacco 2.pdf» del 01-2026).
La data si legge dal nome del file e, se manca, dalle cartelle che lo contengono
(anno, mese). Precisione: giorno, mese o solo anno — scritta nelle note.

Idempotente: ogni verifica importata ha ``import_key`` = tipo + data; un secondo
giro salta quelle gia' presenti.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from django.core.files import File
from django.db import transaction

from ..models import PeriodicCheckSession, PeriodicCheckType
from . import periodic_checks as checks
from .periodic_checks_catalog import ArchiveSource, CatalogType

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

PRECISION_DAY = "giorno"
PRECISION_MONTH = "mese"
PRECISION_YEAR = "anno"

_YYYYMMDD = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
_DMY = re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])[./\-_ ](0?[1-9]|1[0-2])[./\-_ ](20\d{2}|\d{2})(?!\d)")
_MY = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])[.\-_ ](20\d{2})(?!\d)")
_Y = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def parse_date(text: str) -> tuple[date, str] | None:
    """Prima data riconoscibile in ``text`` con la sua precisione."""
    for regex, precision in ((_YYYYMMDD, PRECISION_DAY), (_DMY, PRECISION_DAY)):
        for match in regex.finditer(text):
            if regex is _YYYYMMDD:
                year, month, day = (int(g) for g in match.groups())
            else:
                day, month, year = (int(g) for g in match.groups())
                if year < 100:
                    year += 2000
            try:
                return date(year, month, day), precision
            except ValueError:
                continue
    match = _MY.search(text)
    if match:
        return date(int(match.group(2)), int(match.group(1)), 1), PRECISION_MONTH
    match = _Y.search(text)
    if match:
        return date(int(match.group(1)), 1, 1), PRECISION_YEAR
    return None


def date_for(path: Path, root: Path) -> tuple[date, str] | None:
    """Data dal nome del file; se manca o e' meno precisa, dalle cartelle (dalla piu' vicina)."""
    best = parse_date(path.stem)
    if best and best[1] == PRECISION_DAY:
        return best
    for parent in path.parents:
        if parent == root or root not in parent.parents:
            break
        found = parse_date(parent.name)
        if found and (best is None or _rank(found[1]) > _rank(best[1])) and (
            best is None or found[0].year == best[0].year
        ):
            best = found
            if found[1] == PRECISION_DAY:
                break
    return best


def _rank(precision: str) -> int:
    return {PRECISION_YEAR: 0, PRECISION_MONTH: 1, PRECISION_DAY: PRECISION_RANK_DAY}.get(precision, PRECISION_RANK_DAY)


PRECISION_TEXT = "giorno (dal testo)"
PRECISION_RANK_DAY = 2


def text_date(path: Path, around: date, precision: str) -> date | None:
    """Data esatta letta dentro un PDF con testo, coerente con anno (e mese) gia' noti.

    Fra le date dello stesso anno (e mese, se noto) vince la piu' frequente, a parita'
    la piu' recente: tarature e validita' degli strumenti cadono in altri anni.
    Le scansioni senza testo restano con la data del nome."""
    if path.suffix.lower() != ".pdf":
        return None
    try:
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            text = " ".join(page.get_text() for page in list(doc)[:3])
    except Exception:
        return None
    counts: dict[date, int] = {}
    for match in _DMY.finditer(text):
        day, month, year = (int(g) for g in match.groups())
        if year < 100:
            year += 2000
        try:
            found = date(year, month, day)
        except ValueError:
            continue
        if found.year != around.year or (precision == PRECISION_MONTH and found.month != around.month):
            continue
        counts[found] = counts.get(found, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda d: (counts[d], d))


@dataclass
class PlannedSession:
    catalog: CatalogType
    performed_on: date
    precision: str
    files: list[Path] = field(default_factory=list)

    @property
    def import_key(self) -> str:
        return f"storico:{self.catalog.system}:{self.catalog.name}:{self.performed_on.isoformat()}"[:255]


@dataclass
class ScanReport:
    sessions: list[PlannedSession] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    missing_folders: list[str] = field(default_factory=list)


def _files(source: ArchiveSource, base: Path) -> list[Path]:
    pattern = "**/*" if source.recursive else "*"
    return sorted(p for p in base.glob(pattern) if p.is_file())


def scan(root: Path, catalog: list[CatalogType]) -> ScanReport:
    report = ScanReport()
    for entry in catalog:
        by_date: dict[date, PlannedSession] = {}
        for source in entry.sources:
            base = root / source.folder
            if not base.is_dir():
                report.missing_folders.append(source.folder)
                continue
            for path in _files(source, base):
                name = path.name
                if path.suffix.lower() not in ALLOWED_SUFFIXES or name.startswith("~$"):
                    continue
                if source.include and not re.search(source.include, name, re.IGNORECASE):
                    continue
                if source.exclude and re.search(source.exclude, name, re.IGNORECASE):
                    report.skipped.append((path, "escluso (non e' un esito di verifica)"))
                    continue
                found = date_for(path, base)
                if found is None:
                    report.skipped.append((path, "data non riconoscibile"))
                    continue
                performed_on, precision = found
                if precision != PRECISION_DAY:
                    exact = text_date(path, performed_on, precision)
                    if exact is not None:
                        performed_on, precision = exact, PRECISION_TEXT
                planned = by_date.get(performed_on)
                if planned is None:
                    planned = by_date[performed_on] = PlannedSession(entry, performed_on, precision)
                elif _rank(precision) > _rank(planned.precision):
                    planned.precision = precision
                planned.files.append(path)
        report.sessions.extend(sorted(by_date.values(), key=lambda s: s.performed_on))
    return report


def apply(report: ScanReport, types: dict[tuple[str, str], PeriodicCheckType], *, root: Path) -> tuple[int, int]:
    """Scrive le verifiche pianificate. Ritorna (create, gia' presenti)."""
    created = existing = 0
    for planned in report.sessions:
        check_type = types[(planned.catalog.system, planned.catalog.name)]
        if PeriodicCheckSession.objects.filter(import_key=planned.import_key).exists():
            existing += 1
            continue
        rel = [str(p.relative_to(root)) for p in planned.files]
        note = "Importata dallo storico. Data indicativa: " + {
            PRECISION_DAY: "giorno esatto dal nome del documento.",
            PRECISION_TEXT: "giorno letto nel testo del documento.",
            PRECISION_MONTH: "solo mese (giorno fissato al 1°).",
            PRECISION_YEAR: "solo anno (fissata al 1° gennaio).",
        }[planned.precision]
        note += "\nDocumenti d'origine:\n" + "\n".join(rel)
        with transaction.atomic():
            session = checks.register_session(
                checks.SessionInput(
                    check_type=check_type,
                    performed_on=planned.performed_on,
                    outcome=PeriodicCheckSession.OUTCOME_ARCHIVE,
                    notes=note,
                    source=PeriodicCheckSession.SOURCE_IMPORT,
                    import_key=planned.import_key,
                ),
            )
            for path in planned.files:
                with path.open("rb") as handle:
                    checks.add_attachment(session, File(handle, name=path.name), name=path.name)
        created += 1
    return created, existing
