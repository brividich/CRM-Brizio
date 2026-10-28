"""Regole di validità di un movimento del registro, lato server.

Il wizard controlla solo i campi obbligatori; qui stanno le regole che
proteggono il registro anche da chiamate dirette o da due utenti in
contemporanea (il chiamante tiene i genitori bloccati, vedi
:func:`rentri.servizi.salva_movimento`).

Le regole sui campi si applicano ai movimenti nuovi e ai campi che cambiano:
un movimento storico incompleto resta modificabile negli altri campi.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .catena import GENITORI_AMMESSI, split_rif_op

__all__ = [
    "CER_RE",
    "quantita_da_testo",
    "normalizza_cer",
    "cer_pericoloso",
    "valida_movimento",
    "requisiti_consolidamento",
]

# Sei cifre a coppie, separate o no da spazio, punto o trattino; asterisco = pericoloso.
# Dopo il codice può seguire la descrizione («15 01 06 - imballaggi misti»).
CER_RE = re.compile(r"^\s*(\d{2})[\s.\-]?(\d{2})[\s.\-]?(\d{2})\s*(\*)?")

_EPS = Decimal("0.0005")


def quantita_da_testo(raw) -> Decimal | None:
    """Quantità da testo del modulo: accetta «1,5», «1.5» e «1.234,5».

    Vuoto → ``None``; testo non numerico → ``ValueError``.
    """
    s = str(raw if raw is not None else "").strip().replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        valore = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(s) from exc
    if not valore.is_finite():
        raise ValueError(s)
    return valore.quantize(Decimal("0.001"))


def normalizza_cer(codice: str) -> str:
    """Le sei cifre del codice (``"150106"``), o il testo ripulito se non è un CER."""
    m = CER_RE.match(str(codice or ""))
    if m:
        return "".join(m.group(1, 2, 3))
    return " ".join(str(codice or "").split()).lower()


def cer_pericoloso(codice: str) -> bool:
    m = CER_RE.match(str(codice or ""))
    return bool(m and m.group(4))


def _fmt(q: Decimal) -> str:
    return f"{q:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def valida_movimento(registro, *, prima: dict | None = None) -> list[str]:
    """Errori di un movimento in salvataggio (lista vuota = valido).

    `prima` è la fotografia dei campi prima della modifica (``None`` per un
    movimento nuovo): decide quali regole di campo applicare.
    """
    from .giacenze import giacenza_di
    from .models import RegistroRifiuti

    nuovo = prima is None
    errori: list[str] = []

    def cambiato(campo: str) -> bool:
        return nuovo or prima.get(campo) != getattr(registro, campo)

    tipo = registro.tipo
    oggi = timezone.localdate()

    if registro.data and cambiato("data") and registro.data > oggi:
        errori.append("La data non può essere nel futuro.")

    codice = (registro.codice or "").strip()
    if not codice:
        errori.append("Il codice CER è obbligatorio.")
    elif cambiato("codice") and not CER_RE.match(codice):
        errori.append("Codice CER non valido: servono le sei cifre (per esempio 15 01 06).")

    q = registro.quantita
    if cambiato("quantita") or cambiato("rettifica_scarico"):
        if tipo in ("C", "O", "M"):
            if q is None:
                errori.append("La quantità è obbligatoria.")
            elif q <= 0:
                errori.append("La quantità deve essere maggiore di zero.")
        elif tipo == "R":
            if q is None and registro.rettifica_scarico is None:
                errori.append("Indica la quantità della rettifica.")
            elif (q if q is not None else registro.rettifica_scarico) == 0:
                errori.append("La rettifica non può essere zero.")

    if nuovo and registro.unita not in dict(RegistroRifiuti.UNITA_CHOICES):
        errori.append("Scegli l'unità di misura della quantità.")

    if tipo == "C" and cambiato("codice") and cer_pericoloso(codice) and not (registro.pericolosita or "").strip():
        errori.append("Il codice CER è pericoloso (*): indica le caratteristiche di pericolo (HP).")

    if tipo in GENITORI_AMMESSI and cambiato("rif_op"):
        errori.extend(_errori_rif_op(registro))

    # Giacenza: uno scarico non può portare fuori più di quanto c'è in deposito.
    if (
        tipo in ("O", "M") and q is not None and q > 0 and codice
        and not errori and (cambiato("quantita") or cambiato("codice"))
    ):
        disponibile = giacenza_di(codice, escludi_pk=registro.pk)
        if q > disponibile + _EPS:
            errori.append(
                f"Quantità oltre la giacenza del codice {codice}: disponibili {_fmt(max(disponibile, Decimal(0)))}. "
                "Controlla i carichi registrati."
            )
    return errori


def _errori_rif_op(registro) -> list[str]:
    from .models import RegistroRifiuti

    tipo = registro.tipo
    refs = split_rif_op(registro.rif_op)
    if not refs:
        return ["Scegli il movimento collegato (Rif. Op)."]

    ammessi = GENITORI_AMMESSI[tipo]
    cer = normalizza_cer(registro.codice)
    errori: list[str] = []
    genitori = list(RegistroRifiuti.objects.attivi().filter(id_registrazione__in=refs).exclude(pk=registro.pk))
    per_id: dict[str, list] = {}
    for g in genitori:
        per_id.setdefault(g.id_registrazione, []).append(g)

    for rid in refs:
        if rid == registro.id_registrazione and registro.id_registrazione:
            errori.append(f"{rid}: un movimento non può collegarsi a sé stesso.")
            continue
        validi = [g for g in per_id.get(rid, []) if g.tipo in ammessi]
        if not validi:
            if per_id.get(rid):
                errori.append(f"{rid}: tipo di movimento non collegabile a uno scarico {tipo}.")
            else:
                errori.append(f"{rid}: movimento collegato inesistente o annullato.")
            continue
        g = validi[0]
        if normalizza_cer(g.codice) != cer:
            errori.append(f"{rid}: ha un codice CER diverso ({g.codice}).")
        if g.data and registro.data and registro.data < g.data:
            errori.append(f"{rid}: la data non può precedere quella del movimento collegato ({g.data:%d/%m/%Y}).")

    if not errori:
        errori.extend(_errori_gia_collegato(registro, refs, per_id))
    return errori


def _errori_gia_collegato(registro, refs: list[str], per_id: dict) -> list[str]:
    """Un genitore si collega una volta sola (stesse regole dei candidati del wizard)."""
    from .models import RegistroRifiuti

    tipo = registro.tipo
    altri = RegistroRifiuti.objects.attivi().exclude(pk=registro.pk).exclude(rif_op="")
    if tipo == "O":
        altri = altri.filter(tipo__in=["O", "M", "R"])
    else:
        altri = altri.filter(tipo=tipo)

    usati: set[str] = set()
    insiemi: set[frozenset] = set()
    for raw in altri.values_list("rif_op", flat=True):
        parti = split_rif_op(raw)
        usati.update(parti)
        insiemi.add(frozenset(parti))

    errori = []
    if tipo == "O":
        for rid in refs:
            if rid in usati:
                errori.append(f"{rid}: il carico ha già uno scarico collegato.")
        return errori

    diretti = [rid for rid in refs if any(g.tipo != "C" for g in per_id.get(rid, []))]
    for rid in diretti:
        if rid in usati:
            errori.append(f"{rid}: ha già un movimento {tipo} collegato.")
    if not diretti and frozenset(refs) in insiemi:
        errori.append(f"Esiste già un movimento {tipo} con gli stessi riferimenti.")
    return errori


def requisiti_consolidamento(registro) -> list[str]:
    """Cosa manca a un movimento per essere consolidato (dati minimi del registro)."""
    errori = []
    if not registro.data:
        errori.append("manca la data")
    if not (registro.codice or "").strip():
        errori.append("manca il codice CER")
    if registro.tipo in ("C", "O", "M") and not registro.quantita:
        errori.append("manca la quantità")
    if registro.tipo in GENITORI_AMMESSI and not split_rif_op(registro.rif_op):
        errori.append("manca il movimento collegato")
    return errori
