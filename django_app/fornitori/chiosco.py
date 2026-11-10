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


def nativa() -> bool:
    return bool(getattr(settings, "RECEPTION_NATIVA", False))


def configurato() -> bool:
    return nativa() or bool(getattr(settings, "GUESTPORTAL_CHIOSCO_API_URL", "").strip())


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


def chiama(nome_api: str, dati: dict | None = None, ip: str = "") -> tuple[int, dict]:
    """``public/api/<nome_api>.php``, o le stesse risposte dalle tabelle dell'HUB dopo il passaggio
    (lì ``ip`` finisce nella registrazione dell'informativa). Ritorna stato HTTP e JSON."""
    if nativa():
        from reception import api_chiosco

        return api_chiosco.chiama(nome_api, dati, ip)
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
    elenco = None if nativa() else cache.get(CACHE_REFERENTI)
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
    if nativa():
        from reception import api_chiosco

        return api_chiosco.categorie() or CATEGORIE_PREDEFINITE
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


# ─── Ricerca live dal totem ───────────────────────────────────────────────────────────────
# Chi scrive al totem vede pochi risultati, con il cognome ridotto all'iniziale: basta per
# riconoscersi, non per leggere l'elenco dei visitatori. Il browser riceve solo una chiave firmata
# e a scadenza; nomi, email e telefono li rilegge il server al momento dell'ingresso.
CERCA_MIN = 3
CERCA_MAX_OSPITI = 6
CERCA_MAX_DITTE = 4
CHIAVE_SALE = "chiosco.ospite"
CHIAVE_SECONDI = 900
CACHE_AZIENDE = "chiosco:aziende"
_CODICE = re.compile(r"^[A-Z0-9]{8}$")


def _parole(testo: str) -> list[str]:
    return [p for p in re.split(r"\s+", (testo or "").strip()) if p][:3]


def nome_ridotto(nome: str, cognome: str) -> str:
    nome, cognome = (nome or "").strip(), (cognome or "").strip()
    return f"{nome} {cognome[:1]}." if cognome else nome


def _giorni_conservazione() -> int:
    return max(30, int(getattr(settings, "RECEPTION_CONSERVAZIONE_MESI", 12) or 12) * 31)


def chiave_ospite(origine: str, pk: int) -> str:
    from django.core import signing

    return signing.dumps({"o": origine, "id": int(pk)}, salt=CHIAVE_SALE, compress=True)


def _apri_chiave(chiave: str) -> tuple[str, int] | None:
    from django.core import signing

    try:
        dati = signing.loads(chiave or "", salt=CHIAVE_SALE, max_age=CHIAVE_SECONDI)
        return str(dati["o"]), int(dati["id"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None


def cerca_ospiti(testo: str) -> list[dict]:
    """Visitatori già passati (non fornitori, non anonimizzati, nel periodo di conservazione) con
    nome o cognome che inizia con le parole scritte, o con quell'email esatta. Dal più recente."""
    parole = _parole(testo)
    if len((testo or "").strip()) < CERCA_MIN or not parole:
        return []
    righe = _cerca_ospiti_hub(testo, parole) if nativa() else _cerca_ospiti_gp(testo, parole)
    return [{
        "chiave": chiave_ospite(r["origine"], r["id"]),
        "nome": nome_ridotto(r["nome"], r["cognome"]),
        "azienda": r["azienda"],
        "ultima": r["ultima"].strftime("%d/%m/%Y") if r.get("ultima") else "",
        "referente": r.get("referente") or "",
        "motivo": r.get("motivo") or "",
    } for r in righe]


def _cerca_ospiti_hub(testo: str, parole: list[str]) -> list[dict]:
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    from reception.models import Visita

    filtro = Q()
    for p in parole:
        filtro &= Q(ospite__nome__istartswith=p) | Q(ospite__cognome__istartswith=p)
    if "@" in testo:
        filtro |= Q(ospite__email__iexact=testo.strip())
    visite = (Visita.objects.select_related("ospite")
              .filter(ospite__anonimizzato=False, ingresso__gte=timezone.now() - timedelta(days=_giorni_conservazione()))
              .exclude(tipo=Visita.FORNITORE).filter(filtro).order_by("-ingresso")[:60])
    viste, righe = set(), []
    for v in visite:
        if v.ospite_id in viste:
            continue
        viste.add(v.ospite_id)
        o = v.ospite
        righe.append({"origine": "hub", "id": o.pk, "nome": o.nome, "cognome": o.cognome, "azienda": o.azienda,
                      "ultima": timezone.localtime(v.ingresso) if v.ingresso else None,
                      "referente": v.referente_nome, "motivo": v.motivo})
        if len(righe) >= CERCA_MAX_OSPITI:
            break
    return righe


def _cerca_ospiti_gp(testo: str, parole: list[str]) -> list[dict]:
    from datetime import datetime, timedelta

    from . import guestportal

    if not guestportal.db_configurato():
        return []
    condizioni, params = [], [datetime.now() - timedelta(days=_giorni_conservazione())]
    for p in parole:
        condizioni.append("(g.FirstName LIKE %s OR g.LastName LIKE %s)")
        params.extend([p + "%", p + "%"])
    where = " AND ".join(condizioni)
    if "@" in testo:
        where = f"(({where}) OR g.Email = %s)"
        params.append(testo.strip())
    params.append(CERCA_MAX_OSPITI)
    try:
        ospiti = guestportal._esegui(
            "SELECT g.GuestID, g.FirstName, g.LastName, g.Company, MAX(v.CheckInTime) AS Ultima"
            " FROM Guests g JOIN Visits v ON v.GuestID = g.GuestID"
            " WHERE g.IsAnonymized = 0 AND v.CheckInTime >= %s AND v.VisitType <> 'SUPPLIER' AND " + where +
            " GROUP BY g.GuestID, g.FirstName, g.LastName, g.Company ORDER BY Ultima DESC LIMIT %s", params)
        ultime: dict[int, dict] = {}
        if ospiti:
            ids = [int(o["GuestID"]) for o in ospiti]
            segnaposto = ",".join(["%s"] * len(ids))
            for r in guestportal._esegui(
                "SELECT GuestID, HostEmployee, Purpose FROM Visits WHERE GuestID IN (" + segnaposto + ")"
                " ORDER BY CheckInTime DESC", ids):
                ultime.setdefault(int(r["GuestID"]), r)
    except (guestportal.GuestPortalNonConfigurato, guestportal.GuestPortalNonRaggiungibile):
        return []
    righe = []
    for o in ospiti:
        ultima = ultime.get(int(o["GuestID"])) or {}
        righe.append({"origine": "gp", "id": int(o["GuestID"]), "nome": o.get("FirstName") or "",
                      "cognome": o.get("LastName") or "", "azienda": (o.get("Company") or "").strip(),
                      "ultima": o.get("Ultima"), "referente": ultima.get("HostEmployee") or "",
                      "motivo": ultima.get("Purpose") or ""})
    return righe


def ospite_da_chiave(chiave: str) -> dict | None:
    """Dati completi dell'ospite scelto al totem: ``{origine, id, nome, cognome, email, telefono, azienda}``."""
    aperta = _apri_chiave(chiave)
    if aperta is None:
        return None
    origine, pk = aperta
    if origine == "hub" and nativa():
        from reception.models import Ospite

        o = Ospite.objects.filter(pk=pk, anonimizzato=False).first()
        if o is None:
            return None
        return {"origine": "hub", "id": o.pk, "nome": o.nome, "cognome": o.cognome, "email": o.email,
                "telefono": o.telefono, "azienda": o.azienda}
    if origine == "gp" and not nativa():
        from . import guestportal

        try:
            righe = guestportal._esegui("SELECT FirstName, LastName, Email, Phone, Company FROM Guests"
                                        " WHERE GuestID = %s AND IsAnonymized = 0", [pk])
        except (guestportal.GuestPortalNonConfigurato, guestportal.GuestPortalNonRaggiungibile) as exc:
            raise ChioscoNonDisponibile from exc
        if not righe:
            return None
        r = righe[0]
        return {"origine": "gp", "id": pk, "nome": r.get("FirstName") or "", "cognome": r.get("LastName") or "",
                "email": r.get("Email") or "", "telefono": r.get("Phone") or "", "azienda": r.get("Company") or ""}
    return None


def cerca_ditte(testo: str) -> list[dict]:
    testo = (testo or "").strip().lower()
    if len(testo) < CERCA_MIN:
        return []
    elenco = cache.get(CACHE_AZIENDE)
    if elenco is None:
        elenco = aziende()
        cache.set(CACHE_AZIENDE, elenco, SECONDI_REFERENTI)
    inizio = [a for a in elenco if a["nome"].lower().startswith(testo)]
    dentro = [a for a in elenco if testo in a["nome"].lower() and a not in inizio]
    return (inizio + dentro)[:CERCA_MAX_DITTE]


def sembra_codice(testo: str) -> str:
    codice = re.sub(r"\s+", "", testo or "").upper()
    return codice if _CODICE.match(codice) else ""


def cartellini_in_uso() -> list[str] | None:
    """Numeri dei cartellini delle visite aperte, per uscire con un tocco. None = non si sa."""
    if nativa():
        from reception.models import Visita

        numeri = list(Visita.objects.filter(stato=Visita.DENTRO)
                      .exclude(cartellino=Visita.SENZA_CARTELLINO).values_list("cartellino", flat=True))
    else:
        from . import guestportal

        try:
            numeri = [a.badge for a in guestportal.presenti_ora()]
        except (guestportal.GuestPortalNonConfigurato, guestportal.GuestPortalNonRaggiungibile):
            return None
    puliti = {str(n).strip() for n in numeri if str(n).strip() and str(n).strip().upper() != "N/A"}
    return sorted(puliti, key=lambda n: (int(n) if n.isdigit() else 10**6, n))
