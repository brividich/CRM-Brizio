"""Dati del cruscotto HR (dashboard di anagrafica).

Tutto dal motore unico (:mod:`anagrafica.services.requisiti`): i numeri del
cruscotto sono gli stessi del libretto sanitario, della reportistica e dello
scadenzario. Le visite mediche (dato sanitario) si calcolano solo se chi guarda
ha il permesso visite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

from . import requisiti

SOGLIA_GIORNI = 60
MAX_RIGHE = 8


@dataclass
class Riga:
    legacy_id: int
    nominativo: str
    testo: str
    data: date | None
    tono: str  # "ko" | "warn" | "mancante" | ""


@dataclass
class Copertura:
    ok: int = 0
    warn: int = 0
    ko: int = 0
    mancante: int = 0

    @property
    def totale(self) -> int:
        return self.ok + self.warn + self.ko + self.mancante

    def pct(self, n: int) -> float:
        return round(100 * n / self.totale, 1) if self.totale else 0

    @property
    def pct_in_regola(self) -> int:
        return round(100 * (self.ok + self.warn) / self.totale) if self.totale else 0


@dataclass
class Cruscotto:
    persone: int = 0
    reparti: int = 0
    assunti_30: list = field(default_factory=list)
    cessati_30: list = field(default_factory=list)
    programmati: list = field(default_factory=list)
    formazione: Copertura = field(default_factory=Copertura)
    visite: Copertura | None = None
    righe_formazione: list[Riga] = field(default_factory=list)
    righe_visite: list[Riga] = field(default_factory=list)
    righe_qualifiche: list[Riga] = field(default_factory=list)
    n_qualifiche_scadute: int = 0
    n_qualifiche_in_scadenza: int = 0
    persone_ko: int = 0
    cambi_aperti: int = 0
    cambi_ritardo: int = 0
    righe_cambi: list[Riga] = field(default_factory=list)
    # Stato operativo (prompt 04): solo l'etichetta, mai il motivo sanitario.
    n_non_idonei_operare: int = 0
    righe_stato_operativo: list[Riga] = field(default_factory=list)

    @property
    def copertura_totale(self) -> Copertura:
        tot = Copertura(self.formazione.ok, self.formazione.warn, self.formazione.ko, self.formazione.mancante)
        if self.visite:
            tot.ok += self.visite.ok
            tot.warn += self.visite.warn
            tot.ko += self.visite.ko
            tot.mancante += self.visite.mancante
        return tot


def _tono_scadenza(scadenza: date | None, oggi: date) -> str:
    if scadenza is None:
        return ""
    if scadenza < oggi:
        return "ko"
    if (scadenza - oggi).days <= SOGLIA_GIORNI:
        return "warn"
    return ""


_ORDINE = {"ko": 0, "mancante": 1, "warn": 2, "": 3}


def _prime(righe: list[Riga]) -> list[Riga]:
    return sorted(righe, key=lambda r: (_ORDINE.get(r.tono, 9), r.data or date.max, r.nominativo))[:MAX_RIGHE]


def calcola(*, include_visite: bool, oggi: date | None = None) -> Cruscotto:
    from ..models import AdempimentoCambioMansione, DipendenteAssegnazione, DipendenteQualifica

    oggi = oggi or timezone.localdate()
    ctx = requisiti.ambito(oggi)
    tutti = ctx._tutti()
    in_forza = {p.id: p for p in tutti if p.in_forza_al(oggi)}
    out = Cruscotto(persone=len(in_forza), reparti=len({p.reparto.casefold() for p in in_forza.values() if p.reparto}))
    inizio = oggi - timedelta(days=30)
    out.assunti_30 = sorted((p for p in tutti if p.data_assunzione and inizio <= p.data_assunzione <= oggi),
                            key=lambda p: p.data_assunzione, reverse=True)
    out.cessati_30 = sorted((p for p in tutti if p.data_cessazione and inizio <= p.data_cessazione <= oggi),
                            key=lambda p: p.data_cessazione, reverse=True)
    out.programmati = list(
        DipendenteAssegnazione.objects.filter(attivata_il__isnull=True, data_inizio__gt=oggi)
        .order_by("data_inizio")[:MAX_RIGHE]
    )
    nomi = {p.id: p.nominativo for p in tutti}
    for a in out.programmati:
        a.nominativo = nomi.get(ctx.canonico(a.legacy_anagrafica_id), f"#{a.legacy_anagrafica_id}")

    persone_ko: set[int] = set()
    righe: list[Riga] = []
    for v in requisiti.formazione(ctx, in_forza):
        if not v.obbligatorio:
            continue
        if v.stato == "SCADUTO":
            out.formazione.ko += 1
            persone_ko.add(v.persona)
            righe.append(Riga(v.persona, nomi[v.persona], v.corso.titolo, v.scadenza, "ko"))
        elif v.stato == "MAI_FREQUENTATO":
            out.formazione.mancante += 1
            righe.append(Riga(v.persona, nomi[v.persona], v.corso.titolo, None, "mancante"))
        elif v.stato == "IN_SCADENZA_30" or (v.scadenza and (v.scadenza - oggi).days <= SOGLIA_GIORNI):
            out.formazione.warn += 1
            righe.append(Riga(v.persona, nomi[v.persona], v.corso.titolo, v.scadenza, "warn"))
        else:
            out.formazione.ok += 1
    out.righe_formazione = _prime(righe)

    if include_visite:
        out.visite = Copertura()
        righe = []
        for v in requisiti.visite(ctx, in_forza):
            if not v.richiesta:
                continue
            if v.ultima is None:
                out.visite.mancante += 1
                righe.append(Riga(v.persona, nomi[v.persona], v.tipo_da_mostrare.nome, None, "mancante"))
                continue
            tono = _tono_scadenza(v.scadenza, oggi)
            if tono == "ko":
                out.visite.ko += 1
                persone_ko.add(v.persona)
            elif tono == "warn":
                out.visite.warn += 1
            else:
                out.visite.ok += 1
            if tono:
                righe.append(Riga(v.persona, nomi[v.persona], v.tipo_da_mostrare.nome, v.scadenza, tono))
        out.righe_visite = _prime(righe)
    out.persone_ko = len(persone_ko)

    correnti, _sostituite = requisiti.qualifiche_correnti(ctx, DipendenteQualifica.objects.all(), in_forza)
    righe = []
    for (pid, _tipo), q in correnti.items():
        tono = _tono_scadenza(q.data_scadenza, oggi)
        if tono == "ko":
            out.n_qualifiche_scadute += 1
        elif tono == "warn":
            out.n_qualifiche_in_scadenza += 1
        if tono:
            righe.append(Riga(pid, nomi[pid], q.tipo.nome, q.data_scadenza, tono))
    out.righe_qualifiche = _prime(righe)

    try:
        from . import stato_operativo
        stati = [s for s in stato_operativo.calcola(giorno=oggi).values() if s.codice != stato_operativo.OK]
        out.n_non_idonei_operare = sum(1 for s in stati if s.bloccante)
        out.righe_stato_operativo = _prime([
            Riga(ctx.canonico(s.legacy_id), nomi.get(ctx.canonico(s.legacy_id), f"#{s.legacy_id}"), s.etichetta,
                 None, "ko" if s.bloccante else "warn")
            for s in stati
        ])
    except Exception:
        import logging
        logging.getLogger(__name__).warning("cruscotto: stato operativo non calcolabile", exc_info=True)

    aperti = list(AdempimentoCambioMansione.objects.filter(stato=AdempimentoCambioMansione.STATO_APERTO, attivo=True)
                  .order_by("entro_il"))
    out.cambi_aperti = len(aperti)
    out.cambi_ritardo = sum(1 for a in aperti if a.in_ritardo)
    per_persona: dict[int, list] = {}
    for a in aperti:
        per_persona.setdefault(ctx.canonico(a.legacy_anagrafica_id), []).append(a)
    out.righe_cambi = _prime([
        Riga(pid, nomi.get(pid, f"#{pid}"),
             f"{len(voci)} adempiment{'o' if len(voci) == 1 else 'i'} da chiudere",
             min(a.entro_il for a in voci), "ko" if any(a.in_ritardo for a in voci) else "warn")
        for pid, voci in per_persona.items()
    ])
    return out
