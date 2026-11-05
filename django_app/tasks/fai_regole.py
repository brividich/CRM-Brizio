"""Regole del FAI della MT CN 15 Rev.2 (§5.1, §5.3.1, §5.10). Nessun accesso al database.

Il portale propone quello che dice la procedura e non ferma il lavoro: chi si discosta
scrive il motivo, che resta registrato.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

COMPLETO = "COMPLETO"
DELTA = "DELTA"

# (lettera della §5.1, testo breve per scegliere, testo esteso della procedura)
CAUSALI = (
    ("a", "Articolo nuovo", "Viene prodotto un nuovo articolo per la prima volta"),
    ("b", "Modifica del cliente", "Modifiche al progetto da parte del cliente"),
    ("c", "Cambio di processo", "Attrezzature, metodi di controllo, programmi macchina"),
    ("d", "Cambio di materiale o risorse", "Materiali e risorse, interne o esterne"),
    ("e", "Azione correttiva", "Azione correttiva implementata sul processo"),
    ("f", "Fermo da oltre 2 anni", "Più di due anni dal termine della produzione dell'ultimo pezzo"),
    ("g", "Cambio di sito", "Modifica del sito produttivo"),
    ("h", "Evento straordinario", "Eventi che possono influire sul processo, per esempio cambio macchina"),
)
CAUSALI_DELTA = frozenset("bcdeh")  # §5.1.1: «è possibile» il Delta, non è un obbligo.
CAUSALI_COMPLETO = frozenset("afg")  # §5.1.2: «si deve» eseguire il FAI completo.

MESI_VERIFICA = 18  # §5.10: «più di un anno e mezzo dall'ultima spedizione»
MESI_RIPETIZIONE = 24  # §5.1 f): «più di due anni dal termine della produzione»


def etichetta_causale(causale: str) -> str:
    for lettera, breve, _esteso in CAUSALI:
        if lettera == causale:
            return f"{lettera}) {breve}"
    return causale


def tipo_proposto(causale: str) -> str:
    return DELTA if causale in CAUSALI_DELTA else COMPLETO


def serve_motivo(causale: str, tipo: str) -> bool:
    """Delta FAI dove la §5.1.2 chiede il completo: si può, ma va motivato.

    Il caso a) lo prevede la «NOTA BENE» della procedura: stesso processo di un articolo
    già coperto al 100%, su richiesta del cliente, o particolari non critici.
    """
    return tipo == DELTA and causale in CAUSALI_COMPLETO


def aggiungi_mesi(giorno: date, mesi: int) -> date:
    indice = giorno.month - 1 + mesi
    anno, mese = giorno.year + indice // 12, indice % 12 + 1
    return date(anno, mese, min(giorno.day, calendar.monthrange(anno, mese)[1]))


@dataclass(frozen=True)
class StatoArticolo:
    codice: str  # da_ripetere, da_verificare, date_mancanti, in_regola
    etichetta: str
    classe: str
    nota: str


def stato_decorrenza(
    oggi: date,
    ultima_produzione: date | None,
    ultima_spedizione: date | None,
    scadenza_cliente: date | None = None,
) -> StatoArticolo:
    """Le due soglie hanno riferimenti diversi: non sono la stessa scadenza anticipata."""
    if scadenza_cliente and scadenza_cliente < oggi:
        return StatoArticolo(
            "da_ripetere", "Da ripetere", "danger",
            f"Il cliente ne chiede la ripetizione entro il {scadenza_cliente:%d/%m/%Y}.",
        )
    if ultima_produzione and aggiungi_mesi(ultima_produzione, MESI_RIPETIZIONE) < oggi:
        return StatoArticolo(
            "da_ripetere", "Da ripetere", "danger",
            f"Oltre 2 anni dall'ultima produzione ({ultima_produzione:%d/%m/%Y}).",
        )
    if ultima_spedizione and aggiungi_mesi(ultima_spedizione, MESI_VERIFICA) < oggi:
        return StatoArticolo(
            "da_verificare", "Oltre 18 mesi", "warn",
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
