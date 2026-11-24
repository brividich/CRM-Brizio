"""Modifiche fatte dal diagramma dell'organigramma (modalità «Modifica»).

Ogni azione scrive la fonte vera, non un disegno a parte:

- **sposta** cambia ``RuoloOperativo.riporta_a`` (vale anche per Albero, capi e team);
- **assegna** / **togli** aprono o chiudono l'assegnazione del ruolo
  (``DipendenteRuoloOperativo``): togliere *chiude* con la data di ieri, lo
  storico resta;
- le **sezioni** (:class:`OrganigrammaSezione`) sono solo raggruppamenti visivi.

Le funzioni sollevano :class:`ModificaNonValida` con un messaggio per l'utente;
la vista lo restituisce in JSON. Il permesso lo controlla la vista.
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import (
    DipendenteRuoloOperativo,
    OrganigrammaSezione,
    OrganigrammaSezioneMembro,
    RuoloOperativo,
)

_COLORE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ModificaNonValida(ValueError):
    """Azione rifiutata: il messaggio va mostrato all'utente così com'è."""


def _ruolo(ruolo_id) -> RuoloOperativo:
    ruolo = RuoloOperativo.objects.filter(pk=ruolo_id, is_active=True).first()
    if ruolo is None:
        raise ModificaNonValida("Ruolo non trovato o non più attivo.")
    return ruolo


def _crea_ciclo(ruolo_id: int, padre_id: int) -> bool:
    if padre_id == ruolo_id:
        return True
    visti: set[int] = set()
    corrente = padre_id
    while corrente and corrente not in visti:
        if corrente == ruolo_id:
            return True
        visti.add(corrente)
        corrente = RuoloOperativo.objects.filter(pk=corrente).values_list("riporta_a_id", flat=True).first()
    return False


def _togli_da_sezioni(ruolo_id: int) -> None:
    """Il ruolo cambia genitore: le sezioni del genitore vecchio non lo contengono più."""
    OrganigrammaSezioneMembro.objects.filter(ruolo_id=ruolo_id).delete()


@transaction.atomic
def sposta(ruolo_id, padre_id) -> tuple[RuoloOperativo, RuoloOperativo | None]:
    """``ruolo`` riporta a ``padre`` (``None`` = diventa una radice)."""
    ruolo = _ruolo(ruolo_id)
    padre = _ruolo(padre_id) if padre_id else None
    if padre is not None and _crea_ciclo(ruolo.pk, padre.pk):
        raise ModificaNonValida(
            f"«{ruolo.nome}» non può riportare a «{padre.nome}»: "
            "chiuderebbe un cerchio nella gerarchia."
        )
    if ruolo.riporta_a_id != (padre.pk if padre else None):
        ruolo.riporta_a = padre
        ruolo.save(update_fields=["riporta_a"])
        _togli_da_sezioni(ruolo.pk)
    return ruolo, padre


@transaction.atomic
def assegna(ruolo_id, legacy_id: int, *, user=None) -> tuple[RuoloOperativo, bool]:
    """Apre (o riapre) l'assegnazione del ruolo alla persona. Ritorna (ruolo, creata)."""
    from .ruoli_sync import dopo_assegnazione

    ruolo = _ruolo(ruolo_id)
    if not legacy_id:
        raise ModificaNonValida("Scegli la persona da assegnare.")
    from core.persone_tendine import cessati_anagrafica_ids

    if legacy_id in cessati_anagrafica_ids():
        raise ModificaNonValida("La persona non è più in forza.")
    assegnazione, creata = DipendenteRuoloOperativo.objects.get_or_create(
        legacy_anagrafica_id=legacy_id, ruolo=ruolo,
        defaults={"assegnato_da": user if getattr(user, "pk", None) else None,
                  "data_inizio": timezone.localdate()},
    )
    if not creata:
        if assegnazione.data_fine is None or assegnazione.data_fine >= timezone.localdate():
            raise ModificaNonValida("La persona ricopre già questo ruolo.")
        assegnazione.data_fine = None
        assegnazione.data_inizio = timezone.localdate()
        # save(), non update(): i segnali azzerano la cache di permessi e team.
        assegnazione.save(update_fields=["data_fine", "data_inizio"])
    dopo_assegnazione(legacy_id, ruolo, user=user)
    return ruolo, creata


@transaction.atomic
def togli(ruolo_id, legacy_id: int, *, user=None) -> RuoloOperativo:
    """Chiude l'assegnazione in corso con la data di ieri: da oggi la posizione è libera."""
    from .ruoli_sync import dopo_rimozione

    ruolo = _ruolo(ruolo_id)
    oggi = timezone.localdate()
    assegnazione = (
        DipendenteRuoloOperativo.objects
        .filter(legacy_anagrafica_id=legacy_id, ruolo=ruolo)
        .exclude(data_fine__lt=oggi)
        .first()
    )
    if assegnazione is None:
        raise ModificaNonValida("La persona non ricopre questo ruolo.")
    ieri = oggi - timedelta(days=1)
    if assegnazione.data_inizio and assegnazione.data_inizio > ieri:
        # Assegnata oggi (o con decorrenza futura): un periodo vuoto non è storia.
        assegnazione.delete()
    else:
        assegnazione.data_fine = ieri
        assegnazione.save(update_fields=["data_fine"])
    OrganigrammaSezioneMembro.objects.filter(ruolo=ruolo, legacy_anagrafica_id=legacy_id).delete()
    dopo_rimozione(legacy_id, ruolo.nome, user=user)
    return ruolo


def _nome_colore(nome, colore) -> tuple[str, str]:
    nome = (nome or "").strip()[:80]
    if not nome:
        raise ModificaNonValida("Dai un nome alla sezione.")
    colore = (colore or "").strip()
    return nome, colore if _COLORE.match(colore) else "#2563eb"


def sezione_crea(ruolo_padre_id, nome, colore, *, user=None) -> OrganigrammaSezione:
    padre = _ruolo(ruolo_padre_id)
    nome, colore = _nome_colore(nome, colore)
    if OrganigrammaSezione.objects.filter(ruolo_padre=padre, nome__iexact=nome).exists():
        raise ModificaNonValida(f"Sotto «{padre.nome}» c'è già una sezione «{nome}».")
    ultimo = OrganigrammaSezione.objects.filter(ruolo_padre=padre).order_by("-ordine").values_list(
        "ordine", flat=True).first()
    return OrganigrammaSezione.objects.create(
        ruolo_padre=padre, nome=nome, colore=colore, ordine=(ultimo or 0) + 10,
        creata_da=user if getattr(user, "pk", None) else None,
    )


def sezione_modifica(sezione_id, nome, colore) -> OrganigrammaSezione:
    sezione = OrganigrammaSezione.objects.filter(pk=sezione_id).first()
    if sezione is None:
        raise ModificaNonValida("Sezione non trovata.")
    nome, colore = _nome_colore(nome, colore)
    if (OrganigrammaSezione.objects.filter(ruolo_padre_id=sezione.ruolo_padre_id, nome__iexact=nome)
            .exclude(pk=sezione.pk).exists()):
        raise ModificaNonValida(f"C'è già una sezione «{nome}» sotto lo stesso ruolo.")
    sezione.nome, sezione.colore = nome, colore
    sezione.save(update_fields=["nome", "colore", "aggiornata_il"])
    return sezione


def sezione_elimina(sezione_id) -> str:
    """Elimina la sezione; le sue tessere tornano libere sotto lo stesso ruolo."""
    sezione = OrganigrammaSezione.objects.filter(pk=sezione_id).first()
    if sezione is None:
        raise ModificaNonValida("Sezione non trovata.")
    nome = sezione.nome
    sezione.delete()
    return nome


@transaction.atomic
def metti_in_sezione(sezione_id, ruolo_id, legacy_id: int = 0) -> tuple[OrganigrammaSezione | None, bool]:
    """Mette la tessera nella sezione (``sezione_id`` vuoto = la toglie da ogni sezione).

    Se la sezione sta sotto un altro ruolo, la tessera si sposta anche nella
    gerarchia: ritorna (sezione, spostato) perché la vista lo dica all'utente.
    Una persona di un ruolo con più titolari entra da sola solo se il ruolo non
    ha riporti; altrimenti entra il ruolo intero (la tessera è una sola).
    """
    ruolo = _ruolo(ruolo_id)
    legacy_id = int(legacy_id or 0)
    if not sezione_id:
        OrganigrammaSezioneMembro.objects.filter(ruolo=ruolo, legacy_anagrafica_id=legacy_id).delete()
        return None, False
    sezione = OrganigrammaSezione.objects.select_related("ruolo_padre").filter(pk=sezione_id).first()
    if sezione is None:
        raise ModificaNonValida("Sezione non trovata.")
    spostato = False
    if ruolo.riporta_a_id != sezione.ruolo_padre_id:
        sposta(ruolo.pk, sezione.ruolo_padre_id)
        spostato = True
    OrganigrammaSezioneMembro.objects.update_or_create(
        ruolo=ruolo, legacy_anagrafica_id=legacy_id, defaults={"sezione": sezione},
    )
    return sezione, spostato
