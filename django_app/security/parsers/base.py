from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedRecord:
    record_type: str
    payload: dict[str, Any]
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class ParsedReport:
    report_type: str
    title: str
    parser_name: str
    records: list[ParsedRecord]
    metrics: dict[str, float] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


QUALITA_COMPLETA = "completa"
QUALITA_PARZIALE = "parziale"
QUALITA_DA_VERIFICARE = "da_verificare"

QUALITA_LABELS = {
    QUALITA_COMPLETA: "Lettura completa",
    QUALITA_PARZIALE: "Lettura parziale",
    QUALITA_DA_VERIFICARE: "Da verificare",
}


class Lettura:
    """Cosa il parser ha capito di un documento, detto in italiano.

    Prima l'unico resoconto erano i ``parse_warnings`` (metà in inglese, metà assenti): un
    report letto a metà sembrava identico a uno letto per intero, e un campo mancante
    diventava in silenzio uno zero. Qui ogni parser dichiara i campi che ha trovato, quelli
    che cercava e non ha trovato (obbligatori o no) e gli avvisi; la qualità ne discende:

    - ``da_verificare``: manca almeno un campo obbligatorio (il dato non è affidabile);
    - ``parziale``: manca un campo facoltativo o c'è un avviso;
    - ``completa``: tutto trovato.
    """

    def __init__(self, formato):
        self.formato = formato
        self.letti = []
        self.mancanti = []
        self.avvisi = []

    def campo(self, etichetta, valore, *, obbligatorio=False):
        """Registra un campo: letto se ha un valore, mancante altrimenti. Ritorna il valore."""
        if valore in (None, "", [], {}):
            self.mancanti.append({"campo": etichetta, "obbligatorio": bool(obbligatorio)})
        else:
            self.letti.append({"campo": etichetta, "valore": _breve(valore)})
        return valore

    def avviso(self, testo):
        if testo and testo not in self.avvisi:
            self.avvisi.append(str(testo))

    @property
    def qualita(self):
        if any(row["obbligatorio"] for row in self.mancanti):
            return QUALITA_DA_VERIFICARE
        if self.mancanti or self.avvisi:
            return QUALITA_PARZIALE
        return QUALITA_COMPLETA

    def as_dict(self):
        qualita = self.qualita
        return {
            "formato": self.formato,
            "qualita": qualita,
            "qualita_label": QUALITA_LABELS[qualita],
            "campi_letti": self.letti,
            "campi_mancanti": self.mancanti,
            "avvisi": self.avvisi[:20],
        }


def _breve(valore):
    if isinstance(valore, (list, tuple)):
        testo = ", ".join(str(v) for v in valore[:5]) + (f" (+{len(valore) - 5})" if len(valore) > 5 else "")
    else:
        testo = str(valore)
    return testo if len(testo) <= 120 else testo[:117] + "..."


class BaseParser:
    name = "base"
    supported_source_types: tuple[str, ...] = ()

    def can_parse(self, item) -> bool:
        raise NotImplementedError

    def parse(self, item) -> ParsedReport:
        raise NotImplementedError

    def perche_riconosce(self, item) -> list[str]:
        """Segnali che hanno fatto riconoscere il contenuto (in italiano), per «Prova i parser».

        Solo spiegazione: non decide nulla, la decisione resta a ``can_parse``.
        """
        return []

    def impersonation_suspect(self, item) -> bool:
        """True when the CONTENT looks like this vendor's report but the provenance check
        rejected the sender. Never used to accept a message: only to flag it instead of
        dropping it in silence (see ``parser_engine.mark_skipped``)."""
        return False

    claimed_vendor = ""
