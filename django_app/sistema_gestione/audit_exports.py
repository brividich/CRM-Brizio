"""Esportazioni conformi alla struttura di MOD.034, MOD.035A e MOD.035B."""
from __future__ import annotations

import io
import os
from html import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from core.pdf import PdfTheme

from .models import Audit, AuditEsito, CellaProgramma, ProgrammaAudit
from .services.audit import contatori_rilievi
from .services.audit_automation import testo_evidenza


def _register_checkbox_font() -> str | None:
    candidates = [
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "seguisym.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                pdfmetrics.registerFont(TTFont("SGCheckbox", path))
                return "SGCheckbox"
            except Exception:
                continue
    return None


_CHECKBOX_FONT = _register_checkbox_font()


def _fmt_user(user) -> str:
    return (user.get_full_name() or user.get_username()).strip() if user else ""


def _dt(value) -> str:
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if value else ""


def _d(value) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _check(flag: bool) -> str:
    return "\u2612" if flag else "\u2610"


def _styles():
    base = getSampleStyleSheet()
    return {
        "cell": ParagraphStyle("mod-cell", parent=base["Normal"], fontSize=7.4, leading=9),
        "small": ParagraphStyle("mod-small", parent=base["Normal"], fontSize=6.4, leading=8),
        "head": ParagraphStyle("mod-head", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=9),
        "title": ParagraphStyle(
            "mod-title", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=13,
            leading=15, alignment=TA_CENTER,
        ),
        "note": ParagraphStyle("mod-note", parent=base["Italic"], fontSize=6.8, leading=8.5),
    }


def _p(value, style):
    testo = escape(str(value or "")).replace("\n", "<br/>")
    if _CHECKBOX_FONT:
        testo = testo.replace("\u2612", '<font name="SGCheckbox">&#x2612;</font>')
        testo = testo.replace("\u2610", '<font name="SGCheckbox">&#x2610;</font>')
    return Paragraph(testo, style)


def _table(rows, widths, *, repeat=0, section_rows=(), font_size=7.5, split_in_row=0):
    table = Table(rows, colWidths=widths, repeatRows=repeat, hAlign="LEFT", splitInRow=split_in_row)
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#444444")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
    ]
    for row in section_rows:
        commands += [
            ("SPAN", (0, row), (-1, row)),
            ("BACKGROUND", (0, row), (-1, row), colors.HexColor("#f1f5f9")),
            ("FONTNAME", (0, row), (-1, row), "Helvetica-Bold"),
        ]
    table.setStyle(TableStyle(commands))
    return table


def _header(title: str, code: str, subtitle: str = "", *, width: float = 184 * mm):
    styles = _styles()
    theme = PdfTheme.from_branding()
    if theme.logo_path:
        left = Image(theme.logo_path, width=38 * mm, height=13 * mm, kind="proportional")
    else:
        left = _p(theme.portal_name, styles["head"])
    center = Paragraph(
        f"{escape(title)}<br/><font size='8'>{escape(subtitle)}</font>",
        styles["title"],
    )
    right = _p(code, styles["small"])
    return _table([[left, center, right]], [width * .28, width * .50, width * .22], font_size=7)


def _firma(label: str, user, when) -> str:
    if user and when:
        return f"{label}: approvato digitalmente da {_fmt_user(user)} il {_dt(when)}"
    return f"{label}: Firma __________________  Data ___/___/______"


def programma_pdf(programma: ProgrammaAudit) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A3), leftMargin=8 * mm, rightMargin=8 * mm,
        topMargin=8 * mm, bottomMargin=12 * mm, title="MOD.034 - Programma audit",
    )
    width = landscape(A3)[0] - 16 * mm
    story = [
        _header(
            "PIANO AUDIT INTERNI ANNO",
            f"Codice: MOD.034\nRev.: 18\nAnno: {programma.anno}",
            str(programma.anno),
            width=width,
        ),
        Spacer(1, 3 * mm),
    ]
    legenda = _table([
            [_p("LEGENDA", styles["head"]), "PR: V.I. Programmata", "RP: V.I. Riprogrammata", "ST: V.I. Straordinaria"],
        ], [30 * mm, 55 * mm, 58 * mm, 55 * mm])
    legenda.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#fff67a")),
        ("BACKGROUND", (2, 0), (2, 0), colors.HexColor("#b8a7d1")),
        ("BACKGROUND", (3, 0), (3, 0), colors.HexColor("#f7dcc4")),
    ]))
    story += [legenda, Spacer(1, 3 * mm)]
    months = ["G", "F", "M", "A", "M", "G", "L", "A", "S", "O", "N", "D"]
    rows = [[
        _p("AREA SOGGETTA AD AUDIT INTERNO", styles["head"]), _p("ENTI", styles["head"]),
        _p("9100:2018", styles["small"]), _p("45001:2018", styles["small"]), _p("14001:2015", styles["small"]),
        _p("27001:2022", styles["small"]), _p("PdR 125:2022", styles["small"]),
        _p("Normative", styles["head"]), *[_p(m, styles["head"]) for m in months],
    ]]
    for riga in programma.righe.prefetch_related("celle"):
        celle = {c.mese: c.stato for c in riga.celle.all()}
        rows.append([
            _p(riga.area + (f"\n{riga.note}" if riga.note else ""), styles["cell"]),
            _p(riga.enti, styles["cell"]), _p(riga.punti_9100, styles["cell"]),
            _p(riga.punti_45001, styles["cell"]), _p(riga.punti_14001, styles["cell"]), _p(riga.punti_27001, styles["cell"]),
            _p(riga.punti_pdr125, styles["cell"]), _p(riga.altre_normative, styles["small"]),
            *[_p(celle.get(mese, ""), styles["head"]) for mese in range(1, 13)],
        ])
    fixed = [56 * mm, 32 * mm, 21 * mm, 21 * mm, 21 * mm, 21 * mm, 21 * mm, 32 * mm]
    month_width = max(8 * mm, (width - sum(fixed)) / 12)
    griglia = _table(rows, fixed + [month_width] * 12, repeat=1, font_size=6.2)
    colori_stato = {
        CellaProgramma.STATO_PR: colors.HexColor("#fff67a"),
        CellaProgramma.STATO_RP: colors.HexColor("#b8a7d1"),
        CellaProgramma.STATO_ST: colors.HexColor("#f7dcc4"),
    }
    for row_index, riga in enumerate(programma.righe.prefetch_related("celle"), start=1):
        for cella in riga.celle.all():
            col = 6 + cella.mese
            griglia.setStyle(TableStyle([
                ("BACKGROUND", (col, row_index), (col, row_index), colori_stato[cella.stato]),
                ("ALIGN", (col, row_index), (col, row_index), "CENTER"),
            ]))
    story += [
        griglia,
        Spacer(1, 4 * mm),
        _table([
            [_p("RIF. VERBALE DI RIESAME", styles["head"]), _p(programma.rif_riesame, styles["cell"])],
            [_p("PERIODI PER NORMA", styles["head"]), _p(programma.periodi, styles["cell"])],
            [_p("ESCLUSIONI ISO/IEC 27002", styles["head"]), _p(programma.esclusioni_27002, styles["small"])],
        ], [55 * mm, width - 55 * mm]),
        Spacer(1, 3 * mm),
        _table([[ _p(_firma("APPROVAZIONE CEO", programma.approvato_da, programma.approvato_il), styles["cell"]),
                  _p(_firma("CONVALIDA RDD", programma.convalidato_da, programma.convalidato_il), styles["cell"]) ]],
               [width / 2, width / 2]),
    ]
    doc.build(story)
    return buf.getvalue()


def piano_audit_pdf(audit: Audit) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=13 * mm, rightMargin=13 * mm,
        topMargin=13 * mm, bottomMargin=13 * mm, title="MOD.035A - Piano di audit",
    )
    width = A4[0] - 26 * mm
    story = [_header(
        "PIANO DI AUDIT / MOD.035A Rev.0",
        f"Codice: MOD.035A\nRev.: 0\nData emissione: {_d(audit.created_at.date())}",
    ), Spacer(1, 4 * mm)]
    tipi = "  ".join([
        f"{_check(audit.tipo == Audit.TIPO_SISTEMA)} Sistema SGI (RAIS)",
        f"{_check(audit.tipo == Audit.TIPO_MANDATORIO_CLIENTE)} Mandatorio Cliente (RAI)",
        f"{_check(audit.tipo == Audit.TIPO_STRAORDINARIO)} Straordinario",
    ])
    norme = "  ".join([
        f"{_check(audit.en9100)} EN 9100:2018", f"{_check(audit.iso45001)} ISO 45001:2018", f"{_check(audit.iso14001)} ISO 14001:2015",
        f"{_check(audit.iso27001)} ISO/IEC 27001:2022", f"{_check(audit.pdr125)} UNI/PdR 125",
    ])
    metodi = "  ".join([
        f"{_check(audit.metodo_intervista)} Intervista", f"{_check(audit.metodo_esame_documenti)} Esame documenti/registrazioni",
        f"{_check(audit.metodo_osservazione_diretta)} Osservazione diretta",
        f"{_check(audit.metodo_verifica_evidenze)} Verifica evidenze oggettive",
    ])
    team = ", ".join(a.nome for a in audit.auditor.all())
    programma = audit.programma
    rif_programma = f"MOD.034 Rev.{programma.revisione} - Anno {programma.anno}" if programma else ""
    comunicazione = (
        f"Data: {_dt(audit.comunicazione_il)}  Metodo: "
        f"{_check(audit.comunicazione_metodo == Audit.COM_EMAIL)} Email  "
        f"{_check(audit.comunicazione_metodo == Audit.COM_CALENDARIO)} Calendario condiviso (Teams/Outlook)"
    )
    main = [
        [_p("1. IDENTIFICAZIONE DELL'AUDIT", styles["head"]), "", "", ""],
        [_p("N° Audit", styles["head"]), audit.numero, _p("Data emissione piano", styles["head"]), _d(audit.created_at.date())],
        [_p("Tipo audit", styles["head"]), audit.get_tipo_display(), "", ""],
        [_p("Lead Auditor", styles["head"]), audit.lead_auditor.nome, _p("Auditor/i", styles["head"]), team],
        [_p("Rif. Programma Audit", styles["head"]), str(programma or ""), _p("Rif. Riesame Direzione", styles["head"]), programma.rif_riesame if programma else ""],
        [_p("2. CAMPO DELL'AUDIT", styles["head"]), "", "", ""],
        [_p("Norma/e di riferimento", styles["head"]), _p(norme, styles["cell"]), "", ""],
        [_p("Processo/i in verifica", styles["head"]), _p(audit.processi, styles["cell"]), "", ""],
        [_p("Punti norma coperti", styles["head"]), _p(audit.punti_norma, styles["cell"]), "", ""],
        [_p("Procedure interne (criteri di verifica)", styles["head"]), _p(audit.procedure_criteri, styles["cell"]), "", ""],
        [_p("Esclusioni / Limitazioni", styles["head"]), _p(audit.esclusioni, styles["cell"]), "", ""],
        [_p("3. LOGISTICA E COMUNICAZIONE", styles["head"]), "", "", ""],
        [_p("Data inizio", styles["head"]), _d(audit.data_inizio), _p("Data fine / chiusura rapporto", styles["head"]), _d(audit.data_fine)],
        [_p("Durata stimata", styles["head"]), audit.durata_stimata, _p("Sede", styles["head"]), audit.sede],
        [_p("Metodi di verifica", styles["head"]), _p(metodi, styles["small"]), "", ""],
        [_p("Comunicazione agli auditati", styles["head"]), _p(
            f"Data: {_dt(audit.comunicazione_il)} · Metodo: {audit.get_comunicazione_metodo_display() if audit.comunicazione_metodo else ''}",
            styles["cell"],
        ), "", ""],
        [_p("4. PERSONE COINVOLTE", styles["head"]), "", "", ""],
        [_p("Nome e Cognome", styles["head"]), _p("Funzione / Ente", styles["head"]), _p("Ruolo", styles["head"]), _p("Email", styles["head"])],
    ]
    main[2] = [_p("Tipo audit", styles["head"]), _p(tipi, styles["cell"]), "", ""]
    main[4][1] = rif_programma
    main[15] = [_p("Comunicazione agli auditati", styles["head"]), _p(comunicazione, styles["cell"]), "", ""]
    main[17] = [
        _p("Nome e Cognome", styles["head"]),
        _p("Funzione / Ente", styles["head"]),
        _p("Ruolo", styles["head"]),
        "",
    ]
    for persona in audit.persone.all():
        main.append([persona.nome, persona.funzione_ente, persona.get_ruolo_display(), persona.email])
    for row in main[18:]:
        row[3] = ""
    while len(main) < 28:
        main.append(["", "", "", ""])
    section_rows = (0, 5, 11, 16)
    t = _table(main, [43 * mm, 49 * mm, 51 * mm, width - 143 * mm], section_rows=section_rows)
    t.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)), ("SPAN", (1, 2), (-1, 2)),
        ("SPAN", (1, 6), (-1, 6)), ("SPAN", (1, 7), (-1, 7)), ("SPAN", (1, 8), (-1, 8)),
        ("SPAN", (1, 9), (-1, 9)), ("SPAN", (1, 10), (-1, 10)),
        ("SPAN", (0, 5), (-1, 5)), ("SPAN", (0, 11), (-1, 11)),
        ("SPAN", (1, 14), (-1, 14)), ("SPAN", (1, 15), (-1, 15)),
        ("SPAN", (0, 16), (-1, 16)),
    ]))
    for row in range(17, len(main)):
        t.setStyle(TableStyle([("SPAN", (2, row), (3, row))]))
    story += [t, PageBreak(), _p("5. PROGRAMMA ORARIO", styles["head"])]
    agenda = [[_p("Data / Ora", styles["head"]), _p("Processo / Area", styles["head"]), _p("Attività / Punto norma / Documento", styles["head"]), _p("Auditor", styles["head"])]]
    for voce in audit.agenda.all():
        agenda.append([_dt(voce.quando), voce.processo_area, _p(voce.attivita, styles["cell"]), voce.auditor])
    while len(agenda) < 10:
        agenda.append(["", "", "", ""])
    story += [
        _table(agenda, [27 * mm, 38 * mm, 82 * mm, width - 147 * mm], repeat=1),
        Spacer(1, 4 * mm), _p("6. APPROVAZIONE", styles["head"]),
        _table([[ _p(_firma("Approvazione Lead Auditor", audit.piano_approvato_lead_da, audit.piano_approvato_lead_il), styles["cell"]),
                  _p(_firma("Approvazione RDD / CEO", audit.piano_approvato_direzione_da, audit.piano_approvato_direzione_il), styles["cell"]) ]],
               [width / 2, width / 2]),
        Spacer(1, 3 * mm),
        _p(f"Documento di output: MOD.035B - Rapporto di Audit (RAIS) n° {audit.numero}", styles["cell"]),
        Spacer(1, 3 * mm),
        _p(
            "Il presente Piano di Audit costituisce il documento di pianificazione del singolo audit ai sensi di "
            "EN 9100:2018 §9.2.2 e MT CN 12. Deve essere emesso prima dell'esecuzione dell'audit, comunicato agli "
            "auditati con congruo anticipo (minimo 5 giorni lavorativi) e approvato dal Lead Auditor e dalla Direzione.",
            styles["note"],
        ),
    ]
    doc.build(story)
    return buf.getvalue()


def _allegato_rilievi(audit: Audit, styles, width) -> list:
    """Rilievi per processo e clausola con le azioni (MOD.174 / CAR): sezione configurabile."""
    from .services.cruscotto import RILIEVI, righe_rilievi

    esiti = list(audit.esiti.filter(esito__in=RILIEVI)
                 .select_related("audit", "processo", "ofi", "ofi__car_procedurale", "responsabile_azione"))
    if not esiti:
        return []
    rows = [[_p(t, styles["head"]) for t in ("Processo", "§", "Rilievo", "Scostamento", "Responsabile / scadenza", "MOD.174 · CAR")]]
    for r in sorted(righe_rilievi(esiti), key=lambda r: (str(r[2]), str(r[3]))):
        rows.append([
            _p(r[2], styles["small"]), _p(r[3], styles["small"]), _p(r[4], styles["small"]), _p(r[5], styles["small"]),
            _p(f"{r[7]}\n{_d(r[8])}", styles["small"]), _p(f"n. {r[9]} · {r[10]}" if r[9] else r[10], styles["small"]),
        ])
    tabella = _table(rows, [34 * mm, 14 * mm, 22 * mm, width - 132 * mm, 34 * mm, 28 * mm], repeat=1, font_size=6.4, split_in_row=1)
    return [PageBreak(), _p("ALLEGATO - RILIEVI E AZIONI", styles["head"]), Spacer(1, 3 * mm), tabella]


def _filigrana_bozza(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 64)
    canvas.setFillColor(colors.Color(0.75, 0.1, 0.1, alpha=0.18))
    canvas.translate(A4[0] / 2, A4[1] / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "BOZZA - NON EMESSO")
    canvas.restoreState()


def rapporto_audit_pdf(audit: Audit, *, bozza: bool = False, nota: str = "") -> bytes:
    """MOD.035B. Con ``bozza`` ogni pagina porta la filigrana: è l'anteprima prima della chiusura.
    ``nota`` compare in testa (es. rapporto rigenerato di un audit chiuso prima dell'archiviazione)."""
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=13 * mm, rightMargin=13 * mm,
        topMargin=13 * mm, bottomMargin=13 * mm, title="MOD.035B - Rapporto di audit interno",
    )
    width = A4[0] - 26 * mm
    story = [_header(
        "RAPPORTO DI AUDIT INTERNO / RAIS - MOD.035B Rev.0",
        f"Codice: MOD.035B\nRev.: 0\nN.: {audit.numero}\nData: {_d(audit.data_fine or audit.data_inizio)}",
    ), Spacer(1, 4 * mm)]
    if nota:
        story += [_p(nota, styles["note"]), Spacer(1, 3 * mm)]
    team = ", ".join(a.nome for a in audit.auditor.all())
    norme_rapporto = "  ".join([
        f"{_check(audit.en9100)} EN 9100:2018",
        f"{_check(audit.iso45001)} ISO 45001:2018",
        f"{_check(audit.iso14001)} ISO 14001:2015",
        f"{_check(audit.iso27001)} ISO/IEC 27001:2022",
        f"{_check(audit.pdr125)} UNI/PdR 125",
    ])
    intestazione = [
        [_p("A. INTESTAZIONE AUDIT", styles["head"]), "", "", ""],
        [_p("N° Rapporto", styles["head"]), audit.numero, _p("Date esecuzione", styles["head"]), f"{_d(audit.data_inizio)} - {_d(audit.data_fine)}"],
        [_p("Lead Auditor", styles["head"]), audit.lead_auditor.nome, _p("Auditor", styles["head"]), team],
        [_p("Norma", styles["head"]), _p(audit.norme_label, styles["cell"]), "", ""],
        [_p("Processi verificati", styles["head"]), _p(audit.processi, styles["cell"]), "", ""],
        [_p("Punti norma", styles["head"]), _p(audit.punti_norma, styles["cell"]), "", ""],
        [_p("Procedure/criteri", styles["head"]), _p(audit.procedure_criteri, styles["cell"]), "", ""],
        [_p("Rif. Piano di Audit", styles["head"]), f"MOD.035A n° {audit.numero}", _p("Rif. Programma", styles["head"]), str(audit.programma or "")],
        [_p("Esclusioni", styles["head"]), _p(audit.esclusioni, styles["cell"]), "", ""],
    ]
    intestazione[3][1] = _p(norme_rapporto, styles["cell"])
    if audit.programma:
        intestazione[7][3] = f"MOD.034 Rev.{audit.programma.revisione} - Anno {audit.programma.anno}"
    head = _table(intestazione, [43 * mm, 49 * mm, 43 * mm, width - 135 * mm], section_rows=(0,))
    head.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("SPAN", (1, 3), (-1, 3)), ("SPAN", (1, 4), (-1, 4)),
        ("SPAN", (1, 5), (-1, 5)), ("SPAN", (1, 6), (-1, 6)), ("SPAN", (1, 8), (-1, 8)),
    ]))
    people = [[_p("B. PERSONE INTERVISTATE", styles["head"]), "", "", ""],
              [_p("Nome e Cognome", styles["head"]), _p("Funzione / Ente", styles["head"]), _p("Data intervista", styles["head"]), _p("Firma", styles["head"])]]
    for p in audit.persone.filter(intervistato=True):
        people.append([p.nome, p.funzione_ente, _d(p.data_intervista), ""])
    while len(people) < 7:
        people.append(["", "", "", ""])
    pt = _table(people, [50 * mm, 67 * mm, 31 * mm, width - 148 * mm], section_rows=(0,))
    pt.setStyle(TableStyle([("SPAN", (0, 0), (-1, 0))]))
    story += [head, Spacer(1, 4 * mm), pt, Spacer(1, 4 * mm), _p("C. FOLDER B - AUDIT DI SISTEMA EN 9100:2018", styles["head"])]
    checklist = [[_p("§", styles["head"]), _p("Requisito / Domande guida", styles["head"]), _p("Evidenze riscontrate", styles["head"]), _p("Rilievo", styles["head"])]]
    section_rows = []
    gruppi = {}
    for esito in audit.esiti.select_related("domanda__sezione", "sezione").all():
        sezione = esito.sezione_effettiva
        if sezione:
            gruppi.setdefault(sezione, []).append(esito)
    car = {c.sezione_id: c.car_aperta for c in audit.car_sezioni.all()}
    for sezione in sorted(gruppi, key=lambda s: (s.ordine, s.pk)):
        section_rows.append(len(checklist))
        checklist.append([_p(f"{sezione.codice} - {sezione.titolo}   Criteri: {sezione.criteri}", styles["head"]), "", "", ""])
        for esito in gruppi[sezione]:
            rilievo = "  ".join([
                _check(esito.esito in {AuditEsito.ESITO_CONFORME, AuditEsito.ESITO_PUNTO_FORZA}) + " ✓",
                _check(esito.esito == AuditEsito.ESITO_OSSERVAZIONE) + " OSS",
                _check(esito.esito == AuditEsito.ESITO_OFI) + " OFI",
                _check(esito.esito == AuditEsito.ESITO_NC) + " NC",
                _check(esito.esito == AuditEsito.ESITO_NA) + " N/A",
            ])
            if esito.esito == AuditEsito.ESITO_NC and esito.gravita:
                rilievo += f"\n{esito.get_gravita_display()}"
            elif esito.esito == AuditEsito.ESITO_PUNTO_FORZA:
                rilievo += "\nPunto di forza"
            if esito.esito in AuditEsito.ESITI_RILIEVO and esito.clausola and esito.clausola != esito.punti:
                rilievo += f"\n§ {esito.clausola}"
            checklist.append([
                _p(esito.punti, styles["head"]), _p(esito.testo, styles["small"]),
                _p(testo_evidenza(esito), styles["small"]), _p(rilievo, styles["small"]),
            ])
        section_rows.append(len(checklist))
        checklist.append([_p(
            f"CAR (MOD.036) aperta - {sezione.codice}: {_check(not car.get(sezione.pk))} NO  {_check(car.get(sezione.pk, False))} SÌ → vedere MOD.174",
            styles["head"],
        ), "", "", ""])
    for esito in audit.esiti.filter(domanda__isnull=True, sezione__isnull=True).select_related("processo"):
        section_rows.append(len(checklist))
        label = esito.domanda_snapshot.get("processo") or "Verifica aggiuntiva"
        checklist.append([_p(f"{label} - domanda Rev.{esito.domanda_snapshot.get('revisione', '-')}", styles["head"]), "", "", ""])
        checklist.append([_p(esito.punti, styles["head"]), _p(esito.testo, styles["small"]),
            _p(testo_evidenza(esito), styles["small"]), _p(esito.esito_label or "Da valutare", styles["small"])])
    ct = _table(checklist, [12 * mm, 66 * mm, 63 * mm, width - 141 * mm], repeat=1, section_rows=tuple(section_rows), font_size=6.5, split_in_row=1)
    for row in section_rows:
        ct.setStyle(TableStyle([("SPAN", (0, row), (-1, row))]))
    counts = contatori_rilievi(audit)
    story += [ct, PageBreak(), _p("D. GIUDIZI ED OSSERVAZIONI DELL'AUDITOR", styles["head"])]
    story += [
        _table([
            *([[_p("RIEPILOGO DEI RILIEVI", styles["head"])], [_p(audit.riepilogo_generato, styles["cell"])]]
              if audit.riepilogo_generato.strip() else []),
            [_p("GIUDIZIO COMPLESSIVO DELL'AUDITOR", styles["head"])], [_p(audit.giudizio, styles["cell"])],
            [_p("PUNTI DI FORZA RILEVATI", styles["head"])], [_p(audit.punti_forza, styles["cell"])],
            [_p(f"OFI emesse: {counts['ofi']}    NC di sistema: {counts['nc']} "
                f"(maggiori {counts['nc_maggiori']}, minori {counts['nc_minori']})    "
                f"Osservazioni: {counts['osservazioni']}    Punti di forza: {counts['punti_forza']}", styles["head"])],
            [_p(_firma("Firma Auditor", audit.rapporto_firmato_auditor_da, audit.rapporto_firmato_auditor_il), styles["cell"])],
            [_p(_firma("Convalida responsabile ente", audit.rapporto_convalidato_ente_da, audit.rapporto_convalidato_ente_il), styles["cell"])],
        ], [width]),
        Spacer(1, 5 * mm), _p("E. VALUTAZIONI RDD", styles["head"]),
        _table([
            [_p("VALUTAZIONI RDD", styles["head"])], [_p(audit.valutazione_rdd, styles["cell"])],
            [_p(f"CAR autorizzate: {audit.car_autorizzate}", styles["cell"])],
            [_p(_firma("Firma RDD", audit.rapporto_valutato_rdd_da, audit.rapporto_valutato_rdd_il), styles["cell"])],
        ], [width]),
        Spacer(1, 4 * mm),
        _p(
            "Il presente documento, firmato da Auditor e RDD, costituisce evidenza documentata dell'audit interno "
            "ai sensi di EN 9100:2018 §9.2.2. È conservato insieme al MOD.035A e al MOD.034. Le OFI/NC emesse "
            "sono registrate nel MOD.174 - SGI Registro OFI/NC.", styles["note"],
        ),
    ]
    from .models import AuditPreparazione
    from .services.programma import impostazione_attiva

    if impostazione_attiva("sistema_gestione.rapporto_allegato_rilievi"):
        story += _allegato_rilievi(audit, styles, width)
    preparazione = AuditPreparazione.objects.filter(audit=audit).select_related("verificato_da").first()
    if preparazione and impostazione_attiva("sistema_gestione.rapporto_allegato_preparazione"):
        story += [PageBreak(), _p("ALLEGATO - PREPARAZIONE MT CN 12", styles["head"])]
        for campo, titolo in [("audit_precedenti", "Audit precedenti"), ("car_cliente", "CAR cliente"), ("documenti_registrazioni", "Documenti e campioni"), ("obiettivi_carenze", "Obiettivi e carenze")]:
            story += [_p(titolo, styles["head"]), _p(getattr(preparazione, campo), styles["cell"]), Spacer(1, 3*mm)]
        story += [_p(_firma("Preparazione confermata", preparazione.verificato_da, preparazione.verificato_il), styles["cell"])]
        if preparazione.origine_ai:
            story += [_p("Bozza iniziale proposta dall'AI e verificata dall'auditor prima della conferma.", styles["note"])]
    allegati = [(e, a) for e in audit.esiti.prefetch_related("allegati") for a in e.allegati.all()]
    if allegati and impostazione_attiva("sistema_gestione.rapporto_indice_evidenze"):
        story += [PageBreak(), _p("ALLEGATO - INDICE DELLE EVIDENZE", styles["head"]), Spacer(1, 4*mm)]
        for esito, allegato in allegati:
            story += [_p(f"Verifica {esito.punti}: {allegato.nome} ({allegato.dimensione} byte)", styles["cell"]),
                      _p(f"SHA-256: {allegato.sha256}", styles["small"]), Spacer(1, 3*mm)]
    if bozza:
        doc.build(story, onFirstPage=_filigrana_bozza, onLaterPages=_filigrana_bozza)
    else:
        doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Audit ISMS: MOD.171 Rev.1 (M-AUD-01 Audit Plan) e MOD.168 Rev.2 (M-AUD-02 Rapporto di Audit)
# ---------------------------------------------------------------------------

_BLU = colors.HexColor("#1f6fc5")
_BLU_TESTATA = colors.HexColor("#4a86e8")
_PESCA = colors.HexColor("#fbe3d6")


def _styles_isms():
    base = getSampleStyleSheet()
    s = _styles()
    s.update({
        "h1": ParagraphStyle("isms-h1", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=11.5, leading=14,
                             spaceBefore=8, spaceAfter=4),
        "h2": ParagraphStyle("isms-h2", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8.6, leading=11,
                             spaceBefore=6, spaceAfter=3),
        "blu": ParagraphStyle("isms-blu", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10, leading=12,
                              textColor=_BLU, alignment=TA_CENTER, spaceBefore=4, spaceAfter=4),
        "blu_sx": ParagraphStyle("isms-blu-sx", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10,
                                 leading=12, textColor=_BLU, spaceBefore=4),
        "link": ParagraphStyle("isms-link", parent=base["Normal"], fontSize=7.4, leading=9, textColor=_BLU),
        "th": ParagraphStyle("isms-th", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.6, leading=9,
                             alignment=TA_CENTER),
        "th_bianco": ParagraphStyle("isms-th-w", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.6,
                                    leading=9, alignment=TA_CENTER, textColor=colors.white),
        "centro": ParagraphStyle("isms-c", parent=base["Normal"], fontSize=7.4, leading=9, alignment=TA_CENTER),
    })
    return s


def _testata_isms(codice: str, titolo: str):
    """Testata ripetuta su ogni pagina come nei moduli: logo, codice e revisione, titolo in blu."""
    styles = _styles_isms()
    theme = PdfTheme.from_branding()
    width = A4[0] - 26 * mm
    if theme.logo_path:
        logo = Image(theme.logo_path, width=30 * mm, height=12 * mm, kind="proportional")
    else:
        logo = _p(theme.portal_name, styles["head"])
    codice_p = Paragraph(escape(codice), ParagraphStyle(
        "isms-cod", fontName="Helvetica-Bold", fontSize=7.6, leading=9, alignment=TA_CENTER))
    titolo_p = Paragraph(escape(titolo), ParagraphStyle(
        "isms-tit", fontName="Helvetica-Bold", fontSize=12.5, leading=15, alignment=TA_CENTER, textColor=_BLU))
    t = Table([[logo, codice_p], ["", titolo_p]], colWidths=[width * .27, width * .73], rowHeights=[6 * mm, 9 * mm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#444444")),
        ("SPAN", (0, 0), (0, 1)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (0, 1), "CENTER"),
    ]))
    return t


def _on_page_isms(codice: str, titolo: str, *, bozza: bool = False):
    def disegna(canvas, doc):
        testata = _testata_isms(codice, titolo)
        _w, h = testata.wrap(doc.width, doc.topMargin)
        testata.drawOn(canvas, doc.leftMargin, A4[1] - 9 * mm - h)
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(A4[0] - doc.rightMargin, 9 * mm, str(doc.page))
        canvas.restoreState()
        if bozza:
            _filigrana_bozza(canvas, doc)
    return disegna


def _doc_isms(buf, titolo: str):
    return SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=13 * mm, rightMargin=13 * mm, topMargin=30 * mm, bottomMargin=15 * mm,
        title=titolo,
    )


def _tabella_isms(rows, widths, *, testata_blu=False, repeat=1, font_size=7.4):
    t = Table(rows, colWidths=widths, repeatRows=repeat, hAlign="LEFT", splitInRow=1)
    comandi = [
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#444444")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if repeat:
        comandi.append(("BACKGROUND", (0, 0), (-1, repeat - 1),
                        _BLU_TESTATA if testata_blu else colors.HexColor("#d9d9d9")))
    t.setStyle(TableStyle(comandi))
    return t


def _team_isms(audit: Audit, styles, width):
    rows = [[_p("Team di audit", styles["th"]), _p("Nomi", styles["th"])],
            [_p("Lead Auditor", styles["cell"]), _p(audit.lead_auditor.nome, styles["cell"])]]
    for auditor in audit.auditor.exclude(pk=audit.lead_auditor_id):
        rows.append([_p("Auditor", styles["cell"]), _p(auditor.nome, styles["cell"])])
    return _tabella_isms(rows, [width * .27, width * .53])


def _scelta(valore, opzioni) -> str:
    return "   ".join(f"{_check(valore == codice)} {etichetta}" for codice, etichetta in opzioni)


def piano_isms_pdf(audit: Audit) -> bytes:
    """MOD.171 Rev.1 - M-AUD-01 Audit Plan."""
    from .models import AuditIsms
    from .services.audit_isms import assicura_isms

    styles = _styles_isms()
    dati = AuditIsms.objects.filter(audit=audit).first() or assicura_isms(audit)
    buf = io.BytesIO()
    doc = _doc_isms(buf, "MOD.171 - M-AUD-01 Audit Plan")
    width = doc.width
    periodo = _d(audit.data_inizio)
    if audit.data_fine and audit.data_fine != audit.data_inizio:
        periodo += f" - {_d(audit.data_fine)}"
    story = [
        Paragraph("<b>Norma di riferimento</b>: ISO/IEC 27001, 27002:2022", styles["cell"]),
        _p(f"Audit n. {audit.numero} - {periodo}", styles["small"]),
        Paragraph("Audit Plan", styles["blu"]),
        Paragraph("Team di audit", styles["h1"]),
        _team_isms(audit, styles, width),
        Paragraph("Elenco siti oggetto di audit", styles["h2"]),
        _tabella_isms([
            [_p("ID", styles["th"]), _p("Campo d'applicazione", styles["th"]),
             _p("Attività da remoto (S/N)", styles["th"]), _p("Funzione e/o processi", styles["th"])],
            [_p(dati.sito_id, styles["cell"]), _p(dati.sito_campo, styles["cell"]),
             _p("S" if dati.sito_remoto else "N", styles["centro"]), _p(dati.sito_funzioni, styles["cell"])],
        ], [width * .11, width * .52, width * .16, width * .21]),
        Paragraph("Piano di audit", styles["h2"]),
    ]
    rows = [[_p(t, styles["th"]) for t in (
        "Data", "Ora", "Sede / Unità organizzativa / Processo", "Responsabile coinvolto",
        "Processo del SGSI / Attività / Requisito di norma (e controlli applicabili)", "Auditor")]]
    for voce in audit.agenda.select_related("processo__responsabile"):
        quando = timezone.localtime(voce.quando)
        responsabile = _fmt_user(voce.processo.responsabile) if voce.processo_id and voce.processo.responsabile_id else ""
        rows.append([
            _p(quando.strftime("%d/%m/%Y"), styles["cell"]), _p(quando.strftime("%H:%M"), styles["cell"]),
            _p(voce.processo_area, styles["cell"]), _p(responsabile, styles["cell"]),
            _p(voce.attivita, styles["cell"]), _p(voce.auditor, styles["cell"]),
        ])
    story += [
        _tabella_isms(rows, [width * .11, width * .07, width * .19, width * .15, width * .32, width * .16]),
        Spacer(1, 5 * mm),
        _table([[_p(_firma("Approvazione Lead Auditor", audit.piano_approvato_lead_da, audit.piano_approvato_lead_il), styles["cell"]),
                 _p(_firma("Approvazione Direzione", audit.piano_approvato_direzione_da, audit.piano_approvato_direzione_il), styles["cell"])]],
               [width / 2, width / 2]),
    ]
    disegna = _on_page_isms("MOD.171 - M-AUD-01 – REV.1", "M-AUD-01 Audit Plan")
    doc.build(story, onFirstPage=disegna, onLaterPages=disegna)
    return buf.getvalue()


def _rilievo_isms(riga) -> str:
    testo = riga.evidenze or ""
    if riga.rilievo:
        etichetta = riga.rilievo + (f" {riga.get_gravita_display().replace('NC ', '')}" if riga.gravita else "")
        testo = f"[{etichetta}] {testo}"
        if riga.ofi_id:
            testo += f" (MOD.174 n. {riga.ofi.numero})"
    return testo


def rapporto_isms_pdf(audit: Audit, *, bozza: bool = False, nota: str = "") -> bytes:
    """MOD.168 Rev.2 - M-AUD-02 Rapporto di Audit, con conclusioni e firme del flusso del portale."""
    from .models import AuditIsms
    from .services.audit_isms import assicura_isms, azioni_correttive

    styles = _styles_isms()
    dati = AuditIsms.objects.filter(audit=audit).first() or assicura_isms(audit)
    buf = io.BytesIO()
    doc = _doc_isms(buf, "MOD.168 - M-AUD-02 Rapporto di Audit")
    width = doc.width
    story = []
    if nota:
        story += [_p(nota, styles["note"]), Spacer(1, 2 * mm)]
    story += [
        Paragraph("<b>Norma di riferimento</b>: ISO/IEC 27001, 27002:2022", styles["cell"]),
        _p(f"Audit n. {audit.numero}", styles["small"]), Spacer(1, 2 * mm),
    ]
    percentuale = f"{dati.remoto_percentuale}" if dati.remoto_percentuale is not None else "___"
    for flag, titolo, date, ore in (
        (bool(dati.remoto_date.strip()), f"Report attività in remoto ({percentuale}%)", dati.remoto_date, dati.remoto_ore),
        (bool(dati.campo_date.strip()), "Report attività in campo", dati.campo_date, dati.campo_ore),
    ):
        story += [
            _p(f"{_check(flag)} {titolo}", styles["head"]), Spacer(1, 1 * mm),
            _tabella_isms([[_p("Data/e dell'Audit\nDurata (ore)", styles["cell"]), _p(f"{date}\n{ore}", styles["cell"])]],
                          [width * .35, width * .55], repeat=0),
            Spacer(1, 3 * mm),
        ]
    story += [
        Paragraph("Elenco siti e suddivisione del campo d'applicazione", styles["h1"]),
        _tabella_isms([
            [_p(t, styles["th"]) for t in ("Indirizzo del sito", "Campo d'applicazione", "N.ro Addetti", "Turni di lavoro")],
            [_p(dati.sito_indirizzo, styles["cell"]), _p(dati.campo_applicazione, styles["cell"]),
             _p(dati.numero_addetti, styles["cell"]), _p(dati.turni, styles["cell"])],
        ], [width * .2, width * .5, width * .15, width * .15]),
        Paragraph("Team di audit", styles["h1"]),
        _team_isms(audit, styles, width),
        Paragraph("Report di audit", styles["blu_sx"]),
        Paragraph("Modifiche significative avvenute dopo il precedente audit", styles["h1"]),
    ]
    si_no = [("NO", "no"), ("SI", "sì:")]
    for titolo, valore, note, avviso in (
        ("Sistema di Gestione / Informazioni documentate", dati.modifiche_sistema, dati.modifiche_sistema_note, ""),
        ("Campo di applicazione del Sistema di gestione", dati.modifiche_campo, dati.modifiche_campo_note, ""),
        ("Numero addetti", dati.modifiche_addetti, dati.modifiche_addetti_note,
         "Nota: il termine «addetti» comprende titolari, soci, personale dipendente, includendo tutto il personale "
         "che lavora in ciascun turno"),
    ):
        story.append(_p(titolo, styles["h2"]))
        if avviso:
            story.append(_p(avviso, styles["note"]))
        story.append(_p(f"{_scelta(valore, si_no)}   {note or '(specificare)'}", styles["cell"]))
    story += [
        Paragraph("<b>Altro</b> (Es. prodotti/servizi, processi, installazioni, impianti, infrastrutture, "
                  "prerequisiti per certificazioni multi-sito)", styles["cell"]),
        _p(dati.modifiche_altro or "(specificare)", styles["cell"]),
        PageBreak(),
        _p("Il Team di Audit ha ritenuto le azioni intraprese a seguito delle Non Conformità minori (NCMi) emerse nel "
           "precedente audit, o delle carenze emerse in Stadio 1:", styles["head"]),
        _p(_scelta(dati.efficacia_ncmi, [("EFFICACI", "efficaci"), ("NON_EFFICACI", "non efficaci (*)"),
                                         ("NON_PRESENTI", "non presenti")]), styles["cell"]),
        _p("(*): In tale caso rilasciare una NC maggiore", styles["small"]), Spacer(1, 3 * mm),
        _p("Il Team di Audit ha valutato i report degli ultimi due audit, con particolare riferimento al trattamento dei "
           "rilievi emersi, ritenendolo:", styles["head"]),
        _p(_scelta(dati.report_precedenti, [("EFFICACE", "efficace"), ("NON_EFFICACE", "non efficace"),
                                            ("NA", "non applicabile (per assenza di rilievi)")]), styles["cell"]),
        Spacer(1, 3 * mm),
        _p("L'Organizzazione ha analizzato i commenti registrati nel precedente audit:", styles["head"]),
        _p(_scelta(dati.commenti_precedenti, [("SI", "sì"), ("NO", "no"), ("NON_PRESENTI", "non presenti")]), styles["cell"]),
        Paragraph("Efficacia del sistema di Gestione, rilievi di Audit ed evidenze", styles["h1"]),
    ]
    req_rows = [[_p("ISO 27001:2022", styles["th_bianco"]), _p("Evidenze e rilievi (NC, COM, AP)", styles["th_bianco"])]]
    for req in audit.isms_requisiti.select_related("ofi"):
        etichetta = req.titolo if req.codice in {"Obblighi", "Controlli"} else f"{req.codice} {req.titolo}"
        testo = _rilievo_isms(req)
        if req.codice == "Controlli" and not testo:
            testo = "ISO 27002:2022"
        req_rows.append([_p(etichetta, styles["link"]), _p(testo, styles["cell"])])
    story += [_tabella_isms(req_rows, [width * .4, width * .6], testata_blu=True), PageBreak()]
    ctrl_rows = [[_p("ISO 27001:2022", styles["th_bianco"]), _p("Applicazione controllo (1-4)", styles["th_bianco"]),
                  _p("Evidenze e rilievi (NC, COM, AP)", styles["th_bianco"])]]
    zero = []
    for riga in audit.isms_controlli.select_related("controllo", "ofi"):
        livello = "" if riga.livello is None else str(riga.livello)
        if riga.differisce_da_soa:
            livello += f"\n(SoA {riga.livello_soa})"
        ctrl_rows.append([_p(f"ISO 27002:2022 - {riga.controllo.codice}", styles["link"]), _p(livello, styles["centro"]),
                          _p(_rilievo_isms(riga), styles["cell"])])
        if riga.livello == 0:
            zero.append(len(ctrl_rows) - 1)
    tabella = _tabella_isms(ctrl_rows, [width * .3, width * .17, width * .53], testata_blu=True)
    for indice in zero:
        tabella.setStyle(TableStyle([("BACKGROUND", (1, indice), (-1, indice), _PESCA)]))
    story += [tabella, Paragraph("Elenco azioni correttive", styles["h1"])]
    az_rows = [[_p("NC", styles["th_bianco"]), _p("Azione Correttiva", styles["th_bianco"]),
                _p("Responsabile (da compilare da parte dell'azienda)", styles["th_bianco"]), _p("Scadenza", styles["th_bianco"])]]
    for azione in azioni_correttive(audit):
        az_rows.append([_p(azione["nc"], styles["cell"]), _p(azione["azione"], styles["cell"]),
                        _p(azione["responsabile"], styles["cell"]), _p(_d(azione["scadenza"]), styles["cell"])])
    while len(az_rows) < 3:
        az_rows.append(["", "", "", ""])
    story += [_tabella_isms(az_rows, [width * .25, width * .4, width * .2, width * .15], testata_blu=True)]
    soa = f", revisione {dati.soa_revisione.numero}" if dati.soa_revisione_id else ""
    story += [
        Spacer(1, 5 * mm), Paragraph("Conclusioni e approvazioni", styles["h1"]),
        _table([
            [_p("GIUDIZIO COMPLESSIVO DEL TEAM DI AUDIT", styles["head"])], [_p(audit.giudizio, styles["cell"])],
            [_p("PUNTI DI FORZA", styles["head"])], [_p(audit.punti_forza, styles["cell"])],
            [_p(_firma("Firma Lead Auditor", audit.rapporto_firmato_auditor_da, audit.rapporto_firmato_auditor_il), styles["cell"])],
            [_p(_firma("Convalida responsabile ente", audit.rapporto_convalidato_ente_da, audit.rapporto_convalidato_ente_il), styles["cell"])],
            [_p("VALUTAZIONE RDD", styles["head"])], [_p(audit.valutazione_rdd, styles["cell"])],
            [_p(f"CAR autorizzate: {audit.car_autorizzate}", styles["cell"])],
            [_p(_firma("Firma RDD", audit.rapporto_valutato_rdd_da, audit.rapporto_valutato_rdd_il), styles["cell"])],
        ], [width]),
        Spacer(1, 3 * mm),
        _p("Rapporto di audit interno ISMS ai sensi di UNI CEI EN ISO/IEC 27001:2022 §9.2 e MT CN 276. Le NC e le AP "
           "sono registrate nel MOD.174 - SGI Registro OFI/NC; i livelli di applicazione partono dalla Dichiarazione "
           f"di Applicabilità (MOD.165) in vigore{soa}.", styles["note"]),
    ]
    disegna = _on_page_isms("MOD.168 - M-AUD-02 – REV.2", "M-AUD-02 Rapporto di Audit", bozza=bozza)
    doc.build(story, onFirstPage=disegna, onLaterPages=disegna)
    return buf.getvalue()
