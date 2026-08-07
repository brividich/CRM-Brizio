"""Dal testo di un referto ai campi che ci servono.

L'ESTRAZIONE SI REGGE SULLA RIDONDANZA, NON SU UN PATTERN FORTUNATO

Un certificato Winasped dice più volte le stesse cose, e questo modulo se ne
serve. La data del giudizio compare tre volte («Espresso il», «Trasmesso al datore
di lavoro», «Trasmesso al lavoratore»): su un campione reale l'OCR ne ha corrotta
una — `241-05-2024` invece di `21-05-2024` — e le altre due l'hanno salvata. Un
singolo pattern, per quanto ben scritto, avrebbe scartato quel referto.

DOVE SI LEGGE IL NOME (E DOVE NO)

Dal **blocco anagrafico** in testa, quello dove il nominativo sta accanto alla data
di nascita. La riga di firma «Il Lavoratore ...:» esiste ma è attraversata dalla
firma autografa: l'OCR la spezza e storpia il cognome, e in prova ha prodotto
`AMMAI NATI ALBERTO` — un nome verosimile e falso, che è peggio di nessun nome,
perché nessuno lo mette in dubbio. Resta come ripiego, ma chi lo usa lo dichiara
(``nominativo_da_ripiego``) e a valle non potrà mai auto-confermarsi.

QUELLO CHE QUESTO MODULO NON FA

Non decide chi sia il dipendente e non traduce esami ed esiti in codici: qui si
legge soltanto quello che c'è scritto. La traduzione passa per tabelle di alias
modificabili in pagina, perché è il punto esatto in cui i certificati reali
smentiscono le previsioni — ogni medico scrive «Visita Medica», «Vis. medica» o
«Visita medica periodica» a modo suo, e un nome nuovo deve costare una riga
inserita, non un rilascio.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

__all__ = [
    "CampiReferto",
    "normalizza",
    "analizza_testo",
    "pare_certificato",
    "PERIODICITA_NOTE",
]

# Cadenze che compaiono nella colonna «Periodicita'» del protocollo sanitario.
# Servono a riconoscere *dove finisce il nome dell'esame*, non a calcolare
# scadenze: quelle vengono dal catalogo (TipoVisitaMedica.durata_mesi).
PERIODICITA_NOTE = {
    "semestrale": 6,
    "annuale": 12,
    "biennale": 24,
    "triennale": 36,
    "quadriennale": 48,
    "quinquennale": 60,
    "decennale": 120,
}

# Data tollerante al rumore: l'OCR infila spazi attorno ai trattini e spezza le
# righe a metà campo, quindi `21-05- 2024` deve valere quanto `21-05-2024`.
_DATA = r"(\d{2})\s*[-/]\s*(\d{2})\s*[-/]\s*(\d{4})"

# Il documento si riconosce da due impronte indipendenti: se non è un certificato
# di idoneità non si prova nemmeno a estrarre, si dichiara di non averlo capito.
_IMPRONTE = (
    r"CERTIFICATO\s+MEDICO\s+DI\s+IDONEIT",
    r"WINASPED",
    r"PROTOCOLLO\s+SANITARIO",
)

_NOME_ANAGRAFICO = (
    # Il blocco anagrafico: il nominativo segue la data di nascita, sulla stessa
    # riga o subito dopo. Due maiuscole almeno, per non agganciare un'iniziale.
    rf"Data\s+Nascita\s+{_DATA}\s+([A-ZÀ-Ù][A-ZÀ-Ù'\s]{{2,40}}?)(?:\s*$|\s*\n)"
)
_NOME_RIPIEGO = r"Il\s+Lavoratore\s+([A-ZÀ-Ù][A-ZÀ-Ù'\s]{2,40}?)\s*[:.]"

_ETICHETTE_DATA = {
    "giudizio": rf"Espress[oa]\s+il\s*[.:]*\s*{_DATA}",
    "trasmesso_datore": rf"Trasmesso\s+al\s+datore\s+di\s+lavoro\s*i?l?\s*\.{{0,3}}\s*{_DATA}",
    "trasmesso_lavoratore": rf"Trasmesso\s+al\s+lavoratore\s*(?:il|11|i1)?\s*\.{{0,3}}\s*{_DATA}",
    "nascita": rf"Data\s+Nascita\s+{_DATA}",
    "assunzione": rf"D[a-zì.]*\s*assunzione\s+{_DATA}",
    "inizio_mansione": rf"Data\s+inizio\s+mansione\s+{_DATA}",
}


@dataclass
class CampiReferto:
    """Quello che si è riusciti a leggere. Nessun campo è garantito."""

    nominativo: str = ""
    nominativo_da_ripiego: bool = False
    data_nascita: date | None = None
    data_giudizio: date | None = None
    esito_testo: str = ""
    mansione: str = ""
    protocollo: list[dict] = field(default_factory=list)
    date_trovate: list[dict] = field(default_factory=list)
    e_certificato: bool = False

    @property
    def minimo_utile(self) -> bool:
        """C'è abbastanza per tentare un abbinamento?

        Senza nominativo non si cerca nessuno; senza data del giudizio non si sa
        quando la visita sia avvenuta e la scadenza sarebbe inventata.
        """
        return bool(self.nominativo) and self.data_giudizio is not None


def normalizza(testo: str) -> str:
    """Forma di confronto: maiuscole, senza accenti, spazi compattati.

    Usata per gli alias e per il confronto dei nominativi. Gli accenti spariscono
    perché l'OCR li inventa e li perde con pari disinvoltura, e `PERU'` e `PERU`
    non devono essere due persone diverse.
    """
    testo = unicodedata.normalize("NFKD", testo or "")
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = re.sub(r"[^\w\s]", " ", testo, flags=re.UNICODE)
    return re.sub(r"\s+", " ", testo).strip().upper()


def _piatto(testo: str) -> str:
    """Testo a riga unica: ricuce i campi che l'OCR ha spezzato a metà."""
    return re.sub(r"[ \t]+", " ", (testo or "").replace("\r", "")).strip()


def _a_data(giorno: str, mese: str, anno: str) -> date | None:
    try:
        return date(int(anno), int(mese), int(giorno))
    except (TypeError, ValueError):
        return None


def pare_certificato(testo: str) -> bool:
    """Il documento è un certificato di idoneità?

    Basta una delle impronte: una scansione sbiadita può perderne una, ma perderle
    tutte e tre significa che è un altro documento — e allora è giusto fermarsi.
    """
    piatto = _piatto(testo)
    return any(re.search(p, piatto, re.IGNORECASE) for p in _IMPRONTE)


def _estrai_date(testo: str) -> tuple[list[dict], date | None, date | None]:
    """Date etichettate, data di nascita, data del giudizio per consenso."""
    piatto = _piatto(testo)
    trovate: list[dict] = []
    per_etichetta: dict[str, date] = {}

    for etichetta, pattern in _ETICHETTE_DATA.items():
        for m in re.finditer(pattern, piatto, re.IGNORECASE):
            valore = _a_data(m.group(1), m.group(2), m.group(3))
            if valore is None:
                continue
            trovate.append({"etichetta": etichetta, "data": valore.isoformat()})
            per_etichetta.setdefault(etichetta, valore)

    nascita = per_etichetta.get("nascita")

    # Le tre occorrenze della data del giudizio. Si sceglie per maggioranza; a
    # parità vince «Espresso il», che è il campo con il significato giusto — le
    # altre due dicono *quando è stato trasmesso*, che di norma coincide ma non
    # è la stessa cosa.
    candidate = [
        per_etichetta.get(e)
        for e in ("giudizio", "trasmesso_datore", "trasmesso_lavoratore")
    ]
    candidate = [c for c in candidate if c is not None]
    giudizio = None
    if candidate:
        conteggio: dict[date, int] = {}
        for c in candidate:
            conteggio[c] = conteggio.get(c, 0) + 1
        massimo = max(conteggio.values())
        vincenti = [d for d, n in conteggio.items() if n == massimo]
        espressa = per_etichetta.get("giudizio")
        giudizio = espressa if espressa in vincenti else sorted(vincenti)[0]

    return trovate, nascita, giudizio


def _estrai_nominativo(testo: str) -> tuple[str, bool]:
    """Nominativo e se viene dal ripiego. Stringa vuota se non si legge."""
    piatto = _piatto(testo)

    m = re.search(_NOME_ANAGRAFICO, piatto, re.MULTILINE)
    if m:
        nome = re.sub(r"\s+", " ", m.group(4)).strip()
        if len(nome) >= 3:
            return nome, False

    # Il ripiego non usa IGNORECASE di proposito: la riga di firma va presa solo
    # se è davvero in maiuscolo come la stampa, altrimenti aggancia il testo
    # discorsivo del consenso al trattamento che le sta sotto.
    m = re.search(_NOME_RIPIEGO, piatto)
    if m:
        nome = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(nome) >= 3:
            return nome, True

    return "", False


def _estrai_esito(testo: str) -> str:
    """Il giudizio così com'è scritto, senza tradurlo."""
    piatto = _piatto(testo)
    migliore = ""
    for m in re.finditer(r"((?:NON\s+)?IDONE[OA][A-ZÀ-Ù\s']*)", piatto):
        candidato = re.sub(r"\s+", " ", m.group(1)).strip(" '")
        # «IDONEITA'» compare nei titoli («CERTIFICATO MEDICO DI IDONEITA'»,
        # «GIUDIZIO DI IDONEITA'») e non è un esito.
        if candidato.upper().startswith(("IDONEITA", "IDONEIT")):
            continue
        if len(candidato) > len(migliore):
            migliore = candidato
    return migliore


def _estrai_mansione(testo: str) -> str:
    """La mansione dichiarata sul certificato (compare due volte, basta la prima)."""
    for riga in (testo or "").splitlines():
        m = re.search(r"Mansione\s+([A-ZÀ-Ù][A-ZÀ-Ù.\s]{2,60})", riga)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip(" .")
    return ""


def _estrai_protocollo(testo: str) -> list[dict]:
    """Esami del protocollo con la periodicità dichiarata.

    Si lavora **per riga**: con la segmentazione giusta Tesseract tiene appaiate
    le due colonne, e la riga «Visita Medica annuale» dice già tutto. Quando
    invece le colonne si separano — succede con certi layer testo — la riga
    contiene solo la cadenza e non c'è modo di sapere a quale esame appartenga:
    meglio non estrarre nulla che accoppiare a caso, perché un accoppiamento
    sbagliato diventa una scadenza sbagliata.
    """
    cadenze = "|".join(PERIODICITA_NOTE)
    fuori: list[dict] = []
    visti: set[str] = set()

    for riga in (testo or "").splitlines():
        # I bordi della tabella arrivano all'OCR come caratteri: barre, spigoli,
        # trattini di riquadro. Vanno via prima del confronto, altrimenti si
        # attaccano al nome dell'esame e mandano a vuoto la ricerca dell'alias.
        pulita = re.sub(r"[\[\]{}()=_|\\/]+", " ", riga)
        pulita = re.sub(r"\s+", " ", pulita).strip()
        m = re.search(rf"^(.*?)\s+({cadenze})\s*$", pulita, re.IGNORECASE)
        if not m:
            continue
        esame = m.group(1).strip(" .-:·—–")
        if len(esame) < 3:
            continue  # solo la cadenza, senza esame accanto: non si indovina
        chiave = normalizza(esame)
        if chiave in visti:
            continue
        visti.add(chiave)
        fuori.append({"esame": esame, "periodicita": m.group(2).lower()})

    return fuori


def analizza_testo(testo: str) -> CampiReferto:
    """Tutti i campi leggibili in un colpo solo. Non solleva mai."""
    campi = CampiReferto()
    if not (testo or "").strip():
        return campi

    campi.e_certificato = pare_certificato(testo)

    date_trovate, nascita, giudizio = _estrai_date(testo)
    campi.date_trovate = date_trovate
    campi.data_nascita = nascita
    campi.data_giudizio = giudizio

    campi.nominativo, campi.nominativo_da_ripiego = _estrai_nominativo(testo)
    campi.esito_testo = _estrai_esito(testo)
    campi.mansione = _estrai_mansione(testo)
    campi.protocollo = _estrai_protocollo(testo)

    return campi
