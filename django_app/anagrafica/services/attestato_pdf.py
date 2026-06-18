"""Generazione PDF dell'attestato di formazione e archiviazione nel box documenti.

L'attestato a video è un foglio HTML stampabile (vedi
``anagrafica:attestato_formazione``). Per l'**archiviazione** (salvataggio nel box
documenti del dipendente, export di massa, conservazione GDPR) serve invece un
file reale: questo modulo lo genera lato server con ``reportlab`` riusando il tema
PDF condiviso del portale (:mod:`core.pdf`), in una veste sobria adatta alla copia
cartacea/archivio.

Punti d'ingresso principali:

- :func:`build_attestato_context` — derivazione condivisa (tipo, responsabile,
  nominativo, sede, numero) usata sia dalla view HTML sia dal PDF, così le due
  rese restano allineate.
- :func:`build_attestato_pdf_bytes` — PDF dell'attestato come ``bytes``.
- :func:`get_or_create_cartella_attestati` — cartella «Attestati formazione»
  (scheletro uguale per tutti i dipendenti) creata on-demand.
- :func:`archivia_attestato` — salva il PDF come :class:`DocumentoDipendente`
  (tipo ``CERTIFICATO_FORMAZIONE``), idempotente sul singolo completamento.
"""

from __future__ import annotations

import logging
from io import BytesIO

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

# Tag di riferimento che lega il documento archiviato al completamento di origine
# (idempotenza dell'archiviazione, senza GenericForeignKey).
RIFERIMENTO_TIPO = "anagrafica.training_record"


# ---------------------------------------------------------------------------
# Numero di protocollo (progressivo per anno: ATT-2026-0001)
# ---------------------------------------------------------------------------

def assegna_numero_protocollo(record) -> str:
    """Ritorna il numero di protocollo dell'attestato, assegnandolo se mancante.

    Progressivo per anno (anno del completamento), formato ``ATT-AAAA-NNNN``,
    azzerato a inizio anno. Allocazione concorrenza-safe (transazione +
    ``select_for_update`` sul contatore annuale) e idempotente: una volta
    assegnato resta stabile sul record.
    """
    from django.db import transaction
    from anagrafica.models_formazione import AttestatoProtocolloCounter

    if record.numero_protocollo:
        return record.numero_protocollo

    anno = record.data_completamento.year if record.data_completamento else None
    if not anno:
        from django.utils import timezone
        anno = timezone.localdate().year

    with transaction.atomic():
        counter, _ = (
            AttestatoProtocolloCounter.objects
            .select_for_update()
            .get_or_create(anno=anno)
        )
        counter.ultimo += 1
        counter.save(update_fields=["ultimo"])
        numero = f"{AttestatoProtocolloCounter.PREFISSO}-{anno}-{counter.ultimo:04d}"
        record.numero_protocollo = numero
        record.save(update_fields=["numero_protocollo"])
    return numero


# ---------------------------------------------------------------------------
# Derivazione contesto (condivisa view HTML ↔ PDF)
# ---------------------------------------------------------------------------

def build_attestato_context(record, cfg=None) -> dict:
    """Deriva i campi dell'attestato da un ``TrainingEmployeeRecord``.

    Logica identica alla view HTML: tipo (qualifica/frequenza/partecipazione),
    responsabile del corso, nominativo dall'anagrafica, sede e numero attestato.
    Non scrive nulla; usa i campi snapshot per stabilità storica.
    """
    from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows
    from anagrafica.models_formazione import AttestatoFormazioneConfig, TrainingCertificate

    if cfg is None:
        cfg = AttestatoFormazioneConfig.get_instance()

    try:
        certificato = record.attestato
    except TrainingCertificate.DoesNotExist:
        certificato = None

    legacy_id = record.legacy_anagrafica_id
    dip = None
    try:
        ensure_anagrafica_schema()
        rows = fetch_anagrafica_rows(ids=[legacy_id])
        dip = rows[0] if rows else None
    except Exception:
        logger.exception("Errore lettura anagrafica per attestato record %s", record.pk)

    nominativo = ""
    if dip:
        nominativo = f"{str(dip.get('cognome') or '').strip()} {str(dip.get('nome') or '').strip()}".strip()
    if not nominativo:
        nominativo = f"Dipendente #{legacy_id}"

    corso = record.corso
    qualifica = corso.qualifica if corso else None

    if qualifica:
        attestato_tipo = cfg.titolo_qualifica
    elif corso and corso.obbligatorio:
        attestato_tipo = cfg.titolo_frequenza
    else:
        attestato_tipo = cfg.titolo_partecipazione

    responsabile = (
        (record.teacher_name_snapshot or "").strip()
        or (record.sessione.docente_nome.strip() if record.sessione and record.sessione.docente_nome else "")
        or (str(record.sessione.docente).strip() if record.sessione and record.sessione.docente_id else "")
        or (certificato.rilasciato_da.strip() if certificato and certificato.rilasciato_da else "")
        or (cfg.responsabile_default or "").strip()
    )

    sede_display = (
        (record.session_code_snapshot or "").strip()
        or (record.sessione.sede.strip() if record.sessione and record.sessione.sede else "")
    )

    # Numero di protocollo: quello anagrafico esterno se presente, altrimenti il
    # protocollo interno progressivo per anno (assegnato e stabile sul record).
    if certificato and certificato.numero_attestato:
        numero_display = certificato.numero_attestato
    else:
        numero_display = assegna_numero_protocollo(record)

    return {
        "record": record,
        "certificato": certificato,
        "cfg": cfg,
        "dip": dip,
        "legacy_id": legacy_id,
        "nominativo": nominativo,
        "corso": corso,
        "qualifica": qualifica,
        "attestato_tipo": attestato_tipo,
        "responsabile": responsabile,
        "numero_display": numero_display,
        "sede_display": sede_display,
    }


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def build_attestato_pdf_bytes(record, cfg=None) -> bytes:
    """Genera l'attestato di un completamento come PDF (``bytes``).

    Veste sobria coerente con il tema PDF del portale (header con logo/monogramma,
    footer con paginazione), contenuto identico al foglio a video: tipo, formula,
    nominativo, eventuali dati personali (gated dal toggle GDPR), dati del corso,
    doppia firma (Responsabile del corso + Dipendente) e nota legale.
    """
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, Spacer, Table, TableStyle
    from core.pdf import PdfTheme, build_styles, header_footer_callback, make_document

    ctx = build_attestato_context(record, cfg)
    cfg = ctx["cfg"]
    dip = ctx["dip"] or {}

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = BytesIO()
    doc = make_document(buf, title=f"Attestato {ctx['numero_display']}")

    story: list = []

    # Etichetta sezione + tipo attestato
    story.append(Paragraph(cfg.sezione_label, styles["subtitle"]))
    story.append(Paragraph(ctx["attestato_tipo"], styles["title"]))
    story.append(HRFlowable(width="100%", thickness=1, color=theme.c_accent(), spaceAfter=8))

    # Formula + nominativo
    story.append(Paragraph(cfg.formula_attestazione, styles["body"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"<b><font size=16>{ctx['nominativo']}</font></b>", styles["value"]))

    # Dati personali (gated dal toggle privacy)
    if cfg.mostra_dati_personali:
        pers = []
        if dip.get("codice_fiscale"):
            pers.append(f"C.F. {dip.get('codice_fiscale')}")
        nato = []
        if dip.get("luogo_nascita"):
            nato.append(str(dip.get("luogo_nascita")))
        if dip.get("data_nascita"):
            nato.append(str(dip.get("data_nascita")))
        if nato:
            pers.append("nato/a a " + " il ".join(nato))
        if dip.get("matricola"):
            pers.append(f"matricola {dip.get('matricola')}")
        if pers:
            story.append(Paragraph(" · ".join(pers), styles["body"]))

    story.append(Spacer(1, 4 * mm))

    # Dati del corso (tabella label/valore)
    r = ctx["record"]
    esito = "Idoneo" if r.idoneo else "Non idoneo"
    durata = r.duration_hours_snapshot or (r.corso.durata_ore_teorica if r.corso else None)
    rows = [
        ["Corso", r.course_title_snapshot or (r.corso.titolo if r.corso else "—")],
        ["Codice", r.course_code_snapshot or (r.corso.codice if r.corso else "—")],
        ["Piano formativo", r.plan_name_snapshot or "—"],
        ["Data completamento", r.data_completamento.strftime("%d-%m-%Y") if r.data_completamento else "—"],
        ["Durata", f"{durata} h" if durata else "—"],
        ["Esito", esito],
    ]
    if r.data_scadenza:
        rows.append(["Validità fino al", r.data_scadenza.strftime("%d-%m-%Y")])
    if ctx["qualifica"]:
        rows.append(["Qualifica rilasciata", str(ctx["qualifica"])])
    if ctx["sede_display"]:
        rows.append(["Sede / Sessione", ctx["sede_display"]])
    rows.append(["Numero attestato", ctx["numero_display"]])

    body_rows = [[Paragraph(k, styles["label"]), Paragraph(str(v), styles["value"])] for k, v in rows]
    tbl = Table(body_rows, colWidths=[45 * mm, None])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, theme.c_border()),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 12 * mm))

    # Doppia firma
    firma_cell = TableStyle([
        ("LINEABOVE", (0, 0), (0, 0), 0.6, theme.c_text()),
        ("LINEABOVE", (1, 0), (1, 0), 0.6, theme.c_text()),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ])
    firme = Table(
        [
            [
                Paragraph(f"<b>{cfg.firma_responsabile_label}</b>", styles["body"]),
                Paragraph(f"<b>{cfg.firma_dipendente_label}</b>", styles["body"]),
            ],
            [
                Paragraph(ctx["responsabile"] or "&nbsp;", styles["cell"]),
                Paragraph(ctx["nominativo"], styles["cell"]),
            ],
        ],
        colWidths=[None, None],
    )
    firme.setStyle(firma_cell)
    story.append(firme)
    story.append(Spacer(1, 10 * mm))

    # Nota legale
    if cfg.nota_legale:
        story.append(HRFlowable(width="100%", thickness=0.4, color=theme.c_border(), spaceAfter=4))
        nota_style = styles["cell"]
        story.append(Paragraph(cfg.nota_legale, nota_style))

    draw = header_footer_callback(
        theme,
        title=ctx["attestato_tipo"],
        subtitle=cfg.intestazione_eyebrow,
    )
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Libretto formativo (curriculum) come PDF server-side
# ---------------------------------------------------------------------------

# Tag di riferimento per il libretto archiviato (uno per dipendente, sovrascritto).
RIFERIMENTO_LIBRETTO = "anagrafica.libretto_formativo"


def build_libretto_pdf_bytes(legacy_id: int) -> bytes:
    """Genera il libretto formativo (curriculum) del dipendente come PDF (``bytes``).

    Aggrega storico completamenti (campi snapshot) e obblighi correnti, nello
    stesso tema PDF del portale. Self-contained: legge i dati da sé, così è usabile
    anche da archiviazione/schedulazione senza passare dalla view.
    """
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer
    from django.utils import timezone
    from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows
    from core.pdf import (
        PdfTheme, build_styles, data_table, header_footer_callback,
        make_document, section_heading,
    )
    from anagrafica.models_formazione import TrainingDeadline, TrainingEmployeeRecord

    dip = None
    try:
        ensure_anagrafica_schema()
        rows = fetch_anagrafica_rows(ids=[legacy_id])
        dip = rows[0] if rows else None
    except Exception:
        logger.exception("Errore lettura anagrafica per libretto %s", legacy_id)
    dip = dip or {}
    nominativo = f"{str(dip.get('cognome') or '').strip()} {str(dip.get('nome') or '').strip()}".strip() or f"Dipendente #{legacy_id}"

    records = list(
        TrainingEmployeeRecord.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .select_related("corso")
        .order_by("-data_completamento", "-created_at")
    )
    ore_totali = sum((r.ore_frequentate or 0) for r in records)
    oggi = timezone.localdate()
    obblighi = list(
        TrainingDeadline.objects
        .filter(legacy_anagrafica_id=legacy_id, is_required=True)
        .select_related("corso")
        .order_by("data_scadenza")
    )

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = BytesIO()
    doc = make_document(buf, title=f"Libretto formativo — {nominativo}")
    story: list = []

    # Intestazione dipendente
    sub = []
    if dip.get("matricola"):
        sub.append(f"Matricola {dip.get('matricola')}")
    if dip.get("reparto"):
        sub.append(str(dip.get("reparto")))
    if dip.get("mansione"):
        sub.append(str(dip.get("mansione")))
    story.append(Paragraph(nominativo, styles["title"]))
    if sub:
        story.append(Paragraph(" · ".join(sub), styles["subtitle"]))
    story.append(Paragraph(
        f"<b>{len(records)}</b> corsi completati · <b>{ore_totali}</b> ore totali · "
        f"aggiornato al {oggi.strftime('%d-%m-%Y')}",
        styles["body"],
    ))
    story.append(Spacer(1, 5 * mm))

    # Storico completamenti
    story += section_heading("Storico formazione", theme, styles)
    if records:
        head = ["Corso", "Codice", "Data", "Ore", "Esito", "Validità"]
        body = [[Paragraph(h, styles["table_header"]) for h in head]]
        for r in records:
            body.append([
                Paragraph(r.course_title_snapshot or (r.corso.titolo if r.corso else "—"), styles["cell"]),
                Paragraph(r.course_code_snapshot or (r.corso.codice if r.corso else "—"), styles["cell"]),
                Paragraph(r.data_completamento.strftime("%d-%m-%Y") if r.data_completamento else "—", styles["cell"]),
                Paragraph(str(r.ore_frequentate or "—"), styles["cell_right"]),
                Paragraph("Idoneo" if r.idoneo else "Non idoneo", styles["cell"]),
                Paragraph(r.data_scadenza.strftime("%d-%m-%Y") if r.data_scadenza else "—", styles["cell"]),
            ])
        story.append(data_table(body, theme, col_widths=[None, 60, 52, 28, 50, 52], repeat_rows=1))
    else:
        story.append(Paragraph("Nessun completamento registrato.", styles["body"]))
    story.append(Spacer(1, 5 * mm))

    # Obblighi correnti
    story += section_heading("Obblighi formativi correnti", theme, styles)
    if obblighi:
        head = ["Corso", "Scadenza", "Stato"]
        body = [[Paragraph(h, styles["table_header"]) for h in head]]
        for o in obblighi:
            if o.data_scadenza and o.data_scadenza < oggi:
                stato = "Scaduto"
            elif o.data_scadenza and (o.data_scadenza - oggi).days <= 60:
                stato = "In scadenza"
            elif o.data_scadenza:
                stato = "Valido"
            else:
                stato = "Da pianificare"
            body.append([
                Paragraph(o.corso.titolo if o.corso_id else "—", styles["cell"]),
                Paragraph(o.data_scadenza.strftime("%d-%m-%Y") if o.data_scadenza else "—", styles["cell"]),
                Paragraph(stato, styles["cell"]),
            ])
        story.append(data_table(body, theme, col_widths=[None, 70, 80], repeat_rows=1))
    else:
        story.append(Paragraph("Nessun obbligo formativo corrente.", styles["body"]))

    draw = header_footer_callback(theme, title="Libretto formativo", subtitle=nominativo)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()


def archivia_libretto(legacy_id: int, *, user=None):
    """Genera e salva il libretto formativo PDF nel box documenti del dipendente.

    Un solo libretto per dipendente: l'eventuale copia precedente viene
    **sostituita** (è una fotografia aggiornata, non uno storico immutabile).
    Ritorna il :class:`DocumentoDipendente` salvato.
    """
    from anagrafica.models import DocumentoDipendente

    pdf_bytes = build_libretto_pdf_bytes(legacy_id)
    filename = f"Libretto_formativo_{legacy_id}.pdf"

    esistente = (
        DocumentoDipendente.objects
        .filter(oggetto_riferimento_tipo=RIFERIMENTO_LIBRETTO, oggetto_riferimento_id=legacy_id)
        .order_by("-id").first()
    )
    actor = user if (user and getattr(user, "pk", None)) else None
    display = (actor.get_full_name() or actor.username) if actor else "Sistema (auto)"

    if esistente:
        try:
            esistente.file.delete(save=False)
        except Exception:
            logger.warning("Vecchio libretto non eliminabile (doc %s)", esistente.pk, exc_info=True)
        esistente.nome_originale = filename
        esistente.tipo_mime = "application/pdf"
        esistente.dimensione_bytes = len(pdf_bytes)
        esistente.file.save(filename, ContentFile(pdf_bytes), save=False)
        esistente.save()
        return esistente

    doc = DocumentoDipendente(
        legacy_anagrafica_id=legacy_id,
        tipo=DocumentoDipendente.Tipo.ALTRO,
        nome_originale=filename,
        tipo_mime="application/pdf",
        dimensione_bytes=len(pdf_bytes),
        descrizione="Libretto formativo (curriculum) generato dal portale",
        oggetto_riferimento_tipo=RIFERIMENTO_LIBRETTO,
        oggetto_riferimento_id=legacy_id,
        created_by=actor,
        created_by_display=display,
    )
    doc.file.save(filename, ContentFile(pdf_bytes), save=False)
    doc.save()
    return doc


# ---------------------------------------------------------------------------
# Foglio firme (registro presenze cartaceo) come PDF server-side
# ---------------------------------------------------------------------------

def _nomi_map(legacy_ids):
    """Mappa {legacy_id: 'Cognome Nome'} per gli id richiesti (best-effort)."""
    from core.legacy_models import AnagraficaDipendente

    ids = [int(i) for i in dict.fromkeys(legacy_ids) if i]
    if not ids:
        return {}
    out = {}
    try:
        for r in AnagraficaDipendente.objects.filter(id__in=ids).values("id", "cognome", "nome"):
            lid = int(r.get("id") or 0)
            cog = (r.get("cognome") or "").strip()
            nom = (r.get("nome") or "").strip()
            out[lid] = f"{cog} {nom}".strip() or f"Dipendente #{lid}"
    except Exception:
        logger.exception("Errore lettura nomi anagrafica per foglio firme")
    return out


def _foglio_firme_lezione_story(lezione, nomi_map, theme, styles, min_righe=18):
    """Story (lista flowable) del foglio firme di una singola lezione."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from core.pdf import section_heading

    sessione = lezione.sessione
    corso = sessione.corso
    story = []
    story += section_heading(
        f"{corso.titolo} — Lezione {lezione.numero}", theme, styles
    )
    meta = [
        f"<b>Sessione:</b> {sessione.codice_sessione}",
        f"<b>Data:</b> {lezione.data.strftime('%d-%m-%Y') if lezione.data else '—'}",
        f"<b>Orario:</b> {lezione.ora_inizio.strftime('%H:%M') if lezione.ora_inizio else '—'}"
        f"–{lezione.ora_fine.strftime('%H:%M') if lezione.ora_fine else '—'}",
    ]
    docente = (lezione.docente_nome or "").strip() or (sessione.docente_nome or "").strip()
    if docente:
        meta.append(f"<b>Docente:</b> {docente}")
    story.append(Paragraph(" &nbsp;·&nbsp; ".join(meta), styles["body"]))
    if lezione.argomento:
        story.append(Paragraph(f"<b>Argomento:</b> {lezione.argomento}", styles["body"]))
    story.append(Spacer(1, 3 * mm))

    head = ["#", "Cognome e Nome", "Firma ingresso", "Firma uscita"]
    rows = [[Paragraph(h, styles["table_header"]) for h in head]]
    iscritti = list(
        sessione.iscrizioni.values_list("legacy_anagrafica_id", flat=True)
    )
    nominativi = sorted(
        (nomi_map.get(lid, f"#{lid}") for lid in iscritti),
        key=lambda s: s.casefold(),
    )
    n = 0
    for n, nome in enumerate(nominativi, start=1):
        rows.append([str(n), Paragraph(nome, styles["cell"]), "", ""])
    # Righe vuote per partecipanti aggiuntivi.
    for extra in range(n + 1, max(n + 1, min_righe) + 1):
        rows.append([str(extra), "", "", ""])

    tbl = Table(rows, colWidths=[10 * mm, None, 45 * mm, 45 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, theme.c_border()),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), theme.c_primary()),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("TOPPADDING", (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Firma del docente: ______________________________", styles["body"]
    ))
    return story


def build_registri_corso_pdf_bytes(corso) -> bytes:
    """Foglio firme (vuoto, da compilare) di **tutte le lezioni** del corso.

    Una pagina per lezione, raggruppate per sessione, con l'elenco degli iscritti
    già stampato e le colonne firma ingresso/uscita da firmare a mano. Veste
    coerente col tema PDF del portale.
    """
    from reportlab.platypus import PageBreak
    from core.pdf import PdfTheme, build_styles, header_footer_callback, make_document
    from anagrafica.models_formazione import TrainingLesson

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = BytesIO()
    doc = make_document(buf, title=f"Fogli firme — {corso.titolo}")

    lezioni = list(
        TrainingLesson.objects
        .filter(sessione__corso=corso)
        .select_related("sessione", "sessione__corso")
        .order_by("sessione__data_inizio", "data", "ora_inizio")
    )
    all_ids = []
    for lz in lezioni:
        all_ids += list(lz.sessione.iscrizioni.values_list("legacy_anagrafica_id", flat=True))
    nomi_map = _nomi_map(all_ids)

    story = []
    if not lezioni:
        from reportlab.platypus import Paragraph
        story.append(Paragraph("Nessuna lezione pianificata per questo corso.", styles["body"]))
    for idx, lz in enumerate(lezioni):
        story += _foglio_firme_lezione_story(lz, nomi_map, theme, styles)
        if idx < len(lezioni) - 1:
            story.append(PageBreak())

    draw = header_footer_callback(theme, title="Foglio firme", subtitle=corso.titolo)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Cartella «Attestati formazione» (scheletro uguale per tutti i dipendenti)
# ---------------------------------------------------------------------------

def get_or_create_cartella_attestati(cfg=None):
    """Ritorna la cartella documenti destinata agli attestati.

    Se ``cfg.cartella_attestati`` è impostata la usa; altrimenti crea/riusa la
    cartella predefinita «Attestati formazione» (uguale per tutti i dipendenti).
    """
    from anagrafica.models import CartellaDocumentoDipendente
    from anagrafica.models_formazione import AttestatoFormazioneConfig

    if cfg is None:
        cfg = AttestatoFormazioneConfig.get_instance()
    if cfg.cartella_attestati_id:
        return cfg.cartella_attestati

    cartella, _ = CartellaDocumentoDipendente.objects.get_or_create(
        nome=AttestatoFormazioneConfig.CARTELLA_ATTESTATI_NOME,
        defaults={
            "descrizione": "Attestati di formazione archiviati automaticamente a fine corso.",
            "ordine": 50,
            "attiva": True,
        },
    )
    return cartella


# ---------------------------------------------------------------------------
# Archiviazione nel box documenti
# ---------------------------------------------------------------------------

def _documento_esistente(record):
    from anagrafica.models import DocumentoDipendente
    return (
        DocumentoDipendente.objects
        .filter(oggetto_riferimento_tipo=RIFERIMENTO_TIPO, oggetto_riferimento_id=record.pk)
        .order_by("-id")
        .first()
    )


def archivia_attestato(record, *, cfg=None, user=None, force=None):
    """Genera e salva l'attestato PDF nel box documenti del dipendente.

    Idempotente: se esiste già un documento per questo completamento ritorna
    quello senza rigenerare, a meno che ``force`` (o ``cfg.rigenera_se_esiste``)
    non sia ``True`` — in quel caso il documento precedente viene sostituito.

    Fail-safe per il chiamante: solleva eccezione solo se il PDF non si genera;
    chi lo invoca nei flussi di completamento deve avvolgerlo in try/except.
    Ritorna il :class:`DocumentoDipendente` salvato (o quello esistente).
    """
    from anagrafica.models import DocumentoDipendente
    from anagrafica.models_formazione import AttestatoFormazioneConfig

    if cfg is None:
        cfg = AttestatoFormazioneConfig.get_instance()
    if force is None:
        force = bool(cfg.rigenera_se_esiste)

    esistente = _documento_esistente(record)
    if esistente and not force:
        return esistente

    pdf_bytes = build_attestato_pdf_bytes(record, cfg)
    ctx = None  # numero per il nome file
    try:
        ctx = build_attestato_context(record, cfg)
        numero = ctx["numero_display"]
    except Exception:
        numero = f"FORM-{record.pk:05d}"
    filename = f"Attestato_{numero}.pdf".replace("/", "-").replace(" ", "_")

    cartella = get_or_create_cartella_attestati(cfg)

    if esistente and force:
        # Sostituisce il contenuto, conservando lo stesso record (storia/retention).
        try:
            esistente.file.delete(save=False)
        except Exception:
            logger.warning("Vecchio file attestato non eliminabile (record %s)", record.pk, exc_info=True)
        esistente.cartella = cartella
        esistente.nome_originale = filename
        esistente.tipo_mime = "application/pdf"
        esistente.dimensione_bytes = len(pdf_bytes)
        esistente.file.save(filename, ContentFile(pdf_bytes), save=False)
        esistente.save()
        return esistente

    doc = DocumentoDipendente(
        legacy_anagrafica_id=record.legacy_anagrafica_id,
        tipo=DocumentoDipendente.Tipo.CERTIFICATO_FORMAZIONE,
        cartella=cartella,
        nome_originale=filename,
        tipo_mime="application/pdf",
        dimensione_bytes=len(pdf_bytes),
        descrizione=f"Attestato generato automaticamente — {(ctx or {}).get('attestato_tipo', 'formazione')}",
        oggetto_riferimento_tipo=RIFERIMENTO_TIPO,
        oggetto_riferimento_id=record.pk,
        created_by=user if (user and getattr(user, "pk", None)) else None,
        created_by_display=(user.get_full_name() or user.username) if (user and getattr(user, "pk", None)) else "Sistema (auto)",
    )
    doc.file.save(filename, ContentFile(pdf_bytes), save=False)
    doc.save()
    return doc
