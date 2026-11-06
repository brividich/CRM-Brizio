"""Migrazione del file «Situazione FAI-ISIR» nel Registro FAI.

Ogni riga del foglio diventa un FAI. Il valore originale resta in ``origine_excel``:
una data scritta a parole («Previsione…») non diventa una data, ma non si perde.
Si può rilanciare finché il file resta in uso: le righe già importate si aggiornano,
quelle modificate nel portale non si toccano.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import warnings
from collections import Counter
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from ..models import FaiArticolo, FaiDocumento, FaiFase, FaiGruppo, FaiOpzione, FaiRecord

FOGLIO = "Situazione FAI"
TOLLERANZA_MODIFICA = dt.timedelta(minutes=1)

# Intestazione normalizzata (solo lettere e cifre) -> nome interno.
COLONNE = {
    "CLIENTE": "cliente",
    "FALDONEN": "faldone",
    "CCICNN": "cci_numero",
    "ANNOCCICN": "cci_anno",
    "FAICNN": "fai_numero",
    "ANNOFAICN": "fai_anno",
    "NINVITO": "invito",
    "LINEA": "linea",
    "PNASSY": "pn_assy",
    "PN": "pn",
    "NOMEPARTICOLARE": "nome_particolare",
    "REV": "revisione",
    "PNALTERNATIVO": "pn_alternativo",
    "REVPNALTERNATIVO": "rev_alternativo",
    "CRITICITA": "criticita",
    "PIANOFAIN": "piano_numero",
    "DESCRIZIONEPIANOFAI": "descrizione_piano",
    "AVANZAMENTOPIANOFAI": "avanzamento",
    "STATOPIANOFAI": "stato",
    "DATAINVIODOCUMENTAZIONE": "data_invio",
    "OP": "op",
    "ODAITEM": "oda_item",
    "CHIUSURAFAICON": "chiusura_con",
    "DATACHIUSURAFAI": "data_chiusura",
    "VERISONEDIPRODUZIONE": "versione_produzione",
    "VERSIONEDIPRODUZIONE": "versione_produzione",
    "STATOVERSIONE": "stato_versione",
    "DATAVERSIONE": "data_versione",
    "CODICEDIP": "codice_dip",
    "DATAAPPROVAZIONEDIP": "data_approvazione_dip",
    "INVIOCQ": "invio_cq",
    "CROSSCORRELATION": "cross_correlation",
    "SDC": "doc_sdc",
    "PFC": "doc_pfc",
    "SINTESI": "doc_sintesi",
    "FAI": "doc_fai",
    "NOTE": "note",
}
OBBLIGATORIE = {"cliente", "pn", "stato", "piano_numero", "data_invio", "data_chiusura"}

CAMPI_TESTO = (
    "faldone", "cci_numero", "cci_anno", "fai_numero", "fai_anno", "invito", "linea", "pn_assy", "nome_particolare",
    "revisione", "pn_alternativo", "rev_alternativo", "criticita", "piano_numero", "descrizione_piano", "avanzamento",
    "op", "oda_item", "versione_produzione", "codice_dip", "invio_cq", "note",
)
CAMPI_DATA = ("data_invio", "data_chiusura", "data_versione", "data_approvazione_dip")
CAMPI_DOCUMENTO = ("doc_sdc", "doc_pfc", "doc_sintesi", "doc_fai")

VUOTI = {"", "N/A", "NA", "/", "-", "--", "X", "?", "#REF!"}
SOLO_ERRORE = "#REF!"
DOCUMENTI = {"X": FaiDocumento.PRESENTE, "?": FaiDocumento.DA_VERIFICARE, "N/A": FaiDocumento.NON_APPLICABILE}

# Fase degli stati del file che dicono da soli di essere conclusi; gli altri restano «in corso»
# e si possono cambiare in Impostazioni.
FASI_STATO = {"APPROVATO": FaiFase.POSITIVO, "F2 CHIUSO": FaiFase.POSITIVO, "ANNULLATO": FaiFase.ANNULLATO}
STATO_NON_INDICATO = "Non indicato"
CROSS_NOTE = (
    ("RICHIESTA MA NON FORNITA", "Richiesta ma non fornita"),
    ("NON RICHIESTA", "Non richiesta"),
    ("MANCA CROSS", "Manca cross con ZPN"),
    ("CON ZPN", "Inviata con ZPN"),
    ("INVIATA", "Inviata"),
)
_DATA_TESTO = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")


def _chiave_colonna(intestazione) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(intestazione or "").upper())


def _testo(valore) -> str:
    if valore is None:
        return ""
    if isinstance(valore, float) and valore.is_integer():
        valore = int(valore)
    if isinstance(valore, (dt.datetime, dt.date)):
        return f"{valore:%d/%m/%Y}"
    return " ".join(str(valore).split())


def _originale(valore) -> str:
    if isinstance(valore, (dt.datetime, dt.date)):
        return f"{valore:%Y-%m-%d}"
    return "" if valore is None else str(valore)


def _data_valida(giorno: dt.date) -> dt.date | None:
    # Il 2099 del file è un segnaposto, non una data.
    return giorno if 1990 <= giorno.year <= 2090 else None


def leggi_data(valore) -> tuple[dt.date | None, bool]:
    """Ritorna la data e se il valore andava letto ma non si è potuto."""
    if isinstance(valore, dt.datetime):
        giorno = _data_valida(valore.date())
        return giorno, giorno is None
    if isinstance(valore, dt.date):
        giorno = _data_valida(valore)
        return giorno, giorno is None
    testo = _testo(valore)
    if testo.upper() in VUOTI:
        return None, False
    # «Previsione 21/10/2020» è un'intenzione, non un fatto.
    if re.search(r"[A-Za-z]", testo):
        return None, True
    trovate = []
    for giorno, mese, anno in _DATA_TESTO.findall(testo):
        anno = int(anno) + 2000 if len(anno) == 2 else int(anno)
        try:
            data = _data_valida(dt.date(anno, int(mese), int(giorno)))
        except ValueError:
            continue
        if data:
            trovate.append(data)
    # Più date nella stessa cella: conta l'ultima.
    return (max(trovate), False) if trovate else (None, True)


def _documento(valore) -> str:
    return DOCUMENTI.get(_testo(valore).upper(), "")


def _cross(valore) -> str:
    testo = _testo(valore).upper()
    for frammento, etichetta in CROSS_NOTE:
        if frammento in testo:
            return etichetta
    return ""


@dataclass
class Esito:
    righe: int = 0
    creati: int = 0
    aggiornati: int = 0
    invariati: int = 0
    modificati_nel_portale: int = 0
    scartate: int = 0
    articoli_nuovi: int = 0
    date_illeggibili: int = 0
    celle_errore: int = 0
    testi_troncati: int = 0
    cross_non_riconosciute: int = 0
    stati: Counter = field(default_factory=Counter)
    scarti: list = field(default_factory=list)  # (riga, motivo)
    avvisi: list = field(default_factory=list)  # (riga, colonna, motivo)


class FileNonValido(ValueError):
    pass


def leggi_righe(percorso) -> list[tuple[int, dict]]:
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        libro = openpyxl.load_workbook(percorso, read_only=True, data_only=True)
    if FOGLIO not in libro.sheetnames:
        raise FileNonValido(f"Manca il foglio «{FOGLIO}».")
    foglio = libro[FOGLIO].iter_rows(values_only=True)
    try:
        testata = next(foglio)
    except StopIteration as exc:
        raise FileNonValido("Il foglio è vuoto.") from exc
    colonne = {i: COLONNE.get(_chiave_colonna(nome)) for i, nome in enumerate(testata)}
    mancanti = OBBLIGATORIE - set(colonne.values())
    if mancanti:
        raise FileNonValido(f"Colonne non trovate: {', '.join(sorted(mancanti))}.")
    righe = []
    for numero, valori in enumerate(foglio, start=2):
        if not any(v not in (None, "") for v in valori):
            continue
        righe.append((numero, {colonne[i]: v for i, v in enumerate(valori) if colonne.get(i)}))
    libro.close()
    return righe


class _Opzioni:
    """Trova o crea le voci configurabili, una sola volta per nome."""

    def __init__(self):
        self.cache = {}

    def voce(self, gruppo: str, etichetta: str, **altri) -> FaiOpzione | None:
        if not etichetta:
            return None
        chiave = (gruppo, etichetta.upper())
        if chiave not in self.cache:
            voce = FaiOpzione.objects.filter(gruppo=gruppo, etichetta__iexact=etichetta).first()
            if voce is None:
                ultimo = FaiOpzione.objects.filter(gruppo=gruppo).order_by("-ordine").first()
                voce = FaiOpzione.objects.create(
                    gruppo=gruppo, etichetta=etichetta[:120], ordine=(ultimo.ordine if ultimo else 0) + 10, **altri
                )
            self.cache[chiave] = voce
        return self.cache[chiave]

    def stato(self, testo: str) -> FaiOpzione:
        etichetta = STATO_NON_INDICATO if testo.upper() in VUOTI else testo
        fase = FASI_STATO.get(etichetta.upper(), FaiFase.IN_CORSO)
        return self.voce(FaiGruppo.STATO, etichetta, fase=fase)


def _chiave(riga: dict, occorrenze: Counter) -> str:
    identita = "|".join(
        _testo(riga.get(c)).upper()
        for c in ("cliente", "pn", "fai_numero", "fai_anno", "piano_numero", "op", "oda_item", "revisione")
    )
    occorrenze[identita] += 1
    return hashlib.sha256(f"{identita}#{occorrenze[identita]}".encode()).hexdigest()


def _base_cronologica(riga: dict) -> dt.date:
    return leggi_data(riga.get("data_chiusura"))[0] or leggi_data(riga.get("data_invio"))[0] or dt.date.min


def _valori(numero: int, riga: dict, opzioni: _Opzioni, esito: Esito) -> dict:
    valori = {}
    for campo in CAMPI_TESTO:
        testo = _testo(riga.get(campo))
        if testo == SOLO_ERRORE:
            esito.celle_errore += 1
            testo = ""
        if testo.upper() in ("N/A", "NA", "/"):
            testo = ""
        massimo = FaiRecord._meta.get_field(campo).max_length
        if massimo and len(testo) > massimo:
            esito.testi_troncati += 1
            esito.avvisi.append((numero, campo, "testo troppo lungo, completo nei dati originali"))
            testo = testo[:massimo]
        valori[campo] = testo
    for campo in CAMPI_DATA:
        valori[campo], illeggibile = leggi_data(riga.get(campo))
        if illeggibile:
            esito.date_illeggibili += 1
            esito.avvisi.append((numero, campo, "data non leggibile, resta nei dati originali"))
    for campo in CAMPI_DOCUMENTO:
        if _testo(riga.get(campo)) == SOLO_ERRORE:
            esito.celle_errore += 1
        valori[campo] = _documento(riga.get(campo))

    stato = opzioni.stato(_testo(riga.get("stato")))
    esito.stati[stato.etichetta] += 1
    valori["stato"] = stato

    chiusura = _testo(riga.get("chiusura_con"))
    valori["chiusura_con"] = opzioni.voce(FaiGruppo.CHIUSURA, "" if chiusura.upper() in VUOTI else chiusura)
    versione = _testo(riga.get("stato_versione"))
    valori["stato_versione"] = opzioni.voce(FaiGruppo.VERSIONE, "" if versione.upper() in VUOTI else versione)
    grezzo = _testo(riga.get("cross_correlation"))
    cross = _cross(grezzo)
    if grezzo.upper() not in VUOTI and not cross:
        esito.cross_non_riconosciute += 1
        esito.avvisi.append((numero, "cross_correlation", "valore non riconosciuto, resta nei dati originali"))
    valori["cross_correlation"] = opzioni.voce(FaiGruppo.CROSS, cross)
    return valori


def importa(percorso, *, applica: bool = False, utente=None) -> Esito:
    """Senza ``applica`` fa tutto e annulla: i conteggi sono quelli veri."""
    righe = leggi_righe(percorso)
    esito = Esito(righe=len(righe))
    occorrenze: Counter = Counter()
    # La chiave segue l'ordine del file, così resta stabile fra un'importazione e l'altra.
    con_chiave = [(numero, riga, _chiave(riga, occorrenze)) for numero, riga in righe]
    # I FAI più recenti hanno l'id più alto: il registro prende così quello giusto per articolo.
    con_chiave.sort(key=lambda r: (_base_cronologica(r[1]), r[0]))

    with transaction.atomic():
        opzioni = _Opzioni()
        articoli = {(a.client_name.upper(), a.part_number.upper()): a for a in FaiArticolo.objects.all()}
        esistenti = {r.chiave_import: r for r in FaiRecord.objects.exclude(chiave_import="")}
        adesso = timezone.now()
        for numero, riga, chiave in con_chiave:
            cliente, pn = _testo(riga.get("cliente")), _testo(riga.get("pn"))
            if pn.upper() in VUOTI:
                esito.scartate += 1
                esito.scarti.append((numero, "P/N mancante"))
                continue
            originale = {nome: _originale(v) for nome, v in riga.items() if v not in (None, "")}
            record = esistenti.get(chiave)
            if record is not None:
                if record.importato_il and record.updated_at > record.importato_il + TOLLERANZA_MODIFICA:
                    esito.modificati_nel_portale += 1
                    continue
                if record.origine_excel == originale:
                    esito.invariati += 1
                    continue
            articolo = articoli.get((cliente.upper(), pn.upper()))
            if articolo is None:
                articolo = FaiArticolo.objects.create(client_name=cliente[:180], part_number=pn[:120])
                articoli[(cliente.upper(), pn.upper())] = articolo
                esito.articoli_nuovi += 1
            valori = _valori(numero, riga, opzioni, esito)
            nuovo = record is None
            if nuovo:
                record = FaiRecord(chiave_import=chiave, created_by=utente, tipo="")
            record.articolo = articolo
            record.origine_excel = originale
            record.importato_il = adesso
            for campo, valore in valori.items():
                setattr(record, campo, valore)
            record.save()
            if nuovo:
                esito.creati += 1
            else:
                esito.aggiornati += 1
        if not applica:
            transaction.set_rollback(True)
    return esito
