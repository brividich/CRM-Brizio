"""R1 — Giacenze rifiuti per Codice EER (CER) e deposito temporaneo.

Calcola, in sola lettura, la giacenza in deposito per ogni codice EER. Il conto
è quello del filo conduttore (:mod:`rentri.fili`): ogni carico ha un residuo,
gli scarichi originali O lo consumano, la coppia M/R corregge il peso a destino
senza muovere il deposito. La giacenza di un codice è la somma dei residui.

Fino al 11/2026 la formula era «Σ C − Σ M − Σ R» con la O esclusa: sul registro
reale (M e R in coppia con segni opposti) dava giacenze negative o gonfiate e
bloccava scarichi validi con «oltre la giacenza».

- I movimenti **annullati** non contano mai.
- Il codice si raggruppa per le sei cifre del CER (:func:`chiave_codice`).

Giorni in deposito: età del carico più vecchio con un residuo.

Criterio quantitativo (art. 185-bis): somma delle giacenze aperte espresse in
volume (m³, litri); i codici registrati a peso non sono convertibili e sono
contati a parte.

⚠️ La semantica O/M/R è normativamente delicata: va validata col responsabile
ambientale. Le soglie di deposito temporaneo (D.Lgs 152/2006) sono indicative e
configurabili via ``SiteConfig`` senza migration.
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
    """Il codice come raggruppato dalle giacenze: le sei cifre del CER."""
    from .fili import chiave

    return chiave(codice)


def contributo(r) -> tuple[Decimal, Decimal]:
    """(entrata, uscita) di un movimento preso da solo, senza il suo filo.

    Serve solo ai controlli che non hanno il filo a disposizione; il conto della
    giacenza passa da :func:`rentri.fili.analizza`.
    """
    from .fili import valore

    v = valore(r)
    if r.tipo == "C":
        return (Decimal(r.quantita or 0), Decimal(0))
    if r.tipo == "O" and v:
        return (Decimal(0), abs(Decimal(v)))
    return (Decimal(0), Decimal(0))


def giacenza_di(codice: str, *, escludi_pk=None) -> Decimal:
    """Giacenza attuale di un codice, con lo stesso conto della pagina Giacenze."""
    from .fili import analizza_codice

    return analizza_codice(codice, escludi_pk=escludi_pk).giacenza(codice)


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


def giacenze_per_cer() -> list[GiacenzaCER]:
    """Ritorna le giacenze per CER ordinate per giacenza decrescente."""
    from collections import Counter

    from .fili import EPS, analizza

    oggi = timezone.localdate()
    records = list(
        RegistroRifiuti.objects.attivi().exclude(codice="").only(
            "codice", "tipo", "quantita", "rettifica_scarico", "data", "pericolosita", "unita",
            "rif_op", "id_registrazione", "annullato",
        )
    )
    an = analizza(records)
    agg: dict[str, dict] = {}
    for r in records:
        k = chiave_codice(r.codice)
        if not k:
            continue
        a = agg.setdefault(k, {
            "testi": Counter(), "uscite": Decimal(0), "pericoloso": False, "primo_carico": None,
            "ultimo_movimento": None, "n_carichi": 0, "n_scarichi": 0, "unita": set(),
        })
        a["testi"][" ".join(r.codice.split())] += 1
        a["uscite"] += an.uscita.get(r.pk, Decimal(0))
        if r.unita:
            a["unita"].add(r.unita)
        if r.tipo == "C":
            a["n_carichi"] += 1
            if (r.pericolosita or "").strip() or "*" in r.codice:
                a["pericoloso"] = True
            if r.data and (a["primo_carico"] is None or r.data < a["primo_carico"]):
                a["primo_carico"] = r.data
        elif r.tipo in ("O", "M"):
            a["n_scarichi"] += 1
        if r.data and (a["ultimo_movimento"] is None or r.data > a["ultimo_movimento"]):
            a["ultimo_movimento"] = r.data

    result: list[GiacenzaCER] = []
    for k, a in agg.items():
        carichi = an.carichi.get(k, [])
        entrate = sum((Decimal(c.quantita or 0) for c in carichi), Decimal(0))
        giac = sum((an.residuo[c.pk] for c in carichi), Decimal(0))
        aperto = next((c.data for c in carichi if an.residuo[c.pk] > EPS), None)
        if len(a["unita"]) == 1:
            unita = next(iter(a["unita"]))
        else:
            unita = "misto" if a["unita"] else ""
        result.append(GiacenzaCER(
            codice=a["testi"].most_common(1)[0][0],
            entrate=round(float(entrate), 3),
            uscite=round(float(a["uscite"]), 3),
            giacenza=round(float(giac), 3),
            pericoloso=a["pericoloso"],
            primo_carico=a["primo_carico"],
            ultimo_movimento=a["ultimo_movimento"],
            giorni_giacenza=(oggi - aperto).days if aperto else None,
            n_carichi=a["n_carichi"],
            n_scarichi=a["n_scarichi"],
            unita=unita,
            carico_aperto=aperto,
        ))

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
