"""Renderer PDF del modulo MOD.133 "Flow Down Requisiti" (Rev.2) via reportlab.

Riproduce fedelmente il layout del modulo cartaceo (A4 verticale) a partire da un
dizionario di dati gia' preparato dal chiamante (tipicamente costruito da una
`MOD133` + le sue `RigaMOD133`). Il modulo e' bilingue IT/EN e replica:

- intestazione di pagina con spazio logo a sinistra e titolo bilingue a destra
  ("TABELLA DI VERIFICA DEI NUOVI REQUISITI" / "FLOW DOWN FOR NEW REQUIREMENTS");
- blocco campi testata (FONTE, Documento analizzato, Documenti/Processi C.N., Data);
- tabella principale a 7 colonne con super-intestazione "Impatto su documenti"
  a cavallo di due sotto-colonne e le righe dati compilabili;
- blocco NOTE / NOTE a tutta larghezza;
- riga firme (Revisore Autorizzato a sinistra, Responsabile Approvazione a destra);
- pie' di pagina con codice modulo, sigla FLD e revisione.

Robustezza: chiavi mancanti nel dizionario -> cella vuota (mai eccezioni). Con molte
righe dati il documento va automaticamente in multipagina, ripetendo l'intestazione
delle colonne.

API pubblica:
- ``render_mod133(dati: dict) -> bytes`` : ritorna i byte del PDF.
- ``CAMPI_MOD133`` : mappa documentata delle chiavi attese in ``dati`` (per l'integrazione).

Il renderer NON legge/scrive file su disco e NON accede ad alcuna share: opera solo
sui dati passati e produce byte in memoria.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.doctemplate import LayoutError

# ---------------------------------------------------------------------------
# Testi fissi del modulo (bilingue IT/EN) - SOLO ASCII per compatibilita' console.
# ---------------------------------------------------------------------------
TITOLO_IT = "TABELLA DI VERIFICA DEI NUOVI REQUISITI"
TITOLO_EN = "FLOW DOWN FOR NEW REQUIREMENTS"
FOOTER_TESTO = "Costruzioni Novicrom S.r.l. Mod.133 - FLD - Flow Down Requisiti - Rev.2"
NOTA_INTRO = (
    "N.B.: Indicare tutti i paragrafi oggetto di modifica del documento analizzato / "
    "Note: Indicate all paragraphs of the reviewed document that are subject to modification."
)

# ---------------------------------------------------------------------------
# CAMPI_MOD133: contratto delle chiavi attese in ``dati``.
# L'integrazione costruisce ``dati`` con queste chiavi. Tutte facoltative:
# le chiavi assenti/None rendono celle vuote.
# ---------------------------------------------------------------------------
CAMPI_MOD133 = {
    "testata": {
        "fonte": "FONTE (ente di emissione) / SOURCE (issuing body)",
        "documento_analizzato": "Documento analizzato / Reviewed Document",
        "documenti_cn_interessati": (
            "Documenti e Processi C.N. interessati / Affected C.N. Documents and Processes"
        ),
        "data": "Data / Date",
    },
    # ``righe`` = lista di dict; ogni dict e' una riga della tabella principale.
    "righe": {
        "paragrafi": "Paragrafi / Paragraphs (documento analizzato)",
        "argomenti": "Argomenti del documento analizzato / Topics of the reviewed document",
        "impatto_doc": "Impatto su documenti / Impact on documents (SI / NO)",
        "impatto_doc_desc": "Impatto su documenti - dettaglio / Impact on documents (detail)",
        "impatto_operativo": "Impatto operativo / Operational Impact (SI / NO)",
        "paragrafi_cn": "Paragrafi / Paragraphs (documento Costruzioni Novicrom)",
        "argomenti_cn": (
            "Argomenti modificati su documento Costruzioni Novicrom / "
            "Items Modified in Costruzioni Novicrom documents"
        ),
    },
    "note": "Blocco NOTE / NOTE (testo libero)",
    "firme": {
        "revisore": "Nome e firma Revisore Autorizzato / Authorized Reviewer",
        "approvatore": "Nome e firma Responsabile Approvazione / Approver",
    },
}

# Ordine fisico delle 7 colonne dati (chiavi di ogni riga).
_COLONNE_RIGHE = [
    "paragrafi",
    "argomenti",
    "impatto_doc",
    "impatto_doc_desc",
    "impatto_operativo",
    "paragrafi_cn",
    "argomenti_cn",
]

# Proporzioni larghezza colonne (in inch, dal layout del docx originale).
_COL_BASE = [0.83, 1.48, 1.38, 1.38, 1.18, 0.79, 1.54]

# Etichette dell'intestazione tabella (col3+col4 unite -> super-intestazione).
_HEADER_COLONNE = [
    "Paragrafi / Paragraphs",
    "Argomenti del documento analizzato / Topics of the reviewed document",
    "Impatto su documenti / Impact on documents<br/>(SI / NO) - (YES / NO)",
    "",  # coperta dallo SPAN con la col3
    "Impatto operativo / Operational Impact<br/>(SI / NO)",
    "Paragrafi / Paragraphs",
    "Argomenti modificati su documento Costruzioni Novicrom / "
    "Items Modified in Costruzioni Novicrom documents",
]

# Margini di pagina (inch): top piu' ampio per ospitare l'header disegnato a canvas.
_MARGINE_SX = 0.79 * inch
_MARGINE_DX = 0.79 * inch
_MARGINE_TOP = 1.45 * inch
_MARGINE_BOTTOM = 0.60 * inch


# ---------------------------------------------------------------------------
# Stili paragrafo.
# ---------------------------------------------------------------------------
_STILE_CAMPO = ParagraphStyle(
    "mod133_campo",
    fontName="Helvetica",
    fontSize=9,
    leading=12,
    alignment=TA_LEFT,
    spaceAfter=3,
)
_STILE_NOTA_INTRO = ParagraphStyle(
    "mod133_nota_intro",
    fontName="Helvetica-Oblique",
    fontSize=7.5,
    leading=9.5,
    alignment=TA_LEFT,
    spaceBefore=2,
    spaceAfter=4,
)
_STILE_HEADER_CELLA = ParagraphStyle(
    "mod133_header_cella",
    fontName="Helvetica-Bold",
    fontSize=7,
    leading=8.5,
    alignment=TA_CENTER,
    textColor=colors.black,
)
_STILE_CELLA = ParagraphStyle(
    "mod133_cella",
    fontName="Helvetica",
    fontSize=8,
    leading=10,
    alignment=TA_LEFT,
)
_STILE_NOTE_LABEL = ParagraphStyle(
    "mod133_note_label",
    fontName="Helvetica-Bold",
    fontSize=8,
    leading=10,
    alignment=TA_CENTER,
)
_STILE_FIRMA_LABEL = ParagraphStyle(
    "mod133_firma_label",
    fontName="Helvetica-Bold",
    fontSize=8,
    leading=10,
    alignment=TA_LEFT,
)


def _str(valore) -> str:
    """Converte in stringa gestendo None/valori mancanti (mai eccezioni)."""
    if valore is None:
        return ""
    return str(valore)


def _p(testo: str, stile: ParagraphStyle, *, gia_markup: bool = False) -> Paragraph:
    """Costruisce un Paragraph con escaping XML (salvo markup gia' pronto)."""
    if not gia_markup:
        testo = escape(testo)
    if not testo:
        testo = "&nbsp;"
    return Paragraph(testo, stile)


def _larghezze_colonne() -> list[float]:
    """Scala le proporzioni base sulla larghezza utile della pagina A4."""
    utile = A4[0] - _MARGINE_SX - _MARGINE_DX
    totale = sum(_COL_BASE)
    return [base / totale * utile for base in _COL_BASE]


def _disegna_cornice(canvas, doc) -> None:
    """onPage: intestazione (logo + titolo bilingue) e pie' di pagina su OGNI pagina."""
    canvas.saveState()
    larghezza, altezza = A4
    box_sx = _MARGINE_SX
    box_dx = larghezza - _MARGINE_DX

    # --- Intestazione ---
    top = altezza - 0.28 * inch
    header_h = 0.92 * inch
    logo_w = 1.7 * inch

    canvas.setLineWidth(0.7)
    # riquadro logo (sinistra)
    canvas.rect(box_sx, top - header_h, logo_w, header_h)
    canvas.setFont("Helvetica-Bold", 8)
    cx_logo = box_sx + logo_w / 2.0
    cy_logo = top - header_h / 2.0
    canvas.drawCentredString(cx_logo, cy_logo + 3, "COSTRUZIONI")
    canvas.drawCentredString(cx_logo, cy_logo - 8, "NOVICROM S.r.l.")

    # riquadro titolo (destra)
    tit_x = box_sx + logo_w
    tit_w = box_dx - tit_x
    canvas.rect(tit_x, top - header_h, tit_w, header_h)
    cx_tit = tit_x + tit_w / 2.0
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawCentredString(cx_tit, top - header_h / 2.0 + 6, TITOLO_IT)
    canvas.setFont("Helvetica-Oblique", 9)
    canvas.drawCentredString(cx_tit, top - header_h / 2.0 - 11, TITOLO_EN)

    # --- Pie' di pagina ---
    canvas.setFont("Helvetica", 7)
    canvas.drawCentredString(larghezza / 2.0, 0.30 * inch, FOOTER_TESTO)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(box_dx, 0.30 * inch, "Pag. %d" % doc.page)
    canvas.restoreState()


def _blocco_testata(dati: dict) -> list:
    """Paragrafi dei campi testata sopra la tabella principale."""
    testata = CAMPI_MOD133["testata"]
    story = []
    for chiave, etichetta in testata.items():
        valore = _str(dati.get(chiave))
        markup = "<b>%s:</b> %s" % (escape(etichetta), escape(valore))
        story.append(_p(markup, _STILE_CAMPO, gia_markup=True))
    story.append(_p(NOTA_INTRO, _STILE_NOTA_INTRO))
    return story


def _tabella_principale(dati: dict) -> Table:
    """Tabella a 7 colonne con intestazione ripetuta e righe dati (multipagina)."""
    col_w = _larghezze_colonne()

    # Riga intestazione colonne.
    header = [_p(txt, _STILE_HEADER_CELLA, gia_markup=True) for txt in _HEADER_COLONNE]

    righe = dati.get("righe")
    if not isinstance(righe, (list, tuple)):
        righe = []
    if not righe:
        # Nessuna riga: mostra alcune righe vuote per aspetto "modulo da compilare".
        righe = [{} for _ in range(5)]

    corpo = []
    for riga in righe:
        if not isinstance(riga, dict):
            riga = {}
        cella = [_p(_str(riga.get(col)), _STILE_CELLA) for col in _COLONNE_RIGHE]
        corpo.append(cella)

    dati_tabella = [header] + corpo

    stile = TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("SPAN", (2, 0), (3, 0)),  # super-intestazione "Impatto su documenti"
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.85, 0.85, 0.85)),
            ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
            ("TOPPADDING", (0, 1), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
    )
    tabella = Table(dati_tabella, colWidths=col_w, repeatRows=1)
    tabella.setStyle(stile)
    return tabella


def _blocco_note(dati: dict) -> Table:
    """Fascia NOTE / NOTE a tutta larghezza con area testo libero."""
    utile = A4[0] - _MARGINE_SX - _MARGINE_DX
    note = _str(dati.get("note"))
    dati_tabella = [
        [_p("NOTE / NOTE", _STILE_NOTE_LABEL)],
        [_p(note, _STILE_CELLA)],
    ]
    # rowHeights=None sulla riga contenuto: cresce col testo invece di troncarlo a 0.6in
    # (l'eventuale overflow oltre pagina e' gestito dal fallback anti-LayoutError in render).
    tabella = Table(dati_tabella, colWidths=[utile], rowHeights=[None, None])
    tabella.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (0, 0), colors.Color(0.85, 0.85, 0.85)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tabella


def _blocco_firme(dati: dict) -> Table:
    """Riga firme: Revisore Autorizzato (sinistra) e Responsabile Approvazione (destra)."""
    utile = A4[0] - _MARGINE_SX - _MARGINE_DX
    meta = utile / 2.0
    firme = CAMPI_MOD133["firme"]
    lab_rev = _p(
        "<b>%s:</b>" % escape("Nome e firma Revisore Autorizzato / Authorized Reviewer"),
        _STILE_FIRMA_LABEL,
        gia_markup=True,
    )
    lab_appr = _p(
        "<b>%s:</b>" % escape("Nome e firma Responsabile Approvazione / Approver"),
        _STILE_FIRMA_LABEL,
        gia_markup=True,
    )
    val_rev = _p(_str(dati.get("revisore")), _STILE_CELLA)
    val_appr = _p(_str(dati.get("approvatore")), _STILE_CELLA)

    dati_tabella = [
        [lab_rev, lab_appr],
        [val_rev, val_appr],
    ]
    tabella = Table(dati_tabella, colWidths=[meta, meta], rowHeights=[None, 0.75 * inch])
    tabella.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tabella


# Limiti di sicurezza (rete anti-overflow): usati SOLO come fallback se una cella di
# testo libero e' cosi' lunga da eccedere l'altezza pagina (reportlab LayoutError).
# I dati normali non passano mai da qui.
_LIMITE_CELLA = 500
_LIMITE_NOTE = 3000
_LIMITE_TESTATA = 300


def _tronca(valore, limite: int) -> str:
    s = _str(valore)
    if len(s) <= limite:
        return s
    return s[:limite].rstrip() + " [...]"


def _tronca_dati(dati: dict) -> dict:
    """Copia di ``dati`` coi testi liberi troncati a lunghezze pagina-sicure.

    Invocata solo dopo un ``LayoutError`` (cella troppo alta per la pagina) per garantire
    che un PDF venga comunque prodotto, con marcatore visibile ``[...]`` sul testo tagliato.
    """
    fuori = dict(dati)
    for chiave in ("fonte", "documento_analizzato", "documenti_cn_interessati", "data"):
        if chiave in fuori:
            fuori[chiave] = _tronca(fuori.get(chiave), _LIMITE_TESTATA)
    righe = fuori.get("righe")
    if isinstance(righe, (list, tuple)):
        nuove = []
        for riga in righe:
            if isinstance(riga, dict):
                nuove.append({k: _tronca(v, _LIMITE_CELLA) for k, v in riga.items()})
            else:
                nuove.append(riga)
        fuori["righe"] = nuove
    if "note" in fuori:
        fuori["note"] = _tronca(fuori.get("note"), _LIMITE_NOTE)
    return fuori


def _story(dati: dict) -> list:
    story = []
    story.extend(_blocco_testata(dati))
    story.append(Spacer(1, 4))
    story.append(_tabella_principale(dati))
    story.append(Spacer(1, 6))
    story.append(_blocco_note(dati))
    story.append(Spacer(1, 6))
    story.append(_blocco_firme(dati))
    return story


def _costruisci_pdf(dati: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGINE_SX,
        rightMargin=_MARGINE_DX,
        topMargin=_MARGINE_TOP,
        bottomMargin=_MARGINE_BOTTOM,
        title="MOD.133 - Flow Down Requisiti",
    )
    # I flowable non sono riusabili dopo un build fallito: la story si ricostruisce a ogni giro.
    doc.build(_story(dati), onFirstPage=_disegna_cornice, onLaterPages=_disegna_cornice)
    return buffer.getvalue()


COVER_ATTESA_TITOLO = "SPECIFICA IN ATTESA DI COMPILAZIONE MOD.133"
COVER_ATTESA_SUB = (
    "Documento non ancora sottoposto al Flow Down dei requisiti (MOD.133) / "
    "Awaiting requirements flow-down (MOD.133)"
)
_STILE_COVER_TITOLO = ParagraphStyle(
    "cover_titolo", fontName="Helvetica-Bold", fontSize=18, leading=24,
    alignment=TA_CENTER, spaceAfter=10,
)
_STILE_COVER_SUB = ParagraphStyle(
    "cover_sub", fontName="Helvetica-Oblique", fontSize=10.5, leading=14,
    alignment=TA_CENTER, textColor=colors.Color(0.3, 0.3, 0.3), spaceAfter=26,
)
_STILE_COVER_LABEL = ParagraphStyle(
    "cover_label", fontName="Helvetica-Bold", fontSize=10, leading=14, alignment=TA_LEFT,
)
_STILE_COVER_VAL = ParagraphStyle(
    "cover_val", fontName="Helvetica", fontSize=10, leading=14, alignment=TA_LEFT,
)


def _story_cover_attesa(dati: dict) -> list:
    """Story della cover: titolo grande + sottotitolo + tabella metadati della specifica."""
    utile = A4[0] - _MARGINE_SX - _MARGINE_DX
    story = [Spacer(1, 1.3 * inch)]
    story.append(_p(COVER_ATTESA_TITOLO, _STILE_COVER_TITOLO))
    story.append(_p(COVER_ATTESA_SUB, _STILE_COVER_SUB))
    campi = [
        ("Codice / Code", _str(dati.get("codice"))),
        ("Revisione / Revision", _str(dati.get("revisione"))),
        ("Titolo / Title", _str(dati.get("titolo"))),
        ("Fonte / Source", _str(dati.get("cliente"))),
        ("Data / Date", _str(dati.get("data"))),
    ]
    rows = [[_p(k, _STILE_COVER_LABEL), _p(v, _STILE_COVER_VAL)] for k, v in campi]
    tab = Table(rows, colWidths=[utile * 0.32, utile * 0.68])
    tab.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.7, 0.7, 0.7)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.93, 0.93, 0.93)),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tab)
    return story


def render_cover_attesa(dati: dict) -> bytes:
    """Genera la pagina di copertina "SPECIFICA IN ATTESA DI COMPILAZIONE MOD.133" (byte PDF).

    ``dati`` accetta le chiavi ``codice``, ``revisione``, ``titolo``, ``cliente``, ``data``
    (tutte facoltative -> celle vuote, mai crash). Nessun accesso a file/share.
    """
    if not isinstance(dati, dict):
        dati = {}
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=_MARGINE_SX, rightMargin=_MARGINE_DX,
        topMargin=_MARGINE_TOP, bottomMargin=_MARGINE_BOTTOM,
        title="Specifica in attesa MOD.133",
    )
    doc.build(_story_cover_attesa(dati), onFirstPage=_disegna_cornice, onLaterPages=_disegna_cornice)
    return buffer.getvalue()


def render_mod133(dati: dict) -> bytes:
    """Genera il PDF del MOD.133 dai dati forniti e ne ritorna i byte.

    ``dati`` e' un dizionario le cui chiavi sono documentate in ``CAMPI_MOD133``.
    Tutte le chiavi sono facoltative: quelle assenti rendono celle vuote (mai crash).
    Il documento va in multipagina automaticamente quando le righe eccedono la pagina.
    Se una singola cella di testo libero eccede l'altezza pagina (``LayoutError``), il
    renderer ritenta una volta coi testi troncati a lunghezze pagina-sicure: produce
    comunque un PDF (con marcatore ``[...]``) invece di sollevare.
    """
    if not isinstance(dati, dict):
        dati = {}
    try:
        return _costruisci_pdf(dati)
    except LayoutError:
        return _costruisci_pdf(_tronca_dati(dati))
