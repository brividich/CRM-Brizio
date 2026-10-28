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
- I movimenti **annullati** non contano mai.

Il conto di un movimento è uno solo, :func:`contributo`: lo usano la pagina
Giacenze, il controllo «quantità oltre la giacenza» del salvataggio e la
verifica di coerenza.

Giorni in deposito: le uscite consumano i carichi dal più vecchio (FIFO); l'età
è quella del carico più vecchio con un residuo. Prima si usava il primo carico
di sempre del codice, che con carichi continui e scarichi parziali dava età
false in entrambi i sensi.

Criterio quantitativo (art. 185-bis): somma delle giacenze aperte espresse in
volume (m³, litri); i codici registrati a peso non sono convertibili e sono
contati a parte.

⚠️ La semantica O/M/R è normativamente delicata: questa formula va validata col
responsabile ambientale. È isolata qui (single source of truth) per renderla
facile da correggere. Le soglie di deposito temporaneo (D.Lgs 152/2006) sono
indicative e configurabili via ``SiteConfig`` senza migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone

from core.models import SiteConfig

from .models import RegistroRifiuti


# Soglie deposito temporaneo (giorni). Default conservativi (3 mesi); override
# via SiteConfig: chiavi `rentri_deposito_giorni_max` / `rentri_deposito_giorni_warn`.
_DEFAULT_GIORNI_MAX = 90
_DEFAULT_GIORNI_WARN = 75
# Criterio quantitativo (m³), chiavi `rentri_deposito_m3_max` / `rentri_deposito_m3_pericolosi_max`.
_DEFAULT_M3_MAX = 30
_DEFAULT_M3_PERICOLOSI_MAX = 10

# Tolleranza per considerare "azzerata" una giacenza (arrotondamenti decimali).
_EPS = 0.0005
_D_EPS = Decimal("0.0005")

# Fattore verso m³ delle unità di volume.
_M3 = {"m3": Decimal(1), "l": Decimal("0.001")}


def _cfg_int(chiave: str, default: int) -> int:
    raw = (SiteConfig.get(chiave, "") or "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def soglie_deposito() -> dict[str, int]:
    """Soglie del deposito temporaneo (configurabili): giorni e m³."""
    gmax = _cfg_int("rentri_deposito_giorni_max", _DEFAULT_GIORNI_MAX)
    gwarn = _cfg_int("rentri_deposito_giorni_warn", _DEFAULT_GIORNI_WARN)
    if gwarn > gmax:
        gwarn = gmax
    return {
        "giorni_max": gmax,
        "giorni_warn": gwarn,
        "m3_max": _cfg_int("rentri_deposito_m3_max", _DEFAULT_M3_MAX),
        "m3_pericolosi_max": _cfg_int("rentri_deposito_m3_pericolosi_max", _DEFAULT_M3_PERICOLOSI_MAX),
    }


def chiave_codice(codice: str) -> str:
    """Il codice come raggruppato dalle giacenze (spazi normalizzati)."""
    return " ".join((codice or "").split())


def contributo(r) -> tuple[Decimal, Decimal]:
    """(entrata, uscita) di un movimento: l'unica definizione del conto giacenza."""
    q = r.quantita
    if r.tipo == "C":
        return (Decimal(q or 0), Decimal(0))
    if r.tipo == "M":
        return (Decimal(0), Decimal(q or 0))
    if r.tipo == "R":
        if q is None:
            q = r.rettifica_scarico
        return (Decimal(0), Decimal(q or 0))
    return (Decimal(0), Decimal(0))


def giacenza_di(codice: str, *, escludi_pk=None) -> Decimal:
    """Giacenza attuale di un codice, con lo stesso conto della pagina Giacenze."""
    chiave = chiave_codice(codice)
    qs = RegistroRifiuti.objects.attivi().filter(tipo__in=["C", "M", "R"]).only(
        "codice", "tipo", "quantita", "rettifica_scarico"
    )
    if escludi_pk:
        qs = qs.exclude(pk=escludi_pk)
    totale = Decimal(0)
    for r in qs:
        if chiave_codice(r.codice) != chiave:
            continue
        entrata, uscita = contributo(r)
        totale += entrata - uscita
    return totale


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
    giorni_giacenza: int | None  # età del carico più vecchio con residuo (FIFO)
    n_carichi: int
    n_scarichi: int
    unita: str = ""  # unità dichiarata; "misto" se i movimenti ne usano più d'una
    carico_aperto: date | None = None  # data del carico più vecchio con residuo

    @property
    def aperta(self) -> bool:
        return self.giacenza > _EPS

    @property
    def m3(self) -> float | None:
        """Giacenza in m³ se l'unità è di volume, altrimenti ``None``."""
        fattore = _M3.get(self.unita)
        if fattore is None:
            return None
        return float(Decimal(str(self.giacenza)) * fattore)

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


def carico_aperto_fifo(carichi: list[tuple[date | None, Decimal]], uscite: Decimal) -> date | None:
    """Data del carico più vecchio non ancora consumato dalle uscite (FIFO)."""
    residuo_uscite = uscite
    for data_c, q in sorted(carichi, key=lambda c: (c[0] or date.min)):
        if residuo_uscite >= q - _D_EPS:
            residuo_uscite -= q
            continue
        return data_c
    return None


def giacenze_per_cer() -> list[GiacenzaCER]:
    """Ritorna le giacenze per CER ordinate per giacenza decrescente.

    Aggregazione in Python (registro di dimensioni modeste) per gestire il
    fallback ``quantita``/``rettifica_scarico`` delle rettifiche e l'età FIFO
    del carico più vecchio ancora aperto.
    """
    oggi = timezone.localdate()
    agg: dict[str, dict] = {}

    qs = RegistroRifiuti.objects.attivi().exclude(codice="").only(
        "codice", "tipo", "quantita", "rettifica_scarico", "data", "pericolosita", "unita"
    )
    for r in qs:
        codice = chiave_codice(r.codice)
        if not codice or r.tipo == "O":
            # O (scarico originale): pianificato, non muove la giacenza reale.
            continue
        a = agg.setdefault(
            codice,
            {
                "entrate": Decimal(0),
                "uscite": Decimal(0),
                "pericoloso": False,
                "primo_carico": None,
                "ultimo_movimento": None,
                "n_carichi": 0,
                "n_scarichi": 0,
                "carichi": [],
                "unita": set(),
            },
        )
        entrata, uscita = contributo(r)
        a["entrate"] += entrata
        a["uscite"] += uscita
        if r.unita:
            a["unita"].add(r.unita)

        if r.tipo == "C":
            a["n_carichi"] += 1
            a["carichi"].append((r.data, entrata))
            if (r.pericolosita or "").strip() or "*" in codice:
                a["pericoloso"] = True
            if r.data and (a["primo_carico"] is None or r.data < a["primo_carico"]):
                a["primo_carico"] = r.data
        elif r.tipo == "M":
            a["n_scarichi"] += 1

        if r.data and (a["ultimo_movimento"] is None or r.data > a["ultimo_movimento"]):
            a["ultimo_movimento"] = r.data

    result: list[GiacenzaCER] = []
    for codice, a in agg.items():
        giac = round(float(a["entrate"] - a["uscite"]), 3)
        aperta = giac > _EPS
        carico_aperto = carico_aperto_fifo(a["carichi"], a["uscite"]) if aperta else None
        giorni = (oggi - carico_aperto).days if carico_aperto else None
        if len(a["unita"]) == 1:
            unita = next(iter(a["unita"]))
        else:
            unita = "misto" if a["unita"] else ""
        result.append(
            GiacenzaCER(
                codice=codice,
                entrate=round(float(a["entrate"]), 3),
                uscite=round(float(a["uscite"]), 3),
                giacenza=giac,
                pericoloso=a["pericoloso"],
                primo_carico=a["primo_carico"],
                ultimo_movimento=a["ultimo_movimento"],
                giorni_giacenza=giorni,
                n_carichi=a["n_carichi"],
                n_scarichi=a["n_scarichi"],
                unita=unita,
                carico_aperto=carico_aperto,
            )
        )

    result.sort(key=lambda g: (-g.giacenza, g.codice))
    return result


def criterio_quantitativo(giacenze: list[GiacenzaCER], soglie: dict[str, int]) -> dict:
    """Totale in m³ delle giacenze aperte, confrontato con le soglie del deposito.

    I codici a peso (kg, t), senza unità o con unità miste non si convertono in
    volume: sono contati in ``non_convertibili`` perché il totale non sembri
    completo quando non lo è.
    """
    totale = Decimal(0)
    pericolosi = Decimal(0)
    non_convertibili = 0
    for g in giacenze:
        if not g.aperta:
            continue
        m3 = g.m3
        if m3 is None:
            non_convertibili += 1
            continue
        totale += Decimal(str(m3))
        if g.pericoloso:
            pericolosi += Decimal(str(m3))
    totale_f = round(float(totale), 3)
    pericolosi_f = round(float(pericolosi), 3)
    return {
        "m3_totale": totale_f,
        "m3_pericolosi": pericolosi_f,
        "m3_max": soglie["m3_max"],
        "m3_pericolosi_max": soglie["m3_pericolosi_max"],
        "oltre": totale_f > soglie["m3_max"] or pericolosi_f > soglie["m3_pericolosi_max"],
        "non_convertibili": non_convertibili,
    }
