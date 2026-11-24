"""Storico di formazione e competenze di una persona in PDF («MOD.053 dinamico» della specifica).

Aggrega ciò che il portale sa già: mansioni e livelli di oggi, competenze con livello raggiunto,
sessioni formative con l'esito e la storia delle valutazioni. Sempre aggiornato, mai compilato a
mano. Il formato del MOD.053 cartaceo resta da far approvare alla Qualità: il titolo lo dice.
"""
from __future__ import annotations

from io import BytesIO

from django.utils import timezone

from ..models import ValutazioneCompetenzaStorico
from ..models_sessioni import SessioneFormativa

DOC_TITOLO = "Storico di formazione e competenze"


def sessioni_persona(legacy_id: int) -> list:
    return list(SessioneFormativa.objects.filter(partecipanti__legacy_anagrafica_id=legacy_id).distinct()
                .select_related("richiesta__mansione", "richiesta__competenza").prefetch_related("righe")
                .order_by("-aperta_il"))


def build_pdf(legacy_id: int, persona: dict) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    from core.pdf import PdfTheme, build_styles, data_table, header_footer_callback, make_document, section_heading

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = BytesIO()
    nome = next((c["valore"] for c in persona["campi"] if c["etichetta"] == "Persona"), "")
    doc = make_document(buf, title=f"{DOC_TITOLO} - {nome}")
    P = Paragraph
    story: list = [P(DOC_TITOLO, styles["title"]),
                   P(f"Costruzioni Novicrom srl - MOD.053 dinamico (bozza, formato da approvare) - "
                     f"aggiornato al {timezone.localdate():%d/%m/%Y}", styles["subtitle"]), Spacer(1, 4 * mm)]
    story.append(data_table([[P(c["etichetta"], styles["cell"]), P(str(c["valore"]), styles["cell"])] for c in persona["campi"]],
                            theme, col_widths=[120, None]))
    story.append(Spacer(1, 4 * mm))

    story += section_heading("Mansioni di oggi", theme, styles)
    if persona["mansioni"]:
        righe = [[P(h, styles["table_header"]) for h in ["Mansione", "Livello", "Stato"]]]
        righe += [[P(m["nome"], styles["cell"]), P((m["livello"] or {}).get("codice", "-"), styles["cell"]),
                   P(m["stato"], styles["cell"])] for m in persona["mansioni"]]
        story.append(data_table(righe, theme, col_widths=[None, 60, 140], repeat_rows=1))
    else:
        story.append(P("Nessuna mansione assegnata.", styles["body"]))
    story.append(Spacer(1, 3 * mm))

    story += section_heading("Competenze", theme, styles)
    if persona["competenze"]:
        righe = [[P(h, styles["table_header"]) for h in ["Competenza", "Mansione", "Livello", "Richiesto"]]]
        righe += [[P(c["nome"], styles["cell"]), P(c["mansione"], styles["cell"]),
                   P((c["livello"] or {}).get("codice", "-"), styles["cell"]),
                   P((c["richiesto"] or {}).get("codice", "-"), styles["cell"])] for c in persona["competenze"]]
        story.append(data_table(righe, theme, col_widths=[None, 140, 50, 56], repeat_rows=1))
    else:
        story.append(P("Nessuna competenza richiesta dalle sue mansioni.", styles["body"]))
    story.append(Spacer(1, 3 * mm))

    story += section_heading("Sessioni formative", theme, styles)
    sessioni = sessioni_persona(legacy_id)
    if sessioni:
        righe = [[P(h, styles["table_header"]) for h in ["Sessione", "Oggetto", "Modalità", "Esito", "Chiusa il"]]]
        for s in sessioni:
            modi = sorted({r.get_modalita_display() for r in s.righe.all() if r.modalita})
            righe.append([P(s.codice, styles["cell"]), P(s.richiesta.oggetto, styles["cell"]),
                          P(", ".join(modi) or "-", styles["cell"]), P(s.get_stato_display(), styles["cell"]),
                          P(f"{timezone.localtime(s.chiusa_il):%d/%m/%Y}" if s.chiusa_il else "-", styles["cell"])])
        story.append(data_table(righe, theme, col_widths=[80, None, 100, 80, 60], repeat_rows=1))
    else:
        story.append(P("Nessuna sessione formativa.", styles["body"]))
    story.append(Spacer(1, 3 * mm))

    story += section_heading("Storia delle valutazioni", theme, styles)
    storia = list(ValutazioneCompetenzaStorico.objects.filter(legacy_anagrafica_id=legacy_id).order_by("-valutato_il")[:200])
    if storia:
        righe = [[P(h, styles["table_header"]) for h in ["Data", "Competenza", "Prima", "Dopo", "Valutata da"]]]
        righe += [[P(f"{timezone.localtime(v.valutato_il):%d/%m/%Y}", styles["cell"]), P(v.competenza_nome or "-", styles["cell"]),
                   P(v.livello_prima or "-", styles["cell"]), P(v.livello or "tolto", styles["cell"]),
                   P(v.valutato_da or "-", styles["cell"])] for v in storia]
        story.append(data_table(righe, theme, col_widths=[60, None, 40, 40, 110], repeat_rows=1))
    else:
        story.append(P("Nessuna valutazione registrata.", styles["body"]))
    story.append(P("Livelli: I in formazione, L intermedio, U autonomo, O formatore/esperto.", styles["body"]))

    draw = header_footer_callback(theme, title=DOC_TITOLO, subtitle=nome)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()
