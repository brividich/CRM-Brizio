"""Proposte di acronimo per gli asset che non ce l'hanno (pagina «Proponi acronimi»).

L'acronimo è la sigla di riconoscimento (DM11, AGV1, MK2). Quasi sempre è già scritto
nel nome o nel tag: qui si estrae e si propone, senza scrivere niente. Salva solo
``applica`` con le righe confermate dall'utente.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import IT_DEVICE_TYPES, Asset
from .planimetria_lettura import sigle_in

LUNGHEZZA_MAX = Asset._meta.get_field("acronimo").max_length
_SIGLA_MAX = 8  # oltre è un codice modello o un seriale, non una sigla da officina
# «DM7 - DMG Mori», «C1 Tornio»: sigla corta in testa al nome (sigle_in vuole almeno 3 caratteri)
_INIZIALE = re.compile(r"^\s*([A-Za-z]{1,3}\d{1,3})(?:\s|-|$)")
# «1400mm», «5assi», «380V»: misure e targhe, non sigle
_MISURA = re.compile(r"^\d+([.,]\d+)?[A-Za-z]+$")


@dataclass
class Riga:
    asset: Asset
    proposte: list[str] = field(default_factory=list)
    spuntata: bool = False
    avviso: str = ""

    @property
    def proposta(self) -> str:
        return self.proposte[0] if self.proposte else ""


def candidati(asset: Asset) -> list[str]:
    """Sigle plausibili lette da nome e tag, la più probabile per prima, senza doppioni."""
    grezzi: list[str] = []
    iniziale = _INIZIALE.match(asset.name or "")
    if iniziale:
        grezzi.append(iniziale.group(1))
    grezzi += sigle_in(asset.name) + sigle_in(asset.asset_tag)
    out: list[str] = []
    for sigla in grezzi:
        sigla = sigla.strip().upper()
        if not sigla or len(sigla) > _SIGLA_MAX or _MISURA.match(sigla) or sigla in out:
            continue
        out.append(sigla)
    return out


def da_compilare(qs):
    """Asset senza acronimo, non dismessi."""
    return qs.filter(acronimo="").exclude(status=Asset.STATUS_RETIRED)


def righe(qs) -> tuple[list[Riga], list[Riga]]:
    """``(con proposta, senza proposta)`` per gli asset di ``qs`` ancora senza acronimo.

    Spuntate in partenza solo le proposte sicure: una sola sigla possibile, non già
    usata da un altro asset e non su un dispositivo IT (lì le sigle sono spesso modelli).
    """
    assets = list(da_compilare(qs).select_related("asset_category").order_by("name", "asset_tag"))
    usati = {a.upper() for a in Asset.objects.exclude(acronimo="").values_list("acronimo", flat=True)}
    tutte = [Riga(asset=a, proposte=candidati(a)) for a in assets]
    conteggio: dict[str, int] = {}
    for r in tutte:
        if r.proposta:
            conteggio[r.proposta] = conteggio.get(r.proposta, 0) + 1
    con, senza = [], []
    for r in tutte:
        if not r.proposta:
            senza.append(r)
            continue
        if r.proposta in usati:
            r.avviso = "Già usato da un altro asset"
        elif conteggio[r.proposta] > 1:
            r.avviso = f"Stessa sigla su {conteggio[r.proposta]} asset"
        elif len(r.proposte) > 1:
            r.avviso = "Più sigle possibili"
        elif r.asset.asset_type in IT_DEVICE_TYPES:
            r.avviso = "Dispositivo IT: controlla"
        r.spuntata = not r.avviso
        con.append(r)
    con.sort(key=lambda r: (not r.spuntata, _ordine(r.proposta)))
    return con, senza


def _ordine(sigla: str):
    m = re.match(r"^([A-Z]*)(\d*)(.*)$", sigla)
    return (m.group(1), int(m.group(2) or 0), m.group(3)) if m else (sigla, 0, "")


def applica(qs, scelte: dict[int, str]) -> int:
    """Scrive gli acronimi confermati sugli asset di ``qs`` che ne sono ancora privi. Ritorna quanti."""
    salvati = 0
    for asset_id, valore in scelte.items():
        valore = " ".join(str(valore or "").split())[:LUNGHEZZA_MAX]
        if not valore:
            continue
        salvati += qs.filter(pk=asset_id, acronimo="").update(acronimo=valore)
    return salvati
