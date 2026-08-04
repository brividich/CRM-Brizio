"""Pianificazione sessioni e lezioni della formazione HR — NOVICROM HUB.

Quattro attriti storici del flusso «nuovo corso» si risolvono qui, senza
toccare il modello dati esistente:

1. **codice sessione a mano**: :func:`genera_codice_sessione` lo deriva dal codice
   corso (``<CORSO>-E1``, ``-E2``, …), come già si fa per il codice corso dal piano;
2. **sessione unica**: :func:`crea_sessione_unica` crea in un colpo solo sessione +
   giornate, così un corso "una tantum" non richiede tre passaggi separati;
3. **calendario multi-giorno**: :func:`genera_lezioni` sforna una lezione per giorno
   lavorativo dell'intervallo, con orari e pausa uguali per tutti — filtrabile per
   giorni della settimana (es. solo Mar e Gio) o sostituibile con un elenco di
   date puntuali per calendari non regolari;
4. **gruppi logistici**: :func:`dividi_in_gruppi` divide gli iscritti già presenti
   in una sessione fra più sessioni "gemelle" (stessa ``edizione``, ciascuna con la
   propria copia del programma) — il caso «10 iscritti, ma per l'aula si dividono
   in 2 gruppi da 5» senza inventare un'entità nuova nel modello dati.

Le ore **formative** sono sempre al netto della pausa (vedi
``TrainingLesson.durata_ore``): 08:00–17:00 con 60′ di pausa = 8 ore.

**Perché "gruppo" non è un modello nuovo.** Ogni gruppo logistico È una
``TrainingSession`` con le proprie lezioni: il denominatore della percentuale di
presenza (``_calcola_percentuale_presenza`` in ``views.py``) è già scoped sulle
lezioni della sessione dell'iscritto, quindi resta corretto per costruzione anche
quando un corso viene erogato a più gruppi — non serve toccare quel calcolo.
``edizione`` è solo l'etichetta che tiene insieme i gruppi della stessa erogazione
per la UI (di rado quella tenuta separata in ``TrainingEnrollmentLesson``, i
"turni" mattina/pomeriggio sulla STESSA sessione, che restano un caso diverso).
"""
from __future__ import annotations

from datetime import date, time, timedelta

from django.db import transaction
from django.utils import timezone

from ..models_formazione import TrainingLesson, TrainingSession

__all__ = [
    "genera_codice_sessione",
    "ore_nette",
    "giorni_pianificabili",
    "giorni_da_pianificare",
    "genera_lezioni",
    "crea_sessione_unica",
    "dividi_in_gruppi",
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


def giorni_pianificabili(
    data_inizio: date,
    data_fine: date,
    salta_weekend: bool = True,
    giorni_settimana: set[int] | None = None,
) -> list[date]:
    """Giorni dell'intervallo (estremi inclusi).

    Con ``giorni_settimana`` valorizzato (insieme di ``date.weekday()``, 0=lunedì
    … 6=domenica) restano solo quei giorni della settimana — es. ``{1, 3}`` per un
    corso che si tiene solo il martedì e il giovedì. Se ``None``, ripiega sul
    comportamento storico: tutti i giorni, weekend escludibile con ``salta_weekend``.
    """
    if data_fine < data_inizio:
        return []
    giorni: list[date] = []
    giorno = data_inizio
    while giorno <= data_fine:
        if giorni_settimana is not None:
            ammesso = giorno.weekday() in giorni_settimana
        else:
            ammesso = not (salta_weekend and giorno.weekday() >= 5)
        if ammesso:
            giorni.append(giorno)
        giorno += timedelta(days=1)
    return giorni


def giorni_da_pianificare(
    sessione: TrainingSession,
    salta_weekend: bool = True,
    giorni_settimana: set[int] | None = None,
    date_puntuali: list[date] | None = None,
) -> list[date]:
    """Le date che la generazione prenderebbe in considerazione, ordinate e senza doppioni.

    Stessa gerarchia di :func:`genera_lezioni` (date puntuali > giorni della
    settimana > intervallo). Esposta a parte perché la view ne ha bisogno per
    dire quante giornate erano *già presenti*: senza, il conto delle saltate si
    ricostruirebbe duplicando questa scelta a tre rami.
    """
    if date_puntuali:
        return sorted(set(date_puntuali))
    return giorni_pianificabili(
        sessione.data_inizio, sessione.data_fine, salta_weekend, giorni_settimana
    )


def genera_lezioni(
    sessione: TrainingSession,
    ora_inizio: time,
    ora_fine: time,
    pausa_minuti: int = 0,
    argomento: str = "",
    docente=None,
    salta_weekend: bool = True,
    giorni_settimana: set[int] | None = None,
    date_puntuali: list[date] | None = None,
    user=None,
) -> list[TrainingLesson]:
    """Crea una lezione per ogni giorno pianificabile della sessione.

    Tre modalità, in ordine di priorità:

    - ``date_puntuali``: elenco esplicito di date (calendario non regolare, es.
      lezioni sparse su due mesi) — ignora l'intervallo e i giorni della settimana;
    - ``giorni_settimana``: solo quei giorni della settimana dentro l'intervallo
      della sessione (corso settimanale ricorrente, es. solo Mar+Gio);
    - default: ogni giorno dell'intervallo, weekend escludibile con ``salta_weekend``
      (comportamento storico).

    **Idempotente sui giorni**: salta le date che hanno già una lezione, così
    rilanciare la generazione — anche con parametri diversi — aggiunge solo i
    giorni nuovi. La numerazione riparte dal massimo esistente. Non cancella e
    non riscrive mai una lezione esistente: quello che è già stato compilato a
    mano (argomento, note, presenze, firme) sopravvive a ogni rigenerazione.

    **Tutto o niente, e una alla volta**: la creazione sta in una transazione
    con lock di riga sulla sessione. Senza, due «Genera giornate» simultanei
    leggerebbero lo stesso `numero` massimo e la stessa lista di date occupate,
    e finirebbero o con giornate doppie o con un `IntegrityError` sul vincolo
    ``(sessione, numero)`` — cioè un 500 in faccia al secondo utente.
    """
    with transaction.atomic():
        # Il lock si prende sulla riga sessione: e' il punto di serializzazione
        # naturale, dato che numero e date occupate si contano sulle sue lezioni.
        TrainingSession.objects.select_for_update().get(pk=sessione.pk)

        esistenti = list(sessione.lezioni.all())
        date_occupate = {lz.data for lz in esistenti}
        numero = max((lz.numero for lz in esistenti), default=0)

        argomento = (argomento or "").strip() or sessione.corso.titolo
        docente_nome = docente.nome if docente is not None else (sessione.docente_nome or "")
        if docente is None and sessione.docente_id:
            docente = sessione.docente

        giorni_da_creare = giorni_da_pianificare(
            sessione, salta_weekend, giorni_settimana, date_puntuali,
        )

        creati: list[TrainingLesson] = []
        for giorno in giorni_da_creare:
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
    data_inizio: date | None,
    data_fine: date | None = None,
    ora_inizio: time | None = None,
    ora_fine: time | None = None,
    pausa_minuti: int = 0,
    sede: str = "",
    docente=None,
    modalita: str = "IN_SEDE",
    salta_weekend: bool = True,
    giorni_settimana: set[int] | None = None,
    date_puntuali: list[date] | None = None,
    genera_giornate: bool = True,
    user=None,
) -> TrainingSession:
    """Crea l'unica edizione di un corso, con le sue giornate già pianificate.

    Pensata per il corso "una tantum" (una data, un'aula, un docente): evita il
    triplo passaggio corso → sessione → lezioni. Il codice edizione è automatico.

    Con ``date_puntuali`` valorizzato, ``data_inizio``/``data_fine`` si ricavano
    dal min/max delle date indicate (il chiamante non deve calcolarli a mano).

    Solleva ``ValueError`` se non c'è nessuna data utilizzabile o se l'intervallo
    è rovesciato: il form lo verifica già, ma questo è il punto in cui una
    sessione incoerente entrerebbe nel database (e ``data_inizio=None`` sarebbe
    un ``IntegrityError``, cioè un 500, invece di un messaggio).
    """
    if date_puntuali:
        date_puntuali = sorted(set(date_puntuali))
        data_inizio = date_puntuali[0]
        data_fine = date_puntuali[-1]
    if data_inizio is None:
        raise ValueError(
            "Serve una data: indica la data della sessione oppure un elenco di date puntuali."
        )
    if data_fine and data_fine < data_inizio:
        raise ValueError("La data di fine non può precedere la data di inizio.")

    with transaction.atomic():
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
                giorni_settimana=giorni_settimana,
                date_puntuali=date_puntuali,
                user=user,
            )
    return sessione


def dividi_in_gruppi(
    sessione_sorgente: TrainingSession,
    n_gruppi: int,
    edizione: str = "",
    giorni_tra_gruppi: int = 0,
    user=None,
) -> list[TrainingSession]:
    """Divide gli iscritti già presenti in ``sessione_sorgente`` fra ``n_gruppi`` sessioni.

    Caso reale: un corso apre con 10 iscritti su un'unica sessione, ma per motivi
    logistici (aula, turni di lavoro) va erogato a **2 gruppi da 5**, ciascuno con
    il proprio calendario di lezioni. Non serve un'entità "gruppo" nel modello: si
    creano ``n_gruppi - 1`` sessioni gemelle che clonano il programma di lezioni
    della sorgente (stesso orario/pausa/docente/argomento; la data si sposta di
    ``giorni_tra_gruppi × indice`` — 0 = stesse date, utile se i gruppi cambiano
    solo aula o turno) e vi si spostano gli iscritti del proprio gruppo
    (round-robin sull'elenco ordinato per ``legacy_anagrafica_id``).

    La sessione sorgente **resta il primo gruppo**: non viene ricreata, i suoi
    iscritti del bucket 0 restano lì. Tutte le sessioni risultanti condividono
    ``edizione`` (etichetta esplicita, o quella già sulla sorgente, o generata
    automaticamente) così restano collegate in UI (:meth:`TrainingSession.sessioni_gemelle`).

    Solleva ``ValueError`` se la sorgente ha già presenze registrate: spostare un
    iscritto dopo che ha firmato una lezione lo scollegherebbe dal proprio
    registro. Va quindi usata **prima** di iniziare le lezioni, appena si sa come
    si dividono i gruppi — non a corso già partito.
    """
    from ..models_formazione import TrainingEnrollment, TrainingEnrollmentLesson, TrainingLessonAttendance

    n_gruppi = int(n_gruppi)
    if n_gruppi < 2:
        raise ValueError("Servono almeno 2 gruppi per dividere una sessione.")

    if TrainingLessonAttendance.objects.filter(lezione__sessione=sessione_sorgente).exists():
        raise ValueError(
            "Questa sessione ha già presenze registrate: dividerla ora sposterebbe "
            "iscritti su lezioni diverse da quelle in cui sono stati firmati presenti. "
            "Dividi i gruppi prima di iniziare a registrare le presenze."
        )

    corso = sessione_sorgente.corso
    etichetta = (edizione or "").strip() or sessione_sorgente.edizione or (
        f"{corso.codice} · gruppi {timezone.localdate():%d-%m-%Y}"
    )

    # Sessioni nuove, lezioni clonate e iscritti spostati sono un'unica mossa:
    # a metà strada resterebbero gruppi senza calendario o iscritti senza turni.
    with transaction.atomic():
        if sessione_sorgente.edizione != etichetta:
            sessione_sorgente.edizione = etichetta[:80]
            sessione_sorgente.save(update_fields=["edizione"])

        lezioni_sorgente = list(sessione_sorgente.lezioni.order_by("data", "ora_inizio"))
        iscrizioni = list(
            TrainingEnrollment.objects.filter(sessione=sessione_sorgente)
            .order_by("legacy_anagrafica_id")
        )
        # Bucket 0 = resta sulla sorgente; i successivi vanno ai gruppi nuovi.
        secchi: list[list[TrainingEnrollment]] = [[] for _ in range(n_gruppi)]
        for i, iscrizione in enumerate(iscrizioni):
            secchi[i % n_gruppi].append(iscrizione)

        gruppi = [sessione_sorgente]
        for indice in range(1, n_gruppi):
            offset = timedelta(days=giorni_tra_gruppi * indice)
            nuovo = TrainingSession.objects.create(
                corso=corso,
                codice_sessione=genera_codice_sessione(corso),
                stato="PIANIFICATA",
                modalita=sessione_sorgente.modalita,
                data_inizio=sessione_sorgente.data_inizio + offset,
                data_fine=sessione_sorgente.data_fine + offset,
                sede=sessione_sorgente.sede,
                docente=sessione_sorgente.docente,
                docente_nome=sessione_sorgente.docente_nome,
                edizione=etichetta[:80],
                created_by=user,
            )
            for lz in lezioni_sorgente:
                TrainingLesson.objects.create(
                    sessione=nuovo,
                    numero=lz.numero,
                    data=lz.data + offset,
                    ora_inizio=lz.ora_inizio,
                    ora_fine=lz.ora_fine,
                    pausa_minuti=lz.pausa_minuti,
                    argomento=lz.argomento,
                    docente=lz.docente,
                    docente_nome=lz.docente_nome,
                    updated_by=user,
                )
            for iscrizione in secchi[indice]:
                # I turni erano riferiti alle lezioni della sorgente: non hanno più senso
                # sul nuovo gruppo (invariante lezione.sessione_id == enrollment.sessione_id).
                TrainingEnrollmentLesson.objects.filter(enrollment=iscrizione).delete()
                iscrizione.sessione = nuovo
                iscrizione.save(update_fields=["sessione"])
            gruppi.append(nuovo)

    return gruppi
