"""F5 — Generazione OFI (verso registro MOD.174) e sotto-flusso documento CN.

Decisioni vincolanti:
- Generazione OFI **su conferma** DM/Approvatore (mai automatica) — decisione F0 #1.
- Approvazione documento CN con `modo_approvazione` ∈ {mod133_approver, car_flow,
  rdd_dedicato}, default da `APPROVAZIONE_DOC_CN_MODE` — decisione F0 #2.

Registro MOD.174 inesistente nel portale (BLOCKER B1): l'OFI è rappresentato da un
numero intero (`RigaMOD133.ofi` / `AzioneOFI.ofi`). Finché non esiste il registro
Django, il numero è assegnato localmente in modo sequenziale (sostituibile con
FK transazionale al registro reale, migrazione additiva). Nessuna modifica
distruttiva a registri esterni.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from . import constants as C
from .models import AzioneOFI, EventoSpecifica, RigaMOD133

logger = logging.getLogger(__name__)

_OFI_BASE = 1000  # base numerica locale finché non esiste il registro MOD.174 reale


def _log_evento(spec, trigger: str, payload: dict, attore=None) -> None:
    try:
        EventoSpecifica.objects.create(
            specifica=spec, stato_da=spec.stato, stato_a=spec.stato,
            attore=attore, trigger=trigger,
            payload={"snapshot": spec.snapshot_metadati(), **payload},
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("gs AUDIT evento OFI fallito (evento non registrato): %s", exc)


def _prossimo_numero_ofi() -> int:
    # M6: chiamata DENTRO crea_ofi_da_riga (@transaction.atomic). Il lock sulle AzioneOFI con
    # ofi valorizzato serializza i creatori concorrenti (SQL Server) -> niente due OFI con lo
    # stesso numero MAX+1. Mitigazione finche' non esiste il registro MOD.174 reale (B1).
    list(AzioneOFI.objects.select_for_update().filter(ofi__isnull=False).values_list("id", flat=True))
    massimo = max(
        RigaMOD133.objects.aggregate(m=models.Max("ofi"))["m"] or 0,
        AzioneOFI.objects.aggregate(m=models.Max("ofi"))["m"] or 0,
    )
    return max(massimo, _OFI_BASE) + 1


@transaction.atomic
def crea_ofi_da_riga(riga: RigaMOD133, *, attore=None, ofi_numero: int | None = None) -> AzioneOFI:
    """Crea l'OFI per una riga con impatto (genera_ofi=True), **su conferma**.

    Idempotente: se l'OFI per la riga esiste già, restituisce l'azione esistente
    senza duplicare. Crea l'`AzioneOFI` (sotto-flusso documento CN) con
    `modo_approvazione` di default da `APPROVAZIONE_DOC_CN_MODE`.
    """
    if not riga.genera_ofi:
        raise ValidationError("La riga non è marcata per generare un OFI (genera_ofi=False).")

    riga = RigaMOD133.objects.select_for_update().get(pk=riga.pk)

    esistente = AzioneOFI.objects.filter(riga_mod133=riga).first()
    if esistente is not None:
        return esistente  # idempotenza: nessuna doppia creazione

    numero = ofi_numero if ofi_numero is not None else _prossimo_numero_ofi()
    riga.ofi = numero
    riga.save(update_fields=["ofi"])

    cfg = getattr(settings, "GESTIONE_SPECIFICHE", {}) or {}
    modo = cfg.get("APPROVAZIONE_DOC_CN_MODE", C.APPROV_CAR_FLOW)

    azione = AzioneOFI.objects.create(
        riga_mod133=riga, ofi=numero, documento_cn=riga.rif_doc_cn,
        tipo_azione="modifica_documento_cn", stato=C.AZIONE_OFI_BOZZA,
        modo_approvazione=modo,
    )

    spec = riga.mod133.specifica
    _log_evento(spec, "ofi_creato", {"ofi": numero, "riga_id": riga.id, "modo": modo}, attore)
    return azione


def invia_in_approvazione(azione: AzioneOFI) -> AzioneOFI:
    if azione.stato != C.AZIONE_OFI_BOZZA:
        raise ValidationError("L'azione OFI non è in bozza.")
    azione.stato = C.AZIONE_OFI_IN_APPROVAZIONE
    azione.save(update_fields=["stato", "updated_at"])
    return azione


def approva_azione_ofi(azione: AzioneOFI, *, approvatore, esito: str = C.AZIONE_OFI_APPROVATA, note: str = "") -> AzioneOFI:
    """Approva/respinge l'azione documento CN secondo `modo_approvazione`.

    - `mod133_approver`: l'approvazione spetta all'approvatore del MOD.133.
    - `car_flow`: instradata al flusso CAR (approvatore generico abilitato).
    - `rdd_dedicato`: approvatore del ruolo RDD dedicato.
    (Per car_flow/rdd_dedicato il controllo di ruolo è demandato all'ACL; qui si
    registra l'approvatore fornito.)
    """
    if esito not in (C.AZIONE_OFI_APPROVATA, C.AZIONE_OFI_RESPINTA):
        raise ValidationError("Esito azione OFI non valido.")
    # M7: un'azione gia' decisa non e' ribaltabile (no approvata<->respinta con un nuovo POST).
    if azione.stato in (C.AZIONE_OFI_APPROVATA, C.AZIONE_OFI_RESPINTA):
        raise ValidationError("Azione OFI gia' decisa: non e' piu' modificabile.")

    mod = azione.riga_mod133.mod133
    if azione.modo_approvazione == C.APPROV_MOD133:
        if mod.approvatore_id and approvatore is not None and approvatore.id != mod.approvatore_id:
            raise ValidationError(
                "In modalità 'mod133_approver' l'approvazione spetta all'approvatore del MOD.133."
            )

    azione.approvatore = approvatore
    azione.data_approvazione = timezone.now()
    azione.stato = esito
    azione.save(update_fields=["approvatore", "data_approvazione", "stato", "updated_at"])

    spec = azione.riga_mod133.mod133.specifica
    _log_evento(spec, "azione_ofi_approvata", {
        "ofi": azione.ofi, "modo": azione.modo_approvazione, "esito": esito, "note": note,
    }, approvatore)
    return azione
