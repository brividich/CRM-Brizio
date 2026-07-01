"""F2 - Deposito di una nuova revisione PDF sulla share master (dry-run / rollback / audit).

Scrive SOLO dentro le radici consentite (allowlist di ``share_link``) e MAI dentro una
cartella esclusa (``_SUPERATO``) come destinazione *attiva*. Le revisioni superate vengono
**SPOSTATE** (mai cancellate) in ``_SUPERATO``, preservando la sottostruttura relativa e con
suffisso anti-collisione. L'aggiornamento del collegamento usa ``update()`` (niente FSM/auto_now).

Modello operativo (tutto passa da qui, il comando/UI e' solo un guscio):

1. ``pianifica(...)``  -> calcola il PIANO senza toccare nulla (dry-run): path canonico della
   nuova revisione, file superato da spostare e dove, eventuale collisione al target.
2. ``esegui(..., apply=True)`` -> esegue il piano con **rollback** completo: se un passo fallisce,
   annulla i precedenti (rimette i file spostati, cancella il nuovo scritto, non tocca il DB) e
   ritorna esito ``errore`` (mai lasciare la share in stato incoerente).

Politica collisione al path canonico (deciso con l'utente):
- file **identico** gia' presente (stesso hash) -> ``identico`` (no-op idempotente);
- file **diverso** -> ``collisione`` (rifiuto) salvo ``forza``, che archivia l'esistente in
  ``_SUPERATO`` e scrive il nuovo. Mai overwrite silenzioso, mai delete.
"""
from __future__ import annotations

import hashlib
import logging
import ntpath
import os
import re
import shutil
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from .models import EventoSpecifica, Specifica
from .share_link import (
    _real_nc,
    _segmenti_esclusi,
    radici_consentite,
    risolvi_consentito,
)

logger = logging.getLogger(__name__)

_CARATTERI_ILLEGALI = '<>:"/\\|?*'
_TRIGGER_AUDIT = "deposito_revisione_share"


# ---------------------------------------------------------------------------
# Naming canonico
# ---------------------------------------------------------------------------
def _sanitizza_nome(s: str) -> str:
    """Segmento di nome file Windows sicuro: niente caratteri illegali ne' spazio/punto finale."""
    pulito = "".join("_" if c in _CARATTERI_ILLEGALI else c for c in str(s or ""))
    return pulito.rstrip(" .")


def nome_canonico(codice: str, revisione: str) -> str:
    """``<codice> REV.<rev>.pdf`` (convenzione share); senza revisione -> ``<codice>.pdf``."""
    cod = _sanitizza_nome(codice)
    rev = _sanitizza_nome(revisione)
    return f"{cod} REV.{rev}.pdf" if rev else f"{cod}.pdf"


# Suffisso di revisione in coda a un nome file (varianti reali: "REV.0", "REV. 02", "REV.A1",
# "_REV.B", ".REV.C"). Ancorato a fine stringa: NON tocca eventuali "REV" interni al nome.
_REV_RE = re.compile(r"(?i)[\s._-]*REV\.?\s*[A-Za-z0-9][A-Za-z0-9\-]*\s*$")


def _stem_documento(nome_file: str) -> str:
    """Estrae il "numero documento" (il NOME che deve restare invariato) da un nome file.

    Rimuove estensione e suffisso di revisione: ``15500 REV.0.pdf`` -> ``15500``,
    ``DMH 00-04.002 REV. 02.pdf`` -> ``DMH 00-04.002``. Il nome documento e' la parte che
    NON cambia tra una revisione e l'altra (la rev e' input umano, imprevedibile).
    """
    base = re.sub(r"(?i)\.pdf$", "", str(nome_file or "")).rstrip()
    stem = _REV_RE.sub("", base).rstrip(" .-_")
    return stem or base


def nome_nuova_revisione(base_documento: str, revisione: str) -> str:
    """``<base_documento> REV.<rev>.pdf`` con la rev VERBATIM (mai auto-incrementata).

    Il ``base_documento`` (numero documento) resta invariato; cambia solo la rev, che e'
    quella inserita dall'umano. Senza rev -> ``<base_documento>.pdf``.
    """
    base = _sanitizza_nome(base_documento)
    rev = _sanitizza_nome(revisione)
    return f"{base} REV.{rev}.pdf" if rev else f"{base}.pdf"


def _assicura_pdf(nome: str) -> str:
    """Nome file sicuro (segmento singolo) con estensione .pdf garantita (per l'override --nome)."""
    n = _sanitizza_nome(nome)  # sostituisce anche separatori di path -> niente traversal
    if not n.lower().endswith(".pdf"):
        n = n + ".pdf"
    return n


# ---------------------------------------------------------------------------
# Geometria share (radici / esclusioni / relativi)
# ---------------------------------------------------------------------------
def _contenuto(child_nc: str, root_nc: str) -> bool:
    try:
        return os.path.commonpath([child_nc, root_nc]) == root_nc
    except ValueError:  # drive/share diversi
        return False


def _radice_reale_di(path: str):
    """Ritorna il realpath (case-preserved) della radice consentita che contiene ``path``, o None."""
    pn = _real_nc(path)
    if not pn:
        return None
    for root in radici_consentite():
        rn = _real_nc(root)
        if rn and _contenuto(pn, rn):
            return os.path.realpath(root)
    return None


def _segmenti_rel(path_reale: str, root_reale: str) -> list[str]:
    """Segmenti di ``path_reale`` relativi a ``root_reale`` (case-preserved)."""
    rel = os.path.relpath(path_reale, root_reale)
    if rel in (".", ""):
        return []
    return [s for s in rel.replace("/", os.sep).split(os.sep) if s and s != "."]


def _in_cartella_esclusa(path: str) -> bool:
    """True se un segmento (relativo a una radice) e' tra gli esclusi (``_SUPERATO``)."""
    esclusi = _segmenti_esclusi()
    if not esclusi:
        return False
    root = _radice_reale_di(path)
    if root is None:
        return False
    return any(s.lower() in esclusi for s in _segmenti_rel(os.path.realpath(path), root))


def _nome_cartella_superato() -> str:
    """Nome (case-preservato) della cartella d'archivio, dal primo valore di SHARE_EXCLUDE."""
    vals = [str(s).strip() for s in getattr(settings, "GESTIONE_SPECIFICHE_SHARE_EXCLUDE", []) if str(s).strip()]
    return vals[0] if vals else "_SUPERATO"


def elenca_cartelle_consentite(max_depth: int = 2) -> list[dict]:
    """Cartelle reali (dir) sotto le radici consentite, ESCLUSE ``_SUPERATO`` e i suoi sottoalberi.

    Serve alla "selezione vera" della destinazione (picker UI / validazione CLI): ritorna
    ``[{'path': <abs>, 'label': <relativo-alla-radice>, 'root': <root>}]`` ordinate, limitate a
    ``max_depth`` livelli sotto ciascuna radice per restare pratiche su share grandi.
    """
    esclusi = _segmenti_esclusi()
    out: list[dict] = []
    for root in radici_consentite():
        if not os.path.isdir(root):
            continue
        root_abs = os.path.abspath(root)
        for dirpath, dirnames, _files in os.walk(root):
            rel = os.path.relpath(dirpath, root_abs)
            depth = 0 if rel == "." else len(rel.split(os.sep))
            # pota le cartelle escluse e non scendere oltre max_depth
            dirnames[:] = [] if depth >= max_depth else [d for d in dirnames if d.lower() not in esclusi]
            if rel != "." and any(s.lower() in esclusi for s in rel.split(os.sep)):
                continue
            out.append({"path": dirpath, "label": "(radice)" if rel == "." else rel, "root": root})
    return sorted(out, key=lambda d: (str(d["root"]).lower(), d["label"].lower()))


def valida_cartella_destinazione(cartella: str) -> str | None:
    """Realpath della cartella se e' una dir ESISTENTE, dentro allowlist e NON esclusa; altrimenti None."""
    reale = risolvi_consentito(cartella)
    if reale is None or not os.path.isdir(reale):
        return None
    if _in_cartella_esclusa(reale):
        return None
    return reale


# ---------------------------------------------------------------------------
# Pianificazione / esecuzione
# ---------------------------------------------------------------------------
@dataclass
class PianoDeposito:
    esito: str  # ok|identico|collisione|cartella_richiesta|cartella_non_valida|sorgente_mancante|path_non_consentito|errore
    target: str = ""          # path canonico della nuova revisione (destinazione attiva)
    sposta_da: str = ""       # file della revisione precedente da archiviare (o "")
    sposta_a: str = ""        # destinazione in _SUPERATO per la revisione precedente (o "")
    collisione_da: str = ""   # file gia' presente al target da archiviare con --forza (o "")
    collisione_a: str = ""    # destinazione in _SUPERATO per il file in collisione (o "")
    note: str = ""

    def descrizione(self) -> list[str]:
        """Righe ASCII per il riepilogo dry-run."""
        r = [f"esito: {self.esito}"]
        if self.target:
            r.append(f"  scrivi nuovo -> {self.target}")
        if self.collisione_da:
            r.append(f"  archivia collisione: {self.collisione_da} -> {self.collisione_a}")
        if self.sposta_da:
            r.append(f"  supera precedente: {self.sposta_da} -> {self.sposta_a}")
        if self.note:
            r.append(f"  nota: {self.note}")
        return r


def _leggi_sorgente(sorgente) -> bytes | None:
    if isinstance(sorgente, (bytes, bytearray)):
        return bytes(sorgente)
    try:
        with open(sorgente, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _sha256(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blocco in iter(lambda: fh.read(65536), b""):
            h.update(blocco)
    return h.hexdigest()


def _dest_superato(file_reale: str) -> str:
    """Destinazione d'archivio in ``_SUPERATO`` preservando la sottostruttura relativa alla radice."""
    root = _radice_reale_di(file_reale)
    if root is None:
        # non dovrebbe accadere (file gia' validato consentito): archivia nella radice esclusa piatta
        base = ntpath.basename(file_reale)
        return os.path.join(radici_consentite()[0], _nome_cartella_superato(), base)
    segs = _segmenti_rel(os.path.realpath(file_reale), root)
    rel_dir, nome = segs[:-1], segs[-1] if segs else ntpath.basename(file_reale)
    return os.path.join(root, _nome_cartella_superato(), *rel_dir, nome)


def _dest_superato_unica(dest: str) -> str:
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(dest)
    stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    cand = f"{base} (superato {stamp}){ext}"
    n = 1
    while os.path.exists(cand):
        cand = f"{base} (superato {stamp}-{n}){ext}"
        n += 1
    return cand


def pianifica(spec: Specifica, sorgente, *, cartella: str | None = None, nome: str | None = None,
              revisione: str | None = None, forza: bool = False) -> PianoDeposito:
    """Calcola il piano di deposito SENZA effetti collaterali (dry-run).

    Naming (deciso con l'utente):
    - il **numero documento** (il nome che deve restare invariato) si eredita dal FILE ATTUALE
      collegato alla specifica, NON dal codice gestionale;
    - la **revisione** e' input umano verbatim (mai auto-incrementata): ``spec.revisione`` di
      default, oppure l'override ``revisione``;
    - ``nome`` (override) forza il nome file esatto;
    - se la specifica non ha ancora un file collegato non c'e' un numero documento da cui derivare
      -> serve ``nome`` esplicito (esito ``nome_richiesto``).
    """
    dati = _leggi_sorgente(sorgente)
    if not dati:
        return PianoDeposito(esito="sorgente_mancante", note="PDF sorgente assente o vuoto.")

    corrente = (getattr(spec, "percorso_esterno", "") or "").strip()
    corrente_reale = risolvi_consentito(corrente) if corrente else None
    ha_corrente = bool(corrente_reale and os.path.isfile(corrente_reale))

    # 1) cartella di destinazione: quella della revisione corrente, oppure --cartella esistente.
    if cartella:
        cartella_reale = valida_cartella_destinazione(cartella)
        if cartella_reale is None:
            return PianoDeposito(esito="cartella_non_valida",
                                 note="Cartella inesistente, fuori allowlist o in _SUPERATO.")
    elif ha_corrente:
        cartella_reale = os.path.dirname(corrente_reale)
    elif corrente and corrente_reale is None:
        return PianoDeposito(esito="path_non_consentito", note="percorso_esterno corrente fuori allowlist.")
    else:
        return PianoDeposito(esito="cartella_richiesta",
                             note="Specifica senza file collegato: indicare una cartella esistente e --nome.")

    # 2) revisione VERBATIM (umano) e nome file (numero documento invariato).
    rev = revisione if (revisione is not None and str(revisione).strip() != "") else (getattr(spec, "revisione", "") or "")
    if nome:
        fname = _assicura_pdf(nome)
    elif ha_corrente:
        fname = nome_nuova_revisione(_stem_documento(os.path.basename(corrente_reale)), rev)
    else:
        return PianoDeposito(esito="nome_richiesto",
                             note="Nessun file collegato da cui derivare il numero documento: indicare --nome.")

    # 3) target e validazione destinazione attiva (dentro allowlist, mai in _SUPERATO).
    target = os.path.join(cartella_reale, fname)
    target_reale = risolvi_consentito(target)
    if target_reale is None or _in_cartella_esclusa(target_reale):
        return PianoDeposito(esito="path_non_consentito", note="Target fuori allowlist o dentro _SUPERATO.")

    piano = PianoDeposito(esito="ok", target=target_reale)

    # 4) revisione precedente da archiviare (se e' un file diverso dal target).
    if ha_corrente and _real_nc(corrente_reale) != _real_nc(target_reale):
        piano.sposta_da = corrente_reale
        piano.sposta_a = _dest_superato(corrente_reale)

    # 5) collisione al target.
    if os.path.isfile(target_reale):
        if _sha256(dati) == _sha256_file(target_reale):
            piano.esito = "identico"
            piano.note = "Un file identico e' gia' presente al path del target: nessuna scrittura."
            return piano
        if not forza:
            piano.esito = "collisione"
            piano.note = "Esiste gia' un file DIVERSO al path del target. Usare forza per archiviarlo in _SUPERATO."
            return piano
        piano.collisione_da = target_reale
        piano.collisione_a = _dest_superato(target_reale)

    return piano


def esegui(spec: Specifica, sorgente, *, cartella: str | None = None, nome: str | None = None,
           revisione: str | None = None, forza: bool = False, apply: bool = False, attore=None) -> PianoDeposito:
    """Esegue il deposito con rollback. Con ``apply=False`` ritorna solo il piano (dry-run)."""
    piano = pianifica(spec, sorgente, cartella=cartella, nome=nome, revisione=revisione, forza=forza)
    if not apply or piano.esito in ("identico",):
        return piano
    if piano.esito != "ok":
        return piano

    dati = _leggi_sorgente(sorgente)
    undo: list = []
    percorso_precedente = getattr(spec, "percorso_esterno", "") or ""
    try:
        # (a) archivia l'eventuale file in collisione al target (--forza)
        if piano.collisione_da:
            os.makedirs(os.path.dirname(piano.collisione_a), exist_ok=True)
            dest = _dest_superato_unica(piano.collisione_a)
            shutil.move(piano.collisione_da, dest)
            undo.append(lambda src=piano.collisione_da, dst=dest: shutil.move(dst, src))

        # (b) scrivi il nuovo PDF al path canonico
        os.makedirs(os.path.dirname(piano.target), exist_ok=True)
        with open(piano.target, "wb") as fh:
            fh.write(dati)
        undo.append(lambda p=piano.target: os.path.exists(p) and os.remove(p))

        # (c) archivia la revisione precedente
        if piano.sposta_da:
            os.makedirs(os.path.dirname(piano.sposta_a), exist_ok=True)
            dest_prev = _dest_superato_unica(piano.sposta_a)
            shutil.move(piano.sposta_da, dest_prev)
            piano.sposta_a = dest_prev
            undo.append(lambda src=piano.sposta_da, dst=dest_prev: shutil.move(dst, src))

        # (d) aggiorna il collegamento (senza toccare la FSM)
        Specifica.objects.filter(pk=spec.pk).update(percorso_esterno=piano.target)
        undo.append(lambda pk=spec.pk, val=percorso_precedente:
                    Specifica.objects.filter(pk=pk).update(percorso_esterno=val))

        # (e) audit immutabile
        EventoSpecifica.objects.create(
            specifica=spec,
            stato_da=spec.stato,
            stato_a=spec.stato,  # nessuna transizione
            attore=attore,
            trigger=_TRIGGER_AUDIT,
            payload={
                "target": piano.target,
                "nome": os.path.basename(piano.target),
                "precedente": percorso_precedente,
                "superato_in": piano.sposta_a,
                "collisione_archiviata_in": piano.collisione_a,
                "forza": bool(forza),
                "sha256": _sha256(dati),
            },
        )
        spec.percorso_esterno = piano.target  # allinea l'istanza in memoria
        return piano
    except Exception as exc:  # noqa: BLE001 - rollback e report, mai lasciare la share incoerente
        for annulla in reversed(undo):
            try:
                annulla()
            except Exception:  # noqa: BLE001
                logger.exception("Rollback deposito_revisione_share: passo di annullamento fallito")
        logger.exception("deposito_revisione_share fallito per spec %s: rollback eseguito", spec.pk)
        return PianoDeposito(esito="errore", target=piano.target,
                             note="Operazione fallita e annullata (rollback): " + str(exc))
