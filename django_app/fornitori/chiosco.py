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


# ─── Riconoscimento dal totem ─────────────────────────────────────────────────────────────
# Il visitatore scrive nome e cognome. Se qualcuno con esattamente quel nome è già venuto, il totem
# mostra solo la sua azienda e chiede conferma: più righe = omonimi. Nessun elenco di nomi né di
# aziende altrui. Il browser riceve una chiave firmata e a scadenza; nomi, email e telefono li
# rilegge il server al momento dell'ingresso.
RICONOSCI_MIN = 2
RICONOSCI_MAX = 5
CHIAVE_SALE = "chiosco.ospite"
CHIAVE_SECONDI = 900


def _giorni_conservazione() -> int:
    return max(30, int(getattr(settings, "RECEPTION_CONSERVAZIONE_MESI", 12) or 12) * 31)


def chiave(origine: str, tipo: str, pk: int, ditta: int | None = None) -> str:
    from django.core import signing

    return signing.dumps({"o": origine, "t": tipo, "id": int(pk), "d": ditta}, salt=CHIAVE_SALE, compress=True)


def _apri_chiave(valore: str, tipo: str) -> tuple[str, int, int | None] | None:
    from django.core import signing

    try:
        dati = signing.loads(valore or "", salt=CHIAVE_SALE, max_age=CHIAVE_SECONDI)
        if dati.get("t") != tipo:
            return None
        origine = str(dati["o"])
        if origine != ("hub" if nativa() else "gp"):
            return None
        return origine, int(dati["id"]), (int(dati["d"]) if dati.get("d") is not None else None)
    except (signing.BadSignature, KeyError, TypeError, ValueError, AttributeError):
        return None


def riconosci(nome: str, cognome: str) -> list[dict]:
    """Chi si chiama esattamente così: ``{chiave, tipo, azienda, referente, motivo}``.
    ``tipo`` è ``fornitore`` (nominativo di una ditta accreditata) o ``ospite`` (visitatore degli
    ultimi mesi, non anonimizzato). Prima i fornitori, poi gli ospiti dal più recente."""
    nome, cognome = (nome or "").strip()[:100], (cognome or "").strip()[:100]
    if len(nome) < RICONOSCI_MIN or len(cognome) < RICONOSCI_MIN:
        return []
    righe = _riconosci_hub(nome, cognome) if nativa() else _riconosci_gp(nome, cognome)
    return righe[:RICONOSCI_MAX]


def _riconosci_hub(nome: str, cognome: str) -> list[dict]:
    from datetime import timedelta

    from django.utils import timezone

    from reception.models import ContattoDitta, Visita

    righe = []
    for c in ContattoDitta.objects.select_related("ditta").filter(
            nome__iexact=nome, cognome__iexact=cognome, attivo=True, ditta__attiva=True)[:RICONOSCI_MAX]:
        ultima = Visita.objects.filter(contatto=c).order_by("-ingresso").first()
        righe.append({"chiave": chiave("hub", "fornitore", c.pk, c.ditta_id), "tipo": "fornitore", "azienda": c.ditta.nome,
                      "referente": ultima.referente_nome if ultima else "", "motivo": ""})
    visite = (Visita.objects.select_related("ospite")
              .filter(ospite__nome__iexact=nome, ospite__cognome__iexact=cognome, ospite__anonimizzato=False,
                      ingresso__gte=timezone.now() - timedelta(days=_giorni_conservazione()))
              .exclude(tipo=Visita.FORNITORE).order_by("-ingresso")[:50])
    visti = set()
    for v in visite:
        if v.ospite_id in visti:
            continue
        visti.add(v.ospite_id)
        righe.append({"chiave": chiave("hub", "ospite", v.ospite_id), "tipo": "ospite", "azienda": v.ospite.azienda,
                      "referente": v.referente_nome, "motivo": v.motivo})
    return righe


def _riconosci_gp(nome: str, cognome: str) -> list[dict]:
    from datetime import datetime, timedelta

    from . import guestportal

    if not guestportal.db_configurato():
        return []
    try:
        contatti = guestportal._esegui(
            "SELECT c.ContactID, c.SupplierID, s.CompanyName FROM SupplierContacts c"
            " JOIN Suppliers s ON s.SupplierID = c.SupplierID"
            " WHERE c.IsActive = 1 AND s.IsActive = 1 AND c.FirstName = %s AND c.LastName = %s LIMIT %s",
            [nome, cognome, RICONOSCI_MAX])
        ospiti = guestportal._esegui(
            "SELECT g.GuestID, g.Company, MAX(v.CheckInTime) AS Ultima FROM Guests g JOIN Visits v ON v.GuestID = g.GuestID"
            " WHERE g.IsAnonymized = 0 AND v.CheckInTime >= %s AND v.VisitType <> 'SUPPLIER'"
            " AND g.FirstName = %s AND g.LastName = %s GROUP BY g.GuestID, g.Company ORDER BY Ultima DESC LIMIT %s",
            [datetime.now() - timedelta(days=_giorni_conservazione()), nome, cognome, RICONOSCI_MAX])
        ultime_c: dict[int, dict] = {}
        ultime_o: dict[int, dict] = {}
        if contatti:
            ids = [int(c["ContactID"]) for c in contatti]
            for r in guestportal._esegui(
                    "SELECT ContactID, HostEmployee FROM Visits WHERE ContactID IN (" + ",".join(["%s"] * len(ids)) + ")"
                    " ORDER BY CheckInTime DESC", ids):
                ultime_c.setdefault(int(r["ContactID"]), r)
        if ospiti:
            ids = [int(o["GuestID"]) for o in ospiti]
            for r in guestportal._esegui(
                    "SELECT GuestID, HostEmployee, Purpose FROM Visits WHERE GuestID IN (" + ",".join(["%s"] * len(ids)) + ")"
                    " ORDER BY CheckInTime DESC", ids):
                ultime_o.setdefault(int(r["GuestID"]), r)
    except (guestportal.GuestPortalNonConfigurato, guestportal.GuestPortalNonRaggiungibile):
        return []
    righe = [{"chiave": chiave("gp", "fornitore", int(c["ContactID"]), int(c["SupplierID"])), "tipo": "fornitore",
              "azienda": (c.get("CompanyName") or "").strip(),
              "referente": (ultime_c.get(int(c["ContactID"])) or {}).get("HostEmployee") or "", "motivo": ""}
             for c in contatti]
    for o in ospiti:
        ultima = ultime_o.get(int(o["GuestID"])) or {}
        righe.append({"chiave": chiave("gp", "ospite", int(o["GuestID"])), "tipo": "ospite",
                      "azienda": (o.get("Company") or "").strip(), "referente": ultima.get("HostEmployee") or "",
                      "motivo": ultima.get("Purpose") or ""})
    return righe


def ospite_da_chiave(valore: str) -> dict | None:
    """Dati completi dell'ospite confermato al totem: ``{origine, id, nome, cognome, email, telefono, azienda}``."""
    aperta = _apri_chiave(valore, "ospite")
    if aperta is None:
        return None
    origine, pk, _ditta = aperta
    if origine == "hub":
        from reception.models import Ospite

        o = Ospite.objects.filter(pk=pk, anonimizzato=False).first()
        if o is None:
            return None
        return {"origine": "hub", "id": o.pk, "nome": o.nome, "cognome": o.cognome, "email": o.email,
                "telefono": o.telefono, "azienda": o.azienda}
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


def fornitore_da_chiave(valore: str) -> tuple[int, int] | None:
    """``(azienda_id, nominativo_id)`` del fornitore confermato al totem."""
    aperta = _apri_chiave(valore, "fornitore")
    if aperta is None or aperta[2] is None:
        return None
    return aperta[2], aperta[1]


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


# ─── Suggerimenti mentre si scrive cognome e nome ─────────────────────────────────────────
# Dalla terza lettera: cognomi presenti (visitatori nel periodo di conservazione, nominativi delle
# ditte accreditate); per il nome, solo i nomi di chi ha quel cognome. Mai aziende né altri dati.
SUGGERISCI_MIN = 3
SUGGERISCI_MAX = 6


def _like(testo: str) -> str:
    return testo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _unici(valori) -> list[str]:
    visti, uscita = set(), []
    for v in valori:
        v = (v or "").strip()
        if v and v.lower() not in visti:
            visti.add(v.lower())
            uscita.append(v)
    return sorted(uscita, key=str.lower)[:SUGGERISCI_MAX]


def suggerisci(campo: str, testo: str, cognome: str = "") -> list[str]:
    testo, cognome = (testo or "").strip()[:100], (cognome or "").strip()[:100]
    if campo not in ("cognome", "nome") or len(testo) < SUGGERISCI_MIN or (campo == "nome" and not cognome):
        return []
    if nativa():
        return _suggerisci_hub(campo, testo, cognome)
    return _suggerisci_gp(campo, testo, cognome)


def _suggerisci_hub(campo: str, testo: str, cognome: str) -> list[str]:
    from datetime import timedelta

    from django.utils import timezone

    from reception.models import ContattoDitta, Ospite

    ospiti = Ospite.objects.filter(anonimizzato=False, visite__ingresso__gte=timezone.now() - timedelta(days=_giorni_conservazione()))
    contatti = ContattoDitta.objects.filter(attivo=True, ditta__attiva=True)
    filtro = {f"{campo}__istartswith": testo}
    if campo == "nome":
        filtro["cognome__iexact"] = cognome
    valori = list(ospiti.filter(**filtro).values_list(campo, flat=True).distinct()[:50])
    valori += list(contatti.filter(**filtro).values_list(campo, flat=True).distinct()[:50])
    return _unici(valori)


def _suggerisci_gp(campo: str, testo: str, cognome: str) -> list[str]:
    from datetime import datetime, timedelta

    from . import guestportal

    if not guestportal.db_configurato():
        return []
    colonna = "LastName" if campo == "cognome" else "FirstName"
    extra_g, extra_c, params_g, params_c = "", "", [], []
    if campo == "nome":
        extra_g, extra_c, params_g, params_c = " AND g.LastName = %s", " AND c.LastName = %s", [cognome], [cognome]
    sql = (f"SELECT DISTINCT g.{colonna} AS v FROM Guests g JOIN Visits v ON v.GuestID = g.GuestID"
           f" WHERE g.IsAnonymized = 0 AND v.CheckInTime >= %s AND g.{colonna} LIKE %s{extra_g}"
           f" UNION SELECT DISTINCT c.{colonna} FROM SupplierContacts c JOIN Suppliers s ON s.SupplierID = c.SupplierID"
           f" WHERE c.IsActive = 1 AND s.IsActive = 1 AND c.{colonna} LIKE %s{extra_c} LIMIT 50")
    params = [datetime.now() - timedelta(days=_giorni_conservazione()), _like(testo), *params_g, _like(testo), *params_c]
    try:
        righe = guestportal._esegui(sql, params)
    except (guestportal.GuestPortalNonConfigurato, guestportal.GuestPortalNonRaggiungibile):
        return []
    return _unici(r.get("v") for r in righe)


# ─── Logo del chiosco (Reception → Impostazioni) ──────────────────────────────────────────
CHIAVE_LOGO = "chiosco_logo"
LOGO_ESTENSIONI = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
LOGO_MAX_BYTE = 1024 * 1024
LOGO_CARTELLA = "reception"


def logo_percorso() -> str:
    """Percorso nello storage del logo caricato, o vuoto. Valore SiteConfig: ``percorso|versione``."""
    from core.models import SiteConfig

    return (SiteConfig.get(CHIAVE_LOGO, "") or "").split("|", 1)[0]


def logo_versione() -> str:
    from core.models import SiteConfig

    parti = (SiteConfig.get(CHIAVE_LOGO, "") or "").split("|", 1)
    return parti[1] if len(parti) == 2 else ""
