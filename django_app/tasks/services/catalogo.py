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


def suggerimenti(tipo: str, limite: int = 200) -> list[CatalogoVoce]:
    return list(CatalogoVoce.objects.filter(tipo=tipo, attiva=True).order_by("-usi", "testo")[:limite])


def unisci(sorgente: CatalogoVoce, destinazione: CatalogoVoce) -> None:
    if sorgente.pk == destinazione.pk or sorgente.tipo != destinazione.tipo:
        raise ValueError("Si uniscono solo voci diverse dello stesso tipo.")
    with transaction.atomic():
        CatalogoVoce.objects.filter(pk=destinazione.pk).update(usi=F("usi") + sorgente.usi)
        if not destinazione.nota and sorgente.nota:
            CatalogoVoce.objects.filter(pk=destinazione.pk).update(nota=sorgente.nota)
        sorgente.delete()
