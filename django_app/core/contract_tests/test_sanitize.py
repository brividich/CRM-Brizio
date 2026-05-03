"""
Verifica che le cassette in core/contract_tests/cassettes/ NON contengano
segreti, email reali o domini interni.

Esegui questo test prima di committare nuove cassette: e' la tua rete di
sicurezza per evitare che credenziali finiscano in repo per errore.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from django.test import TestCase

CASSETTES_DIR = Path(__file__).resolve().parent / "cassettes"

# Domini considerati sintetici/sicuri (RFC 2606 + convenzioni progetto).
ALLOWED_EMAIL_DOMAINS = {
    "example.invalid",
    "example.com",
    "example.org",
    "example.net",
    "example.local",
    "test.invalid",
}

# Pattern di valori che NON devono mai apparire nelle cassette.
FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Bearer JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}")),
    ("Authorization Bearer header", re.compile(r"(?i)authorization:\s*bearer\s+[a-z0-9._\-]{20,}")),
    ("UUID-style refresh-token", re.compile(r"\brefresh_token\b\s*[:=]\s*\"[^\"]{40,}\"")),
    ("MS-GUID novicrom", re.compile(r"(?i)novicrom\.(?:com|it|local|onmicrosoft\.com)")),
    ("dominio interno costruzioninovicrom", re.compile(r"(?i)costruzioninovicrom\.")),
]

# Chiavi i cui valori, se non vuoti e non placeholder, sono sospetti.
SENSITIVE_VALUE_KEYS = ("client_secret", "password", "id_token", "refresh_token")


def _iter_cassettes() -> list[Path]:
    return sorted(CASSETTES_DIR.glob("*.json"))


def _is_synthetic_value(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return True
    return (
        lowered.startswith("synthetic")
        or lowered.startswith("placeholder")
        or lowered.startswith("<")
        and lowered.endswith(">")
        or lowered in {"changeme", "fake", "test"}
    )


def _walk(value, callback) -> None:
    if isinstance(value, dict):
        for key, sub in value.items():
            callback(key, sub)
            _walk(sub, callback)
    elif isinstance(value, list):
        for item in value:
            _walk(item, callback)


class CassetteSanitizationTests(TestCase):
    def test_cassettes_directory_exists(self):
        self.assertTrue(CASSETTES_DIR.is_dir(), f"Cartella cassette non trovata: {CASSETTES_DIR}")

    def test_no_forbidden_patterns_anywhere(self):
        for cassette_path in _iter_cassettes():
            text = cassette_path.read_text(encoding="utf-8")
            for label, pattern in FORBIDDEN_PATTERNS:
                match = pattern.search(text)
                self.assertIsNone(
                    match,
                    f"Cassetta {cassette_path.name} contiene pattern vietato '{label}': "
                    f"{match.group(0) if match else ''}",
                )

    def test_email_domains_are_synthetic(self):
        email_re = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
        for cassette_path in _iter_cassettes():
            text = cassette_path.read_text(encoding="utf-8")
            for match in email_re.finditer(text):
                domain = match.group(1).lower()
                self.assertIn(
                    domain,
                    ALLOWED_EMAIL_DOMAINS,
                    f"Cassetta {cassette_path.name} contiene email con dominio non sintetico: "
                    f"{match.group(0)} (dominio={domain})",
                )

    def test_sensitive_keys_are_synthetic_or_empty(self):
        for cassette_path in _iter_cassettes():
            payload = json.loads(cassette_path.read_text(encoding="utf-8"))
            issues: list[str] = []

            def visit(key, value):
                if not isinstance(key, str):
                    return
                if key.lower() in SENSITIVE_VALUE_KEYS and isinstance(value, str):
                    if not _is_synthetic_value(value):
                        issues.append(f"chiave sensibile '{key}' con valore non sintetico")

            _walk(payload, visit)
            self.assertFalse(
                issues,
                f"Cassetta {cassette_path.name} ha valori sensibili reali: {issues}",
            )
