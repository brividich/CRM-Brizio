"""Filtro «Centro di costo» delle pagine di Formazione, Visite, Scadenzario e DPI.

L'appartenenza è quella dei report (``reportistica.dati.carica_dipendenti``):
centro dell'area canonica, con tutti gli id della persona, così una scadenza
registrata su un doppione finisce nello stesso centro. Il filtro legge
l'anagrafica solo quando è scelto un centro: senza filtro la pagina non cambia.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

from ..models import CentroDiCosto

PARAMETRO = "centro"
SENZA = "senza"
ETICHETTA_SENZA = "Senza centro di costo"


def centro_per_persona() -> dict[int, str]:
    """``legacy_id`` (anche dei doppioni) → nome del centro, vuoto se la persona non ne ha."""
    from ..reportistica.dati import carica_dipendenti

    return {i: p.centro_costo for p in carica_dipendenti() for i in p.tutti_gli_id}


@dataclass
class Filtro:
    valore: str = ""
    nome: str = ""
    scelte: list = field(default_factory=list)
    ids: set | None = None
    avviso: str = ""
    conserva: list = field(default_factory=list)

    @property
    def attivo(self) -> bool:
        return self.ids is not None

    def applica(self, qs, campo: str = "legacy_anagrafica_id"):
        return qs if self.ids is None else qs.filter(**{f"{campo}__in": sorted(self.ids)})

    def contiene(self, legacy_id) -> bool:
        return self.ids is None or int(legacy_id or 0) in self.ids

    @property
    def suffisso(self) -> str:
        """Da accodare a un link che ha già una querystring."""
        return f"&{PARAMETRO}={self.valore}" if self.attivo else ""

    @property
    def prefisso(self) -> str:
        """Querystring per un link che non ne ha."""
        return f"?{PARAMETRO}={self.valore}" if self.attivo else ""

    @property
    def senza_filtro(self) -> str:
        return urlencode(self.conserva)

    @property
    def etichetta(self) -> str:
        return f"Centro di costo: {self.nome}" if self.attivo and self.valore != SENZA else (self.nome if self.attivo else "")


def leggi(request) -> Filtro:
    """Il filtro della richiesta. Un valore che non esiste vale come nessun filtro."""
    scelte = [(str(pk), nome) for pk, nome in
              CentroDiCosto.objects.filter(is_active=True).order_by("nome").values_list("pk", "nome")]
    conserva = [(k, v) for k, valori in request.GET.lists() if k not in (PARAMETRO, "page", "format", "scope")
                for v in valori]
    filtro = Filtro(scelte=scelte, conserva=conserva)
    valore = (request.GET.get(PARAMETRO) or "").strip()
    nome = ETICHETTA_SENZA if valore == SENZA else dict(scelte).get(valore, "")
    if not nome:
        return filtro
    mappa = centro_per_persona()
    if not mappa:
        filtro.avviso = "Anagrafica non leggibile: il filtro per centro di costo non è applicato."
        return filtro
    cercato = "" if valore == SENZA else nome.casefold()
    filtro.valore, filtro.nome = valore, nome
    filtro.ids = {i for i, centro in mappa.items() if centro.casefold() == cercato}
    return filtro
