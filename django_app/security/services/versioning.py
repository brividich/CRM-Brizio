"""Confronto di versioni software robusto (inventario ↔ range vulnerabili NVD).

Prima ``packaging.version`` (PEP 440); se una delle due stringhe non è PEP 440 si passa
al confronto per segmenti: numeri come numeri, testo come testo, con i suffissi di
pre-release («beta», «rc», «alpha», «pre», «preview») che vengono prima della release.
Se due versioni non sono confrontabili in modo affidabile si restituisce ``None``: il
chiamante dirà «da verificare», mai «sicuro».

Esempi gestiti: ``10.0.19045.4651``, ``23.01``, ``2.4.1-beta``, ``24.07``, ``1.2.3a1``.
"""
from __future__ import annotations

import re

try:
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover - packaging è in requirements; il fallback resta comunque corretto
    Version = None
    InvalidVersion = ValueError

_PRE_TAGS = {"dev": -4, "alpha": -3, "a": -3, "beta": -2, "b": -2, "pre": -1, "preview": -1, "rc": -1}
_TOKEN = re.compile(r"\d+|[a-z]+")
_LEADING = re.compile(r"^[vV](?=\d)")
_NOISE = re.compile(r"\s*\(.*?\)\s*|\s+(x64|x86|64-bit|32-bit|amd64)$", re.I)


def normalize(raw):
    """Forma confrontabile: senza prefisso «v», senza note tra parentesi e architettura."""
    text = str(raw or "").strip()
    text = _NOISE.sub("", text).strip()
    text = _LEADING.sub("", text)
    return text.strip()[:120]


def _pep440(text):
    if Version is None:
        return None
    try:
        return Version(text)
    except InvalidVersion:
        return None


def _segments(text):
    tokens = _TOKEN.findall(text.lower())
    if not tokens or not tokens[0].isdigit():
        return None
    out = []
    for token in tokens:
        if token.isdigit():
            out.append((1, int(token)))
        elif token in _PRE_TAGS:
            out.append((0, _PRE_TAGS[token]))
        else:
            return None  # testo sconosciuto in mezzo (es. «21H2», «R2»): non confrontabile
    return out


def _cmp_segments(a, b):
    length = max(len(a), len(b))
    for i in range(length):
        left = a[i] if i < len(a) else (1, 0)
        right = b[i] if i < len(b) else (1, 0)
        # Un marcatore di pre-release contro uno zero di riempimento: 2.4.1-beta < 2.4.1
        if left != right:
            return -1 if left < right else 1
    return 0


def compare(a, b):
    """-1 / 0 / 1, oppure None se il confronto non è affidabile."""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return None
    pa, pb = _pep440(a), _pep440(b)
    if pa is not None and pb is not None:
        return (pa > pb) - (pa < pb)
    sa, sb = _segments(a), _segments(b)
    if sa is None or sb is None:
        return None
    return _cmp_segments(sa, sb)


def in_range(version, *, start_including=None, start_excluding=None, end_including=None, end_excluding=None, exact=None):
    """True/False se ``version`` cade nel range vulnerabile, None se non confrontabile."""
    if exact not in (None, "", "*", "-"):
        result = compare(version, exact)
        return None if result is None else result == 0
    checks = (
        (start_including, lambda c: c >= 0),
        (start_excluding, lambda c: c > 0),
        (end_including, lambda c: c <= 0),
        (end_excluding, lambda c: c < 0),
    )
    for bound, ok in checks:
        if bound in (None, ""):
            continue
        result = compare(version, bound)
        if result is None:
            return None
        if not ok(result):
            return False
    # Tutti i limiti rispettati; nessun limite e nessuna versione esatta = «tutte le versioni».
    return True
