"""Registro FAI: articolo, situazione del P/N e allineamento con «Programmi e FAI»."""
from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from ..fai_regole import StatoArticolo, prossimo_piano_interno, stato_decorrenza
from ..models import (
    FaiArticolo,
    FaiFase,
    FaiGruppo,
    FaiOpzione,
    FaiRecord,
    ProjectTechRef,
    TaskImpostazioni,
    TechRefKind,
    TechRefStatus,
)

# Fasi in cui il lavoro di chi esegue il FAI è ancora da fare: la riga resta aperta.
FASI_DA_FARE = {FaiFase.DA_FARE, FaiFase.NON_COMPLETO}
FASI_IN_CORSO = {FaiFase.DA_FARE, FaiFase.IN_CORSO}

# Codici delle causali che il portale propone da solo (MT CN 15 §5.1 a e f).
CAUSALE_NUOVO = "a"
CAUSALE_FERMO = "f"


@dataclass(frozen=True)
class Soglie:
    mesi_verifica: int
    mesi_ripetizione: int


def soglie() -> Soglie:
    cfg = TaskImpostazioni.get_singleton()
    return Soglie(cfg.fai_mesi_verifica, cfg.fai_mesi_ripetizione)


def opzioni_attive(gruppo: str, corrente: FaiOpzione | None = None) -> list[FaiOpzione]:
    """Le opzioni da offrire; quella già scelta resta visibile anche se poi disattivata."""
    righe = list(FaiOpzione.objects.filter(gruppo=gruppo, attiva=True))
    if corrente is not None and all(o.pk != corrente.pk for o in righe):
        righe.insert(0, corrente)
    return righe


def _prima_con_fase(fase: str) -> FaiOpzione | None:
    return FaiOpzione.objects.filter(gruppo=FaiGruppo.STATO, attiva=True, fase=fase).first()


def stato_iniziale() -> FaiOpzione | None:
    return _prima_con_fase(FaiFase.DA_FARE)


def causale_proposta(codice: str) -> FaiOpzione | None:
    return FaiOpzione.objects.filter(gruppo=FaiGruppo.CAUSALE, attiva=True, codice=codice).first()


def trova_articolo(client_name: str, part_number: str) -> FaiArticolo | None:
    return FaiArticolo.objects.filter(
        client_name__iexact=(client_name or "").strip(), part_number__iexact=(part_number or "").strip()
    ).first()


def trova_o_crea_articolo(client_name: str, part_number: str) -> FaiArticolo:
    client_name, part_number = (client_name or "").strip(), (part_number or "").strip()
    return trova_articolo(client_name, part_number) or FaiArticolo.objects.create(
        client_name=client_name, part_number=part_number
    )


def stato_articolo(articolo: FaiArticolo, ultimo: FaiRecord | None, oggi=None, limiti: Soglie | None = None) -> StatoArticolo:
    """Situazione del P/N rispetto alle soglie, tenendo conto dell'ultimo FAI."""
    oggi = oggi or timezone.localdate()
    limiti = limiti or soglie()
    if ultimo is not None and ultimo.stato.fase in FASI_IN_CORSO:
        return StatoArticolo("in_corso", "In corso", "info", "")
    produzione, spedizione = articolo.ultima_produzione, articolo.ultima_spedizione
    if ultimo is not None and ultimo.stato.fase == FaiFase.POSITIVO and ultimo.data_invio:
        # Un FAI positivo prova una produzione: un articolo appena riqualificato non
        # deve restare «da ripetere» solo perché le date non sono state aggiornate.
        produzione = max(filter(None, (produzione, ultimo.data_invio)))
        spedizione = max(filter(None, (spedizione, ultimo.data_invio)))
    return stato_decorrenza(
        oggi, produzione, spedizione, articolo.scadenza_cliente,
        mesi_verifica=limiti.mesi_verifica, mesi_ripetizione=limiti.mesi_ripetizione,
    )


@dataclass(frozen=True)
class EsitoProgetto:
    titolo: str
    nota: str
    classe: str
    causale: str  # codice della causale proposta; vuoto se oggi non serve un nuovo FAI
    in_corso: bool = False


def esito_progetto(project, oggi=None) -> EsitoProgetto | None:
    """Cosa prevede la procedura per il P/N di questa commessa, in una riga."""
    if not (project.part_number or "").strip():
        return None
    articolo = trova_articolo(project.client_name, project.part_number)
    ultimo = articolo.fai.select_related("stato").first() if articolo else None
    if ultimo is None:
        return EsitoProgetto(
            "FAI completo previsto", "Il P/N non è nel registro: se è davvero nuovo vale la prima produzione.",
            "warn", CAUSALE_NUOVO,
        )
    stato = stato_articolo(articolo, ultimo, oggi)
    if stato.codice == "in_corso":
        return EsitoProgetto("FAI in corso", ultimo.stato.etichetta, "info", "", in_corso=True)
    if stato.codice == "da_ripetere":
        return EsitoProgetto("FAI completo previsto", stato.nota, "warn", CAUSALE_FERMO)
    if stato.codice == "da_verificare":
        return EsitoProgetto("FAI valido, da segnalare", stato.nota, "warn", "")
    if stato.codice == "date_mancanti":
        return EsitoProgetto("FAI presente, scadenza non calcolabile", stato.nota, "soft", "")
    return EsitoProgetto(
        "Nessun FAI per scadenza", "Un Delta FAI si valuta solo se cambiano progetto, processo o risorse.", "ok", ""
    )


def righe_registro(records, oggi=None) -> list[dict]:
    """Una riga per articolo, con il suo FAI più recente. ``records`` è ordinato dal più nuovo."""
    oggi = oggi or timezone.localdate()
    limiti = soglie()
    righe: dict[int, dict] = {}
    for record in records:
        riga = righe.get(record.articolo_id)
        if riga is None:
            righe[record.articolo_id] = {
                "articolo": record.articolo,
                "fai": record,
                "precedenti": 0,
                "situazione": stato_articolo(record.articolo, record, oggi, limiti),
            }
        else:
            riga["precedenti"] += 1
    return list(righe.values())


def numero_piano_automatico(articolo: FaiArticolo) -> str:
    esistenti = articolo.fai.filter(piano__numerazione_auto=True).values_list("piano_numero", flat=True)
    return prossimo_piano_interno(articolo.part_number, esistenti)


def allinea_riga(record: FaiRecord, user=None) -> None:
    """Il FAI di una commessa ha la sua riga: così arriva a «Le mie attività» del responsabile."""
    if record.project_id is None:
        return
    ref = record.tech_ref or ProjectTechRef(project_id=record.project_id, kind=TechRefKind.FAI, created_by=user)
    ref.code = record.piano_numero[:120]
    ref.path = record.path
    if ref.task_id:
        # Una persona sola: il responsabile è quello dell'attività che chiede il FAI.
        record.responsabile = ref.task.assigned_to
        FaiRecord.objects.filter(pk=record.pk).update(responsabile=record.responsabile)
    ref.assigned_to = record.responsabile
    da_fare = record.stato.fase in FASI_DA_FARE
    if da_fare and ref.status != TechRefStatus.OPEN:
        ref.reopen()
    elif not da_fare and ref.status == TechRefStatus.OPEN:
        ref.mark_done(user=user)
    ref.save()
    if record.tech_ref_id != ref.pk:
        record.tech_ref = ref
        record.save(update_fields=["tech_ref", "updated_at"])


def allinea_da_riga(ref: ProjectTechRef) -> None:
    """Il contrario: la riga corretta da «Programmi e FAI» o chiusa da «Le mie attività»."""
    record = getattr(ref, "fai_record", None)
    if record is None:
        return
    record.piano_numero, record.path, record.responsabile = ref.code, ref.path, ref.assigned_to
    nuovo = None
    if ref.is_open and record.stato.fase not in FASI_DA_FARE:
        nuovo = _prima_con_fase(FaiFase.DA_FARE)
    elif not ref.is_open and record.stato.fase in FASI_DA_FARE:
        nuovo = _prima_con_fase(FaiFase.IN_CORSO)
    if nuovo is not None:
        record.stato = nuovo
    record.save()
