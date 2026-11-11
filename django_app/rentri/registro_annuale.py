"""Registro cronologico annuale e riepilogo per codice (base per il MUD).

Due letture dello stesso registro, per anno solare:

- :func:`registro_cronologico` — tutte le registrazioni dell'anno in ordine di
  data e numero, **annullate comprese** (in un registro non si cancella: si
  annota). È la base della stampa «Registro cronologico».
- :func:`riepilogo_anno` — per codice CER (sei cifre) e unità: giacenza al
  1° gennaio, caricato, scaricato (uscite dal deposito), giacenza al 31 dicembre,
  numero di movimenti e formulari. Le giacenze vengono dal conto del filo
  (:mod:`rentri.fili`) sui movimenti fino a quella data, così i numeri sono gli
  stessi della pagina Giacenze.

⚠️ Il modello ufficiale del registro (D.M. 59/2023) e il tracciato del MUD vanno
confrontati col responsabile ambientale: qui c'è il contenuto, non il tracciato
telematico.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .fili import EPS, analizza, chiave

TIPO_OPERAZIONE = {
    "C": "Carico",
    "O": "Scarico",
    "M": "Scarico effettivo",
    "R": "Rettifica",
}


def anni_disponibili() -> list[int]:
    from .models import RegistroRifiuti

    anni = sorted({d.year for d in RegistroRifiuti.objects.dates("data", "year")}, reverse=True)
    oggi = date.today().year
    return anni if oggi in anni else [oggi, *anni]


def _catalogo() -> dict[str, tuple[str, bool]]:
    from .models import CatalogoEER

    return {c.codice: (c.descrizione, c.pericoloso) for c in CatalogoEER.objects.all()}


def codice_esteso(k: str) -> str:
    return f"{k[0:2]} {k[2:4]} {k[4:6]}" if len(k) == 6 else k


def registro_cronologico(anno: int) -> list:
    """Registrazioni dell'anno (annullate comprese), in ordine cronologico."""
    from .models import RegistroRifiuti

    qs = RegistroRifiuti.objects.filter(data__year=anno).order_by("data", "id_registrazione", "id")
    return list(qs)


def annotazioni(r) -> str:
    """Testo «Annotazioni» di una riga del registro."""
    parti = []
    if r.annullato:
        quando = r.annullato_il.strftime("%d/%m/%Y") if r.annullato_il else ""
        parti.append(f"ANNULLATA {quando}: {r.motivo_annullamento}".strip(" :"))
    if r.tipo == "M" and r.rettifica_scarico is not None and r.quantita is None:
        parti.append("peso verificato a destino")
    if r.rif_op_storico:
        parti.append(f"collegamenti tolti: {r.rif_op_storico}")
    if (r.note_rentri or "").strip():
        parti.append(" ".join(r.note_rentri.split()))
    return " · ".join(parti)


@dataclass
class RigaRiepilogo:
    chiave: str
    unita: str
    descrizione: str = ""
    pericoloso: bool = False
    giacenza_inizio: Decimal = Decimal(0)
    caricato: Decimal = Decimal(0)
    scaricato: Decimal = Decimal(0)
    giacenza_fine: Decimal = Decimal(0)
    n_carichi: int = 0
    n_scarichi: int = 0
    fir: list[str] = field(default_factory=list)
    unita_miste: bool = False

    @property
    def codice(self) -> str:
        return codice_esteso(self.chiave) + ("*" if self.pericoloso else "")

    @property
    def differenza(self) -> Decimal:
        """Quanto non torna fra inizio + caricato − scaricato e la giacenza finale
        (scarichi oltre il carico: la Verifica li elenca)."""
        return self.giacenza_inizio + self.caricato - self.scaricato - self.giacenza_fine


def _giacenze_al(validi: list, giorno: date) -> dict[str, Decimal]:
    a = analizza([r for r in validi if r.data and r.data <= giorno])
    return {k: sum((a.residuo[c.pk] for c in lst), Decimal(0)) for k, lst in a.carichi.items()}


def riepilogo_anno(anno: int) -> list[RigaRiepilogo]:
    """Una riga per codice CER movimentato o in giacenza nell'anno."""
    from .models import RegistroRifiuti

    validi = [r for r in RegistroRifiuti.objects.attivi() if chiave(r.codice)]
    inizio = _giacenze_al(validi, date(anno - 1, 12, 31))
    fine_an = analizza([r for r in validi if r.data and r.data <= date(anno, 12, 31)])
    fine = {k: sum((fine_an.residuo[c.pk] for c in lst), Decimal(0)) for k, lst in fine_an.carichi.items()}
    nell_anno = [r for r in validi if r.data and r.data.year == anno]

    unita: dict[str, Counter] = {}
    for r in validi:
        if r.unita:
            unita.setdefault(chiave(r.codice), Counter())[r.unita] += 1
    pericolosi = {chiave(r.codice) for r in validi if "*" in r.codice or (r.tipo == "C" and (r.pericolosita or "").strip())}
    catalogo = _catalogo()

    righe: dict[str, RigaRiepilogo] = {}

    def riga(k: str) -> RigaRiepilogo:
        if k not in righe:
            cont = unita.get(k, Counter())
            desc, per = catalogo.get(k, ("", False))
            righe[k] = RigaRiepilogo(
                chiave=k, unita=cont.most_common(1)[0][0] if cont else "", descrizione=desc,
                pericoloso=per or k in pericolosi, unita_miste=len(cont) > 1,
            )
        return righe[k]

    for r in nell_anno:
        k = chiave(r.codice)
        rg = riga(k)
        if r.tipo == "C":
            rg.caricato += max(Decimal(r.quantita or 0), Decimal(0))
            rg.n_carichi += 1
        elif r.pk in fine_an.uscita:
            rg.scaricato += fine_an.uscita[r.pk]
            rg.n_scarichi += 1
        if r.tipo in ("O", "M") and (r.arrivo_fir or "").strip() and r.arrivo_fir.strip() not in rg.fir:
            rg.fir.append(r.arrivo_fir.strip())
    for k, q in list(inizio.items()) + list(fine.items()):
        if q > EPS:
            riga(k)
    for k, rg in righe.items():
        rg.giacenza_inizio = inizio.get(k, Decimal(0))
        rg.giacenza_fine = fine.get(k, Decimal(0))
        if not rg.descrizione:
            testi = Counter(" ".join(r.codice.split()) for r in validi if chiave(r.codice) == k)
            rg.descrizione = testi.most_common(1)[0][0] if testi else ""
    return sorted(righe.values(), key=lambda rg: rg.chiave)
