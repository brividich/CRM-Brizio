"""Genera il PDF di riepilogo delle modifiche UI al modulo automazioni.

Eseguibile una tantum:
    .venv\\Scripts\\python.exe docs\\_gen_pdf_ui_polish.py
Genera: docs/automazioni_ui_polish.pdf
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUT_PATH = Path(__file__).resolve().parent / "automazioni_ui_polish.pdf"

# ─── Stili ──────────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "TitleHero", parent=styles["Heading1"],
    fontName="Helvetica-Bold", fontSize=24, textColor=colors.HexColor("#0f172a"),
    spaceAfter=4, leading=28,
)
subtitle_style = ParagraphStyle(
    "Subtitle", parent=styles["Normal"],
    fontName="Helvetica", fontSize=11, textColor=colors.HexColor("#64748b"),
    spaceAfter=18, leading=15,
)
section_style = ParagraphStyle(
    "Section", parent=styles["Heading2"],
    fontName="Helvetica-Bold", fontSize=15, textColor=colors.HexColor("#0f172a"),
    spaceBefore=14, spaceAfter=8, leading=18,
)
h3_style = ParagraphStyle(
    "H3", parent=styles["Heading3"],
    fontName="Helvetica-Bold", fontSize=12, textColor=colors.HexColor("#1d4ed8"),
    spaceBefore=10, spaceAfter=4, leading=15,
)
body_style = ParagraphStyle(
    "Body", parent=styles["Normal"],
    fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#1e293b"),
    spaceAfter=6, leading=14, alignment=TA_LEFT,
)
mono_style = ParagraphStyle(
    "Mono", parent=styles["Normal"],
    fontName="Courier", fontSize=9, textColor=colors.HexColor("#475569"),
    leading=12, leftIndent=8, rightIndent=8, spaceAfter=8,
    backColor=colors.HexColor("#f1f5f9"),
)
small_style = ParagraphStyle(
    "Small", parent=styles["Normal"],
    fontName="Helvetica-Oblique", fontSize=9, textColor=colors.HexColor("#94a3b8"),
    leading=12, spaceAfter=4,
)
chip_style = ParagraphStyle(
    "Chip", parent=styles["Normal"],
    fontName="Helvetica-Bold", fontSize=8, textColor=colors.HexColor("#1d4ed8"),
    leading=11,
)


def hr(color: str = "#e2e8f0") -> HRFlowable:
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor(color),
                      spaceBefore=4, spaceAfter=10)


def pair_table(rows: list[tuple[str, str]]) -> Table:
    """Tabella due colonne Etichetta/Valore in stile auto-meta."""
    data = [[Paragraph(f"<b>{k}</b>", body_style), Paragraph(v, body_style)] for k, v in rows]
    tbl = Table(data, colWidths=[45 * mm, None])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#f1f5f9")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def visual_section(title: str, intro: str, points: list[str]) -> list:
    elems = [Paragraph(title, section_style)]
    if intro:
        elems.append(Paragraph(intro, body_style))
    for p in points:
        elems.append(Paragraph(f"&bull; {p}", body_style))
    elems.append(hr())
    return elems


# ─── Contenuto: Riepilogo visivo ───────────────────────────────────────────────
story: list = []

story.append(Paragraph("NOVICROM HUB — Polish UI Automazioni", title_style))
story.append(Paragraph(
    "Riepilogo modifiche al modulo Automazioni con esempi visivi pagina per pagina "
    "e dettaglio tecnico delle modifiche per il team di sviluppo. "
    "Tutte le modifiche sono SSR/CSS + JS vanilla, niente framework, con parity dark "
    "mode e <font face='Courier'>prefers-reduced-motion</font>.",
    subtitle_style,
))
story.append(pair_table([
    ("Versione app", "1.1.0"),
    ("Data", "2026-06-01"),
    ("Blocchi UI", "9 (rule_detail, run_log_list, queue_list, rule_test, toast, breadcrumb, skeleton, diff old/new, mini-mappa)"),
    ("Verifiche", "manage.py check OK · suite automazioni 321/321 OK"),
    ("File toccati", "6 template pagina, 3 nuovi componenti, 1 templatetags, 1 view"),
]))
story.append(Spacer(1, 10))

story.append(Paragraph("Parte 1 — Riepilogo visivo (cosa vedrai)", section_style))
story.append(hr("#0f172a"))

story.extend(visual_section(
    "1. Lista regole — /admin/automazioni/regole/",
    "Accanto al nome di ogni regola appare una micro-mappa del flusso (22px per step).",
    [
        "Strip icone: <b>⚡</b> trigger &rsaquo; <b>?</b> condizioni &rsaquo; <b>✉</b> email "
        "&rsaquo; <b>✎</b> update &rsaquo; <b>+2</b> altre azioni.",
        "Tooltip su hover spiega il dettaglio (es. action_type, conteggio condizioni).",
        "Si capisce a colpo d'occhio cosa fa una regola senza aprirla.",
    ],
))

story.extend(visual_section(
    "2. Dettaglio regola — /admin/automazioni/regole/&lt;id&gt;/",
    "Riscrittura completa con health indicator, micro-icone e timeline run.",
    [
        "Pallino salute inline col titolo: 🟢 Operativa · 🔵 Pronta · 🟡 Bozza · ⚫ Inattiva.",
        "Breadcrumb compatto in alto: <i>Regole &rsaquo; anomalie &rsaquo; Notifica creazione</i>.",
        "Condizioni come card con chip operatore (= equals, ↻ changed, ≤d days_from_now_lte, ecc.).",
        "Azioni con icone categorizzate per tipo (✉ email, 💬 teams, ✅ approval, ↻ for_each, ⑂ branch).",
        "Hint <font color='#92400e'>Old↔New</font> sulle condizioni con <font face='Courier'>compare_with_old</font>.",
        "Timeline run con pallino verde/rosso/giallo + sparkbar durata invece di tabella piatta.",
    ],
))

story.extend(visual_section(
    "3. Run Log — /admin/automazioni/run-log/",
    "Chip rapidi con conteggi reali sopra ai filtri tradizionali.",
    [
        "Chip: <b>[Tutti] [Solo errori (N)] [Solo test (N)] [Ultime 24h (N)]</b>.",
        "I conteggi escludono i filtri 'di status' attivi, mostrando quanti record "
        "vedresti cliccando il chip.",
        "Stato → status pill colorato (verde/rosso/giallo/blu).",
        "Durata → barra micro proporzionale al run più lento + valore in ms.",
        "Segmented control <b>Lista | Per regola</b> con preferenza in localStorage.",
    ],
))

story.extend(visual_section(
    "4. Queue — /admin/automazioni/queue/",
    "I 4 contatori statici diventano card cliccabili che filtrano lo stato.",
    [
        "Pending / Processing / Done / Error → card con accent laterale colorato.",
        "Click su una card applica il filtro stato; secondo click rimuove il filtro.",
        "Card attiva diventa nera con etichetta <b>× pulisci</b>.",
        "Mini-icona di stato dentro l'etichetta (⏳ ⚙ ✓ !).",
    ],
))

story.extend(visual_section(
    "5. Test regola — /admin/automazioni/regole/&lt;id&gt;/test/",
    "Copy-to-clipboard e riepilogo esito più leggibile.",
    [
        "Bottone <b>Copia</b> in alto a destra su entrambi i textarea JSON raw "
        "(con fallback execCommand per browser legacy).",
        "Feedback visivo 'Copiato ✓' verde per 1.4 secondi.",
        "Esito ultimo test: pill colorato (success/error/skipped) + durata in ms + link al run log.",
        "Messaggio dettagliato in &lt;details&gt; espandibile, auto-open sugli errori.",
    ],
))

story.extend(visual_section(
    "6. Toast non bloccanti (tutte le pagine)",
    "Sostituisce il flash message statico in cima a tutte le pagine automazioni.",
    [
        "Posizione: in alto a destra, sovrapposti, max 380px di larghezza.",
        "Auto-dismiss: 4.5s per info/success/warning, 9s per gli errori.",
        "Progress bar in basso che scorre verso sinistra.",
        "Pausa al passaggio del mouse, riprende all'uscita.",
        "4 varianti con icona e colore: success ✓ · error ✕ · warning ! · info i.",
        "Animazione di entrata da destra (slide + scale).",
    ],
))

story.extend(visual_section(
    "7. Skeleton loader (designer regola)",
    "Sostituisce lo spinner piccolo durante le chiamate HTMX.",
    [
        "Pill animato <i>'Generazione card…'</i> con pallino blu che pulsa.",
        "Componente <font face='Courier'>auto-skeleton-pill</font> riutilizzabile.",
        "Disponibili anche <font face='Courier'>auto-skeleton-card</font> e <font face='Courier'>auto-skeleton-text</font>.",
        "Mostrato/nascosto automaticamente da HTMX via classe <font face='Courier'>htmx-request</font>.",
    ],
))

story.append(PageBreak())

# ─── Parte 2 — Dettaglio tecnico ───────────────────────────────────────────────
story.append(Paragraph("Parte 2 — Dettaglio tecnico (handoff sviluppo)", section_style))
story.append(hr("#0f172a"))

story.append(Paragraph("File modificati", h3_style))
file_rows = [
    ("rule_detail.html", "Riscritto: health indicator, micro-icone, timeline run, diff hint."),
    ("rule_list.html", "Mini-mappa flusso accanto al nome regola; load automazioni_extras."),
    ("rule_designer.html", "Toast + skeleton + indicator skeleton sul bottone HTMX 'Nuova azione'."),
    ("run_log_list.html", "Chip rapidi + status pill + sparkbar + segmented Lista/Per regola."),
    ("queue_list.html", "Card stato cliccabili filtranti con accent laterale colorato."),
    ("rule_test.html", "Copy JSON + esito con pill + messaggio espandibile."),
    ("components/toasts.html", "NUOVO. Toast riutilizzabili (CSS + JS vanilla, dark mode + reduced-motion)."),
    ("components/breadcrumbs.html", "NUOVO. Breadcrumb data-driven (items=[{label, url}])."),
    ("components/skeletons.html", "NUOVO. auto-skeleton-pill / -card / -text."),
    ("templatetags/automazioni_extras.py", "NUOVO. 5 filter custom (op/action symbol, chip class, status class, dur_pct)."),
    ("views.py", "rule_detail_page (max_execution_ms, has_compare_with_old, breadcrumb_items); "
                "rule_list_page (flow_preview + prefetch actions/conditions); "
                "run_log_list_page (chip_counts, max_execution_ms, filtro recent=24h)."),
]
for fn, desc in file_rows:
    story.append(Paragraph(f"<font face='Courier' color='#1d4ed8'>{fn}</font> — {desc}", body_style))

story.append(Paragraph("Template filter custom", h3_style))
story.append(Paragraph(
    "Tutti in <font face='Courier'>automazioni/templatetags/automazioni_extras.py</font>, "
    "caricati con <font face='Courier'>{% load automazioni_extras %}</font>:",
    body_style,
))
for name, desc in [
    ("automazioni_op_symbol", "= ≠ ↻ → ≥ ≤ ∋ ∅ ∈ ≤d ≥d  per ogni operatore condizione."),
    ("automazioni_action_symbol", "✉ 💬 ✅ ✎ ⊕ ⏱ ⏰ ↻ ⑂ ∞ 📊 per ogni action_type."),
    ("automazioni_action_chip_class", "Categoria CSS: is-action / is-control / is-side."),
    ("automazioni_run_status_class", "Mapping status run: is-ok / is-fail / is-skip / is-pending."),
    ("automazioni_dur_pct", "Percentuale durata su max (per sparkbar). Min 5% per visibilità."),
]:
    story.append(Paragraph(f"<font face='Courier' color='#6d28d9'>{name}</font> &mdash; {desc}", body_style))

story.append(Paragraph("Componenti nuovi (uso)", h3_style))
story.append(Paragraph("<b>Toast</b>:", body_style))
story.append(Paragraph(
    "{% include &quot;automazioni/components/toasts.html&quot; %}<br/>"
    "Renderizza i messaggi Django come toast. Sostituisce flash_messages.html nelle pagine automazioni.",
    mono_style,
))
story.append(Paragraph("<b>Breadcrumb</b>:", body_style))
story.append(Paragraph(
    "{% include &quot;automazioni/components/breadcrumbs.html&quot; with items=breadcrumb_items only %}<br/>"
    "items = [{&quot;label&quot;: &quot;Regole&quot;, &quot;url&quot;: rule_list_url}, "
    "{&quot;label&quot;: rule.name, &quot;url&quot;: None}]",
    mono_style,
))
story.append(Paragraph("<b>Skeleton</b> (con HTMX):", body_style))
story.append(Paragraph(
    "{% include &quot;automazioni/components/skeletons.html&quot; %}<br/>"
    "&lt;span class=&quot;htmx-indicator auto-skeleton-pill&quot;&gt;...&lt;/span&gt;",
    mono_style,
))

story.append(Paragraph("Decisioni di scope", h3_style))
for d in [
    "<b>Blocco 4 (rule_test split-pane)</b>: la pagina aveva già un layout 2-colonne "
    "(composer + JSON raw + catalogo sorgenti laterale). Ho aggiunto solo i ritocchi "
    "mancanti (copy JSON, pill esito, dettaglio espandibile) invece di riscriverla.",
    "<b>Blocco 5 (toast)</b>: applicati alle 6 pagine principali. Pattern 'non bloccante' "
    "via auto-dismiss/pause-on-hover, non async (le view continuano a fare POST + redirect).",
    "<b>Blocco 7 (skeleton)</b>: HTMX nel modulo è limitato (1 punto in rule_designer). "
    "Il componente è generico e pronto per usi futuri.",
    "<b>Blocco 8 (diff Prima/Dopo)</b>: sulla pagina della <i>regola</i> (configurazione) il "
    "diff vero non esiste — emerge solo nei run log. Ho aggiunto l'hint configurativo "
    "che evidenzia le condizioni con compare_with_old. Il diff valori reali resta più "
    "adatto a run_log_detail se vorrai estenderlo lì.",
]:
    story.append(Paragraph(f"&bull; {d}", body_style))

story.append(Paragraph("Verifiche", h3_style))
story.append(Paragraph(
    "<font face='Courier'>python django_app/manage.py check --settings=config.settings.dev</font> &rarr; "
    "<font color='#166534'><b>0 issue</b></font>", body_style))
story.append(Paragraph(
    "<font face='Courier'>python django_app/manage.py test automazioni --settings=config.settings.test</font> &rarr; "
    "<font color='#166534'><b>321/321 OK</b></font>", body_style))

story.append(Spacer(1, 6))
story.append(hr())
story.append(Paragraph(
    "Documento generato automaticamente — NOVICROM HUB Automazioni · Polish UI · 2026-06-01",
    small_style,
))


# ─── Build ─────────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    str(OUT_PATH), pagesize=A4,
    leftMargin=18 * mm, rightMargin=18 * mm,
    topMargin=18 * mm, bottomMargin=18 * mm,
    title="NOVICROM HUB — Polish UI Automazioni",
    author="NOVICROM HUB",
)
doc.build(story)
print(f"PDF generato: {OUT_PATH}")
