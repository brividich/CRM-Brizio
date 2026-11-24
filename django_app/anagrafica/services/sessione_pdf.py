"""Verbale della sessione formativa in PDF: chi, che cosa, come, chi ha valutato, chi ha firmato.

Si genera dalla sessione salvata, mai dalla struttura viva: è il documento da mostrare in audit.
Una sessione ancora aperta esce con la dicitura «In corso» e le firme mancanti lasciate in bianco.
"""
from __future__ import annotations

from io import BytesIO

from django.utils import timezone

DOC_TITOLO = "Verbale di sessione formativa"
RIGA_VUOTA = "______________________________"


def _evidenza(r) -> str:
    if r.stato == "gia_presente":
        return f"Già nel profilo della persona (livello {r.livello_oggi})."
    if r.modalita == "P":
        testo = r.descrizione or "-"
        return testo + (f" · verificata il {r.data_verifica:%d/%m/%Y}" if r.data_verifica else "")
    if r.modalita == "A":
        parti = [f"Tutor: {r.tutor_nome or '-'}"]
        if r.dal:
            parti.append(f"dal {r.dal:%d/%m/%Y}" + (f" al {r.al:%d/%m/%Y}" if r.al else ""))
        if r.ore:
            parti.append(f"{r.ore:g} ore")
        parti.append("registro MOD.040 allegato" if r.registro_mod040 else "registro MOD.040 mancante")
        return " · ".join(parti)
    if r.modalita == "C":
        corso = f"{r.corso.codice} {r.corso.titolo}" if r.corso_id else (r.docente_ente or "-")
        parti = [corso]
        if r.data_corso:
            parti.append(f"{r.data_corso:%d/%m/%Y}")
        if r.verifica:
            parti.append(f"verifica: {r.get_verifica_display().lower()}")
        return " · ".join(parti)
    return "-"


def build_pdf(sessione, persona: str) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    from core.pdf import PdfTheme, build_styles, data_table, header_footer_callback, make_document, section_heading

    from . import sessioni

    r = sessione.richiesta
    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = BytesIO()
    doc = make_document(buf, title=f"{DOC_TITOLO} {sessione.codice}")
    P = Paragraph
    story: list = [P(DOC_TITOLO, styles["title"]),
                   P(f"Costruzioni Novicrom srl - {sessione.codice} - {sessione.get_stato_display()}", styles["subtitle"]),
                   Spacer(1, 4 * mm)]

    meta = [["Sessione", sessione.codice], ["Persona", persona],
            ["Richiesta", f"{r.codice} - {r.get_tipo_display()}"]]
    if r.mansione_id:
        meta.append(["Mansione", r.mansione.nome])
    if r.competenza_id:
        meta.append(["Competenza", r.competenza.nome])
    meta += [["Livello da raggiungere", r.livello or "-"],
             ["Motivo della richiesta", r.motivazione or "-"],
             ["Richiesta da", f"{r.richiedente_nome} il {timezone.localtime(r.creata_il):%d/%m/%Y}"],
             ["Approvata da", f"{r.deciso_da_nome or '-'} il {timezone.localtime(r.decisa_il):%d/%m/%Y}" if r.decisa_il else "-"],
             ["Aperta da", f"{sessione.aperta_da_nome} il {timezone.localtime(sessione.aperta_il):%d/%m/%Y}"]]
    story.append(data_table([[P(k, styles["cell"]), P(str(v), styles["cell"])] for k, v in meta], theme, col_widths=[130, None]))
    story.append(Spacer(1, 4 * mm))

    story += section_heading("Competenze", theme, styles)
    righe = list(sessione.righe.select_related("corso"))
    if righe:
        tab = [[P(h, styles["table_header"]) for h in ["Competenza", "Richiesto", "Modalità", "Evidenza", "Raggiunto", "Valutata da"]]]
        for x in righe:
            valutata = f"{x.valutato_da_nome}, {timezone.localtime(x.valutato_il):%d/%m/%Y}" if x.valutato_il else "-"
            tab.append([P(x.competenza_nome, styles["cell"]), P(x.livello_richiesto, styles["cell"]),
                        P(x.get_modalita_display() or "-", styles["cell"]), P(_evidenza(x), styles["cell"]),
                        P(x.livello_raggiunto or "-", styles["cell"]), P(valutata, styles["cell"])])
        story.append(data_table(tab, theme, col_widths=[110, 46, 62, None, 50, 90], repeat_rows=1))
    else:
        story.append(P("La mansione non ha competenze caricate.", styles["body"]))
    story.append(P("Livelli: I in formazione, L intermedio, U autonomo, O formatore/esperto.", styles["body"]))
    story.append(Spacer(1, 4 * mm))

    story += section_heading("Firme", theme, styles)
    sigla = sessioni.sigla_firma(sessione)
    if sessione.firma_approvatore_il:
        testo = (f"{sigla}: firmata da {(sessione.firma_approvatore_nome or '').upper()} il "
                 f"{timezone.localtime(sessione.firma_approvatore_il):%d/%m/%Y} nel portale.")
        if sessione.benestare_mod040:
            testo += " Visti i registri MOD.040 delle righe in affiancamento."
        story.append(P(testo, styles["body"]))
    else:
        story.append(P(f"{sigla}: Firma {RIGA_VUOTA}   Data ________", styles["body"]))
    from . import struttura_vista

    partecipanti = list(sessione.partecipanti.all())
    nomi = struttura_vista._nomi([p.legacy_anagrafica_id for p in partecipanti])
    for p in partecipanti:
        nome = nomi.get(p.legacy_anagrafica_id) or f"#{p.legacy_anagrafica_id}"
        if p.firmato:
            modo = "nel portale" if p.firma_modo == "portale" else f"su carta, registrata da {(p.firma_registrata_da or '').upper()}"
            story.append(P(f"{nome}: firmata {modo} il {p.firma_il:%d/%m/%Y}.", styles["body"]))
        else:
            story.append(P(f"{nome}: Firma {RIGA_VUOTA}   Data ________", styles["body"]))
    story.append(Spacer(1, 4 * mm))

    story += section_heading("Esito", theme, styles)
    if sessione.stato == "positiva":
        story.append(P(f"Chiusa positiva il {timezone.localtime(sessione.chiusa_il):%d/%m/%Y} da "
                       f"{(sessione.chiusa_da_nome or '').upper()}: livelli aggiornati nella skill matrix.", styles["body"]))
    elif sessione.stato == "negativa":
        story.append(P(f"Chiusa negativa il {timezone.localtime(sessione.chiusa_il):%d/%m/%Y} da "
                       f"{(sessione.chiusa_da_nome or '').upper()}. Motivo: {sessione.motivo_negativo}", styles["body"]))
    else:
        story.append(P("In corso: i livelli cambiano solo alla chiusura.", styles["body"]))

    draw = header_footer_callback(theme, title=DOC_TITOLO, subtitle=sessione.codice)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()
