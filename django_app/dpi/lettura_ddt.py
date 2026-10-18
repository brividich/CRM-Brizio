"""Proposta di carico magazzino da un DDT di acquisto DPI (PDF o foto).

Dal testo del documento (``core.lettura_documenti``), senza AI generativa:

- **testata**: numero del DDT (vicino a «DDT», «documento di trasporto», «bolla»),
  data (vicino a «del», «data»), fornitore (fornitori in anagrafica, poi il
  produttore dei modelli trovati);
- **righe**: ogni modello DPI attivo il cui **codice** compare nel testo, con la
  quantità letta sulla stessa riga (il numero seguito da PZ/NR/PAIA/CF…, altrimenti
  l'ultimo intero della riga). Una quantità non letta resta 1 «da controllare».

È una proposta: il gestore spunta le righe giuste, corregge e conferma; il carico
lo fa ``magazzino.carica_ddt`` come per il carico a mano.
"""
from __future__ import annotations

import re

from core.lettura_documenti import Lettura, contiene_parola, data_dopo_etichetta, normalizza

_NUMERO_RE = re.compile(
    r"(?:D\.?\s?D\.?\s?T\.?|DOCUMENTO DI TRASPORTO|BOLLA(?: DI CONSEGNA)?)[^\n]{0,40}?"
    r"(?:N\.|N°|NR\.?|NUM\.?|NUMERO)\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-.]{0,24})"
)
_UNITA = r"(?:PZ|PZZ|PEZZI|NR|N\.|PA|PAIA|PAI|CF|CONF|UN|U\.)"
_QTA_UNITA_RE = re.compile(r"\b(\d{1,5})(?:[.,]0{1,3})?\s*" + _UNITA + r"(?![A-Z])")
_UNITA_QTA_RE = re.compile(r"\b" + _UNITA + r"\s*(\d{1,5})(?:[.,]0{1,3})?\b")
_INTERO_RE = re.compile(r"(?<![\d.,/])(\d{1,5})(?:[.,]0{1,3})?(?![\d/])")


def _numero(t: str) -> str:
    m = _NUMERO_RE.search(t)
    return m.group(1).strip(".-/") if m else ""


def _quantita(riga: str, codice: str) -> tuple[int | None, bool]:
    """(quantità, letta_con_unità). La parte della riga dopo il codice ha la precedenza."""
    pos = riga.find(codice)
    dopo = riga[pos + len(codice):] if pos >= 0 else riga
    for parte in (dopo, riga):
        # Prima «PZ 24» (colonne U.M. | Q.TÀ), poi «24 PZ»: in «taglia 9 PZ 24» il 9 è la taglia.
        m = _UNITA_QTA_RE.search(parte) or _QTA_UNITA_RE.search(parte)
        if m:
            return int(m.group(1)), True
    numeri = [int(n) for n in _INTERO_RE.findall(dopo) if 0 < int(n) <= 10000]
    return (numeri[-1] if numeri else None), False


def _fornitore(t: str, produttori: list[str]) -> str:
    from anagrafica.models import Fornitore

    for nome in Fornitore.objects.filter(is_active=True).values_list("ragione_sociale", flat=True):
        if contiene_parola(t, nome):
            return nome
    for nome in produttori:
        if nome and contiene_parola(t, nome):
            return nome
    return ""


def proponi(lettura: Lettura) -> dict:
    from .models import ModelloDPI

    t = lettura.normalizzato
    righe_testo = t.splitlines()
    righe = []
    produttori = []
    for modello in ModelloDPI.objects.filter(is_active=True).select_related("tipo").order_by("codice"):
        codice = normalizza(modello.codice).strip()
        if len(codice) < 3 or not contiene_parola(t, codice):
            continue
        riga = next((r for r in righe_testo if contiene_parola(r, codice)), "")
        qta, sicura = _quantita(riga, codice)
        righe.append({
            "modello_id": modello.pk, "codice": modello.codice, "nome": modello.nome,
            "tipo": getattr(modello.tipo, "nome", ""), "quantita": qta or 1,
            "da_controllare": qta is None or not sicura, "riga": riga.strip()[:160],
        })
        produttori.append(modello.produttore)
    data = data_dopo_etichetta(t, (r"\bDEL\b", r"\bDATA\b", r"D\.?D\.?T\.?"), finestra=40)
    avvisi = list(lettura.avvisi)
    if t.strip() and not righe:
        avvisi.append("Nessun codice DPI del catalogo trovato nel documento: registra il carico a mano.")
    return {
        "numero": _numero(t),
        "data": data.isoformat() if data else "",
        "fornitore": _fornitore(t, produttori) if t.strip() else "",
        "righe": righe,
        "ocr": lettura.ocr,
        "avvisi": avvisi,
    }
