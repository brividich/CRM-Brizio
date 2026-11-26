"""Pagine interne dei moduli per la ricerca globale (Ctrl+K, sezione «Vai a…»).

La palette conosce dalla pagina solo le voci del menu principale e il sottomenu
della pagina in cui ci si trova: «Recruiting», «Banco consegne», «Sorgenti»…
restavano introvabili da fuori del loro modulo. Qui si raccolgono le voci dei
sottomenu di tutti i moduli, dalle stesse fonti che li disegnano:

- i sottomenu scritti nei template (``components/subnav.html``, ``_nav.html``…):
  letti una volta per processo, solo i link ``{% url 'nome' %}`` senza parametri
  della pagina;
- il sottomenu di Anagrafica (a database, ``SubnavLinkAnagrafica``);
- la navigazione Manutenzione (``assets.maintenance_nav``);
- il Navigation Registry (sottomenu di ogni sezione e, per gli amministratori,
  quello del pannello admin).

Ogni voce trovata passa dallo stesso controllo della navigazione: ACL della
pagina e cancelli in-view (``anagrafica.subnav_gates.section_gate_allows``).
Il controllo si fa solo sulle voci che corrispondono alla frase cercata.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)

LIMITE = 8

# File dei sottomenu dei moduli. Il pannello admin (``admin_subnav.html``) e il
# sottomenu di Anagrafica leggono da database: hanno le loro fonti piu' sotto.
_PATTERN_TEMPLATE = ("*subnav*.html", "_nav.html", "_modulo_nav.html", "section_nav.html")

_RE_LINK = re.compile(
    r"<a\b(?P<attr>[^>]*?)href=\"\{%\s*url\s+'(?P<nome>[\w:.-]+)'(?P<arg>(?:\s+'[^']*')*)\s*%\}(?P<qs>[^\"]*)\"[^>]*>"
    r"(?P<label>.*?)</a>",
    re.S,
)
_RE_TAG = re.compile(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}|<[^>]+>", re.S)
_RE_ALTERNATIVA = re.compile(r"\{%\s*(?:else|elif[^%]*)\s*%\}")


@dataclass(frozen=True)
class Voce:
    label: str
    url: str
    gruppo: str
    parole: str  # testo normalizzato su cui si cerca (etichetta, alternative, modulo)


def normalizza(testo: str) -> str:
    testo = unicodedata.normalize("NFD", str(testo or "").lower())
    return "".join(c for c in testo if unicodedata.category(c) != "Mn")


def _pulisci(testo: str) -> str:
    testo = _RE_TAG.sub(" ", testo)
    testo = re.sub(r"&[a-z]+;|&#\d+;", " ", testo)
    testo = re.sub(r"\s+", " ", testo).strip()
    return re.sub(r"^[^\w(«]+", "", testo).strip()


@lru_cache(maxsize=1)
def _moduli_per_percorso() -> tuple[tuple[str, str], ...]:
    """(prefisso di percorso, nome del modulo) dalle voci del menu principale, prefissi lunghi prima."""
    from core.models import NavigationItem

    coppie = {}
    try:
        righe = NavigationItem.objects.filter(section="topbar", is_enabled=True).values_list("url_path", "route_name", "label")
        for url_path, route_name, label in righe:
            percorso = str(url_path or "").strip()
            if not percorso and route_name:
                try:
                    percorso = reverse(route_name)
                except NoReverseMatch:
                    percorso = ""
            percorso = percorso.split("?", 1)[0]
            if percorso.startswith("/") and percorso != "/" and label:
                coppie.setdefault(percorso if percorso.endswith("/") else percorso + "/", str(label).strip())
    except Exception:
        logger.warning("ricerca pagine: menu principale non leggibile", exc_info=True)
    return tuple(sorted(coppie.items(), key=lambda c: -len(c[0])))


def modulo_di(url: str, ripiego: str = "") -> str:
    percorso = url.split("?", 1)[0]
    for prefisso, label in _moduli_per_percorso():
        if percorso.startswith(prefisso):
            return label
    if ripiego:
        return ripiego
    primo = percorso.strip("/").split("/", 1)[0]
    return primo.replace("-", " ").replace("_", " ").capitalize()


def _cartelle_template() -> list[Path]:
    base = Path(settings.BASE_DIR)
    cartelle = [base / "templates"]
    cartelle += [p for p in base.glob("*/templates") if p.is_dir()]
    return cartelle


@lru_cache(maxsize=1)
def voci_dai_template() -> tuple[Voce, ...]:
    """Link dei sottomenu scritti nei template: (etichetta, url, modulo). Una volta per processo."""
    voci: list[Voce] = []
    visti: set[str] = set()
    for cartella in _cartelle_template():
        for pattern in _PATTERN_TEMPLATE:
            for file in sorted(cartella.rglob(pattern)):
                if file.name == "admin_subnav.html" or "anagrafica" in file.parts and file.name == "subnav.html":
                    continue
                try:
                    sorgente = file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for m in _RE_LINK.finditer(sorgente):
                    if "{{" in m.group("qs") or "{%" in m.group("qs"):
                        continue  # query che dipende dalla pagina
                    argomenti = re.findall(r"'([^']*)'", m.group("arg") or "")
                    try:
                        url = reverse(m.group("nome"), args=argomenti) + m.group("qs")
                    except NoReverseMatch:
                        continue
                    alternative = [_pulisci(p) for p in _RE_ALTERNATIVA.split(m.group("label"))]
                    alternative = [a for a in alternative if a]
                    if not alternative or alternative[0].startswith("?") or url in visti:
                        continue  # «? Guida»: c'e' il Centro guide
                    visti.add(url)
                    gruppo = modulo_di(url)
                    voci.append(Voce(alternative[0], url, gruppo, normalizza(" ".join(alternative + [gruppo]))))
    return tuple(voci)


def _voci_manutenzione() -> list[Voce]:
    try:
        from assets.maintenance_nav import MAINTENANCE_NAV
    except Exception:
        return []
    voci = []
    for gruppo in MAINTENANCE_NAV:
        for item in gruppo.items:
            try:
                url = reverse(f"assets:{item.route}")
            except NoReverseMatch:
                continue
            if item.query:
                url = f"{url}?{item.query}"
            nome = f"Asset · {gruppo.label}"
            voci.append(Voce(item.label, url, nome, normalizza(f"{item.label} {nome}")))
    return voci


def _voci_anagrafica() -> list[Voce]:
    try:
        from anagrafica.models import SubnavCategoriaAnagrafica, SubnavLinkAnagrafica

        categorie = dict(SubnavCategoriaAnagrafica.objects.filter(is_active=True).values_list("pk", "nome"))
        links = list(SubnavLinkAnagrafica.objects.filter(is_active=True).order_by("ordine", "etichetta"))
    except Exception:
        logger.warning("ricerca pagine: sottomenu Anagrafica non leggibile", exc_info=True)
        return []
    voci = []
    for link in links:
        if getattr(link, "url_type", "") == "named":
            try:
                url = reverse(link.url_value)
            except NoReverseMatch:
                continue
        else:
            url = str(getattr(link, "url_value", "") or "").strip()
        if not url.startswith("/"):
            continue  # link esterni o vuoti
        pilastro = categorie.get(link.categoria_id, "")
        gruppo = " · ".join(p for p in ("Anagrafica", pilastro) if p)
        extra = getattr(link, "gruppo", "") or ""
        etichetta = _pulisci(link.etichetta)
        voci.append(Voce(etichetta, url, gruppo, normalizza(f"{etichetta} {extra} {gruppo}")))
    return voci


def _voci_registro(request, legacy_user) -> list[Voce]:
    """Sottomenu del Navigation Registry gia' filtrati per l'utente (in cache per utente)."""
    from core.legacy_utils import is_legacy_admin
    from core.navigation_registry import _apply_user_nav_overrides, _compiled_items_for_role

    is_admin = bool(getattr(request.user, "is_superuser", False) or (legacy_user and is_legacy_admin(legacy_user)))
    role_id = getattr(legacy_user, "ruolo_id", None) if legacy_user else None
    legacy_id = getattr(legacy_user, "id", None) if legacy_user else None
    voci = []
    sezioni = ["subnav"] + (["admin_subnav"] if is_admin else [])
    for sezione in sezioni:
        try:
            righe = _compiled_items_for_role(
                role_id=int(role_id) if role_id else None, is_admin=is_admin, section=sezione,
                legacy_user_id=int(legacy_id) if legacy_id else None,
            )
            if legacy_id and not is_admin:
                righe = _apply_user_nav_overrides(righe, int(legacy_id), sezione, is_admin)
        except Exception:
            logger.warning("ricerca pagine: registro %s non leggibile", sezione, exc_info=True)
            continue
        for riga in righe:
            href = str(riga.get("href") or "").strip()
            if not href.startswith("/") or riga.get("coming"):
                continue
            gruppo = modulo_di(href, "Amministrazione" if sezione == "admin_subnav" else "")
            etichetta = _pulisci(riga["label"])
            voci.append(Voce(etichetta, href, gruppo, normalizza(f"{etichetta} {riga.get('group') or ''} {gruppo}")))
    return voci


def cerca_pagine(request, q: str, *, puo_aprire, limite: int = LIMITE) -> list[dict]:
    """Pagine dei sottomenu che corrispondono a ``q`` e che l'utente puo' aprire.

    ``puo_aprire(request, path)`` e' il controllo ACL della ricerca globale; qui si
    aggiungono i cancelli in-view, come nella navigazione.
    """
    termini = normalizza(q).split()
    if not termini:
        return []
    legacy_user = getattr(request, "legacy_user", None)
    if legacy_user is None:
        from core.legacy_utils import get_legacy_user

        legacy_user = get_legacy_user(request.user)

    candidati: list[tuple[int, Voce]] = []
    visti: set[str] = set()
    for fonte in (_voci_registro(request, legacy_user), _voci_anagrafica(), _voci_manutenzione(), voci_dai_template()):
        for voce in fonte:
            if voce.url in visti or not all(t in voce.parole for t in termini):
                continue
            visti.add(voce.url)
            etichetta = normalizza(voce.label)
            punteggio = 0 if etichetta.startswith(termini[0]) else (1 if termini[0] in etichetta else 2)
            candidati.append((punteggio, voce))
    candidati.sort(key=lambda c: (c[0], c[1].label.lower()))

    from anagrafica.subnav_gates import section_gate_allows

    risultati = []
    for _punteggio, voce in candidati:
        percorso = voce.url.split("?", 1)[0]
        try:
            if not puo_aprire(request, percorso) or not section_gate_allows(request, percorso):
                continue
        except Exception:
            logger.warning("ricerca pagine: controllo fallito per %s", percorso, exc_info=True)
            continue
        risultati.append({"tipo": "pagina", "label": voce.label, "sub": voce.gruppo, "url": voce.url})
        if len(risultati) >= limite:
            break
    return risultati
