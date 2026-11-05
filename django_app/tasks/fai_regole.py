"""Calcoli del FAI (MT CN 15 Rev.2 §5.1 f, §5.3.1, §5.10). Nessun accesso al database.

Causali, piani e stati sono configurabili in Impostazioni (``FaiOpzione``); le soglie in
``TaskImpostazioni``. Qui resta solo il calcolo. Il portale propone e non ferma il lavoro:
chi si discosta scrive il motivo, che resta registrato.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

COMPLETO = "COMPLETO"
DELTA = "DELTA"

MESI_VERIFICA = 18  # §5.10: «più di un anno e mezzo dall'ultima spedizione»
MESI_RIPETIZIONE = 24  # §5.1 f): «più di due anni dal termine della produzione»


def aggiungi_mesi(giorno: date, mesi: int) -> date:
    indice = giorno.month - 1 + mesi
    anno, mese = giorno.year + indice // 12, indice % 12 + 1
    return date(anno, mese, min(giorno.day, calendar.monthrange(anno, mese)[1]))


@dataclass(frozen=True)
class StatoArticolo:
    codice: str  # da_ripetere, da_verificare, date_mancanti, in_regola, in_corso
    etichetta: str
    classe: str
    nota: str


def stato_decorrenza(
    oggi: date,
    ultima_produzione: date | None,
    ultima_spedizione: date | None,
    scadenza_cliente: date | None = None,
    *,
    mesi_verifica: int = MESI_VERIFICA,
    mesi_ripetizione: int = MESI_RIPETIZIONE,
) -> StatoArticolo:
    """Le due soglie hanno riferimenti diversi: non sono la stessa scadenza anticipata."""
    if scadenza_cliente and scadenza_cliente < oggi:
        return StatoArticolo(
            "da_ripetere", "Da ripetere", "danger",
            f"Il cliente ne chiede la ripetizione entro il {scadenza_cliente:%d/%m/%Y}.",
        )
    if ultima_produzione and aggiungi_mesi(ultima_produzione, mesi_ripetizione) < oggi:
        return StatoArticolo(
            "da_ripetere", "Da ripetere", "danger",
            f"Oltre {mesi_ripetizione} mesi dall'ultima produzione ({ultima_produzione:%d/%m/%Y}).",
        )
    if ultima_spedizione and aggiungi_mesi(ultima_spedizione, mesi_verifica) < oggi:
        return StatoArticolo(
            "da_verificare", f"Oltre {mesi_verifica} mesi", "warn",
            f"Ultima spedizione {ultima_spedizione:%d/%m/%Y}: da segnalare a IN1 e MSM.",
        )
    if not ultima_produzione and not ultima_spedizione:
        return StatoArticolo("date_mancanti", "Senza date", "soft", "Inserisci le date per calcolare la scadenza.")
    return StatoArticolo("in_regola", "In regola", "ok", "")


_PROGRESSIVO = re.compile(r"_(\d{3})_[A-Za-z]+$")


def prossimo_piano_interno(part_number: str, numeri_esistenti) -> str:
    """Codifica §5.3.1: PFCN_<articolo>_<progressivo a tre cifre>_<revisione in lettere>."""
    progressivi = [int(m.group(1)) for m in map(_PROGRESSIVO.search, numeri_esistenti) if m]
    return f"PFCN_{part_number}_{max(progressivi, default=0) + 1:03d}_A"
