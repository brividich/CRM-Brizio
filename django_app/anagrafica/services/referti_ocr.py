"""Da una scansione al testo: rasterizzazione della pagina e OCR.

PERCHÉ NON SI LEGGE E BASTA

I referti arrivano firmati dal lavoratore, quindi passano per forza dallo scanner:
sono PDF di sola immagine, con **zero caratteri** di testo estraibile. Non esiste
una via che eviti l'OCR. Qualche file può avere un layer testo — di solito perché
qualcuno l'ha aperto in un editor che l'ha OCR-izzato per conto suo — e in quel
caso lo si usa, ma come conferma, non come unica fonte.

PERCHÉ SI RASTERIZZA LA PAGINA E NON SI ESTRAGGONO LE IMMAGINI

Un PDF scansionato contiene immagini incorporate, e la scorciatoia ovvia sarebbe
tirarle fuori e darle all'OCR. È stato provato: restituisce spazzatura. Le
scansioni arrivano stratificate (fondo, strisce, ritagli ruotati) e la pagina
esiste solo una volta *composta*. Si rasterizza la pagina.

PERCHÉ QUESTI PARAMETRI E NON I DEFAULT

200 dpi e ``--psm 6`` sono stati misurati, non scelti per convenzione. I default
canonici (300 dpi, ``--psm 3``) sulla stessa pagina producevano una data corrotta
— `241-05-2024` al posto di `21-05-2024` — cioè un referto scartato per una cifra.
E la taratura **non è trasferibile fra rasterizzatori**: lo stesso file, stessi dpi,
reso con poppler o con PyMuPDF, non dà lo stesso OCR. Per questo i valori vivono in
configurazione (:class:`RefertoIntakeConfig`) e non fra le costanti di questo file.

REGOLA DI PRUDENZA

Niente qui solleva per un file illeggibile. Un PDF corrotto, una pagina vuota,
Tesseract assente: tutti restituiscono testo vuoto o un errore dichiarato, e chi
chiama decide. Un modulo di acquisizione che esplode su un file lascia fermo tutto
il lotto, ed è esattamente il guasto che nessuno nota.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

__all__ = [
    "disponibile",
    "percorso_tesseract",
    "conta_pagine",
    "testo_pagina",
    "ErroreLettura",
]


class ErroreLettura(Exception):
    """Il file non si è potuto leggere, con un motivo dicibile a una persona."""


def percorso_tesseract() -> str:
    """Eseguibile di Tesseract: quello configurato, o quello nel PATH.

    Restituisce stringa vuota se non se ne trova nessuno.
    """
    configurato = (getattr(settings, "TESSERACT_CMD", "") or "").strip()
    if configurato:
        return configurato if Path(configurato).exists() else ""
    return shutil.which("tesseract") or ""


def disponibile() -> bool:
    """Tesseract è installato e avviabile?

    Serve alle pagine per dire *perché* i referti restano in revisione, invece di
    lasciare l'utente davanti a una coda che non si smaltisce mai.
    """
    return bool(percorso_tesseract())


def _apri(contenuto: bytes):
    """Documento PyMuPDF dal contenuto, o ``ErroreLettura`` con un motivo."""
    import fitz

    try:
        return fitz.open(stream=bytes(contenuto), filetype="pdf")
    except Exception as exc:
        logger.warning("Referto: PDF non apribile (%s)", exc)
        raise ErroreLettura("Il file non è un PDF leggibile.") from exc


def conta_pagine(contenuto: bytes) -> int:
    """Quante pagine ha la scansione. Zero se il file non si apre."""
    try:
        doc = _apri(contenuto)
    except ErroreLettura:
        return 0
    try:
        return doc.page_count
    finally:
        doc.close()


def _testo_nativo(doc, pagina: int) -> str:
    """Layer testo già presente nel PDF, se c'è.

    Sulle scansioni è vuoto quasi sempre. Quando c'è, di solito è a sua volta il
    prodotto di un OCR fatto altrove: vale come conferma, non come verità.
    """
    try:
        return (doc[pagina].get_text() or "").strip()
    except Exception:
        logger.exception("Referto: layer testo non leggibile (pagina %s)", pagina)
        return ""


def _rasterizza(doc, pagina: int, dpi: int) -> bytes:
    """La pagina composta, in PNG."""
    try:
        return doc[pagina].get_pixmap(dpi=dpi).tobytes("png")
    except Exception as exc:
        logger.exception("Referto: rasterizzazione fallita (pagina %s)", pagina)
        raise ErroreLettura("La pagina non si è potuta rasterizzare.") from exc


def _ambiente() -> dict:
    """Ambiente del processo Tesseract, con i dati lingua se sono altrove.

    Un Tesseract *installato* trova da sé la cartella ``tessdata``. Una copia
    **portable** — quella che si ottiene affiancando la cartella all'eseguibile,
    senza installer e senza diritti di amministratore — può non trovarla, e il
    sintomo è un fallimento secco su ``-l ita`` che non dice niente di utile.
    ``TESSDATA_PREFIX`` toglie di mezzo il dubbio.
    """
    ambiente = dict(os.environ)
    dati = (getattr(settings, "TESSDATA_PREFIX", "") or "").strip()
    if dati:
        ambiente["TESSDATA_PREFIX"] = dati
    return ambiente


def _ocr(png: bytes, *, lingua: str, psm: int, timeout: int) -> str:
    """Testo letto da Tesseract. Stringa vuota se non è disponibile."""
    exe = percorso_tesseract()
    if not exe:
        logger.warning("Referto: Tesseract non disponibile")
        return ""

    # Tesseract vuole file su disco: scrive l'uscita accanto al nome che gli si dà.
    with tempfile.TemporaryDirectory(prefix="referto-ocr-") as tmp:
        cartella = Path(tmp)
        ingresso = cartella / "pagina.png"
        ingresso.write_bytes(png)
        uscita = cartella / "testo"
        try:
            subprocess.run(
                [exe, str(ingresso), str(uscita), "-l", lingua, "--psm", str(psm)],
                check=True, capture_output=True, timeout=timeout, env=_ambiente(),
            )
        except subprocess.TimeoutExpired:
            raise ErroreLettura(
                f"La lettura ha superato {timeout} secondi ed è stata interrotta."
            ) from None
        except subprocess.CalledProcessError as exc:
            dettaglio = (exc.stderr or b"").decode("utf-8", "replace").strip()[:200]
            logger.warning("Referto: Tesseract ha fallito (%s)", dettaglio)
            raise ErroreLettura("Il riconoscimento del testo è fallito su questa pagina.") from exc
        except Exception as exc:
            logger.exception("Referto: Tesseract non avviabile")
            raise ErroreLettura("Il motore di riconoscimento non è avviabile.") from exc

        prodotto = uscita.with_suffix(".txt")
        try:
            return prodotto.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.exception("Referto: uscita di Tesseract non leggibile")
            return ""


def testo_pagina(contenuto: bytes, pagina: int = 0, config=None) -> str:
    """Testo di una pagina: OCR come fonte principale, layer nativo come aggiunta.

    Le due fonti vengono **concatenate** invece che scelte. Non è pigrizia: le
    ancore da cui si estraggono i campi sono ridondanti, e un campo che l'OCR
    sbaglia può essere corretto nel layer nativo (o viceversa). Chi estrae cerca
    tutte le occorrenze e decide per consenso: dargliene di più lo aiuta.

    Solleva :class:`ErroreLettura` solo se non si ricava proprio nulla.
    """
    from ..models_sorveglianza import RefertoIntakeConfig

    config = config or RefertoIntakeConfig.load()
    doc = _apri(contenuto)
    try:
        if pagina < 0 or pagina >= doc.page_count:
            raise ErroreLettura(f"La pagina {pagina + 1} non esiste in questo file.")

        nativo = _testo_nativo(doc, pagina)
        png = _rasterizza(doc, pagina, int(config.ocr_dpi or 200))
    finally:
        doc.close()

    try:
        letto = _ocr(
            png,
            lingua=(config.ocr_lingua or "ita").strip(),
            psm=int(config.ocr_psm or 6),
            timeout=int(config.ocr_timeout_secondi or 30),
        )
    except ErroreLettura:
        # Il riconoscimento è fallito, ma se il PDF aveva già un layer testo quello
        # basta a tentare l'estrazione: meglio una lettura parziale che nessuna.
        if nativo:
            logger.info("Referto: OCR fallito, si procede col solo layer testo")
            return nativo
        raise

    if not letto.strip() and not nativo:
        raise ErroreLettura(
            "Nessun testo riconosciuto: la scansione potrebbe essere vuota, "
            "troppo sbiadita o storta."
            if disponibile() else
            "Riconoscimento del testo non disponibile: Tesseract non è installato "
            "su questo server."
        )

    return "\n".join(p for p in (letto, nativo) if p.strip())
