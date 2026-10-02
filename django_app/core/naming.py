"""Formato unico del nominativo dipendente: ``COGNOME NOME``, tutto maiuscolo.

Il dato legacy in ``anagrafica_dipendenti`` è stato popolato in momenti diversi:
l'import massivo ha scritto tutto MAIUSCOLO, gli inserimenti a mano hanno
scritto come capitava ("Luca Bova", "bova luca"). Qui c'è l'unica regola di
normalizzazione, usata sia dal form di inserimento sia dal comando una-tantum
sia dalla visualizzazione.
"""

from __future__ import annotations


def normalizza_parte(valore: str | None) -> str:
    """Normalizza un ``nome`` o un ``cognome``: MAIUSCOLO, spazi multipli ridotti.

    Apostrofi (D'ANGELO, DELL’ACQUA) e trattini (ROSSI-BIANCHI) restano come sono.
    """
    return " ".join(p for p in (valore or "").split() if p).upper()


def nome_completo(nome: str | None, cognome: str | None) -> str:
    """Nominativo nel formato canonico ``COGNOME NOME``."""
    pezzi = [normalizza_parte(cognome), normalizza_parte(nome)]
    return " ".join(p for p in pezzi if p)


def iniziali(nome: str | None, cognome: str | None) -> str:
    """Iniziali per gli avatar, nello stesso ordine del nominativo."""
    n = normalizza_parte(nome)
    c = normalizza_parte(cognome)
    return f"{c[:1]}{n[:1]}" or "?"


def chiave_ordinamento(nome: str | None, cognome: str | None) -> str:
    """Chiave di ordinamento: ``COGNOME NOME``, come nelle liste HR."""
    return nome_completo(nome, cognome)
