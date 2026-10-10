"""Importazione slide da PowerPoint/PDF per i micro-corsi e-learning.

Pipeline (Windows/IIS-friendly):
  - **.pptx/.ppt** -> PDF con **LibreOffice headless** (`soffice --headless --convert-to pdf`)
    -> una **PNG per pagina** con **PyMuPDF** (wheel pip, nessuna dipendenza di sistema).
  - **.pdf** -> direttamente una PNG per pagina con PyMuPDF (nessun bisogno di LibreOffice).

Ogni pagina diventa una :class:`TrainingSlide` di tipo immagine, accodata alle slide
esistenti del corso. Tutto in storage privato fuori webroot; servite dalla view
protetta ``formazione_slide_image``.

LibreOffice è richiesto **solo** per i file PowerPoint. Path risolto da
``settings.LIBREOFFICE_PATH`` / env ``LIBREOFFICE_PATH`` o auto-detect nei percorsi
standard di Windows; se assente, l'import .pptx fallisce con un messaggio chiaro
(si può comunque caricare un PDF).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

# Tipi accettati
PPTX_EXTS = {".pptx", ".ppt", ".odp"}
PDF_EXTS = {".pdf"}
ALLOWED_EXTS = PPTX_EXTS | PDF_EXTS

# Limiti di sicurezza
MAX_PAGES = 80
RENDER_ZOOM = 2.0  # ~144 dpi: buon compromesso leggibilità/peso


class ImportError_(Exception):
    """Errore d'importazione con messaggio adatto all'utente."""


def find_libreoffice() -> str | None:
    """Risolve l'eseguibile LibreOffice (soffice). None se non trovato.

    Ordine: Impostazioni e-learning (DB) → settings.LIBREOFFICE_PATH / env → percorsi
    standard Windows/Linux."""
    try:
        from ..models_formazione import ElearningConfig
        db_path = (ElearningConfig.get_instance().libreoffice_path or "").strip()
    except Exception:
        db_path = ""
    cand = db_path or getattr(settings, "LIBREOFFICE_PATH", "") or os.environ.get("LIBREOFFICE_PATH", "")
    if cand and Path(cand).exists():
        return cand
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for p in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
    ):
        if Path(p).exists():
            return p
    return None


def _convert_pptx_to_pdf(src_path: str, out_dir: str) -> str:
    """Converte un file PowerPoint in PDF con LibreOffice headless. Ritorna il path del PDF."""
    soffice = find_libreoffice()
    if not soffice:
        raise ImportError_(
            "Conversione PowerPoint non disponibile: LibreOffice non è installato sul server. "
            "Carica un file PDF, oppure chiedi all'IT di installare LibreOffice."
        )
    # Profilo utente isolato: evita conflitti con istanze LibreOffice concorrenti.
    user_inst = Path(out_dir) / "lo_profile"
    cmd = [
        soffice, "--headless", "--norestore", "--nolockcheck",
        f"-env:UserInstallation=file:///{str(user_inst).replace(os.sep, '/')}",
        "--convert-to", "pdf", "--outdir", out_dir, src_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise ImportError_("Conversione PowerPoint scaduta (file troppo grande o LibreOffice bloccato).")
    except subprocess.CalledProcessError as e:
        logger.error("LibreOffice convert fallita: %s", e.stderr.decode("utf-8", "ignore")[:500])
        raise ImportError_("Conversione PowerPoint fallita. Verifica il file o caricalo come PDF.")
    pdf_path = Path(out_dir) / (Path(src_path).stem + ".pdf")
    if not pdf_path.exists():
        raise ImportError_("Conversione PowerPoint non riuscita (PDF non generato).")
    return str(pdf_path)


def _pdf_to_png_list(pdf_path: str) -> list[bytes]:
    """Rende ogni pagina del PDF in PNG (bytes) con PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError_("Libreria di rendering PDF (PyMuPDF) non installata sul server.")
    out: list[bytes] = []
    # Aperto dalla memoria: un PDF rotto non lascia il file bloccato (Windows non
    # riuscirebbe più a cancellare la cartella temporanea).
    with open(pdf_path, "rb") as fh:
        dati = fh.read()
    try:
        doc = fitz.open(stream=dati, filetype="pdf")
    except Exception as exc:
        raise ImportError_("Il file non è un PDF leggibile.") from exc
    with doc:
        n = doc.page_count
        if n == 0:
            raise ImportError_("Il documento non contiene pagine.")
        if n > MAX_PAGES:
            raise ImportError_(f"Troppe pagine ({n}). Massimo consentito: {MAX_PAGES}.")
        matrix = fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out.append(pix.tobytes("png"))
    return out


def importa_slides_da_file(corso, uploaded_file, user=None) -> int:
    """Converte il file caricato (.pptx/.ppt/.odp/.pdf) in slide-immagine del corso.

    Ritorna il numero di slide create. Le slide vengono accodate dopo quelle esistenti.
    Solleva ``ImportError_`` con un messaggio utente in caso di problemi.
    """
    from django.db import transaction
    from ..models_formazione import TrainingSlide

    name = (getattr(uploaded_file, "name", "") or "").strip()
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ImportError_(f"Formato non supportato ({ext or 'sconosciuto'}). Carica PPTX, PPT, ODP o PDF.")

    with tempfile.TemporaryDirectory(prefix="elearning_import_") as tmp:
        src_path = os.path.join(tmp, "src" + ext)
        with open(src_path, "wb") as fh:
            for chunk in uploaded_file.chunks():
                fh.write(chunk)

        pdf_path = src_path if ext in PDF_EXTS else _convert_pptx_to_pdf(src_path, tmp)
        png_list = _pdf_to_png_list(pdf_path)

    base_stem = (Path(name).stem or "Slide")[:120]
    last = corso.slides.order_by("-ordine").values_list("ordine", flat=True).first() or 0

    created = 0
    with transaction.atomic():
        for i, png in enumerate(png_list, start=1):
            slide = TrainingSlide(
                corso=corso,
                ordine=last + i,
                titolo=f"{base_stem} — {i}",
                is_active=True,
                created_by=user,
            )
            slide.immagine.save(f"slide_{last + i}.png", ContentFile(png), save=False)
            slide.save()
            created += 1
    return created


# ---------------------------------------------------------------------------
# Import in background (prompt 05, fase 2)
# ---------------------------------------------------------------------------

def accoda_import(corso, uploaded_file, user=None):
    """Salva il file, crea il lavoro e lo accoda a django-q dopo il commit."""
    from django.db import transaction
    from ..models_elearning import TrainingElearningImport

    ext = Path(getattr(uploaded_file, "name", "") or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ImportError_(f"Formato non supportato ({ext or 'sconosciuto'}). Carica PPTX, PPT, ODP o PDF.")
    job = TrainingElearningImport(corso=corso, nome_file=Path(uploaded_file.name).name[:255],
                                  creato_da=user if getattr(user, "is_authenticated", False) else None)
    job.file.save(f"import_{corso.pk}{ext}", uploaded_file, save=False)
    job.save()

    def _accoda():
        try:
            from django_q.tasks import async_task
            async_task("anagrafica.tasks.run_elearning_import", job.pk, q_options={"timeout": 900})
        except Exception:
            logger.exception("Import slide %s non accodato", job.pk)
            type(job).objects.filter(pk=job.pk).update(
                stato=type(job).ERRORE, errore="Servizio di elaborazione non raggiungibile: riprova più tardi.")

    transaction.on_commit(_accoda)
    return job


def esegui_import(job_id: int) -> dict:
    """Corpo del lavoro. Idempotente: un lavoro già preso in carico non riparte."""
    from django.db import transaction
    from django.utils import timezone
    from ..models_elearning import TrainingElearningImport

    with transaction.atomic():
        job = TrainingElearningImport.objects.select_for_update().select_related("corso").filter(pk=job_id).first()
        if job is None or job.stato != TrainingElearningImport.IN_CODA:
            return {"ok": False, "motivo": "non_in_coda"}
        job.stato, job.avviato_il = TrainingElearningImport.IN_CORSO, timezone.now()
        job.save(update_fields=["stato", "avviato_il"])
    try:
        from django.core.files import File
        percorso = job.file.name
        with job.file.open("rb") as grezzo:
            # Copia con il nome originale (estensione e titoli delle slide): il nome
            # del FieldFile è il percorso nello storage e non va toccato.
            n = importa_slides_da_file(job.corso, File(grezzo, name=job.nome_file), user=job.creato_da)
        job.file.name = percorso
        job.stato, job.n_slide, job.errore = TrainingElearningImport.COMPLETATO, n, ""
    except ImportError_ as exc:
        job.stato, job.errore = TrainingElearningImport.ERRORE, str(exc)[:500]
    except Exception:
        logger.exception("Import slide %s fallito", job_id)
        job.stato, job.errore = TrainingElearningImport.ERRORE, "Errore imprevisto nella conversione."
    job.finito_il = timezone.now()
    job.save(update_fields=["stato", "n_slide", "errore", "finito_il"])
    try:
        job.file.delete(save=False)
        TrainingElearningImport.objects.filter(pk=job.pk).update(file="")
    except Exception:
        logger.warning("File di import %s non cancellato", job_id, exc_info=True)
    if job.stato == TrainingElearningImport.COMPLETATO and job.n_slide:
        try:
            from .elearning_versioni import registra
            registra(job.corso, user=job.creato_da, motivo=f"Importate {job.n_slide} slide")
        except Exception:
            logger.exception("Versione non aggiornata dopo l'import %s", job_id)
    return {"ok": job.stato == TrainingElearningImport.COMPLETATO, "slide": job.n_slide}
