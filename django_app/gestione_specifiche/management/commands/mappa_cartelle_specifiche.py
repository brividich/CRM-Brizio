"""Mapping completo Specifica -> cartella share (cliente/categoria REALE), READ-ONLY.

La cartella di 1o livello sotto la radice della share e' l'assegnazione REALE del
cliente/categoria: la share e' la fonte di verita' dell'organizzazione (es. la spec
109040245101_LIN01 sta in FINCANTIERI -> e' FINCANTIERI, a prescindere dal codice
gestionale). Questo comando produce il mapping e **evidenzia dove il campo `cliente`
del gestionale diverge** dalla cartella. NON scrive nulla: l'eventuale assegnazione
(scrittura sul DB) e' un passo successivo, separato e da confermare.

Esempi::

    python manage.py mappa_cartelle_specifiche
    python manage.py mappa_cartelle_specifiche --out "C:/report/mapping_cartelle.csv"
    python manage.py mappa_cartelle_specifiche --solo-difformi --out "C:/report/difformi.csv"
"""
from __future__ import annotations

import os
import re
from collections import Counter

from django.core.management.base import BaseCommand

from gestione_specifiche.models import Specifica
from gestione_specifiche.share_write import (
    cartella_top_da_percorso,
    sottocartella_da_percorso,
)


def _ascii(s) -> str:
    return str(s or "").encode("ascii", "replace").decode("ascii")


def _norm(s) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(s or "").upper()).strip()


def _coerente(cliente: str, cartella: str) -> str:
    """Confronto lasco cliente-gestionale vs cartella-share: SI / NO / ? (dato mancante)."""
    c, k = _norm(cliente), _norm(cartella)
    if not c or not k:
        return "?"
    if c in k or k in c:
        return "SI"
    tc = {t for t in c.split() if len(t) >= 3}
    tk = {t for t in k.split() if len(t) >= 3}
    return "SI" if (tc & tk) else "NO"


class Command(BaseCommand):
    help = (
        "Mapping READ-ONLY Specifica -> cartella share (cliente/categoria reale); "
        "evidenzia le difformita' rispetto al campo cliente del gestionale."
    )

    def add_arguments(self, parser):
        parser.add_argument("--out", default="",
                            help="CSV di output (pk;codice;cliente;cartella;sottocartella;file;coerente).")
        parser.add_argument("--limit", type=int, default=0, help="Analizza al piu' N specifiche (0 = tutte).")
        parser.add_argument("--solo-difformi", action="store_true",
                            help="Elenca solo le specifiche dove cliente gestionale != cartella share.")

    def handle(self, *args, **opts):
        qs = Specifica.objects.exclude(percorso_esterno="").order_by("pk")
        totale = qs.count()
        if opts["limit"]:
            qs = qs[:opts["limit"]]

        righe = []
        per_cartella = Counter()
        difformi = senza_cartella = 0
        for spec in qs:
            perc = spec.percorso_esterno
            cartella = cartella_top_da_percorso(perc)
            sub = sottocartella_da_percorso(perc)
            fn = perc.replace("/", "\\").split("\\")[-1]
            coer = _coerente(spec.cliente, cartella)
            if not cartella:
                senza_cartella += 1
            per_cartella[cartella or "(radice/ignoto)"] += 1
            if coer == "NO":
                difformi += 1
            if opts["solo_difformi"] and coer != "NO":
                continue
            righe.append({
                "pk": spec.pk, "codice": spec.codice, "cliente": spec.cliente,
                "cartella": cartella, "sottocartella": sub, "file": fn, "coerente": coer,
            })

        if opts["out"]:
            self._csv(opts["out"], righe)

        self.stdout.write(self.style.MIGRATE_HEADING("Mapping Specifica -> cartella share (READ-ONLY)"))
        self.stdout.write(
            f"  con percorso: {totale} | difformi (cliente!=cartella): {difformi} | senza cartella: {senza_cartella}"
        )
        self.stdout.write("  --- cartelle (cliente/categoria) per numero di specifiche ---")
        for nome, n in sorted(per_cartella.items(), key=lambda kv: (-kv[1], kv[0].lower())):
            self.stdout.write(f"    {n:5d}  {_ascii(nome)}")
        if opts["out"]:
            self.stdout.write(f"  report CSV: {_ascii(opts['out'])} ({len(righe)} righe)")
        else:
            self.stdout.write(self.style.NOTICE("  (nessun --out: CSV non scritto; usa --out per il dettaglio per-specifica)"))

    def _csv(self, out: str, righe: list) -> None:
        import csv

        cartella = os.path.dirname(out)
        if cartella:
            os.makedirs(cartella, exist_ok=True)
        campi = ["pk", "codice", "cliente", "cartella", "sottocartella", "file", "coerente"]
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=campi, delimiter=";")
            w.writeheader()
            w.writerows(righe)
