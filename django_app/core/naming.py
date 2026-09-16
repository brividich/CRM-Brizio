"""Formato unico del nominativo dipendente: ``Nome Cognome``.

Il dato legacy in ``anagrafica_dipendenti`` è stato popolato in momenti diversi:
l'import massivo ha scritto tutto MAIUSCOLO, gli inserimenti a mano hanno
scritto come capitava ("Luca Bova", "bova luca"). Qui c'è l'unica regola di
normalizzazione, usata sia dal form di inserimento sia dal comando una-tantum
sia dalla visualizzazione.
"""

from __future__ import annotations

# Separatori interni a una singola parola che vogliono comunque l'iniziale
# maiuscola dopo di sé: D'ANGELO -> D'Angelo, ROSSI-BIANCHI -> Rossi-Bianchi.
_SEPARATORI_INTERNI = ("'", "’", "-")


def normalizza_parte(valore: str | None) -> str:
    """Normalizza un ``nome`` o un ``cognome`` in iniziali maiuscole.

    Non usiamo ``str.title()`` perché non gestisce l'apostrofo tipografico e
    perché vogliamo tenere il controllo sugli spazi multipli.
    """
    parole = [p for p in (valore or "").split() if p]
    if not parole:
        return ""

    normalizzate = []
    for parola in parole:
        pezzo = parola.lower()
        pezzo = pezzo[:1].upper() + pezzo[1:]
        for sep in _SEPARATORI_INTERNI:
            if sep not in pezzo:
                continue
            pezzo = sep.join(
                blocco[:1].upper() + blocco[1:] if blocco else blocco
                for blocco in pezzo.split(sep)
            )
        normalizzate.append(pezzo)
    return " ".join(normalizzate)


def nome_completo(nome: str | None, cognome: str | None) -> str:
    """Nominativo nel formato canonico ``Nome Cognome``."""
    pezzi = [normalizza_parte(nome), normalizza_parte(cognome)]
    return " ".join(p for p in pezzi if p)


def iniziali(nome: str | None, cognome: str | None) -> str:
    """Iniziali per gli avatar, nello stesso ordine del nominativo."""
    n = normalizza_parte(nome)
    c = normalizza_parte(cognome)
    return f"{n[:1]}{c[:1]}" or "?"


def chiave_ordinamento(nome: str | None, cognome: str | None) -> str:
    """Chiave di ordinamento: resta ``cognome nome``, come nelle liste HR."""
    return f"{normalizza_parte(cognome)} {normalizza_parte(nome)}".strip()
