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

import html
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
    from .services import OllamaChatError, chat_with_ollama
    from .tools import build_runtime_context

    topic = (topic or "").strip()[:_MAX_TOPIC_CHARS]
    runtime_context = build_runtime_context(request, topic)
    has_context = bool(runtime_context.text.strip())

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


# ── Rendering PDF (reportlab) ───────────────────────────────────────────────

def _md_inline(text: str) -> str:
    """Escapa l'output del modello (untrusted) e applica solo il grassetto markdown.

    L'escape PRIMA del markup evita injection nei tag mini-HTML di reportlab.
    """
    safe = html.escape(text or "", quote=False)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    return safe


def render_report_pdf(report: dict, *, autore: str = "") -> bytes:
    """Renderizza il report in PDF (bytes). Solleva se reportlab non e' disponibile."""
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    base = getSampleStyleSheet()
    st_title = ParagraphStyle(
        "AiTitle", parent=base["Title"], fontSize=18, leading=22, spaceAfter=4, textColor="#0c2545"
    )
    st_meta = ParagraphStyle("AiMeta", parent=base["Normal"], fontSize=8.5, textColor="#64748b", spaceAfter=10)
    st_h2 = ParagraphStyle(
        "AiH2", parent=base["Heading2"], fontSize=12.5, leading=15, spaceBefore=10, spaceAfter=4, textColor="#1f87cd"
    )
    st_body = ParagraphStyle("AiBody", parent=base["Normal"], fontSize=10, leading=14, alignment=TA_LEFT, spaceAfter=4)
    st_bullet = ParagraphStyle("AiBullet", parent=st_body, leftIndent=12, bulletIndent=2)
    st_src = ParagraphStyle("AiSrc", parent=base["Normal"], fontSize=8.5, leading=12, textColor="#475569")

    generato = timezone.localtime().strftime("%d-%m-%Y %H:%M")
    flow: list = []
    flow.append(Paragraph(_md_inline(report.get("titolo") or "Report AI"), st_title))
    meta_bits = [f"Generato il {generato}"]
    if autore:
        meta_bits.append(f"Richiesto da {html.escape(autore, quote=False)}")
    flow.append(Paragraph(" · ".join(meta_bits), st_meta))

    markdown = report.get("markdown") or ""
    if not markdown.strip():
        flow.append(Paragraph(
            "Il servizio AI non ha prodotto contenuto per questo report. Riprova piu' tardi.",
            st_body,
        ))
    for raw in markdown.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            flow.append(Spacer(1, 4))
            continue
        if s.startswith("# "):
            continue  # titolo gia' reso a parte
        if s.startswith("### "):
            flow.append(Paragraph(_md_inline(s[4:].strip()), st_h2))
        elif s.startswith("## "):
            flow.append(Paragraph(_md_inline(s[3:].strip()), st_h2))
        elif s.startswith(("- ", "* ")):
            flow.append(Paragraph(_md_inline(s[2:].strip()), st_bullet, bulletText="•"))
        else:
            flow.append(Paragraph(_md_inline(s), st_body))

    fonti = report.get("fonti") or []
    if fonti:
        flow.append(Spacer(1, 10))
        flow.append(Paragraph("Fonti", st_h2))
        for src in fonti:
            flow.append(Paragraph("• " + html.escape(str(src), quote=False), st_src))

    disclaimer = (
        "Bozza generata dall'AI dal contesto live nei limiti dei tuoi permessi. "
        "Verifica i dati prima di condividere o decidere. L'AI propone, l'umano firma."
    )

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor("#94a3b8")
        width = A4[0]
        canvas.drawString(18 * mm, 12 * mm, disclaimer[:140])
        canvas.drawRightString(width - 18 * mm, 12 * mm, f"NOVICROM HUB · pag. {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        title=(report.get("titolo") or "Report AI"),
    )
    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
