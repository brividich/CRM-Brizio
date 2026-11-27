"""Controlli e azioni del percorso «Prepara la sessione» (28/11/2026).

- ``conflitti_persone``: chi, nelle giornate della sessione, è in ferie/assente
  (assenze confermate) o è iscritto a un altro corso nelle stesse ore;
- ``conflitti_lezioni``: sala già occupata (KICK-OFF, visite, altra formazione) e
  docente già impegnato in un'altra sessione, giornata per giornata;
- ``blocchi_formazione``: le giornate di formazione con sala di un giorno, per la
  griglia sale di reception e KICK-OFF (così la sala risulta occupata anche lì);
- ``ultima_edizione`` / ``copia_giornate``: «come l'ultima edizione»;
- ``salva_programma``: quali argomenti del programma si fanno in quale giornata;
- ``sposta_iscritti``: spostamento di persone fra i gruppi della stessa edizione;
- ``prenota_sala`` / ``libera_giornata`` / ``libera_sala``: prenotazione Outlook.

Tutti i controlli sono avvisi, mai blocchi, e non falliscono mai: una sorgente
che non risponde (assenze legacy, Outlook) toglie solo il suo avviso.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db import transaction

from ..models_formazione import TrainingEnrollment, TrainingEnrollmentLesson, TrainingLesson, TrainingSession

logger = logging.getLogger(__name__)

FUSO_OUTLOOK = "W. Europe Standard Time"
GIORNATA_INTERA = (time(0, 0), time(23, 59))


def _gm(giorno: date) -> str:
    return giorno.strftime("%d/%m")


def _finestra(giorno: date, inizio: time, fine: time) -> tuple[datetime, datetime]:
    return datetime.combine(giorno, inizio), datetime.combine(giorno, fine)


def _sovrapposte(a, b) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _giornate(sessione, lezioni) -> dict[date, list[tuple[time, time]]]:
    """Giorni (e orari) in cui la sessione impegna le persone. Senza giornate
    vale tutto il periodo della sessione, a giornata intera, weekend esclusi."""
    giorni: dict[date, list[tuple[time, time]]] = defaultdict(list)
    for lz in lezioni:
        giorni[lz.data].append((lz.ora_inizio, lz.ora_fine))
    if giorni or not sessione.data_inizio:
        return dict(giorni)
    g, fine = sessione.data_inizio, sessione.data_fine or sessione.data_inizio
    while g <= fine and len(giorni) < 62:
        if g.weekday() < 5:
            giorni[g].append(GIORNATA_INTERA)
        g += timedelta(days=1)
    return dict(giorni)


def conflitti_persone(sessione, lezioni, anagrafica_ids) -> dict[int, list[str]]:
    """``{legacy_anagrafica_id: ["Ferie il 12/12", "Corso X il 13/12 08:00–12:00"]}``."""
    ids = sorted({int(i) for i in anagrafica_ids if i})
    giorni = _giornate(sessione, lezioni)
    if not ids or not giorni:
        return {}
    esito: dict[int, list[str]] = defaultdict(list)
    inizio, fine = min(giorni), max(giorni)

    try:
        from assenze.availability import assenze_per_anagrafica
        assenze = assenze_per_anagrafica(ids, inizio, fine)
    except Exception:  # noqa: BLE001 - l'avviso manca, il percorso continua
        logger.warning("Prepara sessione: assenze non lette", exc_info=True)
        assenze = {}
    for lid, righe in assenze.items():
        for r in righe:
            colpiti = [g for g in sorted(giorni) if r["data_inizio"] <= g <= r["data_fine"]]
            if colpiti:
                quando = ", ".join(_gm(g) for g in colpiti[:4]) + ("…" if len(colpiti) > 4 else "")
                esito[lid].append(f"{r.get('tipo') or 'Assenza'} il {quando}")

    altre = (
        TrainingLesson.objects.filter(data__in=list(giorni))
        .exclude(sessione=sessione).exclude(sessione__stato="ANNULLATA")
        .select_related("sessione")
        .only("data", "ora_inizio", "ora_fine", "sessione__codice_sessione", "sessione__id")
    )
    per_sessione: dict[int, list] = defaultdict(list)
    for lz in altre:
        per_sessione[lz.sessione_id].append(lz)
    if per_sessione:
        iscritti = (
            TrainingEnrollment.objects.filter(sessione_id__in=list(per_sessione), legacy_anagrafica_id__in=ids)
            .exclude(stato="RITIRATO").values_list("sessione_id", "legacy_anagrafica_id")
        )
        visti = set()
        for sid, lid in iscritti:
            for lz in per_sessione[sid]:
                f = _finestra(lz.data, lz.ora_inizio, lz.ora_fine)
                if any(_sovrapposte(f, _finestra(lz.data, a, b)) for a, b in giorni[lz.data]):
                    chiave = (lid, sid, lz.data)
                    if chiave not in visti:
                        visti.add(chiave)
                        esito[lid].append(
                            f"Corso {lz.sessione.codice_sessione} il {_gm(lz.data)} "
                            f"{lz.ora_inizio:%H:%M}–{lz.ora_fine:%H:%M}")
    return dict(esito)


def _altre_lezioni_giorno(giorno: date, sessione):
    return (
        TrainingLesson.objects.filter(data=giorno).exclude(sessione=sessione)
        .exclude(sessione__stato="ANNULLATA").select_related("sessione", "sessione__sala")
    )


def conflitti_lezioni(sessione, lezioni) -> dict[int, list[str]]:
    """``{lezione_id: [avvisi]}``: sala occupata e docente già impegnato."""
    esito: dict[int, list[str]] = defaultdict(list)
    docente_sessione = sessione.docente_id
    per_giorno: dict[date, list] = defaultdict(list)
    for lz in lezioni:
        per_giorno[lz.data].append(lz)
    for giorno, del_giorno in per_giorno.items():
        altre = list(_altre_lezioni_giorno(giorno, sessione))
        occupazioni_sala: list[tuple[tuple[datetime, datetime], str]] = []
        if sessione.sala_id:
            for o in altre:
                if o.sessione.sala_id == sessione.sala_id:
                    occupazioni_sala.append((_finestra(giorno, o.ora_inizio, o.ora_fine),
                                             f"la formazione {o.sessione.codice_sessione}"))
            occupazioni_sala += _sala_altri_moduli(giorno, sessione.sala_id)
        for lz in del_giorno:
            f = _finestra(giorno, lz.ora_inizio, lz.ora_fine)
            for altra, cosa in occupazioni_sala:
                if _sovrapposte(f, altra):
                    esito[lz.pk].append(
                        f"{sessione.sala.nome} già occupata {altra[0]:%H:%M}–{altra[1]:%H:%M} da {cosa}")
            docente = lz.docente_id or docente_sessione
            if not docente:
                continue
            for o in altre:
                if (o.docente_id or o.sessione.docente_id) == docente and _sovrapposte(
                        f, _finestra(giorno, o.ora_inizio, o.ora_fine)):
                    esito[lz.pk].append(
                        f"Docente già in aula {o.ora_inizio:%H:%M}–{o.ora_fine:%H:%M} per {o.sessione.codice_sessione}")
    return dict(esito)


def _sala_altri_moduli(giorno: date, sala_id: int) -> list[tuple[tuple[datetime, datetime], str]]:
    """Incontri KICK-OFF e visite della reception nella stessa sala."""
    righe = []
    try:
        from tasks.services.sale import finestra_incontro, incontri_in_sala
        for m in incontri_in_sala(giorno).filter(sala_id=sala_id):
            f = finestra_incontro(m)
            if f:
                righe.append((f, f"un incontro KICK-OFF ({m.project.name})"))
    except Exception:  # noqa: BLE001
        logger.warning("Prepara sessione: incontri KICK-OFF non letti", exc_info=True)
    try:
        from reception.sale import blocchi_visite
        for b in blocchi_visite(giorno):
            if b["sala_id"] == sala_id:
                righe.append(((b["inizio"], b["fine"]), "una visita ospiti"))
    except Exception:  # noqa: BLE001
        logger.warning("Prepara sessione: visite reception non lette", exc_info=True)
    return righe


def blocchi_formazione(giorno: date, *, escludi_sessione_id=None) -> list[dict]:
    """``{sala_id, inizio, fine, titolo}`` delle giornate di formazione con sala."""
    qs = (
        TrainingLesson.objects.filter(data=giorno, sessione__sala__isnull=False)
        .exclude(sessione__stato="ANNULLATA").select_related("sessione", "sessione__corso")
    )
    if escludi_sessione_id:
        qs = qs.exclude(sessione_id=escludi_sessione_id)
    return [
        {"sala_id": lz.sessione.sala_id, "inizio": _finestra(giorno, lz.ora_inizio, lz.ora_fine)[0],
         "fine": _finestra(giorno, lz.ora_inizio, lz.ora_fine)[1],
         "titolo": f"Formazione · {lz.sessione.corso.titolo}"[:120]}
        for lz in qs
    ]


# ── Come l'ultima edizione ──────────────────────────────────────────────

def ultima_edizione(sessione, *, con_giornate: bool = True):
    """L'edizione precedente dello stesso corso (la più recente, annullate escluse)."""
    qs = TrainingSession.objects.filter(corso_id=sessione.corso_id).exclude(pk=sessione.pk).exclude(stato="ANNULLATA")
    if con_giornate:
        qs = qs.filter(lezioni__isnull=False).distinct()
    if sessione.edizione:
        qs = qs.exclude(edizione=sessione.edizione)
    # Prima le edizioni già partite prima di questa; altrimenti la più vicina.
    prima = qs.filter(data_inizio__lt=sessione.data_inizio).order_by("-data_inizio", "-pk").first()
    return prima or qs.order_by("data_inizio", "pk").first()


def _indice_lavorativo(base: date, giorno: date) -> int:
    n, g = 0, base
    while g < giorno:
        g += timedelta(days=1)
        if g.weekday() < 5:
            n += 1
    return n


def copia_giornate(sessione, sorgente, *, user=None) -> int:
    """Copia lo schema delle giornate di ``sorgente`` a partire dall'inizio di
    ``sessione``: stessa distanza in giorni lavorativi, stessi orari e pause.
    Salta i giorni che hanno già una giornata. Ritorna quante ne ha create."""
    from .formazione_pianificazione import aggiungi_lavorativi

    lezioni = list(sorgente.lezioni.order_by("data", "ora_inizio"))
    if not lezioni:
        return 0
    base = lezioni[0].data
    partenza = sessione.data_inizio
    while partenza.weekday() >= 5:
        partenza += timedelta(days=1)
    with transaction.atomic():
        TrainingSession.objects.select_for_update().filter(pk=sessione.pk).first()
        occupati = {(lz.data, lz.ora_inizio) for lz in sessione.lezioni.all()}
        numero = max([lz.numero for lz in sessione.lezioni.all()] or [0])
        create = []
        for lz in lezioni:
            if lz.data.weekday() < 5:
                giorno = aggiungi_lavorativi(partenza, _indice_lavorativo(base, lz.data))
            else:
                giorno = partenza + timedelta(days=(lz.data - base).days)
            if (giorno, lz.ora_inizio) in occupati:
                continue
            numero += 1
            create.append(TrainingLesson.objects.create(
                sessione=sessione, numero=numero, data=giorno, ora_inizio=lz.ora_inizio, ora_fine=lz.ora_fine,
                pausa_minuti=lz.pausa_minuti, argomento=lz.argomento or sessione.corso.titolo[:500],
                docente=lz.docente if lz.docente_id else None, docente_ente=lz.docente_ente,
                docente_nome=lz.docente_nome, updated_by=user,
            ))
        if create:
            ultimo = max(lz.data for lz in create)
            if not sessione.data_fine or ultimo > sessione.data_fine:
                TrainingSession.objects.filter(pk=sessione.pk).update(data_fine=ultimo)
                sessione.data_fine = ultimo
    return len(create)


# ── Programma per giornata ──────────────────────────────────────────────

def salva_programma(sessione, scelte: dict[int, set[int]]) -> int:
    """``scelte`` = ``{lezione_id: {argomento_id, ...}}`` per tutte le giornate:
    rimpiazza gli argomenti svolti di ciascuna. Ritorna le assegnazioni totali."""
    argomenti = set(sessione.programma.values_list("pk", flat=True))
    totale = 0
    with transaction.atomic():
        for lz in sessione.lezioni.all():
            ids = sorted(scelte.get(lz.pk, set()) & argomenti)
            lz.argomenti_svolti.set(ids)
            totale += len(ids)
    return totale


# ── Gruppi ──────────────────────────────────────────────────────────────

def gruppi_edizione(sessione) -> list[TrainingSession]:
    """La sessione e le sue gemelle (stessa edizione), in ordine di data: Gruppo 1, 2, …"""
    if not sessione.edizione:
        return [sessione]
    return list(
        TrainingSession.objects.filter(corso_id=sessione.corso_id, edizione=sessione.edizione)
        .exclude(stato="ANNULLATA").select_related("sala").order_by("data_inizio", "id")
    )


def sposta_iscritti(sessione, mappa: dict[int, int]) -> tuple[int, list[str]]:
    """``mappa`` = ``{iscrizione_id: sessione_id destinazione}`` dentro i gruppi
    della stessa edizione. Chi ha già firmato una giornata non si sposta.
    Ritorna (spostati, avvisi)."""
    from ..models_formazione import TrainingLessonAttendance

    gruppi = {g.pk for g in gruppi_edizione(sessione)}
    avvisi: list[str] = []
    spostati = 0
    with transaction.atomic():
        iscrizioni = TrainingEnrollment.objects.select_for_update().filter(pk__in=list(mappa), sessione_id__in=gruppi)
        for isc in iscrizioni:
            dest = mappa.get(isc.pk)
            if dest not in gruppi or dest == isc.sessione_id:
                continue
            if TrainingLessonAttendance.objects.filter(enrollment=isc).exists():
                avvisi.append(f"#{isc.legacy_anagrafica_id} ha già firmato una giornata: resta nel suo gruppo.")
                continue
            if TrainingEnrollment.objects.filter(sessione_id=dest, legacy_anagrafica_id=isc.legacy_anagrafica_id).exists():
                continue
            TrainingEnrollmentLesson.objects.filter(enrollment=isc).delete()
            isc.sessione_id = dest
            isc.save(update_fields=["sessione"])
            spostati += 1
    return spostati, avvisi


# ── Sala in Outlook ─────────────────────────────────────────────────────

def stato_prenotazione(sessione, lezioni) -> dict:
    n = len(lezioni)
    prenotate = sum(1 for lz in lezioni if lz.outlook_event_id)
    return {"n": n, "prenotate": prenotate, "tutte": n > 0 and prenotate == n}


def prenota_sala(sessione, organizzatore: str) -> tuple[str, str]:
    """Crea in Outlook un evento per ogni giornata non ancora prenotata, nel
    calendario di ``organizzatore``, con la sala invitata come risorsa: se la sala
    è già occupata Outlook la rifiuta e all'organizzatore arriva la risposta."""
    sala = sessione.sala
    if sala is None:
        return ("error", "Scegli prima la sala.")
    if not sala.email:
        return ("info", f"Sala {sala.nome} segnata nel portale: non ha una casella Microsoft 365, in Outlook va prenotata a mano.")
    from core.outlook_calendar import create_event, graph_ready

    if not graph_ready():
        return ("warning", f"Sala {sala.nome} segnata nel portale, ma Outlook non è configurato sul server: prenotala anche in Outlook.")
    organizzatore = (organizzatore or "").strip().lower()
    if "@" not in organizzatore:
        return ("warning", "Il tuo utente non ha un'email: la sala resta segnata solo nel portale.")
    ok = ko = 0
    for lz in sessione.lezioni.filter(outlook_event_id="").order_by("data", "ora_inizio"):
        payload = {
            "subject": f"Formazione: {sessione.corso.titolo} ({sessione.codice_sessione})"[:255],
            "body": {"contentType": "HTML", "content": f"<p>Giornata {lz.numero} della sessione formativa "
                                                         f"<strong>{sessione.codice_sessione}</strong>, prenotata dal NOVICROM HUB.</p>"},
            "start": {"dateTime": datetime.combine(lz.data, lz.ora_inizio).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": FUSO_OUTLOOK},
            "end": {"dateTime": datetime.combine(lz.data, lz.ora_fine).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": FUSO_OUTLOOK},
            "location": {"displayName": sala.nome, "locationEmailAddress": sala.email, "locationType": "conferenceRoom"},
            "attendees": [{"emailAddress": {"address": sala.email, "name": sala.nome}, "type": "resource"}],
            "showAs": "busy", "isReminderOn": False,
            "transactionId": f"hub-formazione-lezione-{lz.pk}-{lz.data:%Y%m%d}",
        }
        try:
            evento = create_event(target_email=organizzatore, payload=payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Formazione: sala %s non prenotata per la lezione %s: %s", sala.pk, lz.pk, exc)
            ko += 1
            continue
        TrainingLesson.objects.filter(pk=lz.pk).update(
            outlook_event_id=str(evento.get("id") or "")[:255], outlook_organizer_email=organizzatore[:255])
        ok += 1
    if ko:
        return ("warning", f"Sala {sala.nome}: {ok} giornate richieste in Outlook, {ko} non accettate da Outlook: prenotale a mano.")
    if not ok:
        return ("info", f"Sala {sala.nome}: tutte le giornate erano già prenotate.")
    return ("success", f"Sala {sala.nome} richiesta in Outlook per {ok} giornat{'a' if ok == 1 else 'e'}: "
                       "se è già occupata la sala rifiuta e ti arriva la risposta.")


def libera_giornata(lezione) -> None:
    """Cancella l'evento Outlook della giornata. Gli errori si registrano e basta."""
    if not (lezione.outlook_event_id and lezione.outlook_organizer_email):
        return
    try:
        from core.outlook_calendar import delete_event, graph_ready
        if graph_ready():
            delete_event(target_email=lezione.outlook_organizer_email, event_id=lezione.outlook_event_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Formazione: evento Outlook della lezione %s non cancellato: %s", lezione.pk, exc)


def libera_sala(sessione) -> int:
    """Cancella gli eventi Outlook di tutte le giornate (cambio o tolta la sala)."""
    n = 0
    for lz in sessione.lezioni.exclude(outlook_event_id=""):
        libera_giornata(lz)
        n += 1
    sessione.lezioni.exclude(outlook_event_id="").update(outlook_event_id="", outlook_organizer_email="")
    return n
