"""F6b-2 - Deposito del composito controllato sulla share (con "scambio" delle forme).

Il documento controllato sulla share ha due FORME che si scambiano sullo stesso path:
- "attesa"    -> [cover "IN ATTESA MOD.133"] + [originale] + filigrana + protezione;
- "approvato" -> [pagina MOD.133 compilata] + [originale] + protezione.

Questo modulo GENERA la forma corrente (protetta) e la SCRIVE sulla share, sostituendo la forma
precedente. Riusa le sicurezze di ``share_write`` (allowlist + anti-traversal, mai dentro
``_SUPERATO``) e aggiunge: backup della forma esistente con **rollback** in caso di errore e
**audit** immutabile ``EventoSpecifica``. Dry-run di default: con ``dry_run=True`` calcola solo il
piano (forma, target) senza scrivere.

Dormiente finche' non abilitato: l'aggancio automatico all'upload/approvazione e' gated da
``settings.GESTIONE_SPECIFICHE_COMPOSITO_AUTO`` (default False); il deposito richiede comunque
l'owner-password (``GESTIONE_SPECIFICHE_PDF_OWNER_PASSWORD``) e una destinazione risolvibile.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass

from django.utils import timezone

from . import constants as C
from .composito import componi_attesa_da_spec, componi_composito_da_spec
from .models import EventoSpecifica, MOD133, Specifica
from .share_write import (
    _in_cartella_esclusa,
    _stem_documento,
    nome_canonico,
    nome_nuova_revisione,
    valida_cartella_destinazione,
)
from .share_link import risolvi_consentito

logger = logging.getLogger(__name__)

_TRIGGER_AUDIT = "deposito_composito_share"

FORMA_ATTESA = "attesa"
FORMA_APPROVATO = "approvato"


@dataclass
class PianoComposito:
    esito: str  # ok|owner_pw_mancante|originale_mancante|cartella_richiesta|cartella_non_valida|path_non_consentito|errore
    forma: str = ""
    target: str = ""
    dimensione: int = 0
    backup: str = ""
    note: str = ""

    def descrizione(self) -> list[str]:
        r = [f"esito: {self.esito}", f"  forma: {self.forma or '-'}"]
        if self.target:
            r.append(f"  scrivi -> {self.target}")
        if self.dimensione:
            r.append(f"  dimensione composito: {self.dimensione} byte")
        if self.note:
            r.append(f"  nota: {self.note}")
        return r


def forma_corrente(spec) -> str:
    """FORMA della specifica: "approvato" se il MOD.133 e' approvato, altrimenti "attesa"."""
    mod = MOD133.objects.filter(specifica=spec).first()
    if mod is not None and mod.esito == C.ESITO_APPROVATO:
        return FORMA_APPROVATO
    return FORMA_ATTESA


def _leggi_raw(spec) -> bytes | None:
    """Byte dell'originale RAW dal portale (``allegato``). NON legge dalla share (che ospita il
    composito): cosi' la rigenerazione parte SEMPRE dall'originale, mai dal composito gia' depositato
    (evita l'annidamento cover-su-cover / MOD.133-su-MOD.133)."""
    alleg = getattr(spec, "allegato", None)
    if not alleg:
        return None
    try:
        with alleg.open("rb") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001
        return None


def _bytes_forma(spec, forma: str) -> bytes:
    """Byte del composito PROTETTO per la forma richiesta (solleva ValueError: owner-pw/originale).

    L'originale e' letto SOLO dall'allegato del portale (raw), non dalla share, e passato esplicito.
    """
    raw = _leggi_raw(spec)
    if not raw:
        raise ValueError(
            "Originale non disponibile: il deposito del composito richiede l'originale caricato "
            "nel portale (allegato)."
        )
    if forma == FORMA_APPROVATO:
        return componi_composito_da_spec(spec, originale=raw, proteggi=True)
    return componi_attesa_da_spec(spec, originale=raw, proteggi=True)


def _risolvi_target(spec, *, cartella: str | None) -> tuple[str | None, str]:
    """Path (reale) dove scrivere il controllato, o (None, motivo).

    - ``--cartella`` esplicita (esistente, in allowlist, non esclusa) -> nome dal file corrente o
      da ``nome_canonico(codice, rev)``;
    - altrimenti la posizione del ``percorso_esterno`` corrente (si sostituisce li' il controllato);
    - specifica senza destinazione -> ``cartella_richiesta``.
    """
    corrente = (getattr(spec, "percorso_esterno", "") or "").strip()
    corrente_reale = risolvi_consentito(corrente) if corrente else None

    if cartella:
        cartella_reale = valida_cartella_destinazione(cartella)
        if cartella_reale is None:
            return None, "cartella_non_valida"
        if corrente_reale and os.path.isfile(corrente_reale):
            fname = nome_nuova_revisione(_stem_documento(os.path.basename(corrente_reale)),
                                         getattr(spec, "revisione", "") or "")
        else:
            fname = nome_canonico(getattr(spec, "codice", "") or "", getattr(spec, "revisione", "") or "")
        return os.path.join(cartella_reale, fname), "ok"

    if corrente_reale and os.path.isfile(corrente_reale):
        return corrente_reale, "ok"
    if corrente and corrente_reale is None:
        return None, "path_non_consentito"
    # Nuova specifica senza file sulla share: prova la mappatura CONFERMATA cliente -> cartella.
    from .cartelle_cliente import risolvi as _risolvi_cliente

    cartella_map, _fonte = _risolvi_cliente(getattr(spec, "cliente", "") or "")
    if cartella_map:
        fname = nome_canonico(getattr(spec, "codice", "") or "", getattr(spec, "revisione", "") or "")
        return os.path.join(cartella_map, fname), "ok"
    return None, "cartella_richiesta"


def pianifica(spec, *, cartella: str | None = None) -> PianoComposito:
    """Piano del deposito SENZA scrivere: forma corrente, target, dimensione del composito."""
    forma = forma_corrente(spec)
    target, motivo = _risolvi_target(spec, cartella=cartella)
    if target is None:
        return PianoComposito(esito=motivo, forma=forma,
                              note="Specifica senza destinazione share: indicare una cartella esistente."
                              if motivo == "cartella_richiesta" else "Destinazione non consentita.")

    target_reale = risolvi_consentito(target)
    if target_reale is None or _in_cartella_esclusa(target_reale):
        return PianoComposito(esito="path_non_consentito", forma=forma,
                              note="Target fuori allowlist o dentro _SUPERATO.")

    try:
        dati = _bytes_forma(spec, forma)
    except ValueError as exc:
        motivo = "owner_pw_mancante" if "wner-password" in str(exc) else "originale_mancante"
        return PianoComposito(esito=motivo, forma=forma, target=target_reale, note=str(exc))

    return PianoComposito(esito="ok", forma=forma, target=target_reale, dimensione=len(dati))


def deposita(spec, *, cartella: str | None = None, dry_run: bool = True, attore=None) -> PianoComposito:
    """Deposita il composito controllato sulla share (con backup+rollback e audit).

    Con ``dry_run=True`` (default) ritorna solo il piano. Con ``dry_run=False`` scrive: fa il
    **backup** dell'eventuale forma esistente al target, scrive la nuova forma, aggiorna
    ``percorso_esterno`` se cambia, registra l'audit e rimuove il backup; su errore **ripristina**
    il backup (la share non resta mai incoerente).
    """
    piano = pianifica(spec, cartella=cartella)
    if dry_run or piano.esito != "ok":
        return piano

    dati = _bytes_forma(spec, piano.forma)
    target = piano.target
    percorso_precedente = getattr(spec, "percorso_esterno", "") or ""
    backup = ""
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isfile(target):
            stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
            backup = f"{target}.bak-{stamp}"
            shutil.copy2(target, backup)
        with open(target, "wb") as fh:
            fh.write(dati)
        if percorso_precedente != target:
            Specifica.objects.filter(pk=spec.pk).update(percorso_esterno=target)
            spec.percorso_esterno = target
        EventoSpecifica.objects.create(
            specifica=spec, stato_da=spec.stato, stato_a=spec.stato, attore=attore,
            trigger=_TRIGGER_AUDIT,
            payload={
                "forma": piano.forma, "target": target,
                "nome": os.path.basename(target), "precedente": percorso_precedente,
                "sha256": hashlib.sha256(dati).hexdigest(),
            },
        )
        if backup and os.path.exists(backup):
            os.remove(backup)  # successo: il backup non serve piu'
        piano.backup = ""
        return piano
    except Exception as exc:  # noqa: BLE001 - rollback e report, mai lasciare la share incoerente
        try:
            if backup and os.path.exists(backup):
                shutil.move(backup, target)  # ripristina la forma precedente
        except Exception:  # noqa: BLE001
            logger.exception("Rollback deposito_composito_share: ripristino backup fallito")
        logger.exception("deposito_composito_share fallito per spec %s: rollback eseguito", spec.pk)
        return PianoComposito(esito="errore", forma=piano.forma, target=target,
                              note="Operazione fallita e annullata (rollback): " + str(exc))


def deposita_auto(spec, *, attore=None) -> PianoComposito | None:
    """Aggancio AUTOMATICO (upload/approvazione), best-effort e gated dal flag.

    No-op (ritorna None) se ``GESTIONE_SPECIFICHE_COMPOSITO_AUTO`` e' disattivo. Non solleva mai:
    un problema di deposito NON deve rompere l'upload o l'approvazione (viene loggato).
    """
    from django.conf import settings

    if not getattr(settings, "GESTIONE_SPECIFICHE_COMPOSITO_AUTO", False):
        return None
    try:
        esito = deposita(spec, dry_run=False, attore=attore)
        if esito.esito != "ok":
            logger.warning("deposito_composito_share auto non eseguito (spec %s): %s - %s",
                           spec.pk, esito.esito, esito.note)
        return esito
    except Exception:  # noqa: BLE001
        logger.exception("deposito_composito_share auto: errore inatteso (spec %s)", spec.pk)
        return None
