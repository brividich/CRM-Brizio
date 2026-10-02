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


# Apostrofi tipografici e accenti "a mano" (NICCOLO') che nei nomi valgono come
# l'apostrofo semplice.
_APOSTROFI = str.maketrans({"’": "'", "‘": "'", "´": "'", "`": "'"})


def chiave_testo(valore: str | None) -> str:
    """Chiave di CONFRONTO di un testo (nome, cognome, nominativo, email...).

    Non serve a mostrare: due scritture della stessa persona danno la stessa
    chiave. MAIUSCOLO, spazi ridotti, apostrofi uniformati, accenti tolti
    (``Niccolò`` = ``NICCOLO``, ``D’Angelo`` = ``d'angelo``).
    """
    import unicodedata

    testo = str(valore or "").translate(_APOSTROFI)
    testo = "".join(
        ch for ch in unicodedata.normalize("NFKD", testo) if not unicodedata.combining(ch)
    )
    return " ".join(testo.split()).upper()


def chiavi_confronto(nome: str | None, cognome: str | None) -> set[str]:
    """Chiavi di confronto di una persona in entrambi gli ordini
    (``COGNOME NOME`` e ``NOME COGNOME``): i testi delle altre tabelle usano l'uno o l'altro."""
    chiavi = {chiave_testo(f"{cognome or ''} {nome or ''}"), chiave_testo(f"{nome or ''} {cognome or ''}")}
    chiavi.discard("")
    return chiavi
