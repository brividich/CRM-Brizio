"""Censimento dei caricamenti (audit 22/11, voce [56]): nessun file nuovo legge ``request.FILES`` di nascosto.

Ogni caricamento deve passare dal validatore unico ``core.upload_mime`` (nome, estensione,
dimensione, tipo reale e firma) o da un form che lo usa. Questo test tiene come linea di
base, per file, quante volte il codice legge ``request.FILES``: un file nuovo, o un file
che ne aggiunge uno, fa fallire il test finché il nuovo caricamento non viene controllato e
``core/upload_censimento_baseline.json`` aggiornato nello stesso commit.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

DJANGO_APP = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "upload_censimento_baseline.json"
ESCLUSE = {"migrations", "node_modules", "staticfiles", ".tmp_tests", "powerautomate-to-django-automations", "tests"}
_LETTURA = re.compile(r"request\.FILES")


def _conteggi() -> Counter:
    esito: Counter = Counter()
    for percorso in DJANGO_APP.rglob("*.py"):
        rel = percorso.relative_to(DJANGO_APP)
        if set(rel.parts) & ESCLUSE or rel.name.startswith("test"):
            continue
        n = len(_LETTURA.findall(percorso.read_text(encoding="utf-8", errors="ignore")))
        if n:
            esito[rel.as_posix()] = n
    return esito


class CaricamentiCensimentoTest(SimpleTestCase):
    def test_nessun_caricamento_nuovo_senza_controllo(self):
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        nuovi = {f: (baseline.get(f, 0), n) for f, n in _conteggi().items() if n > baseline.get(f, 0)}
        self.assertEqual(
            nuovi,
            {},
            "Nuove letture di request.FILES (file: linea di base -> ora). Valida il file con "
            "core.upload_mime.valida_per_estensione (o un form che lo usa); poi aggiorna "
            f"core/upload_censimento_baseline.json nello stesso commit. {nuovi}",
        )
