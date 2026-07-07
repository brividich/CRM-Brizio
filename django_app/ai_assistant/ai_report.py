"""Generatore di report PDF dell'Assistente AI (Ondata 4).

Report "su qualsiasi argomento" ma **ancorato al contesto autorizzato della chat**:
il topic passa per ``build_runtime_context`` (tool live ACL-gated) + RAG/SGI, e
l'AI scrive un report strutturato basato SOLO su quel contesto, cita le fonti e
dichiara "non disponibile" se mancano i dati.

VINCOLI: read-only (niente DB, niente scrittura), ACL ereditata dai tool live,
audit solo-metadati lato endpoint, **fail-safe** (AI offline -> nessun PDF, errore
gestito). Il PDF e' marcato come **bozza generata dall'AI**: l'umano verifica e firma.
"""
from __future__ import annotations

import io
import logging
import re

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_MAX_TOPIC_CHARS = 2000
_MAX_MARKDOWN_CHARS = 20000

_REPORT_PROMPT = (
    "Genera un REPORT strutturato e professionale sull'argomento richiesto, basandoti "
    "ESCLUSIVAMENTE sul contesto live e sui documenti forniti. Struttura: la prima riga "
    "e' il titolo come '# Titolo'; poi sezioni con '## Sezione' e testo discorsivo, con "
    "elenchi puntati dove utile. Riporta dati, numeri, nomi e codici SOLO se presenti nel "
    "contesto: NON inventare nulla. Se il contesto non contiene informazioni sufficienti, "
    "scrivilo esplicitamente. Cita le fonti come compaiono nel contesto (es. per i "
    "documenti SGI «MT CN 06 Rev.7 §4.2»). Scrivi in italiano.\n\n"
    "ARGOMENTO DEL REPORT: {topic}"
)


def _estrai_titolo(markdown: str, topic: str) -> str:
    for line in (markdown or "").splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()[:200] or f"Report: {topic[:120]}"
        if s:
            break
    return f"Report: {topic[:120]}"


def genera_report(request, topic: str) -> dict:
    """Costruisce il report (markdown) dal contesto autorizzato. Niente DB/scrittura."""
    from .services import OllamaChatError, chat_with_ollama, sgi_rag_access
    from .tools import build_runtime_context

    topic = (topic or "").strip()[:_MAX_TOPIC_CHARS]
    runtime_context = build_runtime_context(request, topic)
    has_context = bool(runtime_context.text.strip())
    # Stesso gate ACL per-sorgente SGI della chat: il report non deve consolidare
    # in un PDF scaricabile contenuto Specifiche/Procedure fuori dai permessi (finding #1).
    allow_specifiche, allow_procedure = sgi_rag_access(request)

    prompt = _REPORT_PROMPT.format(topic=topic)
    ai_disponibile = True
    markdown = ""
    model = ""
    rag_sources: tuple[str, ...] = ()
    try:
        result = chat_with_ollama(
            prompt,
            runtime_context=runtime_context.text,
            user_preferences={"style": "dettagliato", "show_limits": True},
            timeout=int(getattr(settings, "OLLAMA_REPORT_TIMEOUT_SECONDS", 120) or 120),
            allow_specifiche=allow_specifiche,
            allow_procedure=allow_procedure,
        )
        markdown = (result.content or "").strip()[:_MAX_MARKDOWN_CHARS]
        model = result.model
        rag_sources = tuple(result.sources or ())
    except OllamaChatError as exc:
        logger.debug("ai_report: AI non disponibile: %s", exc)
        ai_disponibile = False

    fonti: list[str] = list(runtime_context.sources)
    for s in rag_sources:
        if s not in fonti:
            fonti.append(s)

    return {
        "titolo": _estrai_titolo(markdown, topic),
        "markdown": markdown,
        "fonti": fonti,
        "ai_disponibile": ai_disponibile,
        "has_context": has_context,
        "model": model,
        "topic": topic,
        "runtime_audit": runtime_context.audit,
    }


# ── Rendering PDF — stile NOVICROM HUB (canvas, come i PDF del portale) ──────
# Palette del design system del portale (navy/cyan/orange + neutrali condivisi coi
# PDF ticket): coerenza visiva con i documenti gia' generati dal portale.

def _plain(text: str) -> str:
    """Testo per il canvas (no rich-text): rimuove i marcatori markdown.

    Il canvas disegna stringhe letterali (nessuna interpretazione di tag), quindi
    non c'e' rischio di injection; togliamo solo **grassetto**, `code` e simili.
    """
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")
    s = s.replace("`", "").replace("**", "")
    return s


def render_report_pdf(report: dict, *, autore: str = "") -> bytes:
    """Renderizza il report in PDF (bytes) nello stile NOVICROM HUB.

    Solleva se reportlab non e' disponibile (gestito fail-safe dal chiamante).
    """
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    NAVY = HexColor("#0c2545")
    CYAN = HexColor("#1f87cd")
    ORANGE = HexColor("#ff6b00")
    DARK = HexColor("#0f172a")
    GRAY = HexColor("#64748b")
    BORDER = HexColor("#e2e8f0")
    M = 16 * mm
    FOOTER_H = 12 * mm

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4
    content_w = page_width - 2 * M
    titolo = (report.get("titolo") or "Report AI").strip()
    pdf.setTitle(titolo[:120])
    pdf.setAuthor("NOVICROM HUB — Assistente AI")

    generato = timezone.localtime().strftime("%d-%m-%Y %H:%M")
    disclaimer = "Bozza generata dall'AI nei limiti dei tuoi permessi — verifica i dati. L'AI propone, l'umano firma."

    def wrap(text: str, font: str, size: float, max_w: float) -> list[str]:
        out: list[str] = []
        for raw in _plain(text).splitlines() or [" "]:
            line = raw.strip()
            if not line:
                out.append("")
                continue
            words = line.split(" ")
            cur = ""
            for w in words:
                trial = (cur + " " + w).strip()
                if pdf.stringWidth(trial, font, size) <= max_w or not cur:
                    cur = trial
                else:
                    out.append(cur)
                    cur = w
            if cur:
                out.append(cur)
        return out or [""]

    def footer(page_num: int) -> None:
        pdf.setStrokeColor(BORDER)
        pdf.setLineWidth(0.5)
        pdf.line(M, FOOTER_H, page_width - M, FOOTER_H)
        pdf.setFont("Helvetica", 7)
        pdf.setFillColor(GRAY)
        pdf.drawString(M, FOOTER_H - 4 * mm, f"NOVICROM HUB · Report AI · generato il {generato}")
        pdf.drawRightString(page_width - M, FOOTER_H - 4 * mm, f"Pag. {page_num}")
        pdf.setFillColor(HexColor("#94a3b8"))
        pdf.drawString(M, FOOTER_H - 7.5 * mm, disclaimer[:150])

    def new_page(page_num: int) -> tuple[float, int]:
        footer(page_num)
        pdf.showPage()
        page_num += 1
        # mini header di continuazione (band navy sottile)
        y = page_height - 12 * mm
        pdf.setFillColor(NAVY)
        pdf.rect(M, y, content_w, 8 * mm, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(M + 3 * mm, y + 2.5 * mm, "NOVICROM HUB · Report AI")
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(page_width - M - 3 * mm, y + 2.5 * mm, titolo[:70])
        return y - 7 * mm, page_num

    def check(y: float, needed: float, page_num: int) -> tuple[float, int]:
        if y - needed < FOOTER_H + 8 * mm:
            return new_page(page_num)
        return y, page_num

    def section(title: str, y: float, page_num: int) -> tuple[float, int]:
        y, page_num = check(y, 12 * mm, page_num)
        h = 7 * mm
        pdf.setFillColor(CYAN)
        pdf.rect(M, y - h, content_w, h, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(M + 3 * mm, y - h + 2.2 * mm, _plain(title).upper()[:90])
        return y - h - 3 * mm, page_num

    def paragraph(text: str, y: float, page_num: int, *, indent: float = 0.0, bullet: bool = False) -> tuple[float, int]:
        size = 9.5
        x = M + indent
        max_w = content_w - indent - (4 * mm if bullet else 0)
        lines = wrap(text, "Helvetica", size, max_w)
        line_h = 5.0 * mm
        first = True
        for ln in lines:
            y, page_num = check(y, line_h, page_num)
            if bullet and first:
                pdf.setFillColor(CYAN)
                pdf.setFont("Helvetica-Bold", 9.5)
                pdf.drawString(x, y - 3.6 * mm, "•")
            pdf.setFillColor(DARK)
            pdf.setFont("Helvetica", size)
            pdf.drawString(x + (4 * mm if bullet else 0), y - 3.6 * mm, ln)
            y -= line_h
            first = False
        return y - 1 * mm, page_num

    # ── Header prima pagina (band navy + accento orange + titolo) ──
    band_h = 24 * mm
    by = page_height - band_h
    pdf.setFillColor(NAVY)
    pdf.rect(0, by, page_width, band_h, fill=1, stroke=0)
    pdf.setFillColor(ORANGE)
    pdf.rect(0, by - 1.4 * mm, page_width, 1.4 * mm, fill=1, stroke=0)  # accento
    pdf.setFillColor(white)
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(M, by + band_h - 10 * mm, "NOVICROM HUB")
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(HexColor("#9fb6d6"))
    pdf.drawString(M, by + band_h - 15 * mm, "Assistente AI · Report")
    pdf.setFillColor(white)
    pdf.setFont("Helvetica", 8.5)
    meta = f"Generato il {generato}" + (f"  ·  Richiesto da {_plain(autore)[:40]}" if autore else "")
    pdf.drawRightString(page_width - M, by + band_h - 10 * mm, meta)

    y = by - 8 * mm
    page_num = 1
    # Titolo del report (navy, wrap su max 2 righe)
    pdf.setFillColor(NAVY)
    for ln in wrap(titolo, "Helvetica-Bold", 16, content_w)[:2]:
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(M, y - 6 * mm, ln)
        y -= 7.5 * mm
    y -= 3 * mm

    markdown = report.get("markdown") or ""
    if not markdown.strip():
        y, page_num = paragraph(
            "Il servizio AI non ha prodotto contenuto per questo report. Riprova piu' tardi.",
            y, page_num,
        )
    for raw in markdown.splitlines():
        s = raw.strip()
        if not s:
            y -= 2 * mm
            continue
        if s.startswith("# "):
            continue  # titolo gia' reso nell'header
        if s.startswith("### "):
            y, page_num = section(s[4:], y, page_num)
        elif s.startswith("## "):
            y, page_num = section(s[3:], y, page_num)
        elif s.startswith(("- ", "* ")):
            y, page_num = paragraph(s[2:], y, page_num, indent=4 * mm, bullet=True)
        else:
            y, page_num = paragraph(s, y, page_num)

    fonti = report.get("fonti") or []
    if fonti:
        y, page_num = section("Fonti", y, page_num)
        for src in fonti:
            y, page_num = paragraph(str(src), y, page_num, indent=4 * mm, bullet=True)

    footer(page_num)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
