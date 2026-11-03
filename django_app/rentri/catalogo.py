"""Catalogo EER (elenco europeo dei rifiuti): confronto tra codice scritto e nome ufficiale.

Il catalogo non vincola il registro: dice se il codice esiste, come si chiama e se
è pericoloso. Si carica da file con ``rentri_catalogo_eer``:

- CSV ``codice;descrizione`` (anche con la virgola o il tab), il codice con o senza
  spazi e con l'asterisco se pericoloso;
- la pagina della decisione salvata da EUR-Lex (HTML) o il suo testo/PDF: si
  prendono le righe con un codice a sei cifre seguito dalla descrizione, i titoli
  di capitolo (2 o 4 cifre) si saltano.
"""
from __future__ import annotations

import csv
import html
import io
import re

from django.db import transaction

from .models import CatalogoEER

_CODICE_RE = re.compile(r"^\s*(\d{2})\s*(\d{2})\s*(\d{2})\s*(\*?)\s*$")
_RIGA_RE = re.compile(r"^\s*(\d{2})[  ]?(\d{2})[  ]?(\d{2})[  ]*(\*?)[\s ]+(\S.*?)\s*$")


def normalizza(codice: str) -> tuple[str, bool] | None:
    """``'15 01 06'`` → ``('150106', False)``; ``'16 06 01*'`` → ``('160601', True)``; altro → None."""
    m = _CODICE_RE.match(codice or "")
    if not m:
        return None
    return m.group(1) + m.group(2) + m.group(3), bool(m.group(4))


def esteso(sei_cifre: str, pericoloso: bool = False) -> str:
    return f"{sei_cifre[0:2]} {sei_cifre[2:4]} {sei_cifre[4:6]}" + ("*" if pericoloso else "")


def caricato() -> bool:
    return CatalogoEER.objects.exists()


def confronta(codice: str) -> dict:
    """Esito del confronto, pronto per il modulo.

    ``stato``: ``vuoto`` (nessun codice), ``formato`` (non sono sei cifre),
    ``assente`` (catalogo non caricato), ``sconosciuto`` (non nel catalogo),
    ``asterisco`` (esiste ma l'asterisco non corrisponde), ``ok``.
    """
    if not (codice or "").strip():
        return {"stato": "vuoto"}
    norm = normalizza(codice)
    if norm is None:
        return {"stato": "formato", "messaggio": "Il codice EER ha sei cifre, per esempio 15 01 06."}
    sei, asterisco = norm
    if not caricato():
        return {"stato": "assente"}
    voce = CatalogoEER.objects.filter(codice=sei).first()
    if voce is None:
        return {"stato": "sconosciuto", "messaggio": f"{esteso(sei, asterisco)} non è nell'elenco europeo dei rifiuti: controlla il codice."}
    esito = {
        "codice": voce.codice_esteso,
        "descrizione": voce.descrizione,
        "pericoloso": voce.pericoloso,
    }
    if voce.pericoloso != asterisco:
        esito["stato"] = "asterisco"
        esito["messaggio"] = (
            f"Nell'elenco il codice è {voce.codice_esteso}: "
            + ("è pericoloso, va scritto con l'asterisco." if voce.pericoloso else "non è pericoloso, senza asterisco.")
        )
    else:
        esito["stato"] = "ok"
    return esito


def cerca(q: str, limite: int = 15) -> list[dict]:
    """Voci del catalogo per codice (anche parziale) o per parole della descrizione."""
    q = (q or "").strip()
    if not q:
        return []
    cifre = re.sub(r"[\s*]", "", q)
    qs = CatalogoEER.objects.all()
    if cifre.isdigit():
        qs = qs.filter(codice__startswith=cifre)
    else:
        for parola in q.split()[:5]:
            qs = qs.filter(descrizione__icontains=parola)
    return [
        {"codice": v.codice_esteso, "descrizione": v.descrizione, "pericoloso": v.pericoloso}
        for v in qs.order_by("codice")[:limite]
    ]


# ── Caricamento ──────────────────────────────────────────────────────────────

def _da_csv(testo: str) -> list[tuple[str, bool, str]]:
    righe = []
    primo = testo.splitlines()[0] if testo.strip() else ""
    sep = ";" if primo.count(";") else ("\t" if primo.count("\t") else ",")
    for row in csv.reader(io.StringIO(testo), delimiter=sep):
        if len(row) < 2:
            continue
        norm = normalizza(row[0])
        desc = " ".join(row[1].split())
        if norm and desc:
            righe.append((norm[0], norm[1], desc))
    return righe


def _html_in_testo(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)</t[dh]\s*>", "\t", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</(tr|p|div|li|h\d)\s*>", "\n", markup)
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


def _da_testo(testo: str) -> list[tuple[str, bool, str]]:
    righe = []
    linee = [riga.strip() for riga in testo.replace("\r", "").split("\n")]
    for i, linea in enumerate(linee):
        m = _RIGA_RE.match(linea)
        if m:
            desc = " ".join(m.group(5).split())
            righe.append((m.group(1) + m.group(2) + m.group(3), bool(m.group(4)), desc))
            continue
        # PDF: codice da solo su una riga, descrizione sulla successiva.
        norm = normalizza(linea)
        if norm and i + 1 < len(linee) and linee[i + 1] and normalizza(linee[i + 1]) is None:
            righe.append((norm[0], norm[1], " ".join(linee[i + 1].split())))
    return righe


def leggi_file(nome: str, contenuto: bytes) -> list[tuple[str, bool, str]]:
    """Voci (sei cifre, pericoloso, descrizione) da un file; doppioni: vince la prima."""
    nome = (nome or "").lower()
    if contenuto[:5] == b"%PDF-":
        from core.lettura_documenti import _leggi_pdf

        import fitz

        with fitz.open(stream=contenuto, filetype="pdf") as doc:
            testo = "\n".join(page.get_text() for page in doc)
        voci = _da_testo(testo or _leggi_pdf(contenuto).testo)
    else:
        testo = contenuto.decode("utf-8-sig", errors="replace")
        if nome.endswith((".htm", ".html")) or "<html" in testo[:2000].lower():
            voci = _da_testo(_html_in_testo(testo))
        elif nome.endswith(".csv"):
            voci = _da_csv(testo)
        else:
            voci = _da_testo(testo)
    visti, uniche = set(), []
    for sei, peric, desc in voci:
        if sei not in visti and desc:
            visti.add(sei)
            uniche.append((sei, peric, desc[:500]))
    return uniche


@transaction.atomic
def sostituisci(voci: list[tuple[str, bool, str]]) -> int:
    """Rimpiazza l'intero catalogo con le voci date."""
    CatalogoEER.objects.all().delete()
    CatalogoEER.objects.bulk_create(
        [CatalogoEER(codice=sei, pericoloso=peric, descrizione=desc) for sei, peric, desc in voci],
        batch_size=200,
    )
    return len(voci)
