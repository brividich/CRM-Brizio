"""Pianificazione sessioni e lezioni della formazione HR — NOVICROM HUB.

Tre attriti storici del flusso «nuovo corso» si risolvono qui, senza toccare il
modello dati esistente:

1. **codice sessione a mano**: :func:`genera_codice_sessione` lo deriva dal codice
   corso (``<CORSO>-E1``, ``-E2``, …), come già si fa per il codice corso dal piano;
2. **sessione unica**: :func:`crea_sessione_unica` crea in un colpo solo sessione +
   giornate, così un corso "una tantum" non richiede tre passaggi separati;
3. **calendario multi-giorno**: :func:`genera_lezioni` sforna una lezione per giorno
   lavorativo dell'intervallo, con orari e pausa uguali per tutti.

Le ore **formative** sono sempre al netto della pausa (vedi
``TrainingLesson.durata_ore``): 08:00–17:00 con 60′ di pausa = 8 ore.
"""
from __future__ import annotations

from datetime import date, time, timedelta

from ..models_formazione import TrainingLesson, TrainingSession

__all__ = [
    "genera_codice_sessione",
    "ore_nette",
    "giorni_pianificabili",
    "genera_lezioni",
    "crea_sessione_unica",
]


def genera_codice_sessione(corso) -> str:
    """Codice edizione univoco derivato dal corso: ``<codice corso>-E<N>``.

    N è il primo progressivo libero **a livello globale** (``codice_sessione`` è
    unique su tutta la tabella, non per corso). Fallback su ``SESS`` se il corso
    non ha codice.
    """
    from core.numbering import next_suffix

    base = (getattr(corso, "codice", "") or "").strip().upper() or "SESS"
    prefix = f"{base}-E"
    esistenti = list(
        TrainingSession.objects.filter(codice_sessione__startswith=prefix)
        .values_list("codice_sessione", flat=True)
    )
    n = next_suffix(esistenti, prefix, sep="")
    codice = f"{prefix}{n}"[:40]
    # Cintura e bretelle: il vincolo è unique, meglio un giro in più che un IntegrityError.
    while TrainingSession.objects.filter(codice_sessione=codice).exists():
        n += 1
        codice = f"{prefix}{n}"[:40]
    return codice


def ore_nette(ora_inizio: time, ora_fine: time, pausa_minuti: int = 0) -> float:
    """Ore formative di una giornata: ``(fine - inizio) - pausa``, mai negative.

    Stessa formula di ``TrainingLesson.durata_ore``, disponibile prima di avere
    l'istanza (anteprima nel form, calcolo della durata teorica del corso).
    """
    minuti = (ora_fine.hour * 60 + ora_fine.minute) - (ora_inizio.hour * 60 + ora_inizio.minute)
    return round(max(0, minuti - max(0, int(pausa_minuti or 0))) / 60, 2)


def giorni_pianificabili(data_inizio: date, data_fine: date, salta_weekend: bool = True) -> list[date]:
    """Giorni dell'intervallo (estremi inclusi), opzionalmente senza sabato/domenica."""
    if data_fine < data_inizio:
        return []
    giorni: list[date] = []
    giorno = data_inizio
    while giorno <= data_fine:
        if not (salta_weekend and giorno.weekday() >= 5):
            giorni.append(giorno)
        giorno += timedelta(days=1)
    return giorni


def genera_lezioni(
    sessione: TrainingSession,
    ora_inizio: time,
    ora_fine: time,
    pausa_minuti: int = 0,
    argomento: str = "",
    docente=None,
    salta_weekend: bool = True,
    user=None,
) -> list[TrainingLesson]:
    """Crea una lezione per ogni giorno pianificabile della sessione.

    **Idempotente sui giorni**: salta le date che hanno già una lezione, così
    rilanciare la generazione dopo aver allungato la sessione aggiunge solo i
    giorni nuovi. La numerazione riparte dal massimo esistente.
    """
    esistenti = list(sessione.lezioni.all())
    date_occupate = {lz.data for lz in esistenti}
    numero = max((lz.numero for lz in esistenti), default=0)

    argomento = (argomento or "").strip() or sessione.corso.titolo
    docente_nome = docente.nome if docente is not None else (sessione.docente_nome or "")
    if docente is None and sessione.docente_id:
        docente = sessione.docente

    creati: list[TrainingLesson] = []
    for giorno in giorni_pianificabili(sessione.data_inizio, sessione.data_fine, salta_weekend):
        if giorno in date_occupate:
            continue
        numero += 1
        creati.append(
            TrainingLesson.objects.create(
                sessione=sessione,
                numero=numero,
                data=giorno,
                ora_inizio=ora_inizio,
                ora_fine=ora_fine,
                pausa_minuti=max(0, int(pausa_minuti or 0)),
                argomento=argomento[:500],
                docente=docente,
                docente_nome=(docente_nome or "")[:200],
                updated_by=user,
            )
        )
    return creati


def crea_sessione_unica(
    corso,
    data_inizio: date,
    data_fine: date | None = None,
    ora_inizio: time | None = None,
    ora_fine: time | None = None,
    pausa_minuti: int = 0,
    sede: str = "",
    docente=None,
    modalita: str = "IN_SEDE",
    salta_weekend: bool = True,
    genera_giornate: bool = True,
    user=None,
) -> TrainingSession:
    """Crea l'unica edizione di un corso, con le sue giornate già pianificate.

    Pensata per il corso "una tantum" (una data, un'aula, un docente): evita il
    triplo passaggio corso → sessione → lezioni. Il codice edizione è automatico.
    """
    sessione = TrainingSession.objects.create(
        corso=corso,
        codice_sessione=genera_codice_sessione(corso),
        stato="PIANIFICATA",
        modalita=modalita or "IN_SEDE",
        data_inizio=data_inizio,
        data_fine=data_fine or data_inizio,
        sede=(sede or "")[:200],
        docente=docente,
        docente_nome=(docente.nome if docente is not None else "")[:200],
        created_by=user,
    )
    if genera_giornate and ora_inizio and ora_fine:
        genera_lezioni(
            sessione,
            ora_inizio=ora_inizio,
            ora_fine=ora_fine,
            pausa_minuti=pausa_minuti,
            argomento=corso.titolo,
            docente=docente,
            salta_weekend=salta_weekend,
            user=user,
        )
    return sessione
