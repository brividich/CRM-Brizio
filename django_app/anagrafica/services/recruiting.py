"""Logica del modulo Recruiting MOD. 05-01.

Tre responsabilità, tenute fuori dalle view:

1. **calcolo del punteggio ponderato** — sempre lato server, mai fidandosi di un
   valore arrivato dal client;
2. **tracciamento delle modifiche** — punteggi, giudizio e stato finiscono in
   ``CandidatoLog`` con autore, istante e valore precedente;
3. **transizione di fine iter** — creazione del dipendente in anagrafica e avvio
   della pratica di onboarding, oppure archiviazione nel database candidati.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Mapping

from django.db import transaction
from django.utils import timezone

from ..models_recruiting import (
    Candidato,
    CandidatoLog,
    CandidatoPunteggio,
    PosizioneAperta,
    RecruitingCriterio,
)

logger = logging.getLogger(__name__)

VALORE_MIN = 1
VALORE_MAX = 5


# ---------------------------------------------------------------------------
# Calcolo del punteggio ponderato
# ---------------------------------------------------------------------------

def criteri_attivi() -> list[RecruitingCriterio]:
    return list(RecruitingCriterio.objects.filter(is_active=True).order_by("ordine", "label"))


def calcola_ponderato(voti_pesati: Iterable[tuple[int, Decimal]]) -> Decimal | None:
    """Media pesata di ``(valore, peso)``, arrotondata a 2 decimali.

    La normalizzazione è sulla **somma dei pesi effettivamente presenti**, non su
    100: così il risultato resta sulla scala 1-5 anche quando HR disattiva un
    criterio o la valutazione è ancora parziale. Un criterio con peso 0 non
    sposta il risultato; se nessun criterio è valutabile ritorna ``None``.
    """
    totale = Decimal("0")
    peso_totale = Decimal("0")
    for valore, peso in voti_pesati:
        peso = Decimal(peso or 0)
        if peso <= 0:
            continue
        totale += Decimal(int(valore)) * peso
        peso_totale += peso
    if peso_totale <= 0:
        return None
    return (totale / peso_totale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ricalcola_punteggio(candidato: Candidato, *, save: bool = True) -> Decimal | None:
    """Ricalcola e persiste ``candidato.punteggio_ponderato``.

    Legge **solo** ``CandidatoPunteggio``: per costruzione nessun dato anagrafico
    del candidato (età, cittadinanza, provincia, titolo di studio) può influire
    sul risultato.
    """
    righe = (
        CandidatoPunteggio.objects
        .filter(candidato=candidato, criterio__is_active=True)
        .select_related("criterio")
    )
    punteggio = calcola_ponderato(
        (riga.valore, riga.criterio.peso_percentuale) for riga in righe
    )
    candidato.punteggio_ponderato = punteggio
    candidato.punteggio_aggiornato_il = timezone.now() if punteggio is not None else None
    if save:
        candidato.save(update_fields=[
            "punteggio_ponderato", "punteggio_aggiornato_il", "updated_at",
        ])
    return punteggio


# ---------------------------------------------------------------------------
# Tracciamento delle modifiche
# ---------------------------------------------------------------------------

def _user_display(user) -> str:
    if not user:
        return ""
    full = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    return (full or getattr(user, "username", "") or "")[:160]


def registra_log(
    candidato: Candidato,
    *,
    tipo: str,
    campo: str,
    valore_prima,
    valore_dopo,
    user=None,
    note: str = "",
) -> CandidatoLog | None:
    """Registra una modifica tracciata. Fire-and-forget: non propaga errori.

    Non scrive nulla se il valore non è cambiato: il registro deve restare
    leggibile in audit, non riempirsi di righe inerti.
    """
    prima = "" if valore_prima in (None, "") else str(valore_prima)
    dopo = "" if valore_dopo in (None, "") else str(valore_dopo)
    if prima == dopo:
        return None
    try:
        return CandidatoLog.objects.create(
            candidato=candidato,
            tipo=tipo,
            campo=campo[:120],
            valore_prima=prima[:255],
            valore_dopo=dopo[:255],
            note=note[:255],
            user=user if (user and getattr(user, "is_authenticated", False)) else None,
            user_display=_user_display(user),
        )
    except Exception:
        logger.warning(
            "Registrazione log recruiting fallita (candidato=%s, campo=%s)",
            candidato.pk, campo, exc_info=True,
        )
        return None


def salva_punteggi(
    candidato: Candidato,
    valori: Mapping[int, int | None],
    *,
    user=None,
) -> Decimal | None:
    """Salva i voti per criterio e ricalcola il ponderato, in transazione.

    ``valori`` mappa ``criterio_id -> voto`` (1-5). Un valore ``None`` o fuori
    scala cancella il voto per quel criterio. Ogni variazione genera una riga di
    log. Ritorna il nuovo punteggio ponderato.
    """
    criteri = {c.id: c for c in criteri_attivi()}
    esistenti = {
        riga.criterio_id: riga
        for riga in CandidatoPunteggio.objects.filter(candidato=candidato)
    }

    with transaction.atomic():
        for criterio_id, criterio in criteri.items():
            grezzo = valori.get(criterio_id)
            try:
                voto = int(grezzo) if grezzo not in (None, "") else None
            except (TypeError, ValueError):
                voto = None
            if voto is not None and not (VALORE_MIN <= voto <= VALORE_MAX):
                voto = None

            riga = esistenti.get(criterio_id)
            prima = riga.valore if riga else None
            if voto is None:
                if riga:
                    riga.delete()
                    registra_log(
                        candidato, tipo=CandidatoLog.TIPO_PUNTEGGIO,
                        campo=criterio.label, valore_prima=prima, valore_dopo="",
                        user=user,
                    )
                continue

            if riga is None:
                CandidatoPunteggio.objects.create(
                    candidato=candidato, criterio=criterio, valore=voto,
                    peso_snapshot=criterio.peso_percentuale,
                )
            elif riga.valore != voto or riga.peso_snapshot != criterio.peso_percentuale:
                riga.valore = voto
                riga.peso_snapshot = criterio.peso_percentuale
                riga.save(update_fields=["valore", "peso_snapshot", "updated_at"])
            registra_log(
                candidato, tipo=CandidatoLog.TIPO_PUNTEGGIO,
                campo=criterio.label, valore_prima=prima, valore_dopo=voto, user=user,
            )

        punteggio = ricalcola_punteggio(candidato)
    return punteggio


def registra_cambio_giudizio(candidato: Candidato, prima: str, dopo: str, *, user=None) -> None:
    registra_log(
        candidato, tipo=CandidatoLog.TIPO_GIUDIZIO, campo="Giudizio finale",
        valore_prima=prima, valore_dopo=dopo, user=user,
    )


def registra_cambio_stato(candidato: Candidato, prima: str, dopo: str, *, user=None, note: str = "") -> None:
    registra_log(
        candidato, tipo=CandidatoLog.TIPO_STATO, campo="Stato iter",
        valore_prima=prima, valore_dopo=dopo, user=user, note=note,
    )


# ---------------------------------------------------------------------------
# Transizione di fine iter
# ---------------------------------------------------------------------------

class TransizioneError(RuntimeError):
    """Errore atteso nella transizione di fine iter (messaggio mostrabile a video)."""


def assumi_e_avvia_onboarding(candidato: Candidato, *, user=None, reparto: str = ""):
    """Crea il dipendente in anagrafica dai dati del candidato e avvia l'onboarding.

    Riusa i dati già raccolti: nessuna doppia immissione manuale. È idempotente —
    se il candidato è già collegato a una pratica la ritorna senza duplicare
    nulla, così un doppio click o un retry non creano due dipendenti.

    Se l'offerta era stata accettata la pratica esiste già in pre-ingresso: la si
    collega al dipendente invece di aprirne una seconda.

    Ritorna la ``OnboardingPratica``.
    """
    pratica_pre = candidato.onboarding_pratica if candidato.onboarding_pratica_id else None
    if pratica_pre is not None and pratica_pre.legacy_anagrafica_id and candidato.stato == Candidato.STATO_ASSUNTO:
        return pratica_pre

    from core.legacy_anagrafica import (
        fetch_anagrafica_rows,
        generate_username,
        upsert_anagrafica_dipendente,
    )
    from core.legacy_models import AnagraficaDipendente

    from . import onboarding as onboarding_service

    if not candidato.cognome.strip() and not candidato.nome.strip():
        raise TransizioneError("Il candidato non ha nome né cognome: completa la scheda prima di assumerlo.")

    legacy_id = candidato.legacy_anagrafica_id
    if legacy_id and not fetch_anagrafica_rows(ids=[legacy_id]):
        # Il collegamento punta a un record sparito: meglio ricrearlo che fallire.
        legacy_id = None

    if not legacy_id:
        esistenti = set(
            AnagraficaDipendente.objects
            .exclude(aliasusername="")
            .exclude(aliasusername__isnull=True)
            .values_list("aliasusername", flat=True)
        )
        alias = generate_username(candidato.nome, candidato.cognome, esistenti)
        row = upsert_anagrafica_dipendente(
            aliasusername=alias,
            nome=candidato.nome.strip(),
            cognome=candidato.cognome.strip(),
            reparto=reparto.strip(),
            mansione=candidato.mansione_cercata.strip(),
            email_notifica=candidato.email.strip(),
            attivo=True,
            utente_id=None,
        )
        legacy_id = int(row.get("id") or 0)
        if not legacy_id:
            raise TransizioneError("Creazione del dipendente in anagrafica non riuscita.")

    reparto = reparto.strip() or (candidato.posizione.reparto if candidato.posizione_id else "")
    if pratica_pre is not None and pratica_pre.is_aperta and not pratica_pre.legacy_anagrafica_id:
        pratica = onboarding_service.collega_dipendente(
            pratica_pre, legacy_id, user=user, reparto=reparto,
            mansione=candidato.mansione_cercata.strip(), data_assunzione=candidato.data_assunzione,
        )
    else:
        pratica = onboarding_service.pratica_aperta(legacy_id) or onboarding_service.avvia_onboarding(
            legacy_id=legacy_id,
            dipendente_nome=candidato.nominativo or f"#{legacy_id}",
            reparto=reparto,
            mansione=candidato.mansione_cercata.strip(),
            data_assunzione=candidato.data_assunzione,
            note_hr=f"Da selezione MOD. 05-01 (candidato #{candidato.pk}).",
            user=user,
        )

    stato_prima = candidato.stato
    candidato.legacy_anagrafica_id = legacy_id
    candidato.onboarding_pratica = pratica
    candidato.stato = Candidato.STATO_ASSUNTO
    candidato.updated_by = user if (user and getattr(user, "is_authenticated", False)) else None
    candidato.save(update_fields=[
        "legacy_anagrafica_id", "onboarding_pratica", "stato", "updated_by", "updated_at",
    ])
    registra_cambio_stato(
        candidato, stato_prima, candidato.stato, user=user,
        note=f"Onboarding avviato (pratica #{pratica.pk}).",
    )
    aggiorna_copertura(candidato.posizione)
    return pratica


# ---------------------------------------------------------------------------
# Pipeline: spostamento di fase e offerta
# ---------------------------------------------------------------------------

# Fasi raggiungibili spostando la scheda nella pipeline. «Assunto» no: crea il
# dipendente e passa dal pulsante dedicato in scheda.
STATI_SPOSTABILI = (
    Candidato.STATO_NUOVO, Candidato.STATO_CV_VALUTATO, Candidato.STATO_COLLOQUIO_1,
    Candidato.STATO_COLLOQUIO_2, Candidato.STATO_OFFERTA,
)


def _utente(user):
    return user if (user and getattr(user, "is_authenticated", False)) else None


def sposta_in_fase(candidato: Candidato, stato: str, *, user=None) -> None:
    """Sposta una scheda aperta in un'altra fase della pipeline (tracciato)."""
    if stato not in STATI_SPOSTABILI:
        raise TransizioneError("Fase non raggiungibile da qui: per l'assunzione usa la scheda candidato.")
    if candidato.iter_chiuso:
        raise TransizioneError("La scheda è a iter chiuso: riapri l'iter prima di spostarla.")
    if stato == candidato.stato:
        return
    stato_prima = candidato.stato
    candidato.stato = stato
    campi = ["stato", "updated_by", "updated_at"]
    if stato == Candidato.STATO_OFFERTA and not candidato.offerta_inviata_il:
        candidato.offerta_inviata_il = timezone.localdate()
        campi.append("offerta_inviata_il")
    candidato.updated_by = _utente(user)
    candidato.save(update_fields=campi)
    registra_cambio_stato(candidato, stato_prima, stato, user=user, note="Spostata nella pipeline.")


def invia_offerta(candidato: Candidato, *, inviata_il, data_ingresso=None, note: str = "", user=None) -> None:
    """Registra l'offerta inviata: la scheda passa in fase «Offerta»."""
    if candidato.iter_chiuso:
        raise TransizioneError("La scheda è a iter chiuso: riapri l'iter prima di registrare un'offerta.")
    stato_prima = candidato.stato
    candidato.stato = Candidato.STATO_OFFERTA
    candidato.offerta_inviata_il = inviata_il or timezone.localdate()
    candidato.offerta_esito = Candidato.OFFERTA_IN_ATTESA
    candidato.offerta_esito_il = None
    candidato.offerta_note = (note or "").strip()[:300]
    if data_ingresso:
        candidato.data_assunzione = data_ingresso
    candidato.updated_by = _utente(user)
    candidato.save()
    registra_cambio_stato(candidato, stato_prima, candidato.stato, user=user,
                          note=f"Offerta inviata il {candidato.offerta_inviata_il:%d/%m/%Y}.")


def registra_esito_offerta(candidato: Candidato, esito: str, *, user=None, data_ingresso=None):
    """Accettata → apre la pratica di pre-ingresso; rifiutata → rinuncia del candidato.

    Ritorna la pratica di onboarding se l'offerta è accettata, altrimenti ``None``.
    L'offerta è un passaggio facoltativo: «Assunto» resta raggiungibile anche senza.
    """
    from . import onboarding as onboarding_service

    if esito not in (Candidato.OFFERTA_ACCETTATA, Candidato.OFFERTA_RIFIUTATA):
        raise TransizioneError("Esito dell'offerta non valido.")
    if candidato.stato != Candidato.STATO_OFFERTA:
        raise TransizioneError("Registra prima l'offerta inviata.")
    candidato.offerta_esito = esito
    candidato.offerta_esito_il = timezone.localdate()
    if data_ingresso:
        candidato.data_assunzione = data_ingresso
    candidato.updated_by = _utente(user)

    if esito == Candidato.OFFERTA_RIFIUTATA:
        stato_prima = candidato.stato
        candidato.stato = Candidato.STATO_RINUNCIA
        candidato.save()
        registra_log(candidato, tipo=CandidatoLog.TIPO_STATO, campo="Offerta",
                     valore_prima="Inviata", valore_dopo="Rifiutata", user=user)
        registra_cambio_stato(candidato, stato_prima, candidato.stato, user=user, note="Offerta rifiutata.")
        return None

    if candidato.anagrafica_da_completare:
        raise TransizioneError("Il candidato non ha nome né cognome: completa la scheda prima di accettare l'offerta.")
    pratica = candidato.onboarding_pratica if candidato.onboarding_pratica_id else None
    if pratica is None:
        pratica = onboarding_service.avvia_onboarding(
            legacy_id=None,
            dipendente_nome=candidato.nominativo,
            reparto=candidato.posizione.reparto if candidato.posizione_id else "",
            mansione=candidato.mansione_cercata.strip(),
            data_assunzione=candidato.data_assunzione,
            note_hr=f"Pre-ingresso da offerta accettata (candidato #{candidato.pk}).",
            user=user,
            notifica_dpi=False,
        )
        candidato.onboarding_pratica = pratica
    elif data_ingresso and pratica.is_aperta:
        pratica.data_assunzione = data_ingresso
        pratica.save(update_fields=["data_assunzione", "updated_at"])
        onboarding_service.ricalcola_scadenze(pratica)
    candidato.save()
    registra_log(candidato, tipo=CandidatoLog.TIPO_STATO, campo="Offerta",
                 valore_prima="Inviata", valore_dopo="Accettata", user=user,
                 note=f"Pre-ingresso avviato (pratica #{pratica.pk}).")
    return pratica


# ---------------------------------------------------------------------------
# Posizioni aperte
# ---------------------------------------------------------------------------

def aggiorna_copertura(posizione: PosizioneAperta | None) -> bool:
    """Chiude come «Coperta» la posizione che ha raggiunto i posti richiesti."""
    if posizione is None or not posizione.is_attiva:
        return False
    assunti = posizione.candidati.filter(stato=Candidato.STATO_ASSUNTO).count()
    if assunti < posizione.posti:
        return False
    posizione.stato = PosizioneAperta.STATO_COPERTA
    posizione.chiusa_il = timezone.localdate()
    posizione.save(update_fields=["stato", "chiusa_il", "updated_at"])
    return True


def righe_posizioni(qs) -> list[dict]:
    """Posizioni con conteggi per fase, assunti, ritardo: pronte per lista e cruscotto."""
    from django.db.models import Count

    oggi = timezone.localdate()
    posizioni = list(qs)
    conteggi: dict[int, dict[str, int]] = {}
    for riga in (Candidato.objects.filter(posizione__in=posizioni)
                 .values("posizione_id", "stato").annotate(n=Count("id")).order_by()):
        conteggi.setdefault(riga["posizione_id"], {})[riga["stato"]] = riga["n"]
    righe = []
    for p in posizioni:
        per_stato = conteggi.get(p.pk, {})
        assunti = per_stato.get(Candidato.STATO_ASSUNTO, 0)
        in_corso = sum(n for s, n in per_stato.items() if s not in Candidato.STATI_CHIUSI)
        righe.append({
            "posizione": p,
            "candidati": sum(per_stato.values()),
            "in_corso": in_corso,
            "assunti": assunti,
            "offerte": per_stato.get(Candidato.STATO_OFFERTA, 0),
            "in_ritardo": bool(p.is_attiva and p.entro_il and p.entro_il < oggi),
            "giorni_aperta": (oggi - p.data_richiesta).days if p.is_attiva else None,
        })
    return righe


def kpi_posizioni() -> dict:
    """KPI delle posizioni: aperte, in ritardo, coperte negli ultimi 12 mesi, giorni medi di copertura."""
    oggi = timezone.localdate()
    attive = PosizioneAperta.objects.filter(stato__in=PosizioneAperta.STATI_ATTIVI)
    coperte = list(PosizioneAperta.objects.filter(
        stato=PosizioneAperta.STATO_COPERTA, chiusa_il__gte=oggi - timedelta(days=365),
    ))
    giorni = [p.giorni_copertura for p in coperte if p.giorni_copertura is not None]
    return {
        "aperte": attive.count(),
        "posti_aperti": sum(p.posti for p in attive),
        "in_ritardo": attive.filter(entro_il__lt=oggi).count(),
        "coperte_12m": len(coperte),
        "giorni_medi_copertura": round(sum(giorni) / len(giorni)) if giorni else None,
    }


def archivia_in_database(candidato: Candidato, *, user=None) -> None:
    """Chiude l'iter mantenendo il profilo consultabile per future opportunità."""
    stato_prima = candidato.stato
    candidato.stato = Candidato.STATO_IN_DATABASE
    candidato.updated_by = user if (user and getattr(user, "is_authenticated", False)) else None
    candidato.save(update_fields=["stato", "updated_by", "updated_at"])
    registra_cambio_stato(
        candidato, stato_prima, candidato.stato, user=user,
        note="Profilo mantenuto nel database Recruiting.",
    )


def annulla_scheda(candidato: Candidato, *, user=None, motivo: str = "") -> None:
    """Annulla/archivia una scheda: la toglie dalle liste operative senza cancellarla.

    Distinto dagli esiti reali del processo: serve per le schede inserite per
    errore o ritirate amministrativamente. Dati e log restano — la cancellazione
    fisica (che distruggerebbe la traccia di audit) resta riservata a Django
    admin. Il motivo, se dato, finisce nel log come evidenza.
    """
    stato_prima = candidato.stato
    candidato.stato = Candidato.STATO_ANNULLATO
    candidato.updated_by = user if (user and getattr(user, "is_authenticated", False)) else None
    candidato.save(update_fields=["stato", "updated_by", "updated_at"])
    nota = "Scheda annullata/archiviata."
    if motivo.strip():
        nota += f" Motivo: {motivo.strip()[:180]}"
    registra_cambio_stato(candidato, stato_prima, candidato.stato, user=user, note=nota)


def _stato_aperto_dedotto(candidato: Candidato) -> str:
    """Stato aperto coerente coi dati già presenti, per la riapertura dell'iter."""
    if candidato.data_secondo_colloquio:
        return Candidato.STATO_COLLOQUIO_2
    if candidato.data_primo_colloquio or candidato.colloquio_effettuato:
        return Candidato.STATO_COLLOQUIO_1
    if candidato.cv_esito:
        return Candidato.STATO_CV_VALUTATO
    return Candidato.STATO_NUOVO


def riapri_iter(candidato: Candidato, *, user=None) -> str:
    """Riporta una scheda chiusa a uno stato aperto, tracciando la riapertura.

    Rimettere mano a una decisione già presa deve essere un gesto esplicito e
    visibile in audit, non un effetto collaterale della modifica. Il legame con
    l'eventuale pratica di onboarding **non** viene toccato: riaprire serve a
    correggere la scheda, non a disfare un'assunzione già avviata. Ritorna il
    nuovo stato.
    """
    stato_prima = candidato.stato
    candidato.stato = _stato_aperto_dedotto(candidato)
    candidato.updated_by = user if (user and getattr(user, "is_authenticated", False)) else None
    candidato.save(update_fields=["stato", "updated_by", "updated_at"])
    registra_cambio_stato(
        candidato, stato_prima, candidato.stato, user=user, note="Iter riaperto.",
    )
    return candidato.stato


# ---------------------------------------------------------------------------
# KPI di processo
# ---------------------------------------------------------------------------

def calcola_kpi(queryset) -> dict:
    """KPI di processo sul queryset filtrato (evidenze per audit UNI/PdR 125)."""
    from django.db.models import Avg, Count, Q

    candidati = list(
        queryset.values(
            "stato", "canale_provenienza", "mansione_cercata", "giudizio_finale",
            "punteggio_ponderato", "data_primo_colloquio", "data_secondo_colloquio",
        )
    )
    totale = len(candidati)

    positivi = sum(1 for c in candidati if c["giudizio_finale"] == Candidato.GIUDIZIO_POSITIVO)
    negativi = sum(1 for c in candidati if c["giudizio_finale"] == Candidato.GIUDIZIO_NEGATIVO)
    con_giudizio = positivi + negativi
    assunti = sum(1 for c in candidati if c["stato"] == Candidato.STATO_ASSUNTO)

    scarti = [
        (c["data_secondo_colloquio"] - c["data_primo_colloquio"]).days
        for c in candidati
        if c["data_primo_colloquio"] and c["data_secondo_colloquio"]
    ]

    def _pct(parte: int, intero: int) -> float:
        return round(parte * 100.0 / intero, 1) if intero else 0.0

    return {
        "totale": totale,
        "media_ponderata": queryset.aggregate(v=Avg("punteggio_ponderato"))["v"],
        "positivi": positivi,
        "negativi": negativi,
        "pct_positivi": _pct(positivi, con_giudizio),
        "pct_negativi": _pct(negativi, con_giudizio),
        "assunti": assunti,
        "tasso_assunzione": _pct(assunti, totale),
        "giorni_medi_tra_colloqui": round(sum(scarti) / len(scarti), 1) if scarti else None,
        "per_canale": [
            {**riga, "conversione": _pct(riga["assunti"], riga["n"])}
            for riga in queryset.values("canale_provenienza")
            .annotate(n=Count("id"), media=Avg("punteggio_ponderato"),
                      assunti=Count("id", filter=Q(stato=Candidato.STATO_ASSUNTO)))
            .order_by("-n")
        ],
        "offerte": sum(1 for c in candidati if c["stato"] == Candidato.STATO_OFFERTA),
        "per_mansione": list(
            queryset.exclude(mansione_cercata="")
            .values("mansione_cercata")
            .annotate(n=Count("id"), media=Avg("punteggio_ponderato"))
            .order_by("-n")[:15]
        ),
        "per_stato": list(
            queryset.values("stato").annotate(n=Count("id")).order_by("-n")
        ),
    }
