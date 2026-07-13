"""Query normalization helpers for internal AI memory retrieval."""

from dataclasses import dataclass
import re

from .chunker import normalize_whitespace


TOKEN_RE = re.compile(
    r"CVE-\d{4}-\d{4,7}|"
    r"(?:\d{1,3}\.){3}\d{1,3}|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,}",
    re.IGNORECASE,
)
CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was",
    "con", "che", "del", "della", "degli", "gli", "una", "per", "nel",
    "nella", "sono", "come", "quali", "questo", "questa", "security", "center",
    "spiega", "riassumi", "genera", "piano", "usando", "solo", "fonti",
}

TECHNICAL_HINTS = {
    "cve", "cvss", "defender", "watchguard", "threatsync", "firebox", "epdr",
    "dimension", "synology", "backup", "nas", "host", "hostname", "asset",
    "ticket", "alert", "evidence", "report", "kpi", "vpn", "firewall",
    "critical", "high", "exposed", "devices",
}


@dataclass(frozen=True)
class NormalizedQuery:
    original: str
    normalized: str
    tokens: list[str]
    important_tokens: list[str]
    phrases: list[str]
    entities: dict[str, list[str]]


def normalize_query(query: str) -> NormalizedQuery:
    original = "" if query is None else str(query)
    normalized = normalize_whitespace(original)
    lowered = normalized.lower()
    raw_tokens = TOKEN_RE.findall(normalized)

    tokens: list[str] = []
    for raw_token in raw_tokens:
        token = _normalize_token(raw_token)
        if token and token not in STOPWORDS and token not in tokens:
            tokens.append(token)

    entities = {
        "cves": sorted({match.upper() for match in CVE_RE.findall(normalized)}),
        "ips": sorted({match for match in IPV4_RE.findall(normalized)}),
        "emails": sorted({match.lower() for match in EMAIL_RE.findall(normalized)}),
        "hostnames": sorted(_detect_hostnames(raw_tokens)),
        "vendors": sorted(_detect_vendors(tokens)),
        "products": sorted(_detect_products(tokens)),
    }
    important_tokens = [
        token for token in tokens
        if token in TECHNICAL_HINTS
        or token.startswith("cve-")
        or IPV4_RE.fullmatch(token)
        or "." in token
        or "-" in token
    ]
    phrases = _candidate_phrases(lowered, tokens)
    return NormalizedQuery(
        original=original,
        normalized=lowered,
        tokens=tokens,
        important_tokens=important_tokens,
        phrases=phrases,
        entities=entities,
    )


def _normalize_token(token: str) -> str:
    token = normalize_whitespace(token).strip(".,;!?()[]{}\"'").lower()
    if CVE_RE.fullmatch(token):
        return token.upper().lower()
    return token


def _candidate_phrases(lowered: str, tokens: list[str]) -> list[str]:
    phrases = []
    if len(lowered) >= 8:
        phrases.append(lowered)
    for index in range(max(0, len(tokens) - 1)):
        phrase = f"{tokens[index]} {tokens[index + 1]}"
        if len(phrase) >= 8 and phrase not in phrases:
            phrases.append(phrase)
    return phrases[:4]


def _detect_hostnames(raw_tokens: list[str]) -> set[str]:
    hostnames = set()
    for token in raw_tokens:
        cleaned = token.strip(".,;!?()[]{}\"'")
        if EMAIL_RE.fullmatch(cleaned) or IPV4_RE.fullmatch(cleaned) or CVE_RE.fullmatch(cleaned):
            continue
        if "-" in cleaned and any(char.isalpha() for char in cleaned):
            hostnames.add(cleaned.upper())
    return hostnames


def _detect_vendors(tokens: list[str]) -> set[str]:
    vendors = set()
    for vendor in {"watchguard", "microsoft", "defender", "synology"}:
        if vendor in tokens:
            vendors.add(vendor)
    return vendors


def _detect_products(tokens: list[str]) -> set[str]:
    products = set()
    for product in {"epdr", "threatsync", "dimension", "firebox", "active", "backup"}:
        if product in tokens:
            products.add(product)
    return products
