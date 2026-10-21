"""Rinomina e accorpamento di ruoli senza perdere storico, permessi e collegamenti.

- **rinomina**: il ruolo cambia nome (e sigla); persone, permessi, gerarchia e
  collegamenti restano perché sono legati per id. Il «Ruolo aziendale» della
  scheda è un testo abbinato per nome: si riscrive anche quello. Il vecchio nome
  resta in ``nomi_precedenti``.
- **accorpa**: un ruolo confluisce in un altro (l'«ospite»). Chi lo ricopre
  riceve l'ospite da oggi e il vecchio si chiude ieri (il periodo resta nello
  storico); permessi del portale, regole e collegamenti passano all'ospite; il
  vecchio si spegne. Nulla viene cancellato salvo i doppioni di configurazione
  che l'ospite ha già.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from ..models import DipendenteAnagraficaAziendale, DipendenteRuoloOperativo, RuoloOperativo

logger = logging.getLogger(__name__)


def _aggiungi_nome_precedente(ruolo: RuoloOperativo, nome: str) -> None:
    nome = (nome or "").strip()
    if not nome or nome.casefold() == (ruolo.nome or "").casefold():
        return
    righe = [r.strip() for r in (ruolo.nomi_precedenti or "").splitlines() if r.strip()]
    if nome.casefold() not in {r.casefold() for r in righe}:
        righe.append(nome)
    ruolo.nomi_precedenti = "\n".join(righe)


def _riscrivi_testo_scheda(vecchio_nome: str, nuovo_nome: str, *, user=None) -> int:
    """Il «Ruolo aziendale» della scheda (testo) segue il nome del ruolo."""
    vecchio_nome = (vecchio_nome or "").strip()
    if not vecchio_nome or vecchio_nome.casefold() == (nuovo_nome or "").strip().casefold():
        return 0
    n = 0
    for az in DipendenteAnagraficaAziendale.objects.filter(ruolo_aziendale__iexact=vecchio_nome):
        az.ruolo_aziendale = (nuovo_nome or "")[:200]
        if user is not None and getattr(user, "pk", None):
            az.updated_by = user
            az.save(update_fields=["ruolo_aziendale", "updated_by", "updated_at"])
        else:
            az.save(update_fields=["ruolo_aziendale", "updated_at"])
        n += 1
    return n


@transaction.atomic
def rinomina(ruolo: RuoloOperativo, nuovo_nome: str, *, sigla=None, user=None) -> dict:
    """Cambia nome (e, se data, sigla) del ruolo. Ritorna i conteggi."""
    nuovo_nome = " ".join((nuovo_nome or "").split())[:100]
    if not nuovo_nome:
        raise ValueError("Il nome del ruolo non può essere vuoto.")
    if RuoloOperativo.objects.filter(nome__iexact=nuovo_nome).exclude(pk=ruolo.pk).exists():
        raise ValueError(f"Esiste già un ruolo «{nuovo_nome}».")
    vecchio = ruolo.nome
    schede = 0
    if vecchio != nuovo_nome:
        ruolo.nome = nuovo_nome
        _aggiungi_nome_precedente(ruolo, vecchio)
        schede = _riscrivi_testo_scheda(vecchio, nuovo_nome, user=user)
    if sigla is not None:
        sigla = (sigla or "").strip().upper() or None
        if sigla and RuoloOperativo.objects.filter(sigla=sigla).exclude(pk=ruolo.pk).exists():
            raise ValueError(f"La sigla {sigla} è già di un altro ruolo.")
        ruolo.sigla = sigla
    ruolo.save()
    return {"nome_prima": vecchio if vecchio != nuovo_nome else None, "schede": schede}


def _sposta_collegamenti(vecchio: RuoloOperativo, ospite: RuoloOperativo) -> dict:
    """Ogni FK/M2M verso il vecchio ruolo passa all'ospite (scoperta dal modello,
    così un collegamento aggiunto domani in un altro modulo non resta indietro)."""
    conta = {"fk": 0, "m2m": 0, "doppioni": 0}
    for rel in RuoloOperativo._meta.related_objects:
        modello, campo = rel.related_model, rel.field.name
        if modello is DipendenteRuoloOperativo:
            continue  # le persone si trattano a parte, con le date
        if modello is RuoloOperativo and campo == "riporta_a":
            for figlio in RuoloOperativo.objects.filter(riporta_a=vecchio):
                figlio.riporta_a = None if figlio.pk == ospite.pk else ospite
                figlio.save(update_fields=["riporta_a"])
                conta["fk"] += 1
            continue
        if rel.many_to_many:
            for obj in modello.objects.filter(**{campo: vecchio}):
                gestore = getattr(obj, campo)
                gestore.add(ospite)
                gestore.remove(vecchio)
                conta["m2m"] += 1
            continue
        if rel.one_to_many or rel.one_to_one:
            for obj in modello.objects.filter(**{campo: vecchio}):
                try:
                    with transaction.atomic():
                        setattr(obj, campo, ospite)
                        obj.save(update_fields=[campo])
                    conta["fk"] += 1
                except IntegrityError:
                    # L'ospite ha già la stessa riga (es. stessa qualifica richiesta): resta la sua.
                    obj.delete()
                    conta["doppioni"] += 1
    return conta


@transaction.atomic
def accorpa(vecchio: RuoloOperativo, ospite: RuoloOperativo, *, user=None, oggi=None) -> dict:
    """Il ruolo ``vecchio`` confluisce in ``ospite``. Ritorna i conteggi."""
    from . import ruoli_sync

    if vecchio.pk == ospite.pk:
        raise ValueError("Un ruolo non si accorpa in sé stesso.")
    oggi = oggi or timezone.localdate()
    ieri = oggi - timedelta(days=1)
    conta = {"persone": 0, "principali": 0}

    # Persone: l'ospite da oggi (stessa tipologia), il vecchio si chiude ieri.
    in_essere = DipendenteRuoloOperativo.objects.filter(
        Q(data_fine__isnull=True) | Q(data_fine__gte=oggi), ruolo=vecchio,
    )
    for a in list(in_essere):
        lid = a.legacy_anagrafica_id
        era_principale = (ruoli_sync.ruolo_principale(lid).casefold() == (vecchio.nome or "").casefold()
                          or a.tipologia == DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE)
        nuova, creata = DipendenteRuoloOperativo.objects.get_or_create(
            legacy_anagrafica_id=lid, ruolo=ospite,
            defaults={"tipologia": a.tipologia, "data_inizio": oggi,
                      "assegnato_da": user if getattr(user, "pk", None) else None},
        )
        if not creata and (nuova.is_conclusa or nuova.data_fine):
            nuova.data_fine = None
            nuova.data_inizio = oggi
            nuova.save(update_fields=["data_fine", "data_inizio"])
        if a.tipologia == DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE and nuova.tipologia != a.tipologia:
            nuova.tipologia = a.tipologia
            nuova.save(update_fields=["tipologia"])
        a.data_fine = max(ieri, a.data_inizio) if a.data_inizio else ieri
        a.save(update_fields=["data_fine"])
        if era_principale and ruoli_sync.alimenta_principale(ospite):
            ruoli_sync._scrivi_principale(lid, ospite.nome, user=user)
            conta["principali"] += 1
        conta["persone"] += 1
    # Schede col vecchio nome senza assegnazione (valori storici): stesso testo nuovo.
    conta["schede_testo"] = _riscrivi_testo_scheda(vecchio.nome, ospite.nome, user=user)

    # Permessi del portale: l'ospite li somma (nessuno perde accessi).
    profili = list(vecchio.profili_permessi.all())
    if profili:
        ospite.profili_permessi.add(*profili)
    conta["profili"] = len(profili)
    conta.update(_sposta_collegamenti(vecchio, ospite))

    _aggiungi_nome_precedente(ospite, vecchio.nome)
    for nome in (vecchio.nomi_precedenti or "").splitlines():
        _aggiungi_nome_precedente(ospite, nome)
    ospite.save(update_fields=["nomi_precedenti"])
    vecchio.is_active = False
    vecchio.sigla = None
    vecchio.save(update_fields=["is_active", "sigla"])
    return conta
