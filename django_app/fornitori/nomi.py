"""Confronto dei nomi di ditta tra GuestPortal e anagrafica fornitori dell'HUB.

Le due anagrafiche scrivono la stessa ditta in modi diversi («Rossi Impianti» /
«ROSSI IMPIANTI S.R.L.»). ``chiave_ditta`` toglie maiuscole, accenti,
punteggiatura e forma giuridica: due nomi con la stessa chiave sono la stessa
ditta. Si usa solo quando la chiave identifica UNA ditta (vedi ``unico``): con
due fornitori che danno la stessa chiave non si sceglie a caso.
"""
from __future__ import annotations

import re
import unicodedata

# Forme giuridiche e diciture da ignorare, già senza punteggiatura e con le
# lettere eventualmente separate da spazi («s r l» da «S.r.l.»).
_FORME = [
    r"s ?r ?l ?s", r"s ?r ?l", r"s ?p ?a", r"s ?n ?c", r"s ?a ?p ?a", r"s ?a ?s", r"s ?c ?a ?r ?l", r"s ?c ?r ?l",
    r"s ?c ?p ?a", r"soc(?:ieta)? coop(?:erativa)?(?: a r ?l)?", r"cooperativa", r"coop",
    r"unipersonale", r"in liquidazione", r"ltd", r"gmbh", r"inc", r"e c", r"e figli",
]
_RE_FORME = re.compile(r"\b(?:" + "|".join(_FORME) + r")\b")


def chiave_ditta(nome: str | None) -> str:
    testo = unicodedata.normalize("NFKD", nome or "")
    testo = "".join(c for c in testo if not unicodedata.combining(c)).lower()
    testo = testo.replace("&", " e ")
    testo = re.sub(r"[^\w\s]", " ", testo)
    testo = re.sub(r"\s+", " ", testo).strip()
    senza_forma = re.sub(r"\s+", " ", _RE_FORME.sub(" ", testo)).strip()
    return senza_forma or testo


def unico(chiave: str, coppie) -> object | None:
    """Tra ``coppie`` ``[(valore, nome)]`` il solo valore con quella chiave, o None
    se nessuno o più di uno."""
    if not chiave:
        return None
    trovati = {valore for valore, nome in coppie if chiave_ditta(nome) == chiave}
    return trovati.pop() if len(trovati) == 1 else None


def chiave_tecnico(nome: str | None) -> str:
    """Come ``chiave_persona``, ma non è mai vuota per un nome di una sola parola."""
    return chiave_persona(nome) or (nome or "").strip().lower()


def chiave_persona(nome: str | None) -> str:
    """Chiave di un nominativo: maiuscole, accenti e punteggiatura ignorati, parole
    in ordine alfabetico («ROSSI Mario» = «Mario Rossi»). Vuota sotto le due parole:
    un solo nome o cognome non basta a riconoscere una persona."""
    testo = unicodedata.normalize("NFKD", nome or "")
    testo = "".join(c for c in testo if not unicodedata.combining(c)).lower()
    parole = re.sub(r"[^\w\s]", " ", testo).split()
    return " ".join(sorted(parole)) if len(parole) >= 2 else ""
