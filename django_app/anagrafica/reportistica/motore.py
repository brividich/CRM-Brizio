"""Composizione e rendering dei documenti (anteprima HTML, PDF, Excel).

Un documento si compone una sola volta (:func:`componi`) e lo stesso oggetto
alimenta anteprima, PDF ed Excel: i numeri non possono divergere fra i formati.

Testi liberi: markdown minimo e prevedibile, pensato per chi non scrive codice
— ``## titolo``, righe che iniziano con ``-`` per gli elenchi, ``**grassetto**``,
riga vuota per andare a capo — piu' i segnaposto ``{{oggi}}``, ``{{periodo}}``,
``{{destinatario}}``, ``{{n_persone}}``... sostituiti in generazione.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from html import escape

from django.utils import timezone

from . import sezioni as catalogo
from .dati import Contesto, Perimetro, periodo_da_tipo

logger = logging.getLogger(__name__)

SEGNAPOSTO = (
    ("{{oggi}}", "data di generazione"),
    ("{{periodo}}", "periodo del report"),
    ("{{periodo_da}}", "inizio periodo"),
    ("{{periodo_a}}", "fine periodo"),
    ("{{destinatario}}", "destinatario"),
    ("{{n_persone}}", "persone nel perimetro"),
    ("{{perimetro}}", "descrizione del perimetro"),
    ("{{norme}}", "norme di riferimento"),
    ("{{redatto_da}}", "redattore"),
    ("{{approvato_da}}", "approvatore"),
)

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str) -> str:
    """Testo -> markup inline sicuro (escape + solo <b>), valido per HTML e ReportLab."""
    return _BOLD.sub(r"<b>\1</b>", escape(text, quote=False))


def paragrafi(testo: str) -> list[tuple[str, str]]:
    """Markdown minimo -> [(tipo, markup)] con tipo in {"h", "p", "li"}."""
    out: list[tuple[str, str]] = []
    buffer: list[str] = []

    def _flush() -> None:
        if buffer:
            out.append(("p", "<br/>".join(_inline(x) for x in buffer)))
            buffer.clear()

    for raw in (testo or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            _flush()
        elif line.startswith("#"):
            _flush()
            out.append(("h", _inline(line.lstrip("#").strip())))
        elif line[:2] in ("- ", "* ", "• "):
            _flush()
            out.append(("li", _inline(line[2:].strip())))
        else:
            buffer.append(line)
    _flush()
    return out


@dataclass
class Elemento:
    tipo: str  # testo | sezione | pagina | firme | negata | errore
    blocco_id: int | None = None
    titolo: str = ""
    paragrafi: list[tuple[str, str]] = field(default_factory=list)
    sezione: object = None
    risultato: object = None
    colonne: list[tuple[str, str]] = field(default_factory=list)
    righe: list[list] = field(default_factory=list)
    toni: list[str] = field(default_factory=list)
    mostra_indicatori: bool = True
    mostra_tabella: bool = True
    mostra_note: bool = True
    riferimenti: str = ""

    @property
    def righe_con_tono(self) -> list[tuple[list, str]]:
        return [(riga, self.toni[i] if i < len(self.toni) else "") for i, riga in enumerate(self.righe)]


@dataclass
class Documento:
    titolo: str
    sottotitolo: str
    destinatario: str
    riservatezza: str
    norme: list[str]
    periodo_label: str
    perimetro_label: str
    date_from: date
    date_to: date
    generato_il: object
    generato_da: str
    redatto_da: str = ""
    verificato_da: str = ""
    approvato_da: str = ""
    elementi: list[Elemento] = field(default_factory=list)

    @property
    def contiene_dati_personali(self) -> bool:
        return any(
            e.tipo == "sezione" and e.mostra_tabella and e.righe and getattr(e.sezione, "nominativa", True)
            for e in self.elementi
        )

    @property
    def sezioni_calcolate(self) -> list[Elemento]:
        return [e for e in self.elementi if e.tipo == "sezione"]


@dataclass
class Parametri:
    """Scelte fatte in generazione: prevalgono su quelle salvate nel modello."""

    periodo_tipo: str
    data_da: date | None
    data_a: date | None
    perimetro: Perimetro
    titolo: str = ""
    sottotitolo: str = ""
    destinatario: str = ""
    testi: dict[int, str] = field(default_factory=dict)

    @classmethod
    def dal_modello(cls, modello) -> "Parametri":
        return cls(
            periodo_tipo=modello.periodo_tipo, data_da=modello.data_da, data_a=modello.data_a,
            perimetro=Perimetro.from_dict(modello.filtri), titolo=modello.titolo_documento,
            sottotitolo=modello.sottotitolo, destinatario=modello.destinatario,
            testi={b.pk: b.testo for b in modello.blocchi.all() if b.tipo in ("TESTO", "SEZIONE")},
        )

    def as_dict(self) -> dict:
        return {
            "periodo_tipo": self.periodo_tipo,
            "data_da": self.data_da.isoformat() if self.data_da else "",
            "data_a": self.data_a.isoformat() if self.data_a else "",
            "perimetro": self.perimetro.as_dict(),
            "titolo": self.titolo, "destinatario": self.destinatario,
        }


def _nome_utente(user) -> str:
    if user is None:
        return ""
    return ((getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "")) or "").strip()


def componi(modello, parametri: Parametri, request) -> Documento:
    oggi = timezone.localdate()
    date_from, date_to = periodo_da_tipo(parametri.periodo_tipo, oggi=oggi,
                                         data_da=parametri.data_da, data_a=parametri.data_a)
    ctx = Contesto(date_from=date_from, date_to=date_to, perimetro=parametri.perimetro, request=request, today=oggi)

    nomi = {}
    if parametri.perimetro.persone:
        nomi = {d.id: d.nominativo for d in ctx.dipendenti_perimetro()}
    perimetro_label = parametri.perimetro.label(nomi)
    norme = [n for n in (modello.norme or []) if isinstance(n, str)]
    sostituzioni = {
        "{{oggi}}": oggi.strftime("%d/%m/%Y"),
        "{{periodo}}": ctx.periodo_label,
        "{{periodo_da}}": date_from.strftime("%d/%m/%Y"),
        "{{periodo_a}}": date_to.strftime("%d/%m/%Y"),
        "{{destinatario}}": parametri.destinatario or "",
        "{{perimetro}}": perimetro_label,
        "{{norme}}": ", ".join(norme),
        "{{redatto_da}}": modello.redatto_da or "",
        "{{approvato_da}}": modello.approvato_da or "",
    }

    def _sost(text: str) -> str:
        text = text or ""
        if "{{n_persone}}" in text:
            text = text.replace("{{n_persone}}", str(len(ctx.dipendenti())))
        for chiave, valore in sostituzioni.items():
            text = text.replace(chiave, valore)
        return text

    doc = Documento(
        titolo=_sost(parametri.titolo or modello.titolo_documento or modello.nome),
        sottotitolo=_sost(parametri.sottotitolo),
        destinatario=parametri.destinatario,
        riservatezza=modello.get_riservatezza_display(),
        norme=norme,
        periodo_label=ctx.periodo_label,
        perimetro_label=perimetro_label,
        date_from=date_from, date_to=date_to,
        generato_il=timezone.localtime(),
        generato_da=_nome_utente(getattr(request, "user", None)),
        redatto_da=modello.redatto_da, verificato_da=modello.verificato_da, approvato_da=modello.approvato_da,
    )

    for blocco in modello.blocchi.all():
        testo = parametri.testi.get(blocco.pk, blocco.testo)
        if blocco.tipo == "TESTO":
            doc.elementi.append(Elemento("testo", blocco.pk, _sost(blocco.titolo), paragrafi(_sost(testo))))
        elif blocco.tipo == "PAGINA":
            doc.elementi.append(Elemento("pagina", blocco.pk))
        elif blocco.tipo == "FIRME":
            doc.elementi.append(Elemento("firme", blocco.pk, _sost(blocco.titolo) or "Approvazione"))
        elif blocco.tipo == "SEZIONE":
            doc.elementi.append(_elemento_sezione(blocco, testo, ctx, request, _sost))
    return doc


def _elemento_sezione(blocco, commento: str, ctx: Contesto, request, sost) -> Elemento:
    sezione = catalogo.get(blocco.sezione)
    opzioni = blocco.opzioni if isinstance(blocco.opzioni, dict) else {}
    titolo = sost(blocco.titolo) or (sezione.titolo if sezione else blocco.sezione)
    if sezione is None:
        return Elemento("errore", blocco.pk, titolo, paragrafi("Sezione non più disponibile nel catalogo."))
    if not sezione.consentita(request):
        return Elemento("negata", blocco.pk, titolo,
                        paragrafi("Sezione omessa: non hai i permessi per questi dati."), sezione=sezione)
    try:
        risultato = sezione.builder(ctx)
    except Exception:
        logger.exception("reportistica: sezione %s non calcolabile", sezione.key)
        return Elemento("errore", blocco.pk, titolo,
                        paragrafi("Sezione non calcolabile in questo momento: vedi log applicativo."), sezione=sezione)

    etichette = dict(sezione.colonne) if sezione.colonne else dict(risultato.colonne)
    if sezione.colonne:
        chiavi = sezione.colonne_effettive(opzioni.get("colonne"))
    else:
        chiavi = [k for k, _l in risultato.colonne]
    elemento = Elemento(
        "sezione", blocco.pk, titolo, paragrafi(sost(commento)), sezione=sezione, risultato=risultato,
        colonne=[(k, etichette.get(k, k)) for k in chiavi],
        righe=[[r.get(k, "") for k in chiavi] for r in risultato.righe],
        toni=list(risultato.toni),
        mostra_indicatori=opzioni.get("mostra_indicatori", True) is not False,
        mostra_tabella=opzioni.get("mostra_tabella", True) is not False,
        mostra_note=opzioni.get("mostra_note", True) is not False,
        riferimenti=" · ".join(sezione.riferimenti),
    )
    return elemento


# ═══════════════════════════════════════════════════════════════════════════
# PDF
# ═══════════════════════════════════════════════════════════════════════════

def render_pdf(doc: Documento) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer

    from core.pdf import PdfTheme, build_styles, data_table, header_footer_callback, make_document, section_heading
    # Riuso dei renderer di Report conformità: stessa resa di KPI e tabelle colorate.
    from report_conformita.exports import PdfSection, _data_table, _kpi_table

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    bullet = ParagraphStyle("rp_li", parent=styles["body"], leftIndent=10, bulletIndent=2)
    sub = ParagraphStyle("rp_h", parent=styles["body"], fontName="Helvetica-Bold", spaceBefore=4)
    nota = ParagraphStyle("rp_nota", parent=styles["body"], fontSize=7, textColor=colors.HexColor("#64748b"))
    buf = io.BytesIO()
    pdf = make_document(buf, title=doc.titolo, landscape=True)
    width = pdf.pagesize[0] - pdf.leftMargin - pdf.rightMargin
    el: list = []

    def _testo(pars: list[tuple[str, str]]) -> None:
        for kind, markup in pars:
            if kind == "h":
                el.append(Paragraph(markup, sub))
            elif kind == "li":
                el.append(Paragraph(markup, bullet, bulletText="•"))
            else:
                el.append(Paragraph(markup, styles["body"]))
        if pars:
            el.append(Spacer(1, 3 * mm))

    # Frontespizio: dati che l'auditor o il cliente cercano per primi.
    el.append(Paragraph(escape(doc.titolo), styles["title"]))
    if doc.sottotitolo:
        el.append(Paragraph(escape(doc.sottotitolo), styles["subtitle"]))
    el.append(Spacer(1, 4 * mm))
    info = [
        ("Destinatario", doc.destinatario or "—"),
        ("Periodo di riferimento", doc.periodo_label),
        ("Perimetro", doc.perimetro_label),
        ("Norme di riferimento", ", ".join(doc.norme) or "—"),
        ("Classificazione", doc.riservatezza),
        ("Generato", f"{doc.generato_il:%d/%m/%Y %H:%M}" + (f" da {doc.generato_da}" if doc.generato_da else "")),
    ]
    el.append(data_table(
        [[Paragraph(f"<b>{escape(k)}</b>", styles["cell"]), Paragraph(escape(v), styles["cell"])] for k, v in info],
        theme, col_widths=[width * 0.22, width * 0.78], header=False,
    ))
    el.append(Spacer(1, 6 * mm))

    for e in doc.elementi:
        if e.tipo == "pagina":
            el.append(PageBreak())
            continue
        if e.tipo == "testo":
            if e.titolo:
                el.extend(section_heading(escape(e.titolo), theme, styles))
            _testo(e.paragrafi)
            continue
        if e.tipo == "firme":
            ruoli = _ruoli_firma(doc)
            griglia = [
                [Paragraph(f"<b>{escape(r)}</b>", styles["table_header"]) for r, _n in ruoli],
                [Paragraph(escape(n or ""), styles["cell"]) for _r, n in ruoli],
                [Paragraph("<br/><br/>Firma ____________________<br/><br/>Data ____________", styles["cell"])
                 for _ in ruoli],
            ]
            el.append(KeepTogether([
                *section_heading(escape(e.titolo), theme, styles),
                data_table(griglia, theme, col_widths=[width / len(ruoli)] * len(ruoli)),
                Spacer(1, 4 * mm),
            ]))
            continue
        if e.tipo in ("negata", "errore"):
            el.extend(section_heading(escape(e.titolo), theme, styles))
            _testo(e.paragrafi)
            continue
        # sezione dati
        head = list(section_heading(escape(e.titolo), theme, styles))
        if e.riferimenti:
            head.append(Paragraph(f"<b>Riferimenti:</b> {escape(e.riferimenti)}", styles["body"]))
            head.append(Spacer(1, 2 * mm))
        if e.mostra_indicatori and e.risultato.kpis:
            head.append(_kpi_table(e.risultato.kpis, theme, styles, width))
            head.append(Spacer(1, 3 * mm))
        el.append(KeepTogether(head))
        if e.mostra_tabella and e.colonne:
            if e.righe:
                section = PdfSection(title=e.titolo, clausole="", kpis=[], columns=[l for _k, l in e.colonne],
                                     rows=e.righe, row_tones=e.toni)
                el.append(_data_table(section, theme, styles, width))
            else:
                el.append(Paragraph("Nessun dato nel perimetro selezionato.", styles["body"]))
            el.append(Spacer(1, 2 * mm))
        if e.mostra_note:
            for n in e.risultato.note:
                el.append(Paragraph(f"• {escape(n)}", nota))
        _testo(e.paragrafi)
        el.append(Spacer(1, 4 * mm))

    subtitle = f"{doc.riservatezza} | Periodo {doc.periodo_label}"
    if doc.destinatario:
        subtitle += f" | {doc.destinatario}"
    draw = header_footer_callback(theme, title=doc.titolo.upper()[:90], subtitle=subtitle[:140])
    pdf.build(el, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()


def _ruoli_firma(doc: Documento) -> list[tuple[str, str]]:
    return [("Redatto da", doc.redatto_da), ("Verificato da", doc.verificato_da), ("Approvato da", doc.approvato_da)]


# ═══════════════════════════════════════════════════════════════════════════
# Excel
# ═══════════════════════════════════════════════════════════════════════════

_TAG = re.compile(r"<[^>]+>")
_SHEET_BAD = re.compile(r"[\[\]\*\?/\\:]")


def _plain(markup: str) -> str:
    return _TAG.sub("", markup.replace("<br/>", "\n")).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def render_xlsx(doc: Documento) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    from core.excel_export import append_row

    wb = Workbook()
    ws = wb.active
    ws.title = "Documento"
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="0C2545")
    head_font = Font(bold=True, color="FFFFFF")
    tone_fill = {"danger": PatternFill("solid", fgColor="FDE8E8"), "warn": PatternFill("solid", fgColor="FDF3D8")}

    append_row(ws, [doc.titolo])
    ws["A1"].font = Font(bold=True, size=14)
    if doc.sottotitolo:
        append_row(ws, [doc.sottotitolo])
    append_row(ws, [])
    for k, v in (("Destinatario", doc.destinatario or "—"), ("Periodo", doc.periodo_label),
                 ("Perimetro", doc.perimetro_label), ("Norme", ", ".join(doc.norme) or "—"),
                 ("Classificazione", doc.riservatezza),
                 ("Generato", f"{doc.generato_il:%d/%m/%Y %H:%M} {doc.generato_da}".strip())):
        append_row(ws, [k, v])
        ws.cell(row=ws.max_row, column=1).font = bold
    append_row(ws, [])

    usati: set[str] = {"Documento"}
    for e in doc.elementi:
        if e.tipo == "pagina":
            continue
        if e.tipo == "firme":
            append_row(ws, [e.titolo])
            ws.cell(row=ws.max_row, column=1).font = bold
            for ruolo, nome in _ruoli_firma(doc):
                if nome:
                    append_row(ws, [ruolo, nome])
            append_row(ws, [])
            continue
        if e.titolo:
            append_row(ws, [e.titolo])
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=12)
        if e.tipo == "sezione":
            nome = _nome_foglio(e.titolo, usati)
            if e.riferimenti:
                append_row(ws, ["Riferimenti", e.riferimenti])
            if e.mostra_indicatori:
                for kpi in e.risultato.kpis:
                    append_row(ws, [kpi.label, "" if kpi.value is None else str(kpi.value), kpi.hint])
            if e.mostra_tabella and e.colonne:
                append_row(ws, ["Dettaglio", f"foglio «{nome}» ({len(e.righe)} righe)"])
                _foglio_sezione(wb.create_sheet(nome), e, append_row, bold, head_fill, head_font, tone_fill)
            if e.mostra_note:
                for n in e.risultato.note:
                    append_row(ws, [f"• {n}"])
        for _kind, markup in e.paragrafi:
            append_row(ws, [_plain(markup)])
            ws.cell(row=ws.max_row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        append_row(ws, [])
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 30
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _nome_foglio(titolo: str, usati: set[str]) -> str:
    base = _SHEET_BAD.sub(" ", titolo or "Sezione").strip()[:28] or "Sezione"
    nome, i = base, 2
    while nome in usati:
        nome = f"{base[:26]} {i}"
        i += 1
    usati.add(nome)
    return nome


def _foglio_sezione(ws, e: Elemento, append_row, bold, head_fill, head_font, tone_fill) -> None:
    append_row(ws, [e.titolo])
    ws["A1"].font = bold
    append_row(ws, [])
    append_row(ws, [label for _k, label in e.colonne])
    header_row = ws.max_row
    for cell in ws[header_row]:
        cell.fill = head_fill
        cell.font = head_font
    for i, values in enumerate(e.righe):
        append_row(ws, ["" if v is None else v for v in values])
        tono = e.toni[i] if i < len(e.toni) else ""
        if tono in tone_fill:
            for cell in ws[ws.max_row]:
                cell.fill = tone_fill[tono]
    for idx, (_k, label) in enumerate(e.colonne, start=1):
        larghezza = max([len(str(label))] + [len(str(r[idx - 1] or "")) for r in e.righe[:300]])
        ws.column_dimensions[ws.cell(row=header_row, column=idx).column_letter].width = min(max(larghezza + 2, 10), 60)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = f"A{header_row}:{ws.cell(row=ws.max_row, column=len(e.colonne)).coordinate}"
