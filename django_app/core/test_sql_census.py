"""Censimento del SQL grezzo (audit 18/10, fase 4): la quantita' non cresce senza accorgersene.

``ruff --select S608`` segnala ogni query costruita con f-string/format/%. Il censimento
del 19/10/2026 (214 siti) ha verificato che interpolano solo identificatori presi da
registri, costanti o ``quote_name``, e che i valori passano sempre come parametri.
Questo test tiene quel conteggio come linea di base per file: una query nuova costruita
con stringhe fa fallire il test finche' non si usa un parametro, oppure finche' il nuovo
sito non viene riesaminato e aggiunto consapevolmente a ``sql_grezzo_baseline.json``.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

DJANGO_APP = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "sql_grezzo_baseline.json"
EXCLUDE = ".tmp_tests,powerautomate-to-django-automations,migrations,node_modules,staticfiles"


def _ruff_available() -> bool:
    if shutil.which("ruff"):
        return True
    probe = subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True, text=True)
    return probe.returncode == 0


def _s608_counts() -> Counter:
    cmd = [sys.executable, "-m", "ruff", "check", ".", "--select", "S608", "--output-format", "json", "--exclude", EXCLUDE]
    out = subprocess.run(cmd, cwd=DJANGO_APP, capture_output=True, text=True, encoding="utf-8").stdout
    hits = json.loads(out or "[]")
    counts: Counter = Counter()
    for h in hits:
        rel = Path(h["filename"]).resolve().relative_to(DJANGO_APP).as_posix()
        counts[rel] += 1
    return counts


class SqlGrezzoCensimentoTest(SimpleTestCase):
    def test_il_sql_costruito_con_stringhe_non_aumenta(self):
        if not _ruff_available():
            self.skipTest("ruff non installato")
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        current = _s608_counts()
        peggiorati = {f: (baseline.get(f, 0), n) for f, n in current.items() if n > baseline.get(f, 0)}
        self.assertEqual(
            peggiorati,
            {},
            "Nuove query costruite con stringhe (file: linea di base -> ora). Passa i valori come parametri "
            "e gli identificatori da registri/quote_name; se il sito e' stato riesaminato, aggiorna "
            "core/sql_grezzo_baseline.json nello stesso commit. "
            f"{peggiorati}",
        )
