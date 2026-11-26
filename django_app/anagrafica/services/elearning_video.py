"""Video delle slide: caricamento a pezzi e compressione in background.

**A pezzi.** Il browser divide il file in pezzi da 8 MB e li manda uno alla volta: nessuna
richiesta supera il tetto di IIS (``maxAllowedContentLength``) e su una connessione lenta un
pezzo fallito si ripete senza ricominciare da capo. I pezzi si accodano in un file temporaneo
dello storage privato; all'ultimo il file viene verificato (MP4 vero, dimensione massima delle
impostazioni e-learning) e diventa una slide video.

**Compressione.** Se sul server c'è ``ffmpeg`` (``FFMPEG_PATH`` nel ``.env`` o nel PATH), un
lavoro in background ricodifica il video in H.264 fino a 1280 px di larghezza, con l'avvio
rapido per lo streaming, e lo sostituisce solo se il risultato è più piccolo. Senza ffmpeg il
video resta com'è: niente si rompe.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

PEZZO_MAX_BYTES = 9 * 1024 * 1024  # il browser manda 8 MB; margine per l'overhead
_RE_ID = re.compile(r"^[a-f0-9]{16,64}$")


class VideoError(Exception):
    pass


def cartella_pezzi() -> Path:
    base = Path(getattr(settings, "ANAGRAFICA_PRIVATE_ROOT", "") or Path(settings.BASE_DIR) / "media_private")
    cartella = base / "upload_pezzi"
    cartella.mkdir(parents=True, exist_ok=True)
    return cartella


def percorso_parziale(user_id: int, upload_id: str) -> Path:
    if not _RE_ID.match(upload_id or ""):
        raise VideoError("Identificativo del caricamento non valido.")
    return cartella_pezzi() / f"{int(user_id)}_{upload_id}.part"


def aggiungi_pezzo(user_id: int, upload_id: str, indice: int, pezzo, max_bytes: int) -> int:
    """Accoda il pezzo ``indice`` (da 0). Ritorna i byte ricevuti finora.

    I pezzi devono arrivare in ordine: un pezzo già ricevuto (ripetuto dopo un errore di rete)
    viene ignorato, uno che salta avanti viene rifiutato."""
    percorso = percorso_parziale(user_id, upload_id)
    if pezzo.size > PEZZO_MAX_BYTES:
        raise VideoError("Pezzo troppo grande.")
    ricevuti = percorso.stat().st_size if percorso.exists() else 0
    attesi = indice * 8 * 1024 * 1024
    if indice == 0 and ricevuti:
        percorso.unlink()
        ricevuti = 0
    elif ricevuti > attesi:
        return ricevuti  # pezzo già ricevuto
    elif ricevuti < attesi:
        raise VideoError("Manca un pezzo precedente: ricarica il file.")
    if ricevuti + pezzo.size > max_bytes:
        percorso.unlink(missing_ok=True)
        raise VideoError(f"Il video supera il limite di {max_bytes // (1024 * 1024)} MB.")
    with open(percorso, "ab") as fh:
        for chunk in pezzo.chunks():
            fh.write(chunk)
    return ricevuti + pezzo.size


def file_completo(user_id: int, upload_id: str, nome: str):
    """Il file ricomposto, come oggetto File di Django (chi lo usa lo chiude e lo cancella)."""
    from django.core.files.uploadedfile import UploadedFile

    percorso = percorso_parziale(user_id, upload_id)
    if not percorso.exists():
        raise VideoError("Caricamento non trovato: ricomincia.")
    fh = open(percorso, "rb")
    return UploadedFile(file=fh, name=Path(nome or "video.mp4").name[:200], content_type="video/mp4",
                        size=percorso.stat().st_size), percorso


def pulisci_vecchi(ore: int = 24) -> int:
    """Cancella i caricamenti a metà più vecchi di ``ore``."""
    import time
    n = 0
    limite = time.time() - ore * 3600
    for f in cartella_pezzi().glob("*.part"):
        try:
            if f.stat().st_mtime < limite:
                f.unlink()
                n += 1
        except OSError:
            pass
    return n


# ── Compressione ────────────────────────────────────────────────────────────

def ffmpeg() -> str | None:
    percorso = (getattr(settings, "FFMPEG_PATH", "") or os.environ.get("FFMPEG_PATH", "")).strip()
    if percorso and Path(percorso).exists():
        return percorso
    return shutil.which("ffmpeg")


def durata_secondi(percorso_file: str) -> int | None:
    exe = ffmpeg()
    if not exe:
        return None
    probe = str(Path(exe).with_name("ffprobe" + Path(exe).suffix))
    if not Path(probe).exists():
        probe = shutil.which("ffprobe") or ""
    if not probe:
        return None
    try:
        out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=noprint_wrappers=1:nokey=1", percorso_file],
                             capture_output=True, text=True, timeout=60, check=False)
        return int(float(out.stdout.strip())) if out.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def accoda_compressione(slide_id: int) -> None:
    from django.db import transaction

    def _accoda():
        try:
            from django_q.tasks import async_task
            async_task("anagrafica.tasks.run_comprimi_video_slide", slide_id, q_options={"timeout": 3600})
        except Exception:
            logger.exception("Compressione video della slide %s non accodata", slide_id)

    transaction.on_commit(_accoda)


def comprimi_slide(slide_id: int) -> dict:
    """Ricodifica il video della slide; lo sostituisce solo se il risultato è più piccolo."""
    from django.core.files import File

    from ..models_formazione import TrainingSlide

    slide = TrainingSlide.objects.filter(pk=slide_id).first()
    if slide is None or not slide.video:
        return {"esito": "nessun_video"}
    exe = ffmpeg()
    with tempfile.TemporaryDirectory(prefix="video_slide_") as tmp:
        sorgente = os.path.join(tmp, "in.mp4")
        with slide.video.open("rb") as src, open(sorgente, "wb") as dst:
            shutil.copyfileobj(src, dst)
        prima = os.path.getsize(sorgente)
        campi = []
        durata = durata_secondi(sorgente)
        if durata:
            slide.video_durata_secondi = durata
            campi.append("video_durata_secondi")
        if not exe:
            if campi:
                slide.save(update_fields=campi)
            return {"esito": "ffmpeg_assente"}
        uscita = os.path.join(tmp, "out.mp4")
        cmd = [exe, "-y", "-i", sorgente, "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", uscita]
        try:
            subprocess.run(cmd, capture_output=True, timeout=3300, check=True)
        except (OSError, subprocess.SubprocessError):
            logger.exception("ffmpeg non è riuscito a comprimere la slide %s", slide_id)
            if campi:
                slide.save(update_fields=campi)
            return {"esito": "errore"}
        dopo = os.path.getsize(uscita) if os.path.exists(uscita) else 0
        slide.video_originale_mb = round(prima / (1024 * 1024), 1)
        campi.append("video_originale_mb")
        if 0 < dopo < prima:
            vecchio = slide.video.name
            with open(uscita, "rb") as fh:
                slide.video.save(Path(vecchio).stem + "_c.mp4", File(fh), save=False)
            slide.video_compresso = True
            campi += ["video", "video_compresso"]
            slide.save(update_fields=campi)
            try:
                slide.video.storage.delete(vecchio)
            except Exception:
                logger.warning("File video originale non cancellato: %s", vecchio)
            return {"esito": "compresso", "prima_mb": round(prima / 1048576, 1), "dopo_mb": round(dopo / 1048576, 1)}
        slide.save(update_fields=campi)
        return {"esito": "non_conveniente"}



# ── Riconoscimento MP4 ──────────────────────────────────────────────────────
# libmagic guarda i primi 2 KB e per alcuni MP4 validi risponde «application/octet-stream»
# (file che iniziano con un box «free»/«wide»/«mdat» prima di «ftyp», o con marche poco note).
MIME_VIDEO_AMMESSI = {"video/mp4", "video/x-m4v", "video/quicktime", "video/3gpp"}
_BOX_NOTI = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot", b"uuid", b"meta", b"moof", b"styp"}


def sembra_mp4(f, *, max_box: int = 12) -> bool:
    """True se il file ha la struttura a box di un MP4/QuickTime (ISO BMFF) con «ftyp» o «moov» fra i
    primi box. Legge solo le intestazioni dei box, saltando il contenuto."""
    import struct

    try:
        f.seek(0, 2)
        totale = f.tell()
        pos = 0
        for _ in range(max_box):
            if pos + 8 > totale:
                return False
            f.seek(pos)
            testa = f.read(16)
            if len(testa) < 8:
                return False
            dim, tipo = struct.unpack(">I4s", testa[:8])
            if tipo not in _BOX_NOTI:
                return False
            if tipo in (b"ftyp", b"moov"):
                return True
            if dim == 1:  # dimensione a 64 bit
                if len(testa) < 16:
                    return False
                dim = struct.unpack(">Q", testa[8:16])[0]
            elif dim == 0:  # il box arriva fino in fondo al file
                return False
            if dim < 8:
                return False
            pos += dim
        return False
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            f.seek(0)
        except Exception:  # noqa: BLE001
            pass


def valida_video(f, max_bytes: int) -> None:
    """Nome, estensione .mp4, dimensione e contenuto. Solleva ``UploadMimeValidationError``."""
    from core.upload_mime import sniff_upload_mime, validate_extension_and_mime

    ammessi = set(MIME_VIDEO_AMMESSI)
    try:
        mime = sniff_upload_mime(f)
    except Exception:  # noqa: BLE001 - ci riprova la validazione completa, che dà il messaggio giusto
        mime = ""
    if mime not in ammessi and sembra_mp4(f):
        ammessi.add(mime)  # libmagic non lo riconosce, ma la struttura è quella di un MP4
    validate_extension_and_mime(f, allowed_extensions={".mp4"}, allowed_mimes=ammessi,
                                max_bytes=max_bytes, label="Video", allow_empty=False)
