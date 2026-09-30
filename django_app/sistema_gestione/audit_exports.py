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


def _table(rows, widths, *, repeat=0, section_rows=(), font_size=7.5):
    table = Table(rows, colWidths=widths, repeatRows=repeat, hAlign="LEFT")
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
        _p("9100:2018", styles["small"]), _p("45001:2018", styles["small"]),
        _p("27001:2022", styles["small"]), _p("PdR 125:2022", styles["small"]),
        _p("Normative", styles["head"]), *[_p(m, styles["head"]) for m in months],
    ]]
    for riga in programma.righe.prefetch_related("celle"):
        celle = {c.mese: c.stato for c in riga.celle.all()}
        rows.append([
            _p(riga.area + (f"\n{riga.note}" if riga.note else ""), styles["cell"]),
            _p(riga.enti, styles["cell"]), _p(riga.punti_9100, styles["cell"]),
            _p(riga.punti_45001, styles["cell"]), _p(riga.punti_27001, styles["cell"]),
            _p(riga.punti_pdr125, styles["cell"]), _p(riga.altre_normative, styles["small"]),
            *[_p(celle.get(mese, ""), styles["head"]) for mese in range(1, 13)],
        ])
    fixed = [62 * mm, 35 * mm, 23 * mm, 23 * mm, 23 * mm, 23 * mm, 35 * mm]
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
        f"{_check(audit.en9100)} EN 9100:2018", f"{_check(audit.iso45001)} ISO 45001:2018",
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


def rapporto_audit_pdf(audit: Audit) -> bytes:
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
    team = ", ".join(a.nome for a in audit.auditor.all())
    norme_rapporto = "  ".join([
        f"{_check(audit.en9100)} EN 9100:2018",
        f"{_check(audit.iso45001)} ISO 45001:2018",
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
                _check(esito.esito == AuditEsito.ESITO_CONFORME) + " ✓",
                _check(esito.esito == AuditEsito.ESITO_OFI) + " OFI",
                _check(esito.esito == AuditEsito.ESITO_NC) + " NC",
                _check(esito.esito == AuditEsito.ESITO_NA) + " N/A",
            ])
            checklist.append([
                _p(esito.punti, styles["head"]), _p(esito.testo, styles["small"]),
                _p(esito.evidenze, styles["small"]), _p(rilievo, styles["small"]),
            ])
        section_rows.append(len(checklist))
        checklist.append([_p(
            f"CAR (MOD.036) aperta - {sezione.codice}: {_check(not car.get(sezione.pk))} NO  {_check(car.get(sezione.pk, False))} SÌ → vedere MOD.174",
            styles["head"],
        ), "", "", ""])
    ct = _table(checklist, [12 * mm, 66 * mm, 63 * mm, width - 141 * mm], repeat=1, section_rows=tuple(section_rows), font_size=6.5)
    for row in section_rows:
        ct.setStyle(TableStyle([("SPAN", (0, row), (-1, row))]))
    counts = contatori_rilievi(audit)
    story += [ct, PageBreak(), _p("D. GIUDIZI ED OSSERVAZIONI DELL'AUDITOR", styles["head"])]
    story += [
        _table([
            [_p("GIUDIZIO COMPLESSIVO DELL'AUDITOR", styles["head"])], [_p(audit.giudizio, styles["cell"])],
            [_p("PUNTI DI FORZA RILEVATI", styles["head"])], [_p(audit.punti_forza, styles["cell"])],
            [_p(f"OFI emesse: {counts['ofi']}    NC di sistema: {counts['nc']}", styles["head"])],
            [_p(_firma("Firma Auditor", audit.rapporto_firmato_auditor_da, audit.rapporto_firmato_auditor_il), styles["cell"])],
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
    doc.build(story)
    return buf.getvalue()
