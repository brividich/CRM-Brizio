"""Catalogo delle specifiche a copertine, una per cartella della share (stile libreria CN-SGI).

La cartella di primo livello sotto ``GESTIONE_SPECIFICHE_SHARE_ROOTS`` è l'organizzazione
reale (cliente o categoria). Una specifica sta nella cartella del suo PDF collegato; senza
PDF, nella cartella mappata al suo cliente («Mappatura cliente-cartella»); altrimenti in
«Senza cartella». Una sola funzione (:func:`cartella_di`) decide, per copertine, filtro e
conteggi. Solo database: nessun file aperto.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from . import constants as C

SENZA_CARTELLA = "_"
SENZA_CLIENTE = SENZA_CARTELLA  # nome storico del parametro
COLORI = ("#1f4f86", "#0f766e", "#b45309", "#7e3a8a", "#2a6f97", "#9b2c2c", "#3f6212", "#4c51bf", "#a16207", "#0e7490", "#be185d", "#475569")
_FORME = re.compile(r"\b(s\.?\s?p\.?\s?a\.?|s\.?\s?r\.?\s?l\.?s?|s\.?\s?a\.?\s?s\.?|s\.?\s?n\.?\s?c\.?|ltd\.?|inc\.?|gmbh|s\.?\s?a\.?|spa|srl|group|holding)\b", re.I)


@dataclass
class Copertina:
    cartella: str
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
    clienti: tuple = ()
    icona: str = ""
    logo_url: str = ""
    personalizzata: object = None  # CopertinaCliente, se c'è

    @property
    def chiave(self) -> str:
        return self.cartella or SENZA_CARTELLA

    @property
    def cliente(self) -> str:
        """Cliente da proporre in «Nuova per …»: quello mappato alla cartella, o il nome della cartella."""
        return self.clienti[0] if self.clienti else self.cartella


def colore_di(nome: str) -> str:
    if not nome:
        return "#64748b"
    h = hashlib.md5(re.sub(r"\W+", "", nome.lower()).encode("utf-8"), usedforsecurity=False).digest()
    return COLORI[h[0] % len(COLORI)]


def sigla_di(nome: str) -> str:
    """La parola principale, senza forma societaria (es. «FERRARI - FERRARI GES» → «FERRARI»)."""
    pulito = _FORME.sub(" ", nome or "").strip(" .,-")
    parole = [p for p in re.split(r"[\s/,\-]+", pulito) if p]
    if not parole:
        return (nome or "—")[:10].upper()
    return parole[0][:10].upper()


def _mappa_clienti() -> dict[str, str]:
    """cliente (minuscolo) → cartella di primo livello, dalla mappatura confermata."""
    from .models import ClienteCartellaShare

    out = {}
    for m in ClienteCartellaShare.objects.filter(attivo=True).only("cliente", "cartella"):
        top = (m.cartella or "").replace("/", "\\").strip("\\").split("\\")[0].strip()
        if top:
            out[(m.cliente or "").strip().lower()] = top
    return out


def cartella_di(percorso: str, cliente: str, mappa: dict[str, str]) -> str:
    """La cartella (nome com'è sulla share) a cui appartiene una specifica; '' = senza cartella."""
    if percorso:
        from .share_write import cartella_top_da_percorso

        top = cartella_top_da_percorso(percorso)
        if top:
            return top
        parti = [p for p in str(percorso).replace("/", "\\").split("\\") if p]
        if len(parti) >= 2:
            return parti[-2]
    return mappa.get((cliente or "").strip().lower(), "")


def _righe(storico: bool):
    from .models import Specifica

    qs = Specifica.objects.all()
    if not storico:
        qs = qs.filter(stato__in=C.STATI_ATTIVI)
    return qs.values_list("pk", "percorso_esterno", "cliente", "stato", "data_inserimento", "data_verifica")


def q_della_cartella(chiave: str):
    """Filtro database delle specifiche di una cartella (stessa regola di :func:`cartella_di`).

    Niente elenchi di id: su SQL Server un ``IN`` con migliaia di valori supera il limite di parametri.
    """
    from django.db.models import Q

    mappa = _mappa_clienti()
    if chiave == SENZA_CARTELLA:
        q = Q(percorso_esterno="")
        for cliente in mappa:
            q &= ~Q(cliente__iexact=cliente)
        return q
    nome = chiave.strip()
    q = Q(percorso_esterno__icontains="\\" + nome + "\\")
    senza_file = Q()
    for cliente, top in mappa.items():
        if top.lower() == nome.lower():
            senza_file |= Q(cliente__iexact=cliente)
    if senza_file:
        q |= Q(percorso_esterno="") & senza_file
    return q


def copertine(*, storico: bool = False, scadenza_giorni: int = 30) -> list[Copertina]:
    from .models import CopertinaCliente

    mappa = _mappa_clienti()
    clienti_per_cartella: dict[str, list[str]] = {}
    for cliente, top in mappa.items():
        clienti_per_cartella.setdefault(top.lower(), []).append(cliente)
    oggi = timezone.localdate()
    limite = oggi + timedelta(days=scadenza_giorni)
    nuove_dal = oggi - timedelta(days=30)
    per_cartella: dict[str, Copertina] = {}
    for _pk, path, cliente, stato, inserita, verifica in _righe(storico):
        nome = cartella_di(path, cliente, mappa)
        k = nome.lower()
        cop = per_cartella.get(k)
        if cop is None:
            cop = per_cartella[k] = Copertina(
                cartella=nome, sigla=sigla_di(nome) if nome else "—", nome=nome or "Senza cartella",
                colore=colore_di(nome),
            )
        cop.totale += 1
        cop.bozze += stato == C.STATO_BOZZA
        cop.flow_down += stato == C.STATO_FLOW_DOWN
        cop.in_validita += stato == C.STATO_IN_VALIDITA
        cop.sospese += stato == C.STATO_SOSPESO
        if inserita and timezone.localdate(inserita) >= nuove_dal:
            cop.nuove += 1
        if stato == C.STATO_IN_VALIDITA and verifica and verifica <= limite:
            cop.verifica_scad += 1
    from .models import ClienteCartellaShare

    nomi_clienti = {c.cliente.strip().lower(): c.cliente for c in ClienteCartellaShare.objects.filter(attivo=True)}
    for k, cop in per_cartella.items():
        cop.clienti = tuple(nomi_clienti.get(c, c) for c in clienti_per_cartella.get(k, []))
    for p in CopertinaCliente.objects.filter(chiave__in=list(per_cartella)):
        applica_personalizzazione(per_cartella[p.chiave], p)
    return sorted(per_cartella.values(), key=lambda c: (not c.cartella, c.nome.lower()))


def applica_personalizzazione(cop: Copertina, p) -> None:
    from django.urls import reverse

    cop.personalizzata = p
    if p.colore:
        cop.colore = p.colore
    if p.sigla:
        cop.sigla = p.sigla
    cop.icona = p.icona or ""
    if p.logo:
        versione = int(p.aggiornata_il.timestamp()) if p.aggiornata_il else 0
        cop.logo_url = f"{reverse('gestione_specifiche:copertina_logo', args=[p.pk])}?v={versione}"


def copertina_di(chiave: str, *, storico: bool = True, scadenza_giorni: int = 30) -> Copertina | None:
    voluta = "" if chiave == SENZA_CARTELLA else chiave.strip().lower()
    return next((c for c in copertine(storico=storico, scadenza_giorni=scadenza_giorni) if c.cartella.lower() == voluta), None)
