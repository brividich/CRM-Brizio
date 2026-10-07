"""Inventario (sola lettura) della cartella SGI sul file server — fase F0.

Fotografa la share prima di estendere estrazione/indicizzazione: quanti file per
formato e per area, quanti PDF sono scansioni, quante pagine hanno tabelle,
quanti nomi non seguono la convenzione, quanti codici esistono sia in PDF sia in
formato editabile, copertura degli heading ``§`` e confronto col cap
``OLLAMA_RAG_SGI_MAX_PROCS``.

Principi:
- **Sola lettura**: nessuna scrittura DB, nessun file creato/modificato sulla
  share (``--output`` rifiuta un percorso sotto la root). Nessuna AI coinvolta.
- **Riuso**: scansione, parser dei nomi e filtro ``SUPERATO`` sono quelli di
  ``import_sgi_da_share`` (importati, non duplicati) -> l'inventario conta
  esattamente ciò che l'import vedrebbe.
- **Solo aggregati**: il report contiene numeri e codici documento, mai testo
  estratto dai documenti.

Esempi:
    python manage.py sgi_inventario
    python manage.py sgi_inventario --root "\\\\server\\share" --json
    python manage.py sgi_inventario --sample 50 --output C:\\Users\\me\\Desktop\\sgi.json --json
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from procedure_refresh.management.commands.import_sgi_da_share import (
    _SUPERATO_RE,
    _category_from_path,
    parse_sgi_filename,
    scan_share_candidates,
)

# Formati riportati singolarmente; tutto il resto finisce in "altro".
FORMATI_NOTI = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx")
# Formati "editabili" per il confronto PDF vs sorgente.
FORMATI_EDITABILI = (".docx", ".doc", ".xlsx", ".xls", ".pptx")
# Soglia: sotto questa media di caratteri/pagina il PDF e' considerato una scansione.
SOGLIA_SCANSIONE_CHARS = 50
# Quanti codici di esempio riportare (solo codici, mai titoli o testo).
N_ESEMPI = 10


def _is_temp_file(path: Path) -> bool:
    """File di lock/temporanei di Office (``~$nome.docx``) e file nascosti di sistema."""
    name = path.name
    return name.startswith("~$") or name.lower() in {"thumbs.db", "desktop.ini"}


def _formato(path: Path) -> str:
    ext = path.suffix.lower()
    return ext if ext in FORMATI_NOTI else "altro"


def analizza_pdf(path: Path, *, tabelle: bool = True) -> dict:
    """Metriche di un PDF: pagine, caratteri, pagine con tabelle, sezioni ``§``.

    Fail-safe: PDF illeggibile -> ``{"errore": ...}``. Il testo NON viene ritornato.
    """
    try:
        import fitz  # pymupdf
    except Exception:  # pragma: no cover - pymupdf e' una dipendenza del progetto
        return {"errore": "pymupdf non disponibile"}
    try:
        from ai_assistant.services import _sgi_sections
    except Exception:  # pragma: no cover
        _sgi_sections = None

    try:
        with fitz.open(str(path)) as doc:
            pagine = doc.page_count
            parti: list[str] = []
            pagine_tabelle = 0
            for page in doc:
                parti.append(page.get_text())
                if tabelle:
                    try:
                        if page.find_tables().tables:
                            pagine_tabelle += 1
                    except Exception:
                        pass
    except Exception as exc:
        return {"errore": type(exc).__name__}

    testo = "\n".join(parti)
    caratteri = sum(len(p.strip()) for p in parti)
    media = (caratteri / pagine) if pagine else 0.0
    sezioni = 0
    if _sgi_sections is not None and testo.strip():
        sezioni = sum(1 for label, _body in _sgi_sections(testo) if label)
    return {
        "pagine": pagine,
        "caratteri": caratteri,
        "media_caratteri_pagina": round(media, 1),
        "scansione": media < SOGLIA_SCANSIONE_CHARS,
        "pagine_con_tabelle": pagine_tabelle if tabelle else None,
        "sezioni": sezioni,
    }


def _revisioni_correnti_db() -> int | None:
    """Revisioni correnti di documenti attivi (stesso filtro del loader RAG). Sola lettura."""
    try:
        from procedure_refresh.models import ProcedureRevision

        return ProcedureRevision.objects.filter(is_current=True, document__is_active=True).count()
    except Exception:
        return None


def build_inventario(root: Path, *, sample: int = 0, tabelle: bool = True) -> dict:
    """Costruisce l'inventario aggregato della share. Sola lettura."""
    per_formato: Counter = Counter()
    altro_estensioni: Counter = Counter()
    per_area: dict[str, Counter] = defaultdict(Counter)
    esclusi_superato = 0
    esclusi_temp = 0

    # codice -> insieme di revisioni, separati per PDF ed editabile
    pdf_codici: dict[str, set[str]] = defaultdict(set)
    edit_codici: dict[str, set[str]] = defaultdict(set)
    edit_per_formato: Counter = Counter()
    edit_non_riconosciuti = 0
    pdf_files: list[Path] = []

    for path in sorted(root.rglob("*")):
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        if _SUPERATO_RE.search(str(path)):
            esclusi_superato += 1
            continue
        if _is_temp_file(path):
            esclusi_temp += 1
            continue
        formato = _formato(path)
        per_formato[formato] += 1
        if formato == "altro":
            altro_estensioni[path.suffix.lower() or "(nessuna)"] += 1
        area = _category_from_path(path, root) or "(radice)"
        per_area[area][formato] += 1

        if formato == ".pdf":
            pdf_files.append(path)
            info = parse_sgi_filename(path.name)
            if info is not None:
                pdf_codici[info["code"].upper()].add(info["revision"])
        elif formato in FORMATI_EDITABILI:
            info = parse_sgi_filename(path.name)
            if info is None:
                edit_non_riconosciuti += 1
                continue
            edit_codici[info["code"].upper()].add(info["revision"])
            edit_per_formato[formato] += 1

    # Stessa pipeline dell'import (scansione PDF + dedup titolo-aware).
    candidates, _skipped, conflicts = scan_share_candidates(root)
    pdf_non_riconosciuti = sum(1 for p in pdf_files if parse_sgi_filename(p.name) is None)

    codici_comuni = sorted(set(pdf_codici) & set(edit_codici))
    stessa_revisione = sorted(c for c in codici_comuni if pdf_codici[c] & edit_codici[c])
    solo_editabile = sorted(set(edit_codici) - set(pdf_codici))

    # Analisi profonda dei PDF (eventualmente su un campione).
    analizzati = pdf_files[:sample] if sample else pdf_files
    pagine_tot = pagine_scansione = pagine_tabelle = 0
    pdf_scansione = pdf_nativi = pdf_errori = 0
    con_heading = 0
    errori: Counter = Counter()
    for path in analizzati:
        res = analizza_pdf(path, tabelle=tabelle)
        if "errore" in res:
            pdf_errori += 1
            errori[res["errore"]] += 1
            continue
        pagine_tot += res["pagine"]
        if res["scansione"]:
            pdf_scansione += 1
            pagine_scansione += res["pagine"]
        else:
            pdf_nativi += 1
        pagine_tabelle += res["pagine_con_tabelle"] or 0
        if res["sezioni"] >= 2:
            con_heading += 1
    pdf_letti = pdf_scansione + pdf_nativi

    cap = int(getattr(settings, "OLLAMA_RAG_SGI_MAX_PROCS", 300) or 300)
    rev_db = _revisioni_correnti_db()

    return {
        "generato_il": timezone.now().isoformat(timespec="seconds"),
        "root": str(root),
        "file": {
            "totale": sum(per_formato.values()),
            "per_formato": {f: per_formato.get(f, 0) for f in (*FORMATI_NOTI, "altro")},
            "altro_per_estensione": dict(altro_estensioni.most_common()),
            "esclusi_superato": esclusi_superato,
            "esclusi_temporanei": esclusi_temp,
        },
        "per_area": {
            area: {f: cnt.get(f, 0) for f in (*FORMATI_NOTI, "altro")} | {"totale": sum(cnt.values())}
            for area, cnt in sorted(per_area.items())
        },
        "nomi": {
            "pdf_non_riconosciuti_fallback": pdf_non_riconosciuti,
            "editabili_non_riconosciuti": edit_non_riconosciuti,
            "pdf_documenti_unici": len(candidates),
            "pdf_revisioni_superate_in_albero": len(conflicts),
            "pdf_codici_disambiguati": sum(1 for c in candidates if c.get("disambiguated_from")),
        },
        "pdf_vs_editabile": {
            "codici_pdf": len(pdf_codici),
            "codici_editabili": len(edit_codici),
            "editabili_riconosciuti_per_formato": dict(edit_per_formato),
            "codici_in_entrambi": len(codici_comuni),
            "codici_in_entrambi_stessa_revisione": len(stessa_revisione),
            "codici_solo_editabile": len(solo_editabile),
            "esempi_in_entrambi": codici_comuni[:N_ESEMPI],
            "esempi_solo_editabile": solo_editabile[:N_ESEMPI],
        },
        "pdf": {
            "analizzati": len(analizzati),
            "campione": bool(sample),
            "illeggibili": pdf_errori,
            "errori_per_tipo": dict(errori),
            "testo_nativo": pdf_nativi,
            "scansioni": pdf_scansione,
            "soglia_scansione_caratteri_pagina": SOGLIA_SCANSIONE_CHARS,
            "pagine_totali": pagine_tot,
            "pagine_scansione": pagine_scansione,
            "pagine_con_tabelle": pagine_tabelle if tabelle else None,
            "heading_almeno_2_sezioni": con_heading,
            "heading_copertura_pct": round(100.0 * con_heading / pdf_letti, 1) if pdf_letti else 0.0,
        },
        "cap_rag": {
            "OLLAMA_RAG_SGI_MAX_PROCS": cap,
            "revisioni_correnti_db": rev_db,
            "documenti_pdf_share": len(candidates),
            "eccedenza_db": (rev_db - cap) if rev_db is not None and rev_db > cap else 0,
            "eccedenza_share": max(len(candidates) - cap, 0),
        },
    }


def render_markdown(inv: dict) -> str:
    f = inv["file"]
    n = inv["nomi"]
    pe = inv["pdf_vs_editabile"]
    p = inv["pdf"]
    c = inv["cap_rag"]
    formati = list(f["per_formato"].keys())
    righe = [
        f"# Inventario SGI — {inv['generato_il']}",
        "",
        f"File attivi: **{f['totale']}** (esclusi SUPERATO: {f['esclusi_superato']}, temporanei: {f['esclusi_temporanei']})",
        "",
        "## Per formato",
        "",
        "| " + " | ".join(formati) + " |",
        "|" + "---|" * len(formati),
        "| " + " | ".join(str(f["per_formato"][k]) for k in formati) + " |",
        "",
    ]
    if f["altro_per_estensione"]:
        righe.append("Altro: " + ", ".join(f"{k} {v}" for k, v in f["altro_per_estensione"].items()))
        righe.append("")
    righe += [
        "## Per area (cartella di primo livello)",
        "",
        "| Area | " + " | ".join(formati) + " | Totale |",
        "|---|" + "---|" * (len(formati) + 1),
    ]
    for area, cnt in inv["per_area"].items():
        righe.append(f"| {area} | " + " | ".join(str(cnt[k]) for k in formati) + f" | {cnt['totale']} |")
    righe += [
        "",
        "## Nomi file",
        "",
        f"- PDF documenti unici (come l'import): {n['pdf_documenti_unici']}",
        f"- PDF non riconosciuti (fallback): {n['pdf_non_riconosciuti_fallback']}",
        f"- PDF revisioni superate nell'albero attivo: {n['pdf_revisioni_superate_in_albero']}",
        f"- PDF codici disambiguati: {n['pdf_codici_disambiguati']}",
        f"- Editabili non riconosciuti: {n['editabili_non_riconosciuti']}",
        "",
        "## PDF vs editabile",
        "",
        f"- Codici in PDF: {pe['codici_pdf']} — in editabile: {pe['codici_editabili']}",
        f"- Codici in entrambi: **{pe['codici_in_entrambi']}** (stessa revisione: {pe['codici_in_entrambi_stessa_revisione']})",
        f"- Codici solo editabili (nessun PDF): {pe['codici_solo_editabile']}",
        f"- Esempi in entrambi: {', '.join(pe['esempi_in_entrambi']) or '—'}",
        "",
        "## PDF — qualità del testo",
        "",
        f"- Analizzati: {p['analizzati']}{' (campione)' if p['campione'] else ''}, illeggibili: {p['illeggibili']}",
        f"- Testo nativo: {p['testo_nativo']} — scansioni (< {p['soglia_scansione_caratteri_pagina']} car/pag): **{p['scansioni']}**",
        f"- Pagine totali: {p['pagine_totali']} — di cui in scansioni: **{p['pagine_scansione']}**",
        f"- Pagine con tabelle: {p['pagine_con_tabelle'] if p['pagine_con_tabelle'] is not None else 'non calcolate'}",
        f"- Documenti con ≥ 2 sezioni §: {p['heading_almeno_2_sezioni']} ({p['heading_copertura_pct']}%)",
        "",
        "## Cap RAG",
        "",
        f"- OLLAMA_RAG_SGI_MAX_PROCS = {c['OLLAMA_RAG_SGI_MAX_PROCS']}",
        f"- Revisioni correnti nel DB: {c['revisioni_correnti_db'] if c['revisioni_correnti_db'] is not None else 'n/d'}"
        f" (eccedenza {c['eccedenza_db']})",
        f"- Documenti PDF sulla share: {c['documenti_pdf_share']} (eccedenza {c['eccedenza_share']})",
        "",
    ]
    return "\n".join(righe)


class Command(BaseCommand):
    help = "Inventario in sola lettura della cartella SGI (formati, scansioni, tabelle, nomi, cap RAG)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--root",
            default="",
            help="Cartella di rete da scandire (UNC). Default: settings.PROCEDURE_REFRESH_SGI_SHARE_ROOT.",
        )
        parser.add_argument("--json", action="store_true", dest="as_json", help="Output in JSON.")
        parser.add_argument("--sample", type=int, default=0, help="Analizza a fondo solo i primi N PDF (0 = tutti).")
        parser.add_argument(
            "--senza-tabelle", action="store_true", dest="senza_tabelle",
            help="Salta il rilevamento tabelle (page.find_tables), più veloce.",
        )
        parser.add_argument(
            "--output", default="",
            help="Scrive il report anche su file (mai sotto la root della share).",
        )

    def handle(self, *args, **options):
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

        output = str(options.get("output") or "").strip()
        if output:
            out_path = Path(output)
            try:
                out_path.resolve().relative_to(root.resolve())
            except ValueError:
                pass
            else:
                raise CommandError("--output non può stare sotto la root della share (sola lettura).")

        inv = build_inventario(
            root,
            sample=max(int(options.get("sample") or 0), 0),
            tabelle=not options.get("senza_tabelle"),
        )
        text = json.dumps(inv, ensure_ascii=False, indent=2) if options.get("as_json") else render_markdown(inv)
        if output:
            Path(output).write_text(text, encoding="utf-8")
        self.stdout.write(self._safe(text))

    def _safe(self, text: str) -> str:
        enc = getattr(getattr(self.stdout, "_out", None), "encoding", None) or "utf-8"
        try:
            text.encode(enc)
            return text
        except (UnicodeEncodeError, LookupError):
            return text.encode(enc, errors="replace").decode(enc, errors="replace")
