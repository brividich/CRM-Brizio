"""Analisi del rischio del MOD.165 legata alla SoA.

Regole del MOD.165 (verificate sui valori del modulo aziendale):

* vulnerabilità di una minaccia = la più alta fra i controlli che la mitigano (dalla SoA);
* rischio residuo = rischio inerente × vulnerabilità / 4, accettabile fino alla soglia (30);
* per controllo («Threat Monitoring»): rischio residuo = rischio inerente massimo delle minacce collegate ×
  vulnerabilità del controllo / 4; rischio futuro con la vulnerabilità attesa dopo le azioni;
* scenari OT: rischio residuo atteso = inerente × vulnerabilità residua attesa / 4.

Il residuo si ricalcola quindi da solo quando cambiano le vulnerabilità nella SoA.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from ..models import RischioMinaccia, ScenarioRischioOT, SoaRevisione, SoaVoce


def residuo(inerente: int | None, vulnerabilita: int | None) -> int | None:
    if inerente is None or vulnerabilita is None:
        return None
    return (inerente * vulnerabilita * 2 + 4) // 8  # arrotondamento a metà per eccesso di inerente×v/4


def fascia(valore: int | None) -> str:
    """Fasce di colore del MOD.165: zero, 1-10, 11-20, 21-30, 31-40, oltre 40."""
    if valore is None:
        return ""
    for limite, nome in ((0, "zero"), (10, "f1"), (20, "f2"), (30, "f3"), (40, "f4")):
        if valore <= limite:
            return nome
    return "f5"


@dataclass
class RigaMinaccia:
    minaccia: RischioMinaccia
    controlli: list = field(default_factory=list)
    vulnerabilita: int | None = None
    residuo: int | None = None
    accettabile: bool = True
    critici: list = field(default_factory=list)  # controlli con la vulnerabilità massima


@dataclass
class RigaControllo:
    voce: SoaVoce
    minacce: int = 0
    inerente_max: int | None = None
    residuo: int | None = None
    accettabile: bool = True
    futuro: int | None = None
    futuro_accettabile: bool = True


@dataclass
class RigaOT:
    scenario: ScenarioRischioOT
    controlli: list = field(default_factory=list)
    vulnerabilita: int | None = None
    residuo: int | None = None
    atteso: int | None = None
    accettabile: bool = True
    atteso_accettabile: bool = True


@dataclass
class Analisi:
    revisione: SoaRevisione
    soglia: int
    minacce: list[RigaMinaccia]
    controlli: list[RigaControllo]
    scenari: list[RigaOT]

    @property
    def non_accettabili(self) -> list[RigaMinaccia]:
        return [r for r in self.minacce if not r.accettabile]

    @property
    def controlli_oltre_soglia(self) -> list[RigaControllo]:
        return [r for r in self.controlli if not r.accettabile]

    @property
    def ot_oltre_soglia(self) -> list[RigaOT]:
        return [r for r in self.scenari if not r.accettabile]

    @property
    def residuo_massimo(self) -> int | None:
        valori = [r.residuo for r in self.minacce if r.residuo is not None]
        return max(valori) if valori else None

    @property
    def differenze_registrate(self) -> list[RigaMinaccia]:
        """Minacce il cui residuo calcolato differisce da quello letto dal MOD.165 all'import."""
        return [r for r in self.minacce if r.minaccia.residuo_registrato is not None
                and r.residuo is not None and r.residuo != r.minaccia.residuo_registrato]


def analizza(revisione: SoaRevisione) -> Analisi:
    voci = {v.controllo_id: v for v in revisione.voci.select_related("controllo")}
    soglia = revisione.soglia_rischio
    righe = []
    inerente_per_controllo: dict[int, list[int]] = {}
    for m in revisione.minacce.prefetch_related("controlli"):
        controlli = sorted(m.controlli.all(), key=lambda c: c.ordine)
        vuln = [voci[c.pk].vulnerabilita for c in controlli if c.pk in voci]
        vmax = max(vuln) if vuln else None
        r = residuo(m.rischio_inerente, vmax)
        righe.append(RigaMinaccia(
            minaccia=m, controlli=controlli, vulnerabilita=vmax, residuo=r,
            accettabile=r is None or r <= soglia,
            critici=[c for c in controlli if c.pk in voci and voci[c.pk].vulnerabilita == vmax and vmax],
        ))
        for c in controlli:
            if m.rischio_inerente is not None:
                inerente_per_controllo.setdefault(c.pk, []).append(m.rischio_inerente)
    controlli = []
    for voce in sorted(voci.values(), key=lambda v: v.controllo.ordine):
        valori = inerente_per_controllo.get(voce.controllo_id, [])
        massimo = max(valori) if valori else None
        r = residuo(massimo, voce.vulnerabilita)
        futuro = residuo(massimo, voce.vulnerabilita_attesa)
        controlli.append(RigaControllo(
            voce=voce, minacce=len(valori), inerente_max=massimo, residuo=r,
            accettabile=r is None or r <= soglia, futuro=futuro,
            futuro_accettabile=futuro is None or futuro <= soglia,
        ))
    scenari = []
    for s in revisione.scenari_ot.prefetch_related("controlli"):
        ctrl = sorted(s.controlli.all(), key=lambda c: c.ordine)
        vuln = [voci[c.pk].vulnerabilita for c in ctrl if c.pk in voci]
        vmax = max(vuln) if vuln else None
        r = residuo(s.rischio_inerente, vmax)
        atteso = residuo(s.rischio_inerente, s.vulnerabilita_attesa)
        scenari.append(RigaOT(
            scenario=s, controlli=ctrl, vulnerabilita=vmax, residuo=r, atteso=atteso,
            accettabile=r is None or r <= soglia, atteso_accettabile=atteso is None or atteso <= soglia,
        ))
    return Analisi(revisione=revisione, soglia=soglia, minacce=righe, controlli=controlli, scenari=scenari)


@transaction.atomic
def copia_analisi(da: SoaRevisione, a: SoaRevisione) -> None:
    """Copia minacce e scenari OT nella nuova revisione (singoli INSERT: niente batch dentro savepoint)."""
    for m in da.minacce.prefetch_related("controlli"):
        controlli = list(m.controlli.all())
        m.pk = None
        m._prefetched_objects_cache = {}  # altrimenti set() vede i controlli della revisione di origine
        m.revisione = a
        m.save()
        m.controlli.set(controlli)
    for s in da.scenari_ot.prefetch_related("controlli"):
        controlli = list(s.controlli.all())
        s.pk = None
        s._prefetched_objects_cache = {}  # altrimenti set() vede i controlli della revisione di origine
        s.revisione = a
        s.save()
        s.controlli.set(controlli)
