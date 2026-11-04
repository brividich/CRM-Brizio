"""Catalogo dinamico delle voci dello scadenzario, per il pannello di gestione.

Albero fonte → tipo → elemento costruito da:

- i tipi noti di ogni fonte (compaiono anche senza scadenze in corso);
- le voci presenti oggi (raccolta di sistema: scadute più prossimi 90 giorni),
  quindi un tipo di qualifica, un corso, una categoria nuovi compaiono da soli;
- per le scadenze generiche tutte le categorie e le attività dal database;
- le chiavi già impostate nel pannello, anche se oggi non hanno voci (restano
  visibili per poterle cambiare o togliere).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .visibilita import SEP, chiavi_di, slug

TIPI_NOTI: dict[str, dict[str, str]] = {
    "hr": {"qualifica": "Qualifica", "visita": "Visita medica", "formazione": "Formazione", "contratto": "Contratto"},
    "asset": {"administrative": "Scadenza amministrativa", "license": "Licenza software", "contract": "Contratto di assistenza"},
    "impianti": {"verifica_impianto": "Verifica impianto"},
    "dpi": {"dpi": "DPI (vita utile)"},
    "rentri": {"fir": "FIR mancante", "deposito": "Deposito temporaneo"},
    "capa": {"capa": "Azione CAPA"},
}


def _tipi_moduli() -> None:
    from .fonti_moduli import TIPI

    TIPI_NOTI.update(TIPI)


_tipi_moduli()


@dataclass
class Nodo:
    chiave: str
    etichetta: str
    livello: int
    n_voci: int = 0
    figli: list["Nodo"] = field(default_factory=list)
    presente: bool = True

    def figlio(self, chiave: str, etichetta: str) -> "Nodo":
        for f in self.figli:
            if f.chiave == chiave:
                if etichetta and f.etichetta in ("", f.chiave.split(SEP)[-1]):
                    f.etichetta = etichetta
                return f
        nodo = Nodo(chiave=chiave, etichetta=etichetta or chiave.split(SEP)[-1], livello=self.livello + 1)
        self.figli.append(nodo)
        return nodo


def _kind_noti_asset() -> dict[str, str]:
    try:
        from assets.services import deadline_feed as feed

        return {
            feed.KIND_ADMINISTRATIVE: "Scadenza amministrativa",
            feed.KIND_LICENSE: "Licenza software",
            feed.KIND_CONTRACT: "Contratto di assistenza",
        }
    except Exception:
        return TIPI_NOTI["asset"]


def costruisci(*, voci=None, configurate: dict[str, str] | None = None) -> list[Nodo]:
    """Radici dell'albero (una per fonte). ``voci`` = raccolta di sistema."""
    from dashboard.scadenze_providers import PROVIDERS, SOURCE_LABELS, collect_sistema

    from .fonte import SOURCE as GENERICHE, chiave_attivita, chiave_categoria
    from .models import CategoriaScadenza, ScadenzaGenerica

    if voci is None:
        voci = collect_sistema()
    radici: dict[str, Nodo] = {}
    for code in PROVIDERS:
        radici[code] = Nodo(chiave=code, etichetta=SOURCE_LABELS.get(code, code), livello=0)
        tipi = _kind_noti_asset() if code == "asset" else TIPI_NOTI.get(code, {})
        for kind, label in tipi.items():
            radici[code].figlio(chiavi_di(code, kind)[1], label)

    # Scadenze generiche: tutte le categorie e attività, anche oltre i 90 giorni.
    if GENERICHE in radici:
        radice = radici[GENERICHE]
        for cat in CategoriaScadenza.objects.order_by("nome"):
            radice.figlio(chiavi_di(GENERICHE, chiave_categoria(cat.pk))[1], cat.nome)
        for s in ScadenzaGenerica.objects.select_related("categoria").order_by("titolo"):
            kind = chiave_categoria(s.categoria_id)
            nodo_tipo = radice.figlio(chiavi_di(GENERICHE, kind)[1], s.categoria.nome)
            nodo_tipo.figlio(chiavi_di(GENERICHE, kind, chiave_attivita(s.pk))[2], s.titolo)

    for v in voci:
        radice = radici.get(v.source)
        if radice is None:
            continue
        radice.n_voci += 1
        chiavi = chiavi_di(v.source, v.kind, v.elemento)
        if len(chiavi) < 2:
            continue
        nodo_tipo = radice.figlio(chiavi[1], v.kind_label)
        nodo_tipo.n_voci += 1
        if len(chiavi) > 2:
            nodo_el = nodo_tipo.figlio(chiavi[2], v.elemento_label or v.elemento)
            nodo_el.n_voci += 1

    # Chiavi impostate che oggi non hanno voci.
    for chiave, etichetta in (configurate or {}).items():
        parti = chiave.split(SEP)
        radice = radici.get(parti[0])
        if radice is None:
            continue
        nodo = radice
        for i in range(1, len(parti)):
            esiste = any(f.chiave == SEP.join(parti[: i + 1]) for f in nodo.figli)
            nodo = nodo.figlio(SEP.join(parti[: i + 1]), etichetta if i == len(parti) - 1 else "")
            if not esiste:
                nodo.presente = False

    for radice in radici.values():
        _ordina(radice)
    return list(radici.values())


def _ordina(nodo: Nodo) -> None:
    nodo.figli.sort(key=lambda n: (not n.presente, n.etichetta.casefold()))
    for f in nodo.figli:
        _ordina(f)


def trova(radici: list[Nodo], chiave: str) -> Nodo | None:
    for r in radici:
        if r.chiave == chiave:
            return r
        trovato = trova(r.figli, chiave)
        if trovato:
            return trovato
    return None


def percorso_etichette(radici: list[Nodo], chiave: str) -> list[tuple[str, str]]:
    """[(chiave, etichetta)] dalla fonte alla voce."""
    from .visibilita import antenati

    esito = []
    for c in antenati(chiave):
        nodo = trova(radici, c)
        esito.append((c, nodo.etichetta if nodo else c.split(SEP)[-1]))
    return esito


__all__ = ["Nodo", "costruisci", "trova", "percorso_etichette", "slug"]
