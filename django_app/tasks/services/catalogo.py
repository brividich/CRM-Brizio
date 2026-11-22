"""Catalogo delle voci ricorrenti: punti ODG, azioni, attività, problemi.

Ogni titolo scritto nel modulo entra (o conta un uso in più) e torna come
suggerimento nei campi di testo. In Impostazioni → «Catalogo» si rinomina, si
uniscono i doppioni, si nasconde, si cambiano nota e durata predefinite.
"""
from __future__ import annotations

import logging
import re

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from ..models import CatalogoTipo, CatalogoVoce

logger = logging.getLogger(__name__)


def chiave(testo: str) -> str:
    """Stessa voce anche con maiuscole, spazi e punteggiatura finale diversi."""
    testo = re.sub(r"\s+", " ", (testo or "").strip()).rstrip(".:;,-").strip()
    return testo.casefold()[:220]


def registra_uso(tipo: str, testo: str, *, nota: str = "", durata=None) -> None:
    testo = re.sub(r"\s+", " ", (testo or "").strip())[:220]
    k = chiave(testo)
    if len(k) < 3 or tipo not in CatalogoTipo.values:
        return
    try:
        with transaction.atomic():
            voce = CatalogoVoce.objects.select_for_update().filter(tipo=tipo, chiave=k).first()
            if voce is None:
                CatalogoVoce.objects.create(
                    tipo=tipo, testo=testo, chiave=k, nota=(nota or "")[:500], durata_minuti=durata or None,
                    usi=1, ultimo_uso=timezone.now(),
                )
                return
            campi = {"usi": F("usi") + 1, "ultimo_uso": timezone.now()}
            if nota and not voce.nota:
                campi["nota"] = nota[:500]
            if durata and not voce.durata_minuti:
                campi["durata_minuti"] = durata
            CatalogoVoce.objects.filter(pk=voce.pk).update(**campi)
    except IntegrityError:
        CatalogoVoce.objects.filter(tipo=tipo, chiave=k).update(usi=F("usi") + 1, ultimo_uso=timezone.now())
    except Exception:
        logger.exception("Catalogo: uso non registrato (%s)", tipo)


# Attività del piano e attività d'incontro sono la stessa cosa per chi scrive:
# quello che è stato proposto in un posto deve tornare come suggerimento nell'altro.
_TIPI_ATTIVITA = (CatalogoTipo.ATTIVITA, CatalogoTipo.AZIONE)


def suggerimenti(tipo: str, limite: int = 200) -> list[CatalogoVoce]:
    """Voci da proporre in un campo di testo, le più usate per prime.

    Per le attività l'elenco è uno solo: voci del piano, voci d'incontro e nomi dei
    tipi di attività (Programmazione CAM, Scelta macchina...), senza doppioni.
    """
    if tipo not in _TIPI_ATTIVITA:
        return list(CatalogoVoce.objects.filter(tipo=tipo, attiva=True).order_by("-usi", "testo")[:limite])
    viste: dict[str, CatalogoVoce] = {}
    for voce in CatalogoVoce.objects.filter(tipo__in=_TIPI_ATTIVITA, attiva=True).order_by("-usi", "testo"):
        gia = viste.get(voce.chiave)
        if gia is None:
            viste[voce.chiave] = voce
        else:
            gia.usi += voce.usi  # stessa voce nei due elenchi: conta una volta, con gli usi sommati
    try:
        from ..models import TaskCategory

        for nome in TaskCategory.objects.filter(is_active=True).values_list("name", flat=True):
            k = chiave(nome)
            if k and k not in viste:
                viste[k] = CatalogoVoce(tipo=CatalogoTipo.ATTIVITA, testo=nome, chiave=k, usi=0)
    except Exception:
        logger.exception("Catalogo: tipi di attività non letti")
    return sorted(viste.values(), key=lambda v: (-v.usi, v.testo.casefold()))[:limite]


def unisci(sorgente: CatalogoVoce, destinazione: CatalogoVoce) -> None:
    if sorgente.pk == destinazione.pk or sorgente.tipo != destinazione.tipo:
        raise ValueError("Si uniscono solo voci diverse dello stesso tipo.")
    with transaction.atomic():
        CatalogoVoce.objects.filter(pk=destinazione.pk).update(usi=F("usi") + sorgente.usi)
        if not destinazione.nota and sorgente.nota:
            CatalogoVoce.objects.filter(pk=destinazione.pk).update(nota=sorgente.nota)
        sorgente.delete()
