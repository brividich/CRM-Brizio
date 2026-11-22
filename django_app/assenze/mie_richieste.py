"""Pagina «Le mie richieste»: gruppi per momento, etichette e striscia dell'anno.

Solo presentazione: parte dalle righe di ``_helpers._load_personal`` e non
legge né scrive le richieste. La durata è quella di ``hr.valore_richiesta``
(la stessa scalata dal saldo), così a video non compare un secondo conteggio.
"""
from __future__ import annotations

import calendar
import logging
from datetime import datetime

from django.utils import timezone

logger = logging.getLogger(__name__)

MESI = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
GIORNI = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")

# Tipi proposti nel modale «Modifica» e chiave di colore di ciascuno.
TIPI_MODALE = (
    ("Ferie", "ferie"),
    ("Permesso", "permesso"),
    ("Malattia", "malattia"),
    ("Flessibilità", "flessibilita"),
    ("Certifica presenza", "altro"),
    ("Altro", "altro"),
)
_CHIAVE_TIPO = {
    "ferie": "ferie",
    "permesso": "permesso",
    "malattia": "malattia",
    "flessibilità": "flessibilita",
    "flessibilita": "flessibilita",
}

# (chiave, titolo, righe compatte, aperto in partenza)
GRUPPI = (
    ("attesa", "In attesa", False, True),
    ("programma", "In programma", False, True),
    ("passate", "Passate", True, False),
    ("rifiutate", "Rifiutate", True, False),
)

LARGHEZZA_MINIMA_SEGMENTO = 7.0  # % del mese: un permesso di un'ora deve restare visibile


def chiave_tipo(tipo) -> str:
    return _CHIAVE_TIPO.get(str(tipo or "").strip().lower(), "altro")


def _da_iso(value) -> datetime | None:
    """``2026-11-27T13:00:00.000Z`` → datetime locale senza fuso."""
    testo = str(value or "").strip()
    if not testo:
        return None
    try:
        dt = datetime.fromisoformat(testo.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(dt):
        return dt
    return timezone.localtime(dt).replace(tzinfo=None)


def _da_etichetta(value) -> datetime | None:
    """``27-11-2026 14:00`` (formato di ``_dt_label``) → datetime locale."""
    try:
        return datetime.strptime(str(value or "").strip(), "%d-%m-%Y %H:%M")
    except ValueError:
        return None


def _giorno(dt: datetime, anno: int) -> str:
    testo = f"{dt.day} {MESI[dt.month - 1]}"
    return testo if dt.year == anno else f"{testo} {dt.year}"


def _periodo(inizio: datetime, fine: datetime, anno: int, intera: bool) -> str:
    if inizio.date() == fine.date():
        testo = f"{GIORNI[inizio.weekday()]} {_giorno(inizio, anno)}"
        return testo if intera else f"{testo}, {inizio:%H:%M}–{fine:%H:%M}"
    return f"{_giorno(inizio, anno)} → {_giorno(fine, anno)}"


def _attesa(creata: datetime | None, now: datetime) -> tuple[str, int]:
    if creata is None:
        return "", -1
    giorni = max((now.date() - creata.date()).days, 0)
    if giorni == 0:
        return "da oggi", 0
    if giorni == 1:
        return "da ieri", 1
    return f"da {giorni} giorni", giorni


def _gruppo(stato, fine: datetime | None, now: datetime) -> str:
    testo = str(stato or "").strip().lower()
    if "rifiut" in testo:
        return "rifiutate"
    if "approv" not in testo:
        return "attesa"
    return "programma" if fine is not None and fine >= now else "passate"


def _durate(righe: list[dict]) -> None:
    """``durata_label`` con il calendario aziendale. Fail-safe: senza etichetta."""
    datate = [r for r in righe if r.get("_inizio") and r.get("_fine")]
    if not datate:
        return
    try:
        from . import hr

        cal = hr.calendario(min(r["_inizio"] for r in datate).date(), max(r["_fine"] for r in datate).date())
        for r in datate:
            ore, giorni, _lavorativi = hr.valore_richiesta(r["_inizio"], r["_fine"], cal)
            if not ore:
                continue
            if hr.giornata_intera(r["_inizio"], r["_fine"]):
                n = int(giorni)
                r["durata_label"] = "1 giorno" if n == 1 else f"{n} giorni"
            else:
                testo = hr._fmt_ore(ore)
                r["durata_label"] = "1 ora" if testo == "1" else f"{testo} ore"
    except Exception:
        logger.warning("assenze.mie_richieste: durata non calcolabile", exc_info=True)


def _striscia(righe: list[dict], now: datetime) -> list[dict]:
    """I dodici mesi dell'anno in corso con i periodi di assenza (rifiutate escluse)."""
    anno = now.year
    mesi = []
    for mese in range(1, 13):
        ultimo = calendar.monthrange(anno, mese)[1]
        dal, al = datetime(anno, mese, 1), datetime(anno, mese, ultimo, 23, 59, 59)
        segmenti = []
        for r in righe:
            inizio, fine = r.get("_inizio"), r.get("_fine")
            if r["gruppo"] == "rifiutate" or inizio is None or fine is None or fine < dal or inizio > al:
                continue
            g0 = 1 if inizio < dal else inizio.day
            g1 = ultimo if fine > al else fine.day
            larghezza = max((g1 - g0 + 1) / ultimo * 100, LARGHEZZA_MINIMA_SEGMENTO)
            sinistra = min((g0 - 1) / ultimo * 100, 100 - larghezza)
            segmenti.append({
                "tipo_key": r["tipo_key"],
                "attesa": r["gruppo"] == "attesa",
                # Stringa già pronta: un float nel template uscirebbe con la virgola.
                "style": f"left:{sinistra:.1f}%;width:{larghezza:.1f}%",
                "titolo": f"{r.get('tipo') or ''} · {r.get('periodo_label') or ''}",
            })
            r["_mesi"].add(mese)
        mesi.append({"n": mese, "label": MESI[mese - 1], "corrente": mese == now.month, "segmenti": segmenti})
    return mesi


def contesto(righe: list[dict], now: datetime | None = None) -> dict:
    """Annota le righe e restituisce ``mr_gruppi``, ``mr_mesi``, ``mr_anno``, ``mr_tipi``."""
    now = now or timezone.localtime()
    if timezone.is_aware(now):
        now = timezone.localtime(now).replace(tzinfo=None)

    for r in righe:
        inizio, fine = _da_iso(r.get("inizio_iso")), _da_iso(r.get("fine_iso"))
        r["_inizio"], r["_fine"], r["_mesi"] = inizio, fine, set()
        r["tipo_key"] = chiave_tipo(r.get("tipo_raw") or r.get("tipo"))
        r["gruppo"] = _gruppo(r.get("stato"), fine, now)
        r["attesa_label"], r["_attesa_giorni"] = _attesa(_da_etichetta(r.get("creata_label")), now)
        if r["gruppo"] != "attesa":
            r["attesa_label"] = ""
        if inizio and fine:
            intera = fine.date() > inizio.date() or (
                inizio.hour == 0 and inizio.minute == 0 and (fine.hour, fine.minute) >= (23, 59)
            )
            r["periodo_label"] = _periodo(inizio, fine, now.year, intera)
            r["tile_giorno"], r["tile_mese"] = inizio.day, MESI[inizio.month - 1]
        else:
            r["periodo_label"] = " → ".join(x for x in (r.get("inizio"), r.get("fine")) if x)
            r["tile_giorno"], r["tile_mese"] = "–", ""
    _durate(righe)
    mesi = _striscia(righe, now)
    for r in righe:
        r["mesi_attr"] = "," + ",".join(str(m) for m in sorted(r["_mesi"])) + "," if r["_mesi"] else ""

    lontano = datetime.max
    gruppi = []
    for chiave, titolo, compatta, aperta in GRUPPI:
        sue = [r for r in righe if r["gruppo"] == chiave]
        if not sue:
            continue
        nota = ""
        if chiave in {"attesa", "programma"}:
            sue.sort(key=lambda r: r["_inizio"] or lontano)
        if chiave == "attesa":
            piu_vecchia = max(sue, key=lambda r: r["_attesa_giorni"])
            if piu_vecchia["_attesa_giorni"] >= 0:
                nota = f"la più vecchia {piu_vecchia['attesa_label']}"
        elif chiave == "programma":
            nota = f"prossima: {sue[0]['periodo_label']}"
        elif chiave == "passate":
            sue.sort(key=lambda r: r["_inizio"] or datetime.min, reverse=True)
        gruppi.append({"chiave": chiave, "titolo": titolo, "compatta": compatta, "aperta": aperta, "nota": nota, "righe": sue})

    return {
        "mr_gruppi": gruppi,
        "mr_mesi": mesi,
        "mr_anno": str(now.year),  # stringa: niente separatore delle migliaia
        "mr_ha_segmenti": any(m["segmenti"] for m in mesi),
        "mr_tipi": TIPI_MODALE,
    }
