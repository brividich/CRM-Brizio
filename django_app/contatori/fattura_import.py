"""Lettura della fattura elettronica del fornitore MFC (FatturaPA XML o sua stampa PDF).

Produce i dati per precompilare la pagina «Nuova fattura»: nulla viene salvato qui
e il file non viene conservato. Le righe «COPIE EFFETTUATE» non dicono a quale
contatore si riferiscono: lo si ricava dal prezzo per copia, che in ogni contratto
segue le proporzioni A4 B/N = x, A3 B/N = 2x, A4 colore = 10x, A3 colore = 20x.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MAX_BYTES = 5 * 1024 * 1024

# Rapporto del prezzo per copia rispetto all'A4 bianco/nero.
_RAPPORTI = {"a4_bn": 1, "a3_bn": 2, "a4_col": 10, "a3_col": 20}
_TOLLERANZA = 0.15  # scarto relativo accettato sul rapporto atteso

_CONTRATTO_RE = re.compile(r"N\.\s*Contratto\s*:\s*([\w/.-]+)", re.I)
_MATRICOLA_RE = re.compile(r"Matricola\s*:\s*([A-Z0-9]+)", re.I)
_RIGA_RE = re.compile(
    r"Lett\.\s*al\s*(\d{2}/\d{2}/\d{4})\s*:\s*([\d.]+)"      # lettura di apertura
    r".*?(\d{2}/\d{2}/\d{4})\s*:\s*([\d.]+)\s*Totale\s*:\s*([\d.]+)"  # chiusura e totale
    r".*?Eccedenze\s*:\s*([\d.,]+)\s*x",                       # prezzo per copia
    re.I | re.S,
)
_PERIODO_RE = re.compile(r"letture\s+dal\s+(\d{2}/\d{2}/\d{4})\s+al\s+(\d{2}/\d{2}/\d{4})", re.I)
_TESTATA_PDF_RE = re.compile(r"TD\d{2}\s*\([^)]*\)\s+(\S+)\s+(\d{2}-\d{2}-\d{4})")


class FatturaNonLeggibile(ValueError):
    pass


def _intero(testo):
    return int(testo.replace(".", "").strip())


def _decimale(testo):
    try:
        return Decimal(testo.replace(".", "").replace(",", "."))
    except InvalidOperation as e:
        raise FatturaNonLeggibile(f"Prezzo non leggibile: {testo}") from e


def _data(testo, fmt="%d/%m/%Y"):
    return datetime.strptime(testo, fmt).date()


def _normalizza(testo):
    # La stampa PDF va a capo dentro date e numeri ("01/07\n/2026"): si ricompongono.
    testo = re.sub(r"\s+", " ", testo)
    return re.sub(r"\s*/\s*", "/", testo)


# --- Estrazione del testo ---------------------------------------------------

def testo_da_pdf(contenuto: bytes) -> str:
    import fitz  # PyMuPDF, gia' tra le dipendenze del portale
    try:
        with fitz.open(stream=contenuto, filetype="pdf") as doc:
            return "\n".join(pagina.get_text() for pagina in doc)
    except Exception as e:  # file corrotto o non PDF
        raise FatturaNonLeggibile("Il PDF non è leggibile.") from e


def dati_da_xml(contenuto: bytes) -> tuple[str, str, date | None]:
    """(testo delle righe, numero, data) da una FatturaPA. defusedxml blocca DTD ed entita'."""
    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import ParseError, fromstring
    try:
        radice = fromstring(contenuto, forbid_dtd=True)
    except (ParseError, DefusedXmlException) as e:
        raise FatturaNonLeggibile("L'XML non è una fattura elettronica leggibile.") from e

    def locale(el):
        return el.tag.rsplit("}", 1)[-1]

    numero, data_doc, righe = "", None, []
    for el in radice.iter():
        nome = locale(el)
        if nome == "DatiGeneraliDocumento":
            for figlio in el:
                if locale(figlio) == "Numero":
                    numero = (figlio.text or "").strip()
                elif locale(figlio) == "Data" and figlio.text:
                    data_doc = _data(figlio.text.strip(), "%Y-%m-%d")
        elif nome == "DettaglioLinee":
            for figlio in el:
                if locale(figlio) == "Descrizione":
                    righe.append(figlio.text or "")
    if not righe:
        raise FatturaNonLeggibile("Nessuna riga di dettaglio nella fattura elettronica.")
    return " ".join(righe), numero, data_doc


# --- Interpretazione -------------------------------------------------------

def _assegnazione(prezzi, base):
    return [min(_RAPPORTI, key=lambda k: abs(math.log(p / (base * _RAPPORTI[k])))) for p in prezzi]


def _assegna_contatori(righe):
    """Assegna a ogni riga il contatore dal prezzo per copia. Modifica `righe`.

    Si cerca la base x (prezzo A4 B/N) che spiega meglio tutti i prezzi del contratto,
    provando ogni prezzo come A4/A3 B/N o A4/A3 colore. Se due basi diverse spiegano i
    prezzi ugualmente bene ma portano ad assegnazioni diverse (es. una riga B/N e una
    colore in rapporto 10: A4/A4 o A3/A3?) le righe restano incerte.
    """
    valide = [r for r in righe if r["prezzo"] > 0]
    for r in righe:
        r["contatore"], r["certo"] = None, False
    if not valide:
        return
    prezzi = [float(r["prezzo"]) for r in valide]
    candidati = []
    for p in prezzi:
        for rapporto in _RAPPORTI.values():
            base = p / rapporto
            errore = sum(min(abs(math.log(q / (base * k))) for k in _RAPPORTI.values()) for q in prezzi)
            candidati.append((errore, base))
    errore_min = min(e for e, _ in candidati)
    migliori = [b for e, b in candidati if e <= errore_min + 1e-6]
    assegnazioni = {tuple(_assegnazione(prezzi, b)) for b in migliori}
    ambigua = len(assegnazioni) > 1
    base = migliori[0]
    for r, campo in zip(valide, _assegnazione(prezzi, base)):
        rapporto = float(r["prezzo"]) / base
        r["contatore"] = campo
        r["certo"] = not ambigua and abs(rapporto / _RAPPORTI[campo] - 1) <= _TOLLERANZA
    # Due righe sullo stesso contatore: l'assegnazione non e' affidabile.
    visti = {}
    for r in valide:
        visti.setdefault(r["contatore"], []).append(r)
    for doppie in visti.values():
        if len(doppie) > 1:
            for r in doppie:
                r["certo"] = False


def interpreta(testo: str) -> dict:
    """Contratti, letture di chiusura e periodo dal testo della fattura."""
    testo = _normalizza(testo)
    pezzi = _CONTRATTO_RE.split(testo)
    if len(pezzi) < 3:
        raise FatturaNonLeggibile("Nella fattura non ci sono righe «N. Contratto»: formato non riconosciuto.")
    contratti, periodi = [], set()
    for contratto, blocco in zip(pezzi[1::2], pezzi[2::2]):
        righe = []
        for m in _RIGA_RE.finditer(blocco):
            apertura, chiusura, totale = _intero(m.group(2)), _intero(m.group(4)), _intero(m.group(5))
            righe.append({"lettura": chiusura, "apertura": apertura, "totale": totale,
                          "prezzo": _decimale(m.group(6)), "chiusa_il": _data(m.group(3)),
                          "coerente": chiusura - apertura == totale})
        _assegna_contatori(righe)
        periodi.update(_PERIODO_RE.findall(blocco))
        contratti.append({
            "contratto": contratto.strip().rstrip("."),
            "matricole": list(dict.fromkeys(_MATRICOLA_RE.findall(blocco))),
            "righe": righe,
        })
    if not any(c["righe"] for c in contratti):
        raise FatturaNonLeggibile("Nessuna riga «COPIE EFFETTUATE» con le letture: formato non riconosciuto.")
    dal = al = None
    if periodi:
        dal = min(_data(d) for d, _ in periodi)
        al = max(_data(a) for _, a in periodi)
    return {"contratti": contratti, "periodo_dal": dal, "periodo_al": al}


def leggi_fattura(nome_file: str, contenuto: bytes) -> dict:
    """Punto d'ingresso: XML (preferito) o PDF. Ritorna i dati per il form e gli avvisi."""
    from .models import Macchina
    from .services import trimestre_di

    if len(contenuto) > MAX_BYTES:
        raise FatturaNonLeggibile("File troppo grande (massimo 5 MB).")
    nome = (nome_file or "").lower()
    if nome.endswith(".p7m"):
        raise FatturaNonLeggibile("File firmato (.p7m): carica l'XML o il PDF della fattura.")
    if contenuto[:5] == b"%PDF-":
        testo = testo_da_pdf(contenuto)
        numero, data_doc = "", None
        testata = _TESTATA_PDF_RE.search(_normalizza(testo))
        if testata:
            numero, data_doc = testata.group(1), _data(testata.group(2), "%d-%m-%Y")
    elif contenuto.lstrip()[:1] == b"<":
        testo, numero, data_doc = dati_da_xml(contenuto)
    else:
        raise FatturaNonLeggibile("Formato non supportato: carica l'XML o il PDF della fattura.")

    dati = interpreta(testo)
    avvisi = []
    fornitore = "COPYLAB" if re.search(r"copylab", testo, re.I) else "BASE"
    contratti_noti = set(Macchina.objects.exclude(contratto="").values_list("contratto", flat=True))
    righe_form = []
    for c in dati["contratti"]:
        valori = {campo: 0 for campo in _RAPPORTI}
        for r in c["righe"]:
            if r["contatore"]:
                valori[r["contatore"]] = r["lettura"]
            if not r["certo"]:
                avvisi.append(f"Contratto {c['contratto']}: riga con lettura {r['lettura']} e prezzo "
                              f"{r['prezzo']} €/copia assegnata a «{_ETICHETTE.get(r['contatore'], '?')}» "
                              "senza certezza: verificala.")
            if not r["coerente"]:
                avvisi.append(f"Contratto {c['contratto']}: per la lettura {r['lettura']} il totale "
                              "copie in fattura non torna con le letture: verifica.")
        mancanti = [_ETICHETTE[k] for k in _RAPPORTI if k not in {r["contatore"] for r in c["righe"]}]
        if mancanti and c["righe"]:
            avvisi.append(f"Contratto {c['contratto']}: in fattura manca la riga di "
                          f"{', '.join(mancanti)}; il valore resta 0 da completare a mano.")
        if c["contratto"] not in contratti_noti:
            avvisi.append(f"Contratto {c['contratto']} non presente nell'anagrafica stampanti.")
        righe_form.append({"contratto": c["contratto"],
                           "descrizione": ("Matricole " + ", ".join(c["matricole"]))[:120] if c["matricole"] else "",
                           **valori})
    if not numero:
        avvisi.append("Numero e data della fattura non trovati: inseriscili a mano.")
    al = dati["periodo_al"]
    return {
        "testata": {"numero": numero, "data": data_doc, "fornitore": fornitore,
                    "periodo_dal": dati["periodo_dal"], "periodo_al": al,
                    "trimestre": trimestre_di(al) if al else ""},
        "righe": righe_form,
        "avvisi": avvisi,
    }


_ETICHETTE = {"a4_bn": "A4 B/N", "a3_bn": "A3 B/N", "a4_col": "A4 colore", "a3_col": "A3 colore", None: "?"}
