"""Writer CSV sanificato: stessa protezione degli .xlsx, applicata al CSV.

SICUREZZA — la formula injection non riguarda solo gli .xlsx: Excel (e Calc)
valutano le formule anche quando *aprono un CSV*. Una cella che inizia con ``=``
(o ``+``/``-``/``@``/TAB/CR) diventa una formula viva: nei nostri export il testo
libero arriva dal DB (descrizioni, note, nomi file, motivazioni) e in alcuni casi
dalla querystring, quindi un valore malevolo salvato a sistema si trasforma in
codice eseguito sul PC di chi scarica il file.

Rimedio: i valori pericolosi vengono prefissati con un apice, che Excel/Calc
trattano come marcatore "questo è testo". I valori numerici legittimi (anche
negativi, es. ``-12,50``) NON vengono toccati: altrimenti si romperebbero i
re-import e i totali.

I prefissi pericolosi sono definiti una volta sola in :mod:`core.excel_export`
(``FORMULA_PREFIXES``): questa è la stessa politica, applicata all'altro formato.

Uso::

    from core.csv_export import safe_csv_writer

    writer = safe_csv_writer(response)   # al posto di csv.writer(response)
    writer.writerow(["Nome", "Note"])
"""
from __future__ import annotations

import csv
import re

from core.excel_export import FORMULA_PREFIXES

# Numeri "veri" (interi/decimali, con separatore . o , e segno): non vanno sanificati,
# altrimenti un importo negativo diventerebbe testo con un apice davanti.
_NUMERIC_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def csv_safe(value):
    """Ritorna il valore neutralizzato se rischia di essere letto come formula.

    Solo le *stringhe* che iniziano con un prefisso pericoloso e che non sono
    numeri vengono prefissate con un apice; tutto il resto passa invariato.
    """
    if not isinstance(value, str) or not value:
        return value
    if value[0] in FORMULA_PREFIXES and not _NUMERIC_RE.match(value):
        return "'" + value
    return value


class _SafeCsvWriter:
    """Wrapper di ``csv.writer`` che sanifica ogni cella scritta."""

    def __init__(self, writer):
        self._writer = writer

    def writerow(self, row):
        return self._writer.writerow([csv_safe(value) for value in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)

    def __getattr__(self, name):  # dialect, ecc.
        return getattr(self._writer, name)


def safe_csv_writer(fileobj, **kwargs):
    """Come ``csv.writer(fileobj, **kwargs)``, ma con celle sanificate."""
    return _SafeCsvWriter(csv.writer(fileobj, **kwargs))


# Content-type dei CSV scaricabili. NON usare ``charset=utf-8-sig``: Django
# codifica OGNI ``write()`` (e ogni chunk di una StreamingHttpResponse) con il
# charset dichiarato, e il codec ``utf-8-sig`` antepone il BOM a *ciascuno* —
# risultato: un BOM all'inizio di ogni riga, che in Excel finisce dentro la prima
# cella. Il BOM (che serve a Excel per riconoscere l'UTF-8) va scritto UNA volta.
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"
BOM = "﻿"


def csv_download_response(filename: str, *, delimiter: str = ","):
    """HttpResponse CSV pronta (BOM una volta) + writer sanificato.

    Ritorna la coppia ``(response, writer)``.
    """
    from django.http import HttpResponse

    response = HttpResponse(content_type=CSV_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(BOM)
    return response, safe_csv_writer(response, delimiter=delimiter)


def bom_first(chunks):
    """Antepone il BOM al primo chunk di un CSV in streaming (una volta sola)."""
    yield BOM
    yield from chunks
