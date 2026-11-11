"""Catalogo delle specifiche a copertine, una per cliente (stesso stile della libreria CN-SGI).

Solo lettura del database: una query aggregata per cliente, nessun file aperto.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from . import constants as C

SENZA_CLIENTE = "_"
# Stessa famiglia di colori delle copertine CN-SGI, leggibili col testo bianco in chiaro e in scuro.
COLORI = ("#1f4f86", "#0f766e", "#b45309", "#7e3a8a", "#2a6f97", "#9b2c2c", "#3f6212", "#4c51bf", "#a16207", "#0e7490", "#be185d", "#475569")
_FORME = re.compile(r"\b(s\.?\s?p\.?\s?a\.?|s\.?\s?r\.?\s?l\.?s?|s\.?\s?a\.?\s?s\.?|s\.?\s?n\.?\s?c\.?|ltd\.?|inc\.?|gmbh|s\.?\s?a\.?|spa|srl|group|holding)\b", re.I)


@dataclass
class Copertina:
    cliente: str
    sigla: str
    nome: str
    colore: str
    totale: int = 0
    bozze: int = 0
    flow_down: int = 0
    in_validita: int = 0
    sospese: int = 0
    nuove: int = 0
    verifica_scad: int = 0
    cartella_share: str = ""

    @property
    def chiave(self) -> str:
        return self.cliente or SENZA_CLIENTE


def colore_di(cliente: str) -> str:
    if not cliente:
        return "#64748b"
    h = hashlib.md5(re.sub(r"\W+", "", cliente.lower()).encode("utf-8"), usedforsecurity=False).digest()
    return COLORI[h[0] % len(COLORI)]


def sigla_di(cliente: str) -> str:
    """La parola principale del cliente, senza forma societaria (es. «Alfa Aerospace S.p.A.» → «ALFA»)."""
    pulito = _FORME.sub(" ", cliente or "").strip(" .,-")
    parole = [p for p in re.split(r"[\s/,]+", pulito) if p]
    if not parole:
        return (cliente or "—")[:10].upper()
    return parole[0][:10].upper()


def copertine(*, storico: bool = False, scadenza_giorni: int = 30) -> list[Copertina]:
    from .models import ClienteCartellaShare, Specifica

    qs = Specifica.objects.all()
    if not storico:
        qs = qs.filter(stato__in=C.STATI_ATTIVI)
    oggi = timezone.localdate()
    limite = oggi + timedelta(days=scadenza_giorni)
    righe = (
        qs.values("cliente").order_by()
        .annotate(
            totale=Count("id"),
            bozze=Count("id", filter=Q(stato=C.STATO_BOZZA)),
            flow_down=Count("id", filter=Q(stato=C.STATO_FLOW_DOWN)),
            in_validita=Count("id", filter=Q(stato=C.STATO_IN_VALIDITA)),
            sospese=Count("id", filter=Q(stato=C.STATO_SOSPESO)),
            nuove=Count("id", filter=Q(data_inserimento__date__gte=oggi - timedelta(days=30))),
            verifica_scad=Count("id", filter=Q(stato=C.STATO_IN_VALIDITA, data_verifica__isnull=False, data_verifica__lte=limite)),
        )
    )
    cartelle = {c.cliente.strip().lower(): c.cartella for c in ClienteCartellaShare.objects.all()}
    per_cliente: dict[str, Copertina] = {}
    for r in righe:
        nome = (r["cliente"] or "").strip()
        chiave = nome.lower()
        cop = per_cliente.get(chiave)
        if cop is None:
            cop = per_cliente[chiave] = Copertina(
                cliente=nome, sigla=sigla_di(nome) if nome else "—", nome=nome or "Senza cliente",
                colore=colore_di(nome), cartella_share=cartelle.get(chiave, ""),
            )
        for campo in ("totale", "bozze", "flow_down", "in_validita", "sospese", "nuove", "verifica_scad"):
            setattr(cop, campo, getattr(cop, campo) + r[campo])
    return sorted(per_cliente.values(), key=lambda c: (not c.cliente, c.nome.lower()))


def copertina_di(cliente: str, *, storico: bool = False, scadenza_giorni: int = 30) -> Copertina | None:
    chiave = "" if cliente == SENZA_CLIENTE else cliente.strip().lower()
    return next((c for c in copertine(storico=storico, scadenza_giorni=scadenza_giorni) if c.cliente.lower() == chiave), None)
