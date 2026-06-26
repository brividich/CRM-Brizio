"""Import del corpus documentale SGI da una cartella di rete (file server).

Scandisce una share (es. ``\\\\novisrv\\sistema gestione integrato``), registra i
PDF come ``ProcedureDocument`` + ``ProcedureRevision`` corrente (sorgente
``fileserver``, ``source_path`` = path UNC), così l'Assistente AI può indicizzarli
e citarli (``manage.py index_sgi_documents``). NON legge il contenuto dei PDF:
estrazione e indicizzazione restano al RAG.

Principi:
- **Solo revisioni correnti**: la cartella ``SUPERATO`` (documenti obsoleti) è
  esclusa; ogni file nell'albero attivo è la revisione corrente del suo documento.
- **L'AI propone, l'umano firma**: ``--dry-run`` è il default, scrive solo con
  ``--apply``. Il report elenca cosa verrebbe creato/aggiornato, cosa è saltato
  (nome non riconosciuto, es. standard esterni) e i conflitti di codice.
- **Best-effort sul nome**: convenzione ``<CODICE> Rev.<n>_<Titolo>.pdf``
  (es. ``MT CN 06 Rev.21_Risorse Umane.pdf``); gli allegati hanno codice distinto
  (``IDOR CN 01 Allegato A``). I nomi non riconosciuti non vengono importati.

Esempi:
    python manage.py import_sgi_da_share --root "\\\\novisrv\\sistema gestione integrato"
    python manage.py import_sgi_da_share --json
    python manage.py import_sgi_da_share --apply
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from procedure_refresh.models import DocumentType, ProcedureDocument, ProcedureRevision, SourceType

# Codice documento all'inizio del nome file. Riconosce i tipi SGI noti, il punto
# di MOD. (modulistica), "CN" opzionale (con spazio o underscore), il numero (fino
# a 4 cifre), un eventuale sotto-numero "_NN" (es. MT CN 125_10) e un "Allegato X":
# tutto ciò che rende il codice DISTINTO va dentro il codice, per non fondere
# documenti diversi. I separatori "_<lettere>" e " - " restano invece nel titolo.
_CODE_RE = re.compile(
    r"^(?P<code>"
    r"(?:MTSI|MT|IDOR|IDPR|IDP|MOD|MSG|MQ|PQ|PG|IO)"
    r"\.?\s*"
    r"(?:CN[ _]?)?"
    r"\d{1,4}[A-Za-z]?"
    r"(?:_\d{1,3})?"
    r"(?:\s+Allegato\s+[A-Za-z0-9]+)?"
    r")",
    re.IGNORECASE,
)
_REV_RE = re.compile(r"\bRev\.?\s*(\d+)", re.IGNORECASE)
_SUPERATO_RE = re.compile(r"(^|[\\/])SUPERAT", re.IGNORECASE)


def _norm_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _safe_code(text: str) -> str:
    """Codice normalizzato entro i 50 char di ProcedureDocument.code (unique).

    Per i fallback (nome file lungo) tronca e aggiunge un suffisso hash così resta
    univoco anche dopo il taglio.
    """
    code = re.sub(r"\.\s+", ".", _norm_spaces(text))  # "MOD. 093" -> "MOD.093"
    if len(code) <= 50:
        return code
    suffix = "~" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    return code[: 50 - len(suffix)].rstrip() + suffix


def _fallback_parse(filename: str) -> dict:
    """Per i nomi non riconosciuti come codice SGI: importa comunque ('tutto quanto').

    Codice = parte del nome prima di 'Rev'/'rev' (ripulita); revisione e titolo
    best-effort. document_type=ALTRO. Marcato fallback=True per il report.
    """
    stem = Path(filename).stem.lstrip("_ ").strip()
    m_rev = _REV_RE.search(stem)
    revision = m_rev.group(1) if m_rev else ""
    before = stem[: m_rev.start()] if m_rev else stem
    code = _safe_code(before.strip(" _-.") or stem)
    title = _norm_spaces(_REV_RE.sub("", stem).strip(" _-.")) or code
    return {
        "code": code,
        "revision": revision,
        "title": title,
        "document_type": DocumentType.ALTRO,
        "fallback": True,
    }


def parse_sgi_filename(filename: str) -> dict | None:
    """Ricava (code, revision, title, document_type) dal nome file, o None se non
    riconosciuto come documento SGI (es. standard esterni tipo ``prEN_9100_E.pdf``).
    """
    stem = Path(filename).stem.lstrip("_ ").strip()
    if not stem:
        return None
    m_code = _CODE_RE.match(stem)
    if not m_code:
        return None
    code = _safe_code(m_code.group("code"))
    m_rev = _REV_RE.search(stem)
    revision = m_rev.group(1) if m_rev else ""
    rest = stem[m_code.end():]
    rest = _REV_RE.sub("", rest)
    title = _norm_spaces(rest.strip(" _-.")) or code
    upper = code.upper()
    if upper.startswith("MTSI"):
        doc_type = DocumentType.MTSI
    elif upper.startswith("MT"):
        doc_type = DocumentType.MT
    else:
        doc_type = DocumentType.ALTRO
    return {"code": code, "revision": revision, "title": title, "document_type": doc_type, "fallback": False}


def _category_from_path(path: Path, root: Path) -> str:
    """Prima cartella sotto la root (area ISO: 9100_Qualità, 45001_Sicurezza, ...)."""
    try:
        rel = path.resolve().relative_to(root.resolve())
        parts = rel.parts
        return parts[0] if len(parts) > 1 else ""
    except (ValueError, OSError):
        return ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Command(BaseCommand):
    help = "Importa il corpus documentale SGI (PDF) da una share come documenti procedura citabili dall'AI."

    def add_arguments(self, parser):
        parser.add_argument(
            "--root",
            default="",
            help="Cartella di rete da scandire (UNC). Default: settings.PROCEDURE_REFRESH_SGI_SHARE_ROOT.",
        )
        parser.add_argument("--apply", action="store_true", help="Scrive nel DB (default: dry-run).")
        parser.add_argument("--json", action="store_true", dest="as_json", help="Output in JSON.")
        parser.add_argument("--limit", type=int, default=0, help="Max file processati (0 = nessun limite).")
        parser.add_argument(
            "--solo-procedure",
            action="store_true",
            dest="solo_procedure",
            help="Escludi la modulistica MOD.xxx (importa solo procedure/manuali: MT/MTSI/IDOR/IDPR).",
        )

    def handle(self, *args, **options):
        as_json = bool(options.get("as_json"))
        apply = bool(options.get("apply"))
        limit = int(options.get("limit") or 0)
        solo_procedure = bool(options.get("solo_procedure"))
        raw_root = str(options.get("root") or "").strip() or str(
            getattr(settings, "PROCEDURE_REFRESH_SGI_SHARE_ROOT", "") or ""
        ).strip()
        if not raw_root:
            raise CommandError(
                "Nessuna root: passa --root \"\\\\server\\share\" o imposta PROCEDURE_REFRESH_SGI_SHARE_ROOT."
            )
        root = Path(raw_root)
        if not root.exists():
            raise CommandError(f"Root non raggiungibile o inesistente: {raw_root}")

        # 1) Scansione PDF (esclusa SUPERATO).
        parsed: list[dict] = []
        skipped: list[dict] = []
        for pdf in sorted(root.rglob("*.pdf")):
            full = str(pdf)
            if _SUPERATO_RE.search(full):
                continue
            info = parse_sgi_filename(pdf.name)
            if info is None:
                if solo_procedure:
                    skipped.append({"file": pdf.name, "motivo": "non riconosciuto, escluso (--solo-procedure)"})
                    continue
                # "Tutto quanto": importa comunque con codice ricavato dal nome.
                info = _fallback_parse(pdf.name)
            if solo_procedure and info["code"].upper().startswith("MOD"):
                skipped.append({"file": pdf.name, "motivo": "modulistica MOD esclusa (--solo-procedure)"})
                continue
            info["path"] = full
            info["file_name"] = pdf.name
            info["category"] = _category_from_path(pdf, root)
            parsed.append(info)
            if limit and len(parsed) >= limit:
                break

        # 2) Dedup per codice: a parità di codice tiene la revisione più alta
        #    (poi il nome), il resto è un conflitto da segnalare.
        by_code: dict[str, dict] = {}
        conflicts: list[dict] = []
        for info in parsed:
            code = info["code"]
            prev = by_code.get(code)
            if prev is None:
                by_code[code] = info
                continue
            keep, drop = (info, prev) if _rev_int(info) > _rev_int(prev) else (prev, info)
            by_code[code] = keep
            conflicts.append(
                {"code": code, "tenuto": keep["file_name"], "scartato": drop["file_name"]}
            )

        candidates = sorted(by_code.values(), key=lambda d: d["code"])

        # 3) Applica (o simula).
        created_docs = updated_docs = created_revs = 0
        if apply:
            for info in candidates:
                c_doc, c_rev = self._upsert(info)
                created_docs += int(c_doc == "created")
                updated_docs += int(c_doc == "updated")
                created_revs += int(c_rev)

        fallback_count = sum(1 for d in candidates if d.get("fallback"))
        summary = {
            "mode": "apply" if apply else "dry-run",
            "root": raw_root,
            "pdf_validi": len(parsed),
            "documenti_unici": len(candidates),
            "fallback": fallback_count,
            "saltati": len(skipped),
            "conflitti": len(conflicts),
            "documenti_creati": created_docs if apply else None,
            "documenti_aggiornati": updated_docs if apply else None,
            "revisioni_create": created_revs if apply else None,
        }

        if as_json:
            payload = {
                "summary": summary,
                "candidates": [
                    {k: v for k, v in d.items() if k != "path"} | {"path": d["path"]}
                    for d in candidates
                ],
                "skipped": skipped,
                "conflicts": conflicts,
            }
            self.stdout.write(self._safe(json.dumps(payload, ensure_ascii=False, indent=2)))
            return

        self.stdout.write(
            f"{'APPLY' if apply else 'DRY-RUN'} | root={raw_root}"
        )
        self.stdout.write(
            f"PDF validi={len(parsed)} | documenti unici={len(candidates)} "
            f"(di cui fallback nome={fallback_count}) | saltati={len(skipped)} | conflitti={len(conflicts)}"
        )
        self.stdout.write("-" * 78)
        for info in candidates[:40]:
            rev = f"Rev.{info['revision']}" if info["revision"] else "(no rev)"
            self.stdout.write(self._safe(
                f"  [{info['document_type']:>4}] {info['code']} {rev} — {info['title']}  «{info['category']}»"
            ))
        if len(candidates) > 40:
            self.stdout.write(f"  ... e altri {len(candidates) - 40}")
        if skipped:
            self.stdout.write("-" * 78)
            self.stdout.write(self.style.WARNING(f"Saltati ({len(skipped)}), campione:"))
            for s in skipped[:15]:
                self.stdout.write(self._safe(f"  - {s['file']}"))
        if conflicts:
            self.stdout.write("-" * 78)
            self.stdout.write(self.style.WARNING(f"Conflitti di codice ({len(conflicts)}), campione:"))
            for c in conflicts[:15]:
                self.stdout.write(self._safe(f"  - {c['code']}: tengo «{c['tenuto']}», scarto «{c['scartato']}»"))
        self.stdout.write("-" * 78)
        if apply:
            self.stdout.write(self.style.SUCCESS(
                f"Scritti: {created_docs} documenti nuovi, {updated_docs} aggiornati, {created_revs} revisioni."
            ))
            self.stdout.write("Ora: python manage.py index_sgi_documents per indicizzarli nel RAG.")
        else:
            self.stdout.write("Dry-run: nulla scritto. Rilancia con --apply per registrare i documenti.")

    @transaction.atomic
    def _upsert(self, info: dict) -> tuple[str, bool]:
        """Crea/aggiorna documento + revisione corrente. Ritorna (stato_doc, rev_creata)."""
        doc, doc_created = ProcedureDocument.objects.get_or_create(
            code=info["code"],
            defaults={
                "title": info["title"],
                "category": info["category"],
                "document_type": info["document_type"],
                "is_active": True,
                # Import per il RAG: non li marchiamo come "richiede presa visione"
                # (non vanno spinti nei flussi di conferma lettura senza una decisione umana).
                "requires_acknowledgement": False,
            },
        )
        doc_state = "created"
        if not doc_created:
            doc_state = "updated"
            if not doc.is_active:
                doc.is_active = True
                doc.save(update_fields=["is_active", "updated_at"])

        path = Path(info["path"])
        try:
            stat = path.stat()
            file_date = date.fromtimestamp(stat.st_mtime)
            file_hash = _sha256(path)
        except OSError:
            file_date = date.today()
            file_hash = ""

        rev, rev_created = ProcedureRevision.objects.get_or_create(
            document=doc,
            revision_code=info["revision"],
            defaults={
                "revision_date": file_date,
                "effective_date": file_date,
                "source_type": SourceType.FILESERVER,
                "source_path": info["path"],
                "file_name": info["file_name"],
                "file_hash": file_hash,
                "is_current": True,
            },
        )
        if not rev_created:
            rev.source_type = SourceType.FILESERVER
            rev.source_path = info["path"]
            rev.file_name = info["file_name"]
            rev.file_hash = file_hash
            rev.is_current = True  # save() azzera le altre correnti del documento
        else:
            rev.is_current = True
        rev.save()
        return doc_state, rev_created

    def _safe(self, text: str) -> str:
        enc = getattr(getattr(self.stdout, "_out", None), "encoding", None) or "utf-8"
        try:
            text.encode(enc)
            return text
        except (UnicodeEncodeError, LookupError):
            return text.encode(enc, errors="replace").decode(enc, errors="replace")


def _rev_int(info: dict) -> int:
    try:
        return int(info.get("revision") or -1)
    except (TypeError, ValueError):
        return -1
