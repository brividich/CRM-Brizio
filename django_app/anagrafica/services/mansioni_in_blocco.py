"""Mansioni per più persone insieme, con anteprima (27/10/2026); e più mansioni
alla stessa persona (``assegna_mansioni``, scheda persona del Mansionario).

Gemello di ``ruoli_in_blocco`` per il Mansionario: assegnare una mansione con
un livello o toglierla, sullo stesso percorso della scheda della mansione
(``mansionario_struttura.assegna`` / ``togli``: storico compreso). Ogni
persona si registra nel suo savepoint: un errore su una non ferma le altre.
"""
from __future__ import annotations

from django.db import DatabaseError, transaction

from ..models import AbilitazioneMacchina, CompetenzaSkm
from . import mansionario_struttura as mstr
from .ruoli_in_blocco import MAX_PERSONE, Esito

ASSEGNA, TOGLI = "assegna", "togli"
MODI = {
    ASSEGNA: "Assegna la mansione",
    TOGLI: "Togli la mansione",
}
LIVELLI = {"I": "I · in formazione", "L": "L · intermedio", "U": "U · autonomo", "O": "O · esperto"}


def in_lista(mansione: CompetenzaSkm, legacy_ids) -> dict[int, AbilitazioneMacchina]:
    """``legacy_id`` → abilitazione in lista sulla mansione (stessa chiave di ``assegna``)."""
    chiave = {"asset_id": mansione.asset_id} if mansione.asset_id else {"competenza": mansione}
    return {a.legacy_anagrafica_id: a for a in AbilitazioneMacchina.objects.filter(
        legacy_anagrafica_id__in=list(legacy_ids), in_lista=True, **chiave)}


def previsione(ab: AbilitazioneMacchina | None, modo: str, livello: str,
               classificazione: str = "") -> tuple[str, str]:
    """(azione, dettaglio) senza scrivere niente. Classificazione vuota = non si tocca."""
    from .mansioni_coefficienti import CLASSIFICAZIONI

    if modo == ASSEGNA:
        etichetta = CLASSIFICAZIONI.get(classificazione, "")
        if ab is None:
            return "cambia", f"assegnata, livello {livello}" + (f", {etichetta}" if etichetta else "")
        cambi = []
        if (ab.livello or "") != livello:
            cambi.append(f"livello {ab.livello or '—'} → {livello}")
        if classificazione and ab.classificazione != classificazione:
            cambi.append(f"{CLASSIFICAZIONI.get(ab.classificazione, 'non classificata')} → {etichetta}")
        if not cambi:
            return "salta", f"ce l'ha già, livello {livello}" + (f", {etichetta}" if etichetta else "")
        return "cambia", ", ".join(cambi)
    if ab is None:
        return "salta", "non è in lista"
    return "cambia", "tolta dalla lista (lo storico resta)"


def _controlla(mansione, modo: str, livello: str) -> None:
    if modo not in MODI:
        raise ValueError("Scegli che cosa fare.")
    if mansione is None:
        raise ValueError("Scegli la mansione.")
    if modo == ASSEGNA and livello not in LIVELLI:
        raise ValueError("Scegli il livello (I, L, U, O).")
    if modo == ASSEGNA and not mansione.attiva:
        raise ValueError(f"La mansione «{mansione.nome}» è spenta.")


def esegui(legacy_ids, *, mansione: CompetenzaSkm, modo: str, livello: str = "", user=None,
           applica: bool = False, classificazione: str = "") -> list[Esito]:
    """Anteprima (``applica=False``) o registrazione per ogni persona scelta."""
    from .mansioni_coefficienti import leggi_classificazione
    from .ruoli_in_blocco import persone

    livello = (livello or "").strip().upper()
    classificazione = leggi_classificazione(classificazione) if modo == ASSEGNA else ""
    _controlla(mansione, modo, livello)
    ids = list(dict.fromkeys(int(i) for i in legacy_ids))
    if not ids:
        raise ValueError("Scegli almeno una persona.")
    if len(ids) > MAX_PERSONE:
        raise ValueError(f"Al massimo {MAX_PERSONE} persone alla volta.")
    per_id = {p["legacy_id"]: p for p in persone()}
    attuali = in_lista(mansione, ids)
    esiti = []
    for lid in ids:
        p = per_id.get(lid)
        if p is None:
            esiti.append(Esito(lid, f"#{lid}", "", "errore", "non è un dipendente attivo"))
            continue
        ab = attuali.get(lid)
        azione, dettaglio = previsione(ab, modo, livello, classificazione)
        if applica and azione == "cambia":
            try:
                with transaction.atomic():
                    if modo == ASSEGNA:
                        nuova = mstr.assegna(mansione, legacy_anagrafica_id=lid, livello=livello, user=user)
                        if classificazione and nuova.classificazione != classificazione:
                            AbilitazioneMacchina.objects.filter(pk=nuova.pk).update(classificazione=classificazione)
                    else:
                        mstr.togli(ab)
            except (ValueError, DatabaseError) as exc:  # una persona non ferma le altre; il motivo si mostra
                azione, dettaglio = "errore", str(exc) or exc.__class__.__name__
        prima = f"{ab.livello or '—'}" if ab else "non in lista"
        esiti.append(Esito(lid, p["nome"], prima, azione, dettaglio))
    return esiti


def mansioni_assegnabili(legacy_id: int) -> list[CompetenzaSkm]:
    """Mansioni attive che la persona non ha in lista, da offrire nella sua scheda.

    Le responsabilità restano fuori: chi le ha è il capo, si assegnano da
    «Reparti, aree e capi».
    """
    gia = set(AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_id, in_lista=True,
                                                  competenza__isnull=False).values_list("competenza_id", flat=True))
    qs = (CompetenzaSkm.objects.filter(tipo__in=mstr.TIPI_MANSIONE, attiva=True,
                                       responsabilita_reparto__isnull=True, responsabilita_area__isnull=True)
          .exclude(pk__in=gia).select_related("asset", "reparto").prefetch_related("ruoli"))
    return sorted(qs, key=lambda m: m.nome.casefold())


def assegna_mansioni(legacy_id: int, mansioni_ids, *, livello: str, user=None) -> list[tuple[CompetenzaSkm, str, str]]:
    """Più mansioni alla stessa persona, stesso livello di partenza.

    Rovescio di ``esegui``: stesso percorso (``mansionario_struttura.assegna``, storico
    compreso), un savepoint per mansione. Esito per mansione: (mansione, azione, dettaglio).
    """
    livello = (livello or "").strip().upper()
    if livello not in LIVELLI:
        raise ValueError("Scegli il livello (I, L, U, O).")
    ids = list(dict.fromkeys(int(i) for i in mansioni_ids))
    if not ids:
        raise ValueError("Scegli almeno una mansione.")
    mansioni = {m.pk: m for m in CompetenzaSkm.objects.filter(pk__in=ids, tipo__in=mstr.TIPI_MANSIONE)}
    gia = {a.competenza_id: a for a in AbilitazioneMacchina.objects.filter(
        legacy_anagrafica_id=legacy_id, in_lista=True, competenza_id__in=ids)}
    esiti = []
    for mid in ids:
        m = mansioni.get(mid)
        if m is None:
            continue
        if not m.attiva:
            esiti.append((m, "errore", "mansione spenta"))
            continue
        if m.is_responsabilita:
            esiti.append((m, "errore", "è una responsabilità: si assegna da «Reparti, aree e capi»"))
            continue
        if mid in gia:
            esiti.append((m, "salta", f"ce l'ha già, livello {gia[mid].livello or '—'}"))
            continue
        try:
            with transaction.atomic():
                mstr.assegna(m, legacy_anagrafica_id=legacy_id, livello=livello, user=user)
        except (ValueError, DatabaseError) as exc:  # una mansione non ferma le altre
            esiti.append((m, "errore", str(exc) or exc.__class__.__name__))
            continue
        esiti.append((m, "cambia", f"assegnata, livello {livello}"))
    return esiti
