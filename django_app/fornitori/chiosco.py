"""Chiosco della reception dentro l'HUB: il visitatore si registra senza login.

Le pagine stanno nell'HUB (``/chiosco/``), la logica resta nel GuestPortal: check-in,
cartellini, consenso, coda delle mail al referente e pulizia GDPR sono le sue, chiamate qui
via HTTP lato server. Così l'HUB non scrive nel database del GuestPortal: l'utente MySQL
``hub_readonly`` resta di sola lettura e nessun dato di visita viene copiato.

Rispetto alle API del GuestPortal, qui il browser sceglie solo dei numeri (referente, azienda,
nominativo): nomi ed email li rilegge il server. ``create_supplier`` e ``create_contact`` non
sono esposti: una ditta che manca si registra in reception, come oggi al chiosco.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

TIMEOUT_SECONDI = 8
CACHE_REFERENTI = "chiosco:referenti"
CACHE_CATEGORIE = "chiosco:categorie"
SECONDI_REFERENTI = 60
SECONDI_CATEGORIE = 600

# Quelle di partenza del GuestPortal, se la sua pagina non si può leggere. L'elenco vero sta nella
# tabella VisitCategories: il GuestPortal non ha un'API e ``hub_readonly`` non può leggerla.
CATEGORIE_PREDEFINITE = [
    {"nome": "Riunione / Meeting", "icona": "🤝"},
    {"nome": "Assistenza tecnica", "icona": "🔧"},
    {"nome": "Colloquio di lavoro", "icona": "💼"},
    {"nome": "Consegna materiale", "icona": "📦"},
    {"nome": "Altro", "icona": "📋"},
]
_CARD_CATEGORIA = re.compile(
    r'class="category-card"\s+data-id="\d+"\s+data-name="([^"]*)".*?class="cat-icon">([^<]*)<', re.S,
)


class ChioscoNonDisponibile(Exception):
    """Il GuestPortal non risponde o non risponde come previsto."""


def configurato() -> bool:
    return bool(getattr(settings, "GUESTPORTAL_CHIOSCO_API_URL", "").strip())


def _richiesta(url: str, dati: dict | None = None) -> tuple[int, bytes]:
    corpo = json.dumps(dati).encode("utf-8") if dati is not None else None
    richiesta = urllib.request.Request(url, data=corpo, method="POST" if dati is not None else "GET")
    if corpo is not None:
        richiesta.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT_SECONDI) as risposta:  # noqa: S310 - URL da settings
            return risposta.status, risposta.read()
    except urllib.error.HTTPError as exc:
        # 409, 422 e 503 sono esiti del chiosco (già dentro, dati mancanti, cartellini finiti).
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Chiosco: GuestPortal non raggiungibile: %s", exc)
        raise ChioscoNonDisponibile from exc


def chiama(nome_api: str, dati: dict | None = None) -> tuple[int, dict]:
    """``public/api/<nome_api>.php``. Ritorna stato HTTP e JSON."""
    if not configurato():
        raise ChioscoNonDisponibile
    url = settings.GUESTPORTAL_CHIOSCO_API_URL.rstrip("/") + f"/{nome_api}.php"
    stato, corpo = _richiesta(url, dati)
    try:
        esito = json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        logger.warning("Chiosco: risposta non JSON da %s (HTTP %s)", nome_api, stato)
        raise ChioscoNonDisponibile from exc
    if not isinstance(esito, dict):
        raise ChioscoNonDisponibile
    return stato, esito


def referenti() -> list[dict]:
    """Dipendenti attivi: ``{id, nome, reparto, email}``. L'email resta sul server."""
    elenco = cache.get(CACHE_REFERENTI)
    if elenco is not None:
        return elenco
    _stato, esito = chiama("employees")
    if not esito.get("success"):
        raise ChioscoNonDisponibile
    elenco = [
        {"id": int(r["EmployeeID"]), "nome": r.get("FullName") or "", "reparto": r.get("Department") or "",
         "email": r.get("Email") or ""}
        for r in esito.get("data") or []
    ]
    cache.set(CACHE_REFERENTI, elenco, SECONDI_REFERENTI)
    return elenco


def referente(pk) -> dict | None:
    return next((r for r in referenti() if str(r["id"]) == str(pk)), None)


def categorie() -> list[dict]:
    elenco = cache.get(CACHE_CATEGORIE)
    if elenco is not None:
        return elenco
    elenco = []
    if configurato():
        url = settings.GUESTPORTAL_CHIOSCO_API_URL.rstrip("/").rsplit("/", 1)[0] + "/kiosk/checkin.php"
        try:
            _stato, corpo = _richiesta(url)
            elenco = [{"nome": html.unescape(n), "icona": html.unescape(i).strip()}
                      for n, i in _CARD_CATEGORIA.findall(corpo.decode("utf-8", "replace"))]
        except ChioscoNonDisponibile:
            pass
    # Nel GuestPortal l'icona può essere vuota: si usa quella di partenza con lo stesso nome.
    icone = {c["nome"]: c["icona"] for c in CATEGORIE_PREDEFINITE}
    elenco = [{**c, "icona": c["icona"] or icone.get(c["nome"], "📋")} for c in elenco] or CATEGORIE_PREDEFINITE
    cache.set(CACHE_CATEGORIE, elenco, SECONDI_CATEGORIE)
    return elenco


def aziende() -> list[dict]:
    _stato, esito = chiama("supplier_lookup", {"action": "suppliers"})
    return [{"id": int(s["SupplierID"]), "nome": s.get("CompanyName") or ""} for s in esito.get("suppliers") or []]


def nominativi(azienda_id: int) -> list[dict]:
    _stato, esito = chiama("supplier_lookup", {"action": "contacts", "supplier_id": int(azienda_id)})
    return [{"id": int(c["ContactID"]), "nome": c.get("FirstName") or "", "cognome": c.get("LastName") or ""}
            for c in esito.get("contacts") or []]
