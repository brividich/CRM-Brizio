"""Lettura di codici QR e codici a barre da documenti scansionati.

Sta in `core` e non nella formazione di proposito: il primo cliente è il rientro
dei fogli firme, ma il meccanismo — *stampo un documento con un codice, il
documento torna indietro scansionato, il portale riconosce da solo di quale
documento si tratta* — non ha niente di specifico. Vale identico per una scheda
di sicurezza controfirmata, un verbale, una checklist di reparto.

Il modulo espone due funzioni e una domanda:

* :func:`disponibile` — la libreria di decodifica è installata?
* :func:`leggi_codici` — tutti i codici trovati, in ordine di lettura;
* :func:`leggi_codice` — il primo che soddisfa un criterio, o ``None``.

**Non solleva mai per un file illeggibile.** Un documento senza codice, storto,
sbiadito o corrotto restituisce una lista vuota: chi chiama deve avere sempre
una strada alternativa (tipicamente: farsi digitare il codice stampato in
chiaro). Un lettore di codici è una comodità, non un requisito.
"""
from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)

__all__ = ["disponibile", "leggi_codici", "leggi_codice"]

# Risoluzione di rasterizzazione dei PDF. 200 dpi bastano per un QR di 22 mm;
# se non si trova nulla si ritenta più fini (vedi `_pagine`).
DPI_PRIMO_TENTATIVO = 200
DPI_SECONDO_TENTATIVO = 300


def disponibile() -> bool:
    """La libreria di decodifica è installata e importabile?

    Serve alle pagine per dire all'utente *perché* il campo del codice è
    obbligatorio, invece di lasciarlo davanti a un lettore che tace.
    """
    return _zxing() is not None


def _zxing():
    """Modulo di decodifica, o ``None`` se manca.

    L'import è dentro la funzione perché il portale deve avviarsi anche dove la
    libreria non è ancora stata installata — un ambiente aggiornato a metà non
    può tirare giù il sito.
    """
    try:
        import zxingcpp
    except Exception:  # pragma: no cover - dipende dall'ambiente
        return None
    return zxingcpp


def _immagini(sorgente, nome_file: str, dpi: int):
    """Immagini su cui cercare i codici, una per pagina.

    Accetta bytes (PDF o immagine) oppure un'immagine PIL già aperta: chi ha
    già rasterizzato per altri motivi non deve rifarlo.
    """
    from PIL import Image

    if not isinstance(sorgente, (bytes, bytearray)):
        return [sorgente]  # immagine PIL già pronta

    contenuto = bytes(sorgente)
    pare_pdf = contenuto[:5] == b"%PDF" or nome_file.lower().endswith(".pdf")

    if pare_pdf:
        import fitz

        try:
            doc = fitz.open(stream=contenuto, filetype="pdf")
        except Exception:
            logger.warning("QR: PDF non apribile (%s)", nome_file or "senza nome")
            return []
        try:
            fuori = []
            for pagina in doc:
                pix = pagina.get_pixmap(dpi=dpi)
                fuori.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            return fuori
        finally:
            doc.close()

    try:
        img = Image.open(BytesIO(contenuto))
        img.load()
    except Exception:
        logger.warning("QR: file non è immagine né PDF (%s)", nome_file or "senza nome")
        return []
    return [img]


def _decodifica(zxingcpp, img) -> list[str]:
    """Codici leggibili in una singola immagine."""
    try:
        risultati = zxingcpp.read_barcodes(img)
    except Exception:
        # Alcune build vogliono l'immagine in RGB; alcune scansioni arrivano in
        # modi esotici (palette, CMYK, 16 bit).
        try:
            risultati = zxingcpp.read_barcodes(img.convert("RGB"))
        except Exception:
            logger.exception("QR: decodifica fallita sull'immagine")
            return []

    fuori = []
    for r in risultati or []:
        testo = (getattr(r, "text", "") or "").strip()
        if testo:
            fuori.append(testo)
    return fuori


def leggi_codici(sorgente, nome_file: str = "", *, tutte_le_pagine: bool = False) -> list[str]:
    """Codici trovati nel documento, in ordine di lettura.

    `sorgente` è il contenuto del file (PDF o immagine) oppure un'immagine PIL.
    Di default guarda solo la **prima pagina**: un documento con codice ce l'ha
    in testa, e leggere il resto costa tempo e confonde con codici estranei.

    Restituisce lista vuota — mai un'eccezione — se non trova niente, se il file
    è illeggibile o se la libreria non è installata.
    """
    zxingcpp = _zxing()
    if zxingcpp is None:
        logger.info("QR: libreria di decodifica non installata, lettura codici saltata")
        return []

    for dpi in (DPI_PRIMO_TENTATIVO, DPI_SECONDO_TENTATIVO):
        immagini = _immagini(sorgente, nome_file, dpi)
        if not immagini:
            return []
        if not tutte_le_pagine:
            immagini = immagini[:1]

        trovati: list[str] = []
        for img in immagini:
            trovati.extend(_decodifica(zxingcpp, img))
        if trovati:
            return trovati

        # Il secondo giro ha senso solo se stiamo rasterizzando noi: su
        # un'immagine già pronta o su un PIL passato dal chiamante rifare a dpi
        # diverso non cambia un pixel.
        if not isinstance(sorgente, (bytes, bytearray)):
            break
        if not (bytes(sorgente)[:5] == b"%PDF" or nome_file.lower().endswith(".pdf")):
            break

    return []


def leggi_codice(sorgente, nome_file: str = "", *, prefisso: str = "", tutte_le_pagine: bool = False):
    """Primo codice che comincia per `prefisso`, o ``None``.

    Il prefisso è il modo di non confondersi quando nella pagina finisce anche
    un codice di qualcun altro — l'etichetta di un fornitore, un timbro postale.
    """
    for testo in leggi_codici(sorgente, nome_file, tutte_le_pagine=tutte_le_pagine):
        if not prefisso or testo.upper().startswith(prefisso.upper()):
            return testo
    return None
