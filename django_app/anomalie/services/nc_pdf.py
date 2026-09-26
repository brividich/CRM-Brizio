"""PDF della scheda di non conformita' per OP (archivio / audit ISO 9001 §10.2).

Stesso tema grafico degli altri report del portale (:mod:`core.pdf`). Riporta tutte
le sezioni, anche vuote ("non compilata"): in audit conta vedere cosa manca.
"""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from core.pdf import (
    PdfTheme,
    build_styles,
    data_table,
    header_footer_callback,
    make_document,
    section_heading,
)

_W = 174 * mm
_VUOTO = "non compilata"


def _esc(value) -> str:
    return escape(str(value if value is not None else "").strip()).replace("\n", "<br/>")


def _data(d) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def build_nc_pdf_bytes(nc, righe: list[dict], *, ishikawa_labels: dict) -> bytes:
    theme = PdfTheme.from_branding()
    st = build_styles(theme)

    def p(text, style="value"):
        return Paragraph(text or "—", st[style])

    def campi(rows):
        t = Table([[p(_esc(a), "label"), p(b)] for a, b in rows], colWidths=[42 * mm, _W - 42 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    buf = BytesIO()
    doc = make_document(buf, title=f"Non conformità {nc.protocollo}")
    story: list = []

    story += section_heading("Non conformità", theme, st)
    story.append(campi([
        ("Protocollo", _esc(nc.protocollo)),
        ("OP / P/N", f"{_esc(nc.op_titolo)} · {_esc(nc.part_number) or '—'}"),
        ("Capocommessa / CAR", f"{_esc(nc.capocommessa) or '—'} · {_esc(nc.car) or '—'}"),
        ("Stato", _esc(nc.get_stato_display())),
        ("Aperta il", _data(timezone.localtime(nc.created_at).date())),
        ("Ricaduta di", _esc(nc.precedente.protocollo) if nc.precedente_id else "—"),
    ]))

    story += section_heading("Anomalie dell'OP", theme, st)
    rows = [["S/N", "Difetto", "Gravità", "Q.tà NC/scarto", "Decisione", "Avanzamento"]]
    for r in righe:
        s = r["scheda"]
        qta = f"{s.quantita_nc if s.quantita_nc is not None else '—'}/{s.quantita_scartata if s.quantita_scartata is not None else '—'}"
        rows.append([
            p(_esc(r["seriale"])), p(_esc(s.tipo_difetto.nome if s.tipo_difetto_id else "da classificare")),
            p(_esc(s.get_gravita_display() if s.gravita else "—")), qta,
            p(_esc(s.get_disposizione_display())),
            p(_esc(("Chiusa · " if r["chiusa"] else "") + (r["avanzamento"] or "—"))),
        ])
    story.append(data_table(rows, theme, col_widths=[30 * mm, 38 * mm, 20 * mm, 22 * mm, 30 * mm, 34 * mm]))

    story += section_heading("1. Contenimento immediato", theme, st)
    story.append(campi([
        ("Azioni", _esc(nc.contenimento) or _VUOTO),
        ("Data / eseguito da", f"{_data(nc.contenimento_data)} · {_esc(nc.contenimento_da) or '—'}"),
    ]))

    story += section_heading("2. Analisi delle cause", theme, st)
    analisi = [("Metodo", _esc(nc.get_analisi_metodo_display()) if nc.analisi_metodo else _VUOTO)]
    for i, perche in enumerate(nc.analisi_perche or [], start=1):
        if str(perche or "").strip():
            analisi.append((f"Perché {i}", _esc(perche)))
    for key, label in ishikawa_labels.items():
        val = (nc.analisi_ishikawa or {}).get(key)
        if str(val or "").strip():
            analisi.append((label, _esc(val)))
    analisi += [
        ("Riferimento esterno", _esc(nc.analisi_riferimento) or "—"),
        ("Causa radice", _esc(nc.causa_radice) or _VUOTO),
        ("Data / a cura di", f"{_data(nc.analisi_data)} · {_esc(nc.analisi_da) or '—'}"),
    ]
    story.append(campi(analisi))

    story += section_heading("3. Azioni correttive", theme, st)
    azioni = list(nc.azioni.all())
    if azioni:
        rows = [["Azione", "Tipo", "Responsabile", "Scadenza", "Stato"]]
        for a in azioni:
            rows.append([p(_esc(a.descrizione)), a.get_tipo_display(), p(_esc(a.responsabile_nome) or "—"),
                         _data(a.scadenza), p(_esc(a.get_stato_display() + (f" ({_data(a.completata_il)})" if a.completata_il else "")))])
        story.append(data_table(rows, theme, col_widths=[70 * mm, 22 * mm, 36 * mm, 20 * mm, 26 * mm]))
    else:
        story.append(p(_VUOTO))

    story += section_heading("4. Verifica di efficacia", theme, st)
    story.append(campi([
        ("Prevista / eseguita", f"{_data(nc.verifica_prevista)} · {_data(nc.verifica_data)}"),
        ("Esito", _esc(nc.get_verifica_esito_display()) if nc.verifica_esito else _VUOTO),
        ("Note", _esc(nc.verifica_note) or "—"),
        ("Verificata da", _esc(nc.verifica_da) or "—"),
    ]))

    story += section_heading("Chiusura", theme, st)
    if nc.chiusa_il:
        chi = (nc.chiusa_da.get_full_name() or nc.chiusa_da.username) if nc.chiusa_da_id else "—"
        story.append(campi([
            ("Chiusa il", timezone.localtime(nc.chiusa_il).strftime("%d/%m/%Y %H:%M")),
            ("Da", _esc(chi)),
            ("Note", _esc(nc.note_chiusura) or "—"),
        ]))
    else:
        story.append(p("NC aperta"))
    story.append(Spacer(1, 4 * mm))

    draw = header_footer_callback(theme, title="NON CONFORMITÀ", subtitle=f"{nc.protocollo} · OP {nc.op_titolo}")
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()
