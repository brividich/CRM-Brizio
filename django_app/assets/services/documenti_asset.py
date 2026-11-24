"""Operazioni sui documenti di un asset: scadenza, spostamento tra cartelle, ZIP."""
from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from pathlib import Path

#: Un documento è «in scadenza» da questi giorni prima della data di scadenza.
GIORNI_PREAVVISO = 30


def stato_scadenza(scadenza: date | None, oggi: date | None = None) -> str:
    """``scaduto`` / ``in_scadenza`` / ``valido`` / '' (senza data)."""
    if not scadenza:
        return ""
    from django.utils import timezone

    oggi = oggi or timezone.localdate()
    if scadenza < oggi:
        return "scaduto"
    if scadenza <= oggi + timedelta(days=GIORNI_PREAVVISO):
        return "in_scadenza"
    return "valido"


def sposta(asset, document_ids, destinazione: str) -> int:
    """Sposta i documenti dell'asset nella cartella ``destinazione`` (slug). Il file
    resta dov'è: cambia solo la cartella in cui compare. Ritorna quanti ne ha spostati."""
    ids = [int(i) for i in document_ids if str(i).isdigit()]
    if not ids or not destinazione:
        return 0
    return asset.documents.filter(id__in=ids).exclude(category=destinazione).update(category=destinazione)


def zip_cartella(asset, slug: str) -> tuple[bytes, int]:
    """ZIP dei file della cartella, con le sottocartelle caricate. Ritorna (byte, numero file)."""
    buffer = io.BytesIO()
    usati: set[str] = set()
    contati = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archivio:
        for doc in asset.documents.filter(category=slug).order_by("relative_folder", "original_name", "id"):
            nome = doc.original_name or Path(doc.file.name).name
            cartella = (doc.relative_folder or "").strip("/").replace("\\", "/")
            percorso = f"{cartella}/{nome}" if cartella else nome
            base, punto, est = percorso.rpartition(".")
            candidato, n = percorso, 2
            while candidato.lower() in usati:
                candidato = f"{base} ({n}).{est}" if punto else f"{percorso} ({n})"
                n += 1
            usati.add(candidato.lower())
            try:
                with doc.file.open("rb") as f:
                    archivio.writestr(candidato, f.read())
                contati += 1
            except (FileNotFoundError, OSError, ValueError):
                continue
    return buffer.getvalue(), contati


def stato_sds_per_prodotti(prodotto_ids) -> dict[int, dict]:
    """Stato della scheda di sicurezza per prodotto, come nelle Schede di sicurezza:
    ``{"codice": "ok"|"da_rivedere"|"mancante", "etichetta": ...}``. Stessa regola
    dei 36 mesi (``SchedaSicurezza.q_da_rivedere``)."""
    ids = {int(i) for i in prodotto_ids if i}
    if not ids:
        return {}
    from schede_sicurezza.models import SchedaSicurezza

    correnti = SchedaSicurezza.objects.filter(prodotto_id__in=ids, is_corrente=True)
    con_scheda = set(correnti.values_list("prodotto_id", flat=True))
    da_rivedere = set(correnti.filter(SchedaSicurezza.q_da_rivedere()).values_list("prodotto_id", flat=True))
    out = {}
    for pid in ids:
        if pid not in con_scheda:
            out[pid] = {"codice": "mancante", "etichetta": "SDS mancante"}
        elif pid in da_rivedere:
            out[pid] = {"codice": "da_rivedere", "etichetta": "SDS da rivedere"}
        else:
            out[pid] = {"codice": "ok", "etichetta": "SDS aggiornata"}
    return out
