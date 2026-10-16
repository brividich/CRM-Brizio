"""Report di prova: le mansioni scritte nelle schede si abbinano al catalogo?

Passo preliminare al collegamento «mansione → catalogo» (oggi il legame è per
nome: rinominare una mansione nel catalogo cambia in silenzio i requisiti di
chi la ha). Il comando NON scrive nulla: per ogni testo di mansione presente
nelle schede dice se corrisponde a una voce del catalogo

- **esatta**: stesso nome, carattere per carattere;
- **per nome**: stesso nome a meno di maiuscole e spazi (è il legame di oggi,
  ``nome__iexact``);
- **simile**: nessuna corrispondenza per nome, ma una voce del catalogo che
  differisce solo per punteggiatura/accenti (da verificare a mano);
- **assente**: nessuna voce del catalogo.

Uscita senza nominativi: solo testi di mansione e conteggi. ``--report file.csv``
scrive l'elenco completo; ``--tutti`` include anche i dipendenti non in forza.

Utilizzo:
    python manage.py report_mansioni_catalogo
    python manage.py report_mansioni_catalogo --report mansioni.csv
"""
from __future__ import annotations

import unicodedata
from collections import Counter

from django.core.management.base import BaseCommand

from core.legacy_anagrafica import fetch_anagrafica_rows

ESATTA, PER_NOME, SIMILE, ASSENTE = "esatta", "per nome", "simile", "assente"


def _chiave_nome(testo: str) -> str:
    return " ".join(str(testo or "").split()).casefold()


def _chiave_simile(testo: str) -> str:
    base = unicodedata.normalize("NFKD", str(testo or ""))
    return "".join(ch for ch in base.casefold() if ch.isalnum())


def analizza(*, solo_in_forza: bool = True) -> list[dict]:
    """Una riga per testo di mansione: esito dell'abbinamento, voce del catalogo, persone."""
    from anagrafica.models import DipendenteAnagraficaAziendale, Mansione

    catalogo = list(Mansione.objects.values_list("nome", "is_active"))
    esatti = {nome: attiva for nome, attiva in catalogo}
    per_nome = {_chiave_nome(nome): (nome, attiva) for nome, attiva in catalogo}
    simili = {_chiave_simile(nome): (nome, attiva) for nome, attiva in catalogo}

    cessati = set()
    if solo_in_forza:
        cessati = set(
            DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=False)
            .values_list("legacy_anagrafica_id", flat=True)
        )
    conteggio: Counter = Counter()
    for row in fetch_anagrafica_rows(deduplicate=True):
        if solo_in_forza and (not row.get("attivo") or int(row.get("id") or 0) in cessati):
            continue
        testo = str(row.get("mansione") or "").strip()
        if testo:
            conteggio[testo] += 1

    righe = []
    for testo, persone in conteggio.most_common():
        if testo in esatti:
            esito, voce, attiva = ESATTA, testo, esatti[testo]
        elif _chiave_nome(testo) in per_nome:
            esito, (voce, attiva) = PER_NOME, per_nome[_chiave_nome(testo)]
        elif _chiave_simile(testo) in simili:
            esito, (voce, attiva) = SIMILE, simili[_chiave_simile(testo)]
        else:
            esito, voce, attiva = ASSENTE, "", None
        righe.append({"mansione": testo, "persone": persone, "esito": esito,
                      "voce_catalogo": voce, "voce_attiva": attiva})
    return righe


class Command(BaseCommand):
    help = "Report di prova (sola lettura): abbinamento delle mansioni delle schede al catalogo."

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Scrive l'elenco completo in CSV (nessun nominativo).")
        parser.add_argument("--tutti", action="store_true", help="Include anche i dipendenti non in forza.")

    def handle(self, *args, **opts):
        righe = analizza(solo_in_forza=not opts["tutti"])
        persone = Counter()
        testi = Counter()
        for r in righe:
            persone[r["esito"]] += r["persone"]
            testi[r["esito"]] += 1
        totale = sum(persone.values())
        self.stdout.write(f"Persone con una mansione: {totale} · testi diversi: {len(righe)}")
        for esito in (ESATTA, PER_NOME, SIMILE, ASSENTE):
            self.stdout.write(f"  {esito:<9} persone {persone[esito]:>4} · testi {testi[esito]:>3}")
        disattive = [r for r in righe if r["voce_attiva"] is False]
        if disattive:
            self.stdout.write(f"Voci del catalogo abbinate ma disattivate: {len(disattive)}")
        da_vedere = [r for r in righe if r["esito"] in (SIMILE, ASSENTE)]
        if da_vedere:
            self.stdout.write("Da sistemare prima del collegamento (testo → voce simile):")
            for r in da_vedere[:30]:
                simile = f" → «{r['voce_catalogo']}»" if r["voce_catalogo"] else ""
                self.stdout.write(f"  [{r['esito']}] «{r['mansione']}» ({r['persone']}){simile}")
            if len(da_vedere) > 30:
                self.stdout.write(f"  … altri {len(da_vedere) - 30}: usa --report")
        if opts["report"]:
            from core.csv_export import safe_csv_writer

            with open(opts["report"], "w", encoding="utf-8-sig", newline="") as fh:
                writer = safe_csv_writer(fh, delimiter=";")
                writer.writerow(["Mansione nella scheda", "Persone", "Esito", "Voce del catalogo", "Voce attiva"])
                for r in righe:
                    attiva = "" if r["voce_attiva"] is None else ("sì" if r["voce_attiva"] else "no")
                    writer.writerow([r["mansione"], r["persone"], r["esito"], r["voce_catalogo"], attiva])
            self.stdout.write(f"Report scritto: {opts['report']}")
        self.stdout.write("Nessuna modifica: il comando è in sola lettura.")
