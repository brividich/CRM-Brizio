"""MOD.040 Registro Corsi (Rev.4) generato dall'edizione.

Riporta le voci del modulo cartaceo nello stesso ordine: corso n°, oggetto,
argomento, partecipanti con esito, tutor, giornate e ore con il totale, esito
della formazione, verifica di assenza NC nei 6 mesi successivi e approvazione
finale di MSM/MSO. Quello che il portale non conosce resta come riga da
compilare a mano: il registro stampato si firma, non si inventa.
"""
from __future__ import annotations

from io import BytesIO

DOC_CODICE = "MOD.040"
DOC_REVISIONE = "Rev. 4"
DOC_TITOLO = "Registro Corsi"
RIGA_VUOTA = "______________________________"


def _esito_iscrizione(i) -> str:
    if i.stato == "COMPLETATO":
        esito = "Idoneo" if i.idoneo is not False else "Completato, non idoneo"
    else:
        esito = i.get_stato_display()
    if i.verifica_superata is not None:
        esito += " · verifica " + ("superata" if i.verifica_superata else "non superata")
        if i.punteggio is not None:
            esito += f" ({i.punteggio:g}"
            esito += f"/{i.punteggio_minimo})" if i.punteggio_minimo is not None else ")"
    return esito


def build_mod040_pdf_bytes(sessione) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    from core.pdf import PdfTheme, build_styles, data_table, header_footer_callback, make_document, section_heading

    from .attestato_pdf import _nomi_map

    corso = sessione.corso
    lezioni = list(sessione.lezioni.select_related("docente", "docente_ente").order_by("data", "ora_inizio"))
    iscrizioni = list(sessione.iscrizioni.order_by("legacy_anagrafica_id"))
    nomi = _nomi_map([i.legacy_anagrafica_id for i in iscrizioni])
    programma = list(sessione.programma.all())

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = BytesIO()
    titolo_doc = f"{DOC_CODICE} {DOC_TITOLO} - {sessione.codice_sessione}"
    doc = make_document(buf, title=titolo_doc)
    story: list = []
    P = Paragraph

    story.append(P(f"{DOC_TITOLO}", styles["title"]))
    story.append(P(f"Costruzioni Novicrom srl - {DOC_CODICE} - {DOC_REVISIONE}", styles["subtitle"]))
    story.append(Spacer(1, 4 * mm))

    tutor = sessione.erogatore_display or "-"
    tutor_lezioni = sorted({
        (lz.docente_nome or (lz.docente.nome if lz.docente_id else "")
         or (lz.docente_ente.nome if lz.docente_ente_id else "")).strip()
        for lz in lezioni
    } - {""})
    if tutor_lezioni:
        tutor = ", ".join(dict.fromkeys([tutor] + tutor_lezioni)) if tutor != "-" else ", ".join(tutor_lezioni)

    argomento = "; ".join(v.argomento for v in programma) or "; ".join(
        dict.fromkeys(lz.argomento for lz in lezioni if (lz.argomento or "").strip())) or "-"
    meta = [
        ["Corso n°", f"{corso.codice} - edizione {sessione.codice_sessione}"],
        ["Oggetto", corso.titolo],
        ["Argomento", argomento],
        ["Tutor / docente", tutor],
        ["Periodo", f"dal {sessione.data_inizio:%d/%m/%Y} al {sessione.data_fine:%d/%m/%Y}"],
    ]
    story.append(data_table([[P(k, styles["cell"]), P(str(v), styles["cell"])] for k, v in meta],
                            theme, col_widths=[110, None]))
    story.append(Spacer(1, 4 * mm))

    story += section_heading("Giorno e ore", theme, styles)
    totale = 0.0
    if lezioni:
        rows = [[P(h, styles["table_header"]) for h in ["Giorno", "Orario", "Ore", "Argomento", "Data / firma / timbro tutor"]]]
        for lz in lezioni:
            totale += lz.durata_ore
            rows.append([
                P(f"{lz.data:%d/%m/%Y}", styles["cell"]),
                P(f"{lz.ora_inizio:%H:%M}-{lz.ora_fine:%H:%M}", styles["cell"]),
                P(f"{lz.durata_ore:g}", styles["cell_right"]),
                P(lz.argomento or "-", styles["cell"]),
                P("", styles["cell"]),
            ])
        rows.append([P("TOT", styles["table_header"]), P("", styles["cell"]),
                     P(f"{round(totale, 2):g}", styles["cell_right"]), P("", styles["cell"]), P("", styles["cell"])])
        story.append(data_table(rows, theme, col_widths=[58, 64, 32, None, 120], repeat_rows=1))
    else:
        story.append(P("Nessuna giornata a calendario.", styles["body"]))
    story.append(Spacer(1, 4 * mm))

    story += section_heading("Partecipanti", theme, styles)
    if iscrizioni:
        rows = [[P(h, styles["table_header"]) for h in ["Partecipante", "Ore", "Esito", "Firma / timbro partecipante"]]]
        for i in iscrizioni:
            rows.append([
                P(nomi.get(i.legacy_anagrafica_id, f"#{i.legacy_anagrafica_id}"), styles["cell"]),
                P(f"{i.ore_frequentate:g}", styles["cell_right"]),
                P(_esito_iscrizione(i), styles["cell"]),
                P("", styles["cell"]),
            ])
        story.append(data_table(rows, theme, col_widths=[None, 32, 150, 120], repeat_rows=1))
    else:
        story.append(P("Nessun partecipante.", styles["body"]))
    story.append(Spacer(1, 4 * mm))

    idonei = sum(1 for i in iscrizioni if i.stato == "COMPLETATO" and i.idoneo is not False)
    story += section_heading("Esito formazione", theme, styles)
    story.append(P(f"{idonei} partecipanti idonei su {len(iscrizioni)}." if iscrizioni else RIGA_VUOTA, styles["body"]))
    if (sessione.note or "").strip():
        story.append(P(sessione.note.strip(), styles["body"]))
    story.append(Spacer(1, 4 * mm))

    story += section_heading("Verifica assenza NC nei successivi 6 mesi", theme, styles)
    dovuta = sessione.verifica_nc_dovuta_dal
    if sessione.verifica_nc_esito:
        riga = (f"{sessione.get_verifica_nc_esito_display()} - registrata il {sessione.verifica_nc_il:%d/%m/%Y} "
                f"da {(sessione.verifica_nc_da_nome or '').upper() or '-'}")
        story.append(P(riga, styles["body"]))
        if sessione.verifica_nc_note:
            story.append(P("Esito: " + sessione.verifica_nc_note, styles["body"]))
    else:
        story.append(P("SI  [ ]    NO  [ ]    Non applicabile  [ ]" + (
            f"    (dovuta dal {dovuta:%d/%m/%Y})" if dovuta else ""), styles["body"]))
        story.append(P(f"Esito: {RIGA_VUOTA}   Firma MSM/MSO {RIGA_VUOTA}   Data ________", styles["body"]))
    story.append(Spacer(1, 4 * mm))

    story += section_heading("Approvazione finale", theme, styles)
    if sessione.is_approvata:
        story.append(P(f"Approvato da {(sessione.approvata_da_nome or '').upper() or '-'} (MSM/MSO) il "
                       f"{sessione.approvata_il:%d/%m/%Y} con verifica formale nel portale.", styles["body"]))
        if sessione.approvazione_note:
            story.append(P(sessione.approvazione_note, styles["body"]))
    else:
        story.append(P(f"MSM/MSO Firma {RIGA_VUOTA}   Data ________", styles["body"]))

    draw = header_footer_callback(theme, title=f"{DOC_CODICE} {DOC_TITOLO}", subtitle=corso.titolo)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()
