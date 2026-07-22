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
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Mapping

from django.db import transaction
from django.utils import timezone

from ..models_recruiting import (
    Candidato,
    CandidatoLog,
    CandidatoPunteggio,
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

    Ritorna la ``OnboardingPratica``.
    """
    if candidato.onboarding_pratica_id:
        return candidato.onboarding_pratica

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

    pratica = onboarding_service.pratica_aperta(legacy_id) or onboarding_service.avvia_onboarding(
        legacy_id=legacy_id,
        dipendente_nome=candidato.nominativo or f"#{legacy_id}",
        reparto=reparto.strip(),
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
    return pratica


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


# ---------------------------------------------------------------------------
# KPI di processo
# ---------------------------------------------------------------------------

def calcola_kpi(queryset) -> dict:
    """KPI di processo sul queryset filtrato (evidenze per audit UNI/PdR 125)."""
    from django.db.models import Avg, Count

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
        "per_canale": list(
            queryset.values("canale_provenienza")
            .annotate(n=Count("id"), media=Avg("punteggio_ponderato"))
            .order_by("-n")
        ),
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
