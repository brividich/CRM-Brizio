"""Catalogo dei pittogrammi di pericolo GHS/CLP.

I nove simboli sono fissati dal regolamento (CE) 1272/2008 (CLP), allegato V:
non si caricano come immagini, si scelgono da un catalogo chiuso. Questo modulo
e' l'unica fonte di verita' per codici, nomi e ordine di presentazione; il
disegno vive nello sprite SVG ``components/_ghs_icons.html`` (id ``ghs01``..``ghs09``).
"""
from __future__ import annotations

# Ordine di presentazione: fisico, salute, ambiente — lo stesso dell'allegato V.
PITTOGRAMMI_GHS: tuple[tuple[str, str], ...] = (
    ("GHS01", "Esplosivo"),
    ("GHS02", "Infiammabile"),
    ("GHS03", "Comburente"),
    ("GHS04", "Gas sotto pressione"),
    ("GHS05", "Corrosivo"),
    ("GHS06", "Tossicita' acuta"),
    ("GHS07", "Irritante / nocivo"),
    ("GHS08", "Pericoloso per la salute"),
    ("GHS09", "Pericoloso per l'ambiente"),
)

CODICI_NOTI: frozenset[str] = frozenset(codice for codice, _ in PITTOGRAMMI_GHS)

_NOMI = dict(PITTOGRAMMI_GHS)


def normalizza(codici) -> list[str]:
    """Ripulisce una lista di codici: maiuscolo, senza spazi, senza duplicati.

    Conserva l'ordine di inserimento e non scarta i codici sconosciuti: un
    valore fuori catalogo resta visibile (in forma testuale) invece di sparire
    silenziosamente dalla scheda.
    """
    visti: list[str] = []
    for grezzo in codici or ():
        codice = str(grezzo).strip().upper()
        if codice and codice not in visti:
            visti.append(codice)
    return visti


def dettaglio(codici) -> list[dict]:
    """Espande i codici in dizionari pronti per il template.

    Ogni voce: ``codice``, ``nome``, ``noto`` (False se fuori dal catalogo CLP,
    caso in cui il template mostra il codice come testo invece del simbolo).
    """
    return [
        {"codice": codice, "nome": _NOMI.get(codice, codice), "noto": codice in CODICI_NOTI}
        for codice in normalizza(codici)
    ]


def catalogo(selezionati=None, proposti=None) -> list[dict]:
    """Il catalogo completo per il selettore, con stato di selezione.

    ``proposti`` sono i codici individuati dall'estrazione automatica del PDF:
    restano marcati come tali anche dopo la conferma, per tracciabilita'.
    """
    scelti = set(normalizza(selezionati))
    auto = set(normalizza(proposti))
    return [
        {
            "codice": codice,
            "nome": nome,
            "selezionato": codice in scelti,
            "proposto": codice in auto,
        }
        for codice, nome in PITTOGRAMMI_GHS
    ]
