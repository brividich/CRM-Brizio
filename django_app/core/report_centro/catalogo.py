"""Catalogo dei report del portale.

Ogni modulo ha un file ``contenuti/<modulo>.py`` con tre nomi:

- ``MODULO``: chiave breve (es. ``"anagrafica"``), prefisso delle chiavi voce;
- ``ETICHETTA``: nome del modulo come lo vede l'utente;
- ``VOCI``: lista di :class:`ReportVoce`.

Il catalogo è codice, non database: una voce nasce insieme alla route che la
produce e il test ``core.tests_report_centro`` verifica che ogni route e ogni
pagina dichiarata esista davvero. Per aggiungere un modulo: nuovo file in
``contenuti/`` e una riga in ``_MODULI_CONTENUTI``.

Il collegamento con il registro delle emissioni passa dal *view name* della
route (``request.resolver_match.view_name``): un file scaricato da una route
elencata in ``ReportVoce.route`` viene attribuito a quella voce.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from functools import lru_cache

# Veste grafica dichiarata della voce.
LAYOUT_CORE_PDF = "core_pdf"        # PDF con il template unico del portale (core.pdf)
LAYOUT_EXCEL = "excel"              # Excel con intestazione del portale (core.excel_export)
LAYOUT_DATI = "dati"                # esportazione dati senza veste (CSV, Excel tabellare)
LAYOUT_COMPONIBILE = "componibile"  # costruito dall'editor del modulo (modelli/blocchi)
LAYOUT_SU_MISURA = "su_misura"      # modello documentale proprio (attestato, MOD.xxx, etichette)
LAYOUT_STAMPA = "stampa"            # pagina HTML da stampare dal browser

LAYOUT_CHOICES = {
    LAYOUT_CORE_PDF: "Template PDF del portale",
    LAYOUT_EXCEL: "Excel con intestazione",
    LAYOUT_DATI: "Dati (senza veste)",
    LAYOUT_COMPONIBILE: "Componibile dal modulo",
    LAYOUT_SU_MISURA: "Modello su misura",
    LAYOUT_STAMPA: "Pagina da stampare",
}

# Le vesti su cui un profilo di layout ha effetto (passano da PdfTheme).
LAYOUT_CON_PROFILO = frozenset({LAYOUT_CORE_PDF, LAYOUT_COMPONIBILE, LAYOUT_EXCEL})

FORMATI = ("pdf", "xlsx", "csv", "docx", "zip", "html")

_MODULI_CONTENUTI = (
    "admin_portale",
    "ai_assistant",
    "anagrafica",
    "formazione",
    "visite",
    "anomalie",
    "assenze",
    "assets",
    "checklist_operativa",
    "contatori",
    "dashboard",
    "diario_preposto",
    "dpi",
    "gestione_specifiche",
    "notizie",
    "procedure_refresh",
    "rentri",
    "report_conformita",
    "rilevazione_incidenti",
    "schede_sicurezza",
    "security",
    "sistema_gestione",
    "tasks",
    "tickets",
    "timbri",
)


@dataclass(frozen=True)
class ReportVoce:
    """Un report del portale, come lo dichiara il modulo che lo produce."""

    chiave: str
    nome: str
    descrizione: str
    formati: tuple[str, ...]
    route: tuple[str, ...] = ()
    pagina: str = ""
    dati_personali: bool = False
    layout: str = LAYOUT_CORE_PDF
    norma: str = ""
    modulo: str = field(default="", compare=False)
    modulo_etichetta: str = field(default="", compare=False)

    @property
    def layout_etichetta(self) -> str:
        return LAYOUT_CHOICES.get(self.layout, self.layout)

    @property
    def accetta_profilo(self) -> bool:
        return self.layout in LAYOUT_CON_PROFILO

    @property
    def tracciato(self) -> bool:
        """Produce un file (quindi finisce nel registro emissioni)."""
        return bool(self.route) and any(f != "html" for f in self.formati)


def voce(
    slug: str,
    nome: str,
    descrizione: str,
    formati,
    *,
    route=(),
    pagina: str = "",
    dati_personali: bool = False,
    layout: str = LAYOUT_CORE_PDF,
    norma: str = "",
) -> dict:
    """Dichiarazione compatta usata dai file ``contenuti``."""
    if isinstance(formati, str):
        formati = (formati,)
    if isinstance(route, str):
        route = (route,)
    return {
        "slug": slug,
        "nome": nome,
        "descrizione": descrizione,
        "formati": tuple(formati),
        "route": tuple(route),
        "pagina": pagina,
        "dati_personali": dati_personali,
        "layout": layout,
        "norma": norma,
    }


@dataclass(frozen=True)
class Modulo:
    chiave: str
    etichetta: str
    voci: tuple[ReportVoce, ...]


@lru_cache(maxsize=1)
def moduli() -> tuple[Modulo, ...]:
    risultato = []
    for nome in _MODULI_CONTENUTI:
        mod = importlib.import_module(f"core.report_centro.contenuti.{nome}")
        chiave_modulo = mod.MODULO
        voci = tuple(
            ReportVoce(
                chiave=f"{chiave_modulo}.{d['slug']}",
                nome=d["nome"],
                descrizione=d["descrizione"],
                formati=d["formati"],
                route=d["route"],
                pagina=d["pagina"],
                dati_personali=d["dati_personali"],
                layout=d["layout"],
                norma=d["norma"],
                modulo=chiave_modulo,
                modulo_etichetta=mod.ETICHETTA,
            )
            for d in mod.VOCI
        )
        risultato.append(Modulo(chiave=chiave_modulo, etichetta=mod.ETICHETTA, voci=voci))
    return tuple(risultato)


def voci() -> tuple[ReportVoce, ...]:
    return tuple(v for m in moduli() for v in m.voci)


@lru_cache(maxsize=1)
def _indice_chiavi() -> dict[str, ReportVoce]:
    return {v.chiave: v for v in voci()}


@lru_cache(maxsize=1)
def _indice_route() -> dict[str, ReportVoce]:
    indice: dict[str, ReportVoce] = {}
    for v in voci():
        for route in v.route:
            indice.setdefault(route, v)
    return indice


def voce_per_chiave(chiave: str) -> ReportVoce | None:
    return _indice_chiavi().get(str(chiave or ""))


def voce_per_route(view_name: str) -> ReportVoce | None:
    return _indice_route().get(str(view_name or ""))


def etichetta_modulo(chiave: str) -> str:
    for m in moduli():
        if m.chiave == chiave:
            return m.etichetta
    return chiave
