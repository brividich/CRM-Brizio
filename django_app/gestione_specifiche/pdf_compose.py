"""Toolkit PDF offline per il workflow MOD.133 (composizione + protezione).

Funzioni **pure su bytes**: non toccano mai il PDF originale su disco, lavorano su copie
in memoria e ritornano i byte del risultato. Pensate per essere richiamate dalla pipeline
di composizione del composito protetto (cover / pagina MOD.133 compilata -> PDF base) senza
dipendere da settings o da percorsi: l'owner-password si passa come parametro, NON si legge
qui dai settings (vedi wiring_needed).

Backend: PyMuPDF/fitz (>=1.24, verificato su 1.27.2.3). Nessun accesso a rete o disco:
i PDF entrano ed escono come `bytes`.

Contratto delle funzioni pubbliche:
- anteponi_pagine(base_pdf, pagine)      -> antepone una o piu' pagine al PDF base.
- sostituisci_prima_pagina(base_pdf, x)  -> sostituisce la 1a pagina del PDF base.
- applica_protezione(pdf, ...)           -> cifra (owner-pw) con permessi coerenti ai flag
                                            + eventuale filigrana su ogni pagina.
"""
from __future__ import annotations

import fitz  # PyMuPDF


def _apri(pdf: bytes, nome: str = "PDF") -> "fitz.Document":
    """Apre un PDF da bytes con errori ESPLICITI (invece degli errori fitz criptici).

    Rifiuta stream vuoti e PDF senza pagine con un ``ValueError`` chiaro, cosi' il
    chiamante (pipeline di composizione) puo' gestire il caso invece di ricevere
    un crash oscuro a valle.
    """
    if not pdf:
        raise ValueError("%s vuoto o non valido (stream vuoto)." % nome)
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise ValueError("%s non apribile: %s" % (nome, exc)) from exc
    if doc.page_count == 0:
        doc.close()
        raise ValueError("%s senza pagine." % nome)
    return doc


def anteponi_pagine(base_pdf: bytes, pagine: list[bytes]) -> bytes:
    """Antepone al PDF `base_pdf` una o piu' pagine (cover e/o MOD.133) e ritorna il composito.

    Le `pagine` sono una lista di PDF (bytes); ogni loro pagina viene inserita, nell'ordine
    della lista, PRIMA delle pagine di `base_pdf`. Non modifica gli input.
    """
    out = fitz.open()
    try:
        for pg in pagine or []:
            src = _apri(pg, "pagina da anteporre")
            try:
                out.insert_pdf(src)
            finally:
                src.close()
        base = _apri(base_pdf, "PDF base")
        try:
            out.insert_pdf(base)
        finally:
            base.close()
        return out.tobytes()
    finally:
        out.close()


def sostituisci_prima_pagina(base_pdf: bytes, nuova_prima: bytes) -> bytes:
    """Sostituisce la 1a pagina di `base_pdf` con le pagine di `nuova_prima`.

    Milestone: cover d'attesa -> pagina MOD.133 compilata. Le pagine di `nuova_prima`
    (tipicamente una) prendono il posto della prima pagina; le pagine successive del base
    (dalla 2a in poi) vengono conservate in coda. Non modifica gli input.
    """
    out = fitz.open()
    try:
        nuova = _apri(nuova_prima, "nuova prima pagina")
        try:
            out.insert_pdf(nuova)
        finally:
            nuova.close()
        base = _apri(base_pdf, "PDF base")
        try:
            if base.page_count > 1:
                out.insert_pdf(base, from_page=1, to_page=base.page_count - 1)
        finally:
            base.close()
        return out.tobytes()
    finally:
        out.close()


def _applica_filigrana(page: "fitz.Page", testo: str) -> None:
    """Sovrimprime `testo` in diagonale (grigio chiaro, semitrasparente) su una pagina.

    Usa TextWriter con morph (rotazione 45 gradi) perche' insert_textbox ammette solo
    rotate 0/90/180/270. Overlay sopra il contenuto esistente.
    """
    rect = page.rect
    tw = fitz.TextWriter(rect, opacity=0.20, color=(0.6, 0.6, 0.6))
    fontsize = 44
    punto = fitz.Point(rect.width * 0.18, rect.height * 0.58)
    tw.append(punto, testo, fontsize=fontsize)
    pivot = fitz.Point(rect.width / 2.0, rect.height / 2.0)
    mat = fitz.Matrix(45)
    tw.write_text(page, morph=(pivot, mat), overlay=1)


def applica_filigrana(pdf: bytes, testo: str) -> bytes:
    """Sovrimprime `testo` in filigrana su OGNI pagina SENZA cifrare. Ritorna i byte.

    Utile per le anteprime (mostra la filigrana della forma "in attesa" senza applicare la
    protezione owner-password, che nel composito depositato viene aggiunta da ``applica_protezione``).
    Best-effort per pagina: un errore su una pagina non azzera la filigrana sulle altre.
    """
    if not testo:
        return pdf
    doc = _apri(pdf)
    try:
        for page in doc:
            try:
                _applica_filigrana(page, testo)
            except Exception:  # noqa: BLE001
                continue
        return doc.tobytes()
    finally:
        doc.close()


def applica_protezione(
    pdf: bytes,
    *,
    owner_password: str,
    consenti_stampa: bool = False,
    consenti_modifica: bool = False,
    consenti_copia: bool = False,
    filigrana: str | None = None,
) -> bytes:
    """Cifra il PDF con OWNER password e USER password VUOTA (si apre senza password).

    I bit di permesso sono impostati in coerenza coi flag: di default nega stampa e modifica
    (composito protetto). Accessibilita', annotazioni e compilazione form restano sempre
    concesse. Se `filigrana` e' valorizzata, sovrimprime quel testo su OGNI pagina; se il
    watermark fallisce degrada con grazia (il PDF viene comunque cifrato).

    Non modifica l'input: lavora su una copia in memoria.
    """
    doc = _apri(pdf)
    try:
        perm = int(
            fitz.PDF_PERM_ACCESSIBILITY
            | fitz.PDF_PERM_ANNOTATE
            | fitz.PDF_PERM_FORM
        )
        if consenti_stampa:
            perm |= int(fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ)
        if consenti_modifica:
            perm |= int(fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ASSEMBLE)
        if consenti_copia:
            perm |= int(fitz.PDF_PERM_COPY)

        if filigrana:
            # Best-effort PER PAGINA: un errore su una pagina non azzera la filigrana
            # sulle altre (la cifratura resta comunque garantita).
            for page in doc:
                try:
                    _applica_filigrana(page, filigrana)
                except Exception:  # noqa: BLE001
                    continue

        return doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw=owner_password,
            user_pw="",
            permissions=perm,
        )
    finally:
        doc.close()
