"""Report del Registro FAI. I conteggi partono da ``righe_registro``: stessi numeri del registro."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from django.utils import timezone

from ..fai_regole import aggiungi_mesi
from ..models import FaiFase

ORIZZONTE_MESI = 6
SITUAZIONI = ("da_ripetere", "da_verificare", "in_corso", "in_regola", "date_mancanti")
CLIENTE_VUOTO = "Cliente non indicato"


@dataclass(frozen=True)
class Report:
    chiave: str
    nome: str
    descrizione: str
    pdf: bool = True


REPORT = (
    Report("scadenze", "Da ripetere e in scadenza", f"Articoli da ripetere o con la ripetizione entro {ORIZZONTE_MESI} mesi."),
    Report("trimestrale", "Controllo trimestrale", "Articoli da segnalare a IN1 e MSM (MT CN 15 §5.10)."),
    Report("situazione", "Situazione degli articoli", "Un articolo per riga, con il FAI più recente."),
    Report("clienti", "Riepilogo per cliente", "Articoli per cliente e situazione."),
    Report("tutti", "Tutti i FAI", "Le colonne del file Situazione FAI-ISIR, un FAI per riga.", pdf=False),
)
PER_CHIAVE = {r.chiave: r for r in REPORT}

COLONNE_ARTICOLI = (
    "Cliente", "P/N", "Nome particolare", "Rev.", "Piano FAI", "Stato", "Invio", "Chiusura",
    "Ultima produzione", "Ultima spedizione", "Ripetizione entro", "Situazione", "Nota", "Responsabile",
)
# Nel PDF orizzontale non stanno tutte: restano quelle che servono a decidere.
COLONNE_ARTICOLI_PDF = tuple(c for c in COLONNE_ARTICOLI if c not in ("Rev.", "Nota", "Responsabile"))


def filtra_cliente(righe: list[dict], cliente: str) -> list[dict]:
    return [r for r in righe if r["articolo"].client_name == cliente] if cliente else righe


def conta_situazioni(righe: list[dict]) -> dict[str, int]:
    return Counter(r["situazione"].codice for r in righe)


def scadenze(righe: list[dict], oggi=None) -> list[dict]:
    limite = aggiungi_mesi(oggi or timezone.localdate(), ORIZZONTE_MESI)
    scelte = [
        r for r in righe
        if r["situazione"].codice == "da_ripetere" or (r["ripetizione"] and r["ripetizione"] <= limite)
    ]
    return sorted(scelte, key=lambda r: (r["ripetizione"] is None, r["ripetizione"], r["articolo"].part_number))


def trimestrale(righe: list[dict]) -> list[dict]:
    return [r for r in righe if r["situazione"].codice == "da_verificare"]


def per_cliente(righe: list[dict]) -> list[dict]:
    gruppi: dict[str, Counter] = defaultdict(Counter)
    for riga in righe:
        gruppi[riga["articolo"].client_name or CLIENTE_VUOTO][riga["situazione"].codice] += 1
    return [
        {"cliente": cliente, "totale": sum(conti.values()), **{s: conti[s] for s in SITUAZIONI}}
        for cliente, conti in sorted(gruppi.items(), key=lambda g: g[0].lower())
    ]


def per_stato(records) -> list[dict]:
    conti = Counter(records.values_list("stato_id", "stato__etichetta"))
    return [
        {"id": chiave[0], "etichetta": chiave[1], "conta": conta}
        for chiave, conta in sorted(conti.items(), key=lambda e: (-e[1], e[0][1]))
    ]


def per_anno(records) -> list[dict]:
    """Gli annullati non contano. Date di chiusura precedenti all'invio: errori del file, fuori dalla media."""
    inviati, chiusi = Counter(), Counter()
    giorni: dict[int, list[int]] = defaultdict(list)
    dati = records.exclude(stato__fase=FaiFase.ANNULLATO).filter(data_invio__isnull=False)
    for invio, chiusura in dati.values_list("data_invio", "data_chiusura"):
        inviati[invio.year] += 1
        if chiusura:
            chiusi[invio.year] += 1
            if chiusura >= invio:
                giorni[invio.year].append((chiusura - invio).days)
    return [
        {
            "anno": anno, "inviati": inviati[anno], "chiusi": chiusi[anno],
            "giorni": round(sum(giorni[anno]) / len(giorni[anno])) if giorni[anno] else None,
        }
        for anno in sorted(inviati, reverse=True)
    ]


def _nome(utente) -> str:
    return (utente.get_full_name() or utente.username) if utente else ""


def righe_articoli(righe: list[dict]) -> list[list]:
    return [
        [
            r["articolo"].client_name, r["articolo"].part_number, r["fai"].nome_particolare, r["fai"].revisione,
            r["fai"].piano_numero, r["fai"].stato.etichetta, r["fai"].data_invio, r["fai"].data_chiusura,
            r["articolo"].ultima_produzione, r["articolo"].ultima_spedizione, r["ripetizione"],
            r["situazione"].etichetta, r["situazione"].nota, _nome(r["fai"].responsabile),
        ]
        for r in righe
    ]


def righe_pdf(righe_excel: list[list]) -> list[list]:
    indici = [COLONNE_ARTICOLI.index(c) for c in COLONNE_ARTICOLI_PDF]
    return [[_testo(riga[i]) for i in indici] for riga in righe_excel]


def _testo(valore) -> str:
    if valore is None:
        return ""
    return valore.strftime("%d/%m/%Y") if hasattr(valore, "strftime") else str(valore)
