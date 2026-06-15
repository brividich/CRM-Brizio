"""R1 — Giacenze rifiuti per Codice EER (CER) e deposito temporaneo.

Calcola, in sola lettura, la giacenza in deposito per ogni codice EER come
differenza tra carichi e scarichi effettivi registrati nel registro RENTRI.

Modello contabile (semantica registro C/O/M/R)::

    giacenza(CER) = Σ C.quantita − Σ M.quantita − Σ R.(quantita | rettifica_scarico)

- ``C`` (carico): entrata in deposito → somma alle entrate.
- ``M`` (scarico effettivo): uscita reale → somma alle uscite.
- ``R`` (rettifica scarico): corregge uno scarico → somma alle uscite
  (``quantita`` se valorizzata, altrimenti ``rettifica_scarico``).
- ``O`` (scarico originale): movimento **pianificato**, NON muove la giacenza
  reale → escluso dal conteggio.

⚠️ La semantica O/M/R è normativamente delicata: questa formula va validata col
responsabile ambientale. È isolata qui (single source of truth) per renderla
facile da correggere. Le soglie di deposito temporaneo (D.Lgs 152/2006) sono
indicative e configurabili via ``SiteConfig`` senza migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from core.models import SiteConfig

from .models import RegistroRifiuti


# Soglie deposito temporaneo (giorni). Default conservativi (3 mesi); override
# via SiteConfig: chiavi `rentri_deposito_giorni_max` / `rentri_deposito_giorni_warn`.
_DEFAULT_GIORNI_MAX = 90
_DEFAULT_GIORNI_WARN = 75

# Tolleranza per considerare "azzerata" una giacenza (arrotondamenti decimali).
_EPS = 0.0005


def _cfg_int(chiave: str, default: int) -> int:
    raw = (SiteConfig.get(chiave, "") or "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def soglie_deposito() -> dict[str, int]:
    """Soglie giorni per il semaforo deposito temporaneo (configurabili)."""
    gmax = _cfg_int("rentri_deposito_giorni_max", _DEFAULT_GIORNI_MAX)
    gwarn = _cfg_int("rentri_deposito_giorni_warn", _DEFAULT_GIORNI_WARN)
    if gwarn > gmax:
        gwarn = gmax
    return {"giorni_max": gmax, "giorni_warn": gwarn}


@dataclass
class GiacenzaCER:
    """Giacenza aggregata di un singolo codice EER nel registro RENTRI."""

    codice: str
    entrate: float
    uscite: float
    giacenza: float
    pericoloso: bool
    primo_carico: date | None
    ultimo_movimento: date | None
    giorni_giacenza: int | None  # età del carico più vecchio finché la giacenza è aperta
    n_carichi: int
    n_scarichi: int

    @property
    def aperta(self) -> bool:
        return self.giacenza > _EPS

    def tono(self, soglie: dict[str, int]) -> str:
        """Semaforo deposito: rosso/giallo/verde se aperta, 'chiuso' se azzerata."""
        if not self.aperta:
            return "chiuso"
        if self.giorni_giacenza is None:
            return "verde"
        if self.giorni_giacenza >= soglie["giorni_max"]:
            return "rosso"
        if self.giorni_giacenza >= soglie["giorni_warn"]:
            return "giallo"
        return "verde"


def giacenze_per_cer() -> list[GiacenzaCER]:
    """Ritorna le giacenze per CER ordinate per giacenza decrescente.

    Aggregazione in Python (registro di dimensioni modeste) per gestire il
    fallback ``quantita``/``rettifica_scarico`` delle rettifiche e la data del
    carico più vecchio ancora "aperto".
    """
    oggi = timezone.localdate()
    agg: dict[str, dict] = {}

    qs = RegistroRifiuti.objects.exclude(codice="").only(
        "codice", "tipo", "quantita", "rettifica_scarico", "data", "pericolosita"
    )
    for r in qs:
        codice = " ".join((r.codice or "").split())
        if not codice:
            continue
        a = agg.setdefault(
            codice,
            {
                "entrate": 0.0,
                "uscite": 0.0,
                "pericoloso": False,
                "primo_carico": None,
                "ultimo_movimento": None,
                "n_carichi": 0,
                "n_scarichi": 0,
            },
        )
        q = float(r.quantita) if r.quantita is not None else 0.0

        if r.tipo == "C":
            a["entrate"] += q
            a["n_carichi"] += 1
            if (r.pericolosita or "").strip():
                a["pericoloso"] = True
            if r.data and (a["primo_carico"] is None or r.data < a["primo_carico"]):
                a["primo_carico"] = r.data
        elif r.tipo == "M":
            a["uscite"] += q
            a["n_scarichi"] += 1
        elif r.tipo == "R":
            rett = q if r.quantita is not None else (
                float(r.rettifica_scarico) if r.rettifica_scarico is not None else 0.0
            )
            a["uscite"] += rett
        else:
            # O (scarico originale): pianificato, non muove la giacenza reale.
            continue

        if r.data and (a["ultimo_movimento"] is None or r.data > a["ultimo_movimento"]):
            a["ultimo_movimento"] = r.data

    result: list[GiacenzaCER] = []
    for codice, a in agg.items():
        giac = round(a["entrate"] - a["uscite"], 3)
        aperta = giac > _EPS
        giorni = (oggi - a["primo_carico"]).days if (aperta and a["primo_carico"]) else None
        result.append(
            GiacenzaCER(
                codice=codice,
                entrate=round(a["entrate"], 3),
                uscite=round(a["uscite"], 3),
                giacenza=giac,
                pericoloso=a["pericoloso"],
                primo_carico=a["primo_carico"],
                ultimo_movimento=a["ultimo_movimento"],
                giorni_giacenza=giorni,
                n_carichi=a["n_carichi"],
                n_scarichi=a["n_scarichi"],
            )
        )

    result.sort(key=lambda g: (-g.giacenza, g.codice))
    return result
