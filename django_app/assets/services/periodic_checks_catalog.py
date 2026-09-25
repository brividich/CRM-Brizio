"""Catalogo iniziale delle verifiche periodiche e mappa dell'archivio storico.

Fonte: registro «Verifiche riassuntive ditta Bruschi.xlsx» (codici e periodicita')
e le cartelle di ``\\\\novisrv\\privman`` censite il 25/09/2026. Usato da
``seed_periodic_checks`` (crea impianti e tipi) e ``import_periodic_checks``
(porta i documenti gia' archiviati come verifiche storiche).

Le cartelle sono relative alla radice dell'archivio passata al comando. ``include``
/ ``exclude`` sono regex (case-insensitive) sul nome del file; ``recursive`` dice se
scendere nelle sottocartelle (anni, mesi). Solo PDF e immagini: le email (.msg) e i
fogli Excel restano fuori.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import PeriodicCheckType

CHECKLIST = PeriodicCheckType.METHOD_CHECKLIST
REPORT = PeriodicCheckType.METHOD_REPORT
LAYOUT = PeriodicCheckType.METHOD_LAYOUT
MEASURES = PeriodicCheckType.METHOD_MEASURES

ELETTRICO = "Impianto elettrico"
ANTINCENDIO = "Impianto antincendio"
PRIMO_SOCCORSO = "Primo soccorso"
AZOTO = "Impianto azoto"

SYSTEMS: list[tuple[str, str, int]] = [
    (ELETTRICO, "Cabine MT/BT, quadri, distribuzione, illuminazione di emergenza, UPS, antintrusione", 10),
    (ANTINCENDIO, "Impianto idrico fisso, gruppo di pressurizzazione, estintori e manichette", 20),
    (PRIMO_SOCCORSO, "Defibrillatore (DAE) e presidi di primo soccorso", 30),
    (AZOTO, "Serbatoio criogenico e vaporizzazione azoto", 40),
]

_E = "_Impianto Elettrico/Verifiche impianto elettrico"
_DOCS_OUT = r"planimetria|modello|informativa|analisi degli allarmi|straordinari|richiesta|offert|ordine|fattura"


@dataclass
class ArchiveSource:
    folder: str
    recursive: bool = True
    include: str = ""
    exclude: str = _DOCS_OUT


@dataclass
class CatalogType:
    system: str
    name: str
    frequency_months: int
    method: str
    reference_code: str = ""
    executor: str = ""
    supplier_hint: str = ""  # frammento della ragione sociale in anagrafica fornitori
    legal_reference: str = ""
    items: list[str] = field(default_factory=list)
    sources: list[ArchiveSource] = field(default_factory=list)
    sort_order: int = 100


BRUSCHI = "Bruschi Florio"

CATALOG: list[CatalogType] = [
    CatalogType(
        ELETTRICO, "Verifica illuminazione di emergenza", 4, LAYOUT, "002", BRUSCHI, "bruschi",
        sources=[ArchiveSource(f"{_E}/Verifica illuminazione di emergenza (quadrimestrale)")], sort_order=10,
    ),
    CatalogType(
        ELETTRICO, "Verifica quadri elettrici", 6, CHECKLIST, "005", BRUSCHI, "bruschi",
        items=[
            "Esame a vista",
            "Controllo serraggio morsetti",
            "Controllo temperature",
            "Pulizia delle polveri depositate",
            "Spazzolatura e/o aspirazione",
        ],
        sources=[ArchiveSource(f"{_E}/Verifica quadri elettrici (semestrale)")], sort_order=20,
    ),
    CatalogType(
        ELETTRICO, "Verifica cabine MT/BT", 12, CHECKLIST, "023", BRUSCHI, "bruschi",
        items=[
            "Pulizia cabine e celle trasformatore",
            "Esame a vista",
            "Controllo visivo cavi MT",
            "Controllo livello olio",
            "Controllo interruttori e morsettiere",
            "Controllo serraggio morsetti",
            "Aspirazione polveri o depositi",
        ],
        sources=[ArchiveSource(f"{_E}/Verifica cabina MT-BT (annuale)")], sort_order=30,
    ),
    CatalogType(
        ELETTRICO, "Verifica interruttori differenziali con strumento", 12, MEASURES, "001", BRUSCHI, "bruschi",
        legal_reference="CEI 64-8 art. 62.2.1",
        sources=[ArchiveSource(f"{_E}/Verifica interruttori differenziali con strumento (annuale)")], sort_order=40,
    ),
    CatalogType(
        ELETTRICO, "Verifica interruttori differenziali con tasto prova", 12, LAYOUT, "011", BRUSCHI, "bruschi",
        sources=[ArchiveSource(f"{_E}/Verifica interruttori differenziali con tasto prova (annuale)")], sort_order=50,
    ),
    CatalogType(
        ELETTRICO, "Verifica impianto elettrico generale", 12, REPORT, "020", BRUSCHI, "bruschi",
        sources=[ArchiveSource(f"{_E}/Verifica impianto elettrico generale (annuale)")], sort_order=60,
    ),
    CatalogType(
        ELETTRICO, "Verifica impianto di messa a terra", 24, REPORT, "010", "HT S.r.l. (organismo abilitato)", "ht s",
        legal_reference="DPR 462/01",
        sources=[ArchiveSource(f"{_E}/Verifica Impianto a Terra (biennale)/Rapporti verifiche")], sort_order=70,
    ),
    CatalogType(
        ELETTRICO, "Verifica pacchi batteria gruppo UPS", 4, MEASURES, "021", BRUSCHI, "bruschi",
        sources=[ArchiveSource(f"{_E}/Verifica pacchi batteria gruppo UPS (quadrimestrale)")], sort_order=80,
    ),
    CatalogType(
        ELETTRICO, "Verifica impianto antintrusione", 4, MEASURES, "030", BRUSCHI, "bruschi",
        sources=[ArchiveSource(f"{_E}/Verifica impianto antintrusione (quadrimestrale)")], sort_order=90,
    ),
    CatalogType(
        ELETTRICO, "Analisi olio trasformatori cabine", 24, REPORT, "4", BRUSCHI, "bruschi",
        sources=[ArchiveSource(f"{_E}/Verifica Olio Trasformatori Cabine (biennale)")], sort_order=100,
    ),
    CatalogType(
        ANTINCENDIO, "Manutenzione semestrale impianto antincendio", 6, REPORT, executor="Gruppo Lupi",
        supplier_hint="lupi",
        sources=[ArchiveSource("_Antincendio/Verifiche anticendio", exclude=_DOCS_OUT + r"|prova funzionamento")],
        sort_order=10,
    ),
    CatalogType(
        ANTINCENDIO, "Prova di funzionamento ed efficienza impianto idrico antincendio", 12, REPORT,
        executor="Per. Ind. Zega (relazione tecnica)",
        sources=[
            ArchiveSource(
                "_Antincendio/Relazioni Tecniche Funzionamento_Efficienza Impianto Antincendio (Zega)",
                include=r"prova funzionamento|relazione tecnica",
            ),
            ArchiveSource("_Antincendio/Verifiche anticendio", include=r"prova funzionamento"),
        ],
        sort_order=20,
    ),
    CatalogType(
        ANTINCENDIO, "Verifica semestrale estintori e manichette", 6, REPORT, executor="Lattanzi Group",
        supplier_hint="lattanzi",
        sources=[ArchiveSource("_Antincendio/Verifiche semestrali manichette e estintori")], sort_order=30,
    ),
    CatalogType(
        PRIMO_SOCCORSO, "Test annuale defibrillatore (DAE)", 12, REPORT,
        sources=[ArchiveSource("_BLS D", include=r"test")], sort_order=10,
    ),
    CatalogType(
        AZOTO, "Manutenzione annuale impianto azoto", 12, REPORT, executor="Sapio", supplier_hint="sapio",
        sources=[ArchiveSource("_Azoto/Verifiche", exclude=_DOCS_OUT + r"|inail")], sort_order=10,
    ),
]
