"""Chi è la persona di questo referto.

IL PROBLEMA, DETTO CON PRECISIONE

Sul certificato non c'è il codice fiscale, e il numero di cartella è la
numerazione interna del medico: non corrisponde a niente di nostro. Resta un
nominativo passato per l'OCR — cioè un dato *probabile* — e su di esso si decide
a chi attribuire un giudizio di idoneità. È esattamente il tipo di decisione che
non si affida a una somiglianza di stringhe.

LA DATA DI NASCITA È IL PERNO, NON IL NOME

Il certificato porta la data di nascita accanto al nominativo, nello stesso blocco
stampato, e noi ce l'abbiamo in anagrafica (``DipendenteAnagraficaCivile``). È un
dato immutabile e verificabile: se coincide, l'identificazione è praticamente
certa anche con un cognome mangiato dallo scanner; se **non** coincide, nessuna
somiglianza per quanto alta può salvare l'abbinamento. Da qui le due soglie: bassa
quando la data conferma, alta quando manca, e la porta chiusa quando smentisce.

PERCHÉ ``difflib`` E NON UNA LIBRERIA DI FUZZY MATCHING

Perché i dipendenti sono qualche centinaio, non qualche milione: la differenza di
velocità è irrilevante e ``difflib`` è nella libreria standard. È già il criterio
usato altrove nel portale. Una dipendenza in meno da installare su un server IIS
vale più di microsecondi che nessuno percepirà.

COSA NON DECIDE MAI DA SÉ

Un candidato cessato, due candidati sopra soglia, una data di nascita che non
torna, un nominativo arrivato dal riconoscimento di ripiego: tutti casi che
producono una **proposta**, mai una registrazione. La differenza fra proporre e
decidere è tutto il valore di questo modulo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

from .referti_parsing import normalizza

logger = logging.getLogger(__name__)

__all__ = ["Candidato", "EsitoMatch", "cerca_dipendente", "somiglianza"]


@dataclass
class Candidato:
    legacy_id: int
    nominativo: str
    punteggio: int
    data_nascita: date | None = None
    conferma_data_nascita: bool = False
    cessato: bool = False

    def come_dizionario(self) -> dict:
        return {
            "legacy_id": self.legacy_id,
            "nominativo": self.nominativo,
            "punteggio": self.punteggio,
            "cessato": self.cessato,
            "conferma_data_nascita": self.conferma_data_nascita,
        }


@dataclass
class EsitoMatch:
    """L'esito del riconoscimento, con il motivo scritto per chi revisiona."""

    scelto: Candidato | None = None
    candidati: list[Candidato] = field(default_factory=list)
    automatico: bool = False
    motivo: str = ""

    @property
    def legacy_id(self) -> int | None:
        return self.scelto.legacy_id if self.scelto else None


def somiglianza(a: str, b: str) -> int:
    """Quanto si somigliano due nominativi, 0-100.

    Il confronto avviene anche a parole invertite: il certificato scrive
    «COGNOME NOME», l'anagrafica può avere l'ordine opposto, e sono la stessa
    persona. Vince la lettura più favorevole — qui un falso *negativo* manda in
    coda un referto che si sarebbe potuto abbinare, che è uno spreco; il falso
    positivo lo ferma comunque la data di nascita.
    """
    na, nb = normalizza(a), normalizza(b)
    if not na or not nb:
        return 0

    def rapporto(x: str, y: str) -> float:
        return SequenceMatcher(None, x, y, autojunk=False).ratio()

    diretto = rapporto(na, nb)
    invertito = rapporto(na, " ".join(reversed(nb.split())))
    ordinato = rapporto(" ".join(sorted(na.split())), " ".join(sorted(nb.split())))
    return int(round(max(diretto, invertito, ordinato) * 100))


def _anagrafica_civile() -> dict[int, date]:
    """Date di nascita per legacy id, per la conferma dell'identità."""
    from ..models import DipendenteAnagraficaCivile

    return {
        int(lid): nascita
        for lid, nascita in DipendenteAnagraficaCivile.objects
        .exclude(data_nascita=None)
        .values_list("legacy_anagrafica_id", "data_nascita")
        if lid is not None
    }


def _righe_anagrafica() -> list[dict]:
    """Dipendenti su cui cercare, cessati compresi.

    I cessati **si cercano lo stesso**: un referto in ritardo di qualche mese può
    riguardare una persona che nel frattempo è uscita, e non trovarla produrrebbe
    un «dipendente sconosciuto» fuorviante. Vengono trovati e segnalati come tali,
    così chi revisiona decide con l'informazione davanti.
    """
    from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows

    from ..views import _cessati_legacy_ids

    ensure_anagrafica_schema()
    try:
        cessati = _cessati_legacy_ids()
    except Exception:
        logger.exception("Referti: elenco cessati non disponibile")
        cessati = set()

    righe = []
    for row in fetch_anagrafica_rows(deduplicate=True):
        legacy_id = int(row.get("id") or 0)
        if not legacy_id:
            continue
        nominativo = " ".join(
            p for p in (
                str(row.get("cognome") or "").strip(),
                str(row.get("nome") or "").strip(),
            ) if p
        )
        if not nominativo:
            continue
        righe.append({
            "legacy_id": legacy_id,
            "nominativo": nominativo,
            "cessato": legacy_id in cessati,
        })
    return righe


def cerca_dipendente(
    nominativo: str,
    data_nascita: date | None = None,
    *,
    da_ripiego: bool = False,
    config=None,
) -> EsitoMatch:
    """Il dipendente del referto, o una proposta da confermare a mano.

    ``automatico=True`` significa: si può registrare senza che nessuno guardi.
    Tutto il resto è una proposta.
    """
    from ..models_sorveglianza import RefertoIntakeConfig

    config = config or RefertoIntakeConfig.load()
    soglia_con = int(config.soglia_con_data_nascita or 70)
    soglia_senza = int(config.soglia_senza_data_nascita or 92)

    if not (nominativo or "").strip():
        return EsitoMatch(motivo="Nessun nominativo leggibile sul referto.")

    nascite = _anagrafica_civile()
    candidati: list[Candidato] = []

    for riga in _righe_anagrafica():
        punteggio = somiglianza(nominativo, riga["nominativo"])
        nascita_nota = nascite.get(riga["legacy_id"])
        conferma = bool(data_nascita and nascita_nota and nascita_nota == data_nascita)
        # Sotto la soglia bassa non è un candidato, a meno che la data di nascita
        # non lo riporti dentro: è il caso del cognome storpiato dallo scanner.
        if punteggio < soglia_con and not conferma:
            continue
        candidati.append(Candidato(
            legacy_id=riga["legacy_id"],
            nominativo=riga["nominativo"],
            punteggio=punteggio,
            data_nascita=nascita_nota,
            conferma_data_nascita=conferma,
            cessato=riga["cessato"],
        ))

    if not candidati:
        return EsitoMatch(motivo=(
            f"Nessun dipendente somigliante a «{nominativo}». "
            "Il referto resta archiviato: si può abbinare a mano."
        ))

    # Chi ha la data di nascita confermata viene prima di chiunque altro, per
    # quanto somigliante: è l'unico dato del certificato che identifica davvero.
    candidati.sort(key=lambda c: (c.conferma_data_nascita, c.punteggio), reverse=True)
    migliore = candidati[0]
    esito = EsitoMatch(scelto=migliore, candidati=candidati[:5])

    confermati = [c for c in candidati if c.conferma_data_nascita]
    if len(confermati) > 1:
        esito.motivo = (
            "Più dipendenti con la stessa data di nascita e nome somigliante: "
            "va scelto a mano."
        )
        return esito

    if data_nascita and not migliore.conferma_data_nascita:
        esito.motivo = (
            f"La data di nascita sul referto ({data_nascita:%d-%m-%Y}) non coincide "
            f"con quella in anagrafica: da verificare."
        )
        return esito

    if migliore.cessato:
        esito.motivo = "Il dipendente risulta cessato: conferma manuale necessaria."
        return esito

    if da_ripiego:
        esito.motivo = (
            "Il nominativo è stato letto dalla riga di firma, spesso coperta dalla "
            "firma autografa: va confermato a mano."
        )
        return esito

    if migliore.conferma_data_nascita:
        if migliore.punteggio < soglia_con:
            esito.motivo = (
                "Data di nascita coincidente ma nominativo poco somigliante: "
                "da confermare."
            )
            return esito
        esito.automatico = True
        return esito

    # Senza data di nascita serve una somiglianza alta e nessun altro in gara.
    pari_merito = [c for c in candidati if c.punteggio >= soglia_senza]
    if migliore.punteggio >= soglia_senza and len(pari_merito) == 1:
        esito.automatico = True
        return esito

    if len(pari_merito) > 1:
        esito.motivo = "Più dipendenti ugualmente somiglianti: va scelto a mano."
    else:
        esito.motivo = (
            "Data di nascita non leggibile e somiglianza del nominativo insufficiente "
            "per decidere da soli."
        )
    return esito
