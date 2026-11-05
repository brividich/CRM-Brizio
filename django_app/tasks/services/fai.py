"""Registro FAI: articolo, situazione del P/N e allineamento con «Programmi e FAI»."""
from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from ..fai_regole import StatoArticolo, prossimo_piano_interno, stato_decorrenza
from ..models import FaiArticolo, FaiPiano, FaiRecord, FaiStato, ProjectTechRef, TechRefKind, TechRefStatus

# Stati in cui il lavoro di chi esegue il FAI è ancora da fare.
STATI_DA_FARE = {FaiStato.DA_ESEGUIRE, FaiStato.NON_COMPLETO}
STATI_IN_CORSO = {FaiStato.DA_ESEGUIRE, FaiStato.ESEGUITO, FaiStato.IN_VALUTAZIONE}


def trova_articolo(client_name: str, part_number: str) -> FaiArticolo | None:
    return FaiArticolo.objects.filter(
        client_name__iexact=(client_name or "").strip(), part_number__iexact=(part_number or "").strip()
    ).first()


def trova_o_crea_articolo(client_name: str, part_number: str) -> FaiArticolo:
    client_name, part_number = (client_name or "").strip(), (part_number or "").strip()
    return trova_articolo(client_name, part_number) or FaiArticolo.objects.create(
        client_name=client_name, part_number=part_number
    )


def stato_articolo(articolo: FaiArticolo, ultimo: FaiRecord | None, oggi=None) -> StatoArticolo:
    """Situazione del P/N rispetto alle soglie, tenendo conto dell'ultimo FAI."""
    oggi = oggi or timezone.localdate()
    if ultimo is not None and ultimo.stato in STATI_IN_CORSO:
        return StatoArticolo("in_corso", "FAI in corso", "info", ultimo.get_stato_display())
    produzione, spedizione = articolo.ultima_produzione, articolo.ultima_spedizione
    if ultimo is not None and ultimo.stato == FaiStato.POSITIVO and ultimo.data_invio:
        # Un FAI positivo prova una produzione: finché il gestionale non dà le date, non
        # deve restare «da ripetere» un articolo appena riqualificato.
        produzione = max(filter(None, (produzione, ultimo.data_invio)))
        spedizione = max(filter(None, (spedizione, ultimo.data_invio)))
    return stato_decorrenza(oggi, produzione, spedizione, articolo.scadenza_cliente)


@dataclass(frozen=True)
class EsitoProgetto:
    titolo: str
    nota: str
    classe: str
    causale: str  # causale proposta; vuota se oggi non serve un nuovo FAI


def esito_progetto(project, oggi=None) -> EsitoProgetto | None:
    """Cosa dice la MT CN 15 per il P/N di questa commessa, in una riga."""
    if not (project.part_number or "").strip():
        return None
    articolo = trova_articolo(project.client_name, project.part_number)
    ultimo = articolo.fai.first() if articolo else None
    if ultimo is None:
        return EsitoProgetto(
            "FAI completo", "Il P/N non è nel registro: se è davvero nuovo vale il caso a.", "warn", "a"
        )
    stato = stato_articolo(articolo, ultimo, oggi)
    if stato.codice == "in_corso":
        return EsitoProgetto("FAI in corso", stato.nota, "info", "")
    if stato.codice == "da_ripetere":
        return EsitoProgetto("FAI completo", stato.nota, "danger", "f")
    if stato.codice == "da_verificare":
        return EsitoProgetto("FAI valido, da tenere d'occhio", stato.nota, "warn", "")
    if stato.codice == "date_mancanti":
        return EsitoProgetto("FAI presente, scadenza non calcolabile", stato.nota, "soft", "")
    return EsitoProgetto(
        "Nessun FAI per decorrenza", "Serve un Delta FAI solo se cambiano progetto, processo o risorse.", "ok", ""
    )


def righe_registro(records, oggi=None) -> list[dict]:
    """Una riga per articolo, con il suo FAI più recente. ``records`` è ordinato dal più nuovo."""
    oggi = oggi or timezone.localdate()
    righe: dict[int, dict] = {}
    for record in records:
        riga = righe.get(record.articolo_id)
        if riga is None:
            righe[record.articolo_id] = {
                "articolo": record.articolo,
                "fai": record,
                "precedenti": 0,
                "situazione": stato_articolo(record.articolo, record, oggi),
            }
        else:
            riga["precedenti"] += 1
    return list(righe.values())


def numero_piano_interno(articolo: FaiArticolo) -> str:
    esistenti = articolo.fai.filter(piano_tipo=FaiPiano.INTERNO).values_list("piano_numero", flat=True)
    return prossimo_piano_interno(articolo.part_number, esistenti)


def allinea_riga(record: FaiRecord, user=None) -> None:
    """Il FAI di una commessa ha la sua riga: così arriva a «Le mie attività» del responsabile."""
    if record.project_id is None:
        return
    ref = record.tech_ref or ProjectTechRef(project_id=record.project_id, kind=TechRefKind.FAI, created_by=user)
    ref.code = record.piano_numero[:120]
    ref.path = record.path
    ref.assigned_to = record.responsabile
    da_fare = record.stato in STATI_DA_FARE
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
    if ref.is_open and record.stato not in STATI_DA_FARE:
        record.stato = FaiStato.DA_ESEGUIRE
    elif not ref.is_open and record.stato in STATI_DA_FARE:
        record.stato = FaiStato.ESEGUITO
    record.save()
