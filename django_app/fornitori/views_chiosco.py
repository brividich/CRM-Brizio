"""Pagina e API del chiosco (``/chiosco/``): senza login, solo dalle postazioni ammesse.

Prefisso in ``MIDDLEWARE_EXEMPT_PREFIXES``, view in ``PUBLIC_VIEWS``. A proteggere è l'elenco
``CHIOSCO_ALLOWED_IPS`` (IP o reti del PC della reception): vuoto = chiosco chiuso. MAI pubblicare
su Entra Application Proxy. Logica e motivazioni in ``fornitori/chiosco.py``.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core.net import client_ip
from core.public_headers import risposta_pubblica_con_form

from . import chiosco

logger = logging.getLogger(__name__)

MAX_CAMPO = 200
NON_DISPONIBILE = "Il sistema di registrazione non risponde. Rivolgiti alla reception."
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def postazione_ammessa(request) -> bool:
    """Stessa regola delle altre superfici a IP: ``client_ip`` e voci IP o CIDR. Vuoto = nessuno."""
    ip = client_ip(request)
    if not ip:
        return False
    try:
        indirizzo = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for voce in getattr(settings, "CHIOSCO_ALLOWED_IPS", []) or []:
        voce = str(voce).strip()
        if not voce:
            continue
        try:
            if "/" in voce:
                if indirizzo in ipaddress.ip_network(voce, strict=False):
                    return True
            elif indirizzo == ipaddress.ip_address(voce):
                return True
        except ValueError:
            logger.warning("CHIOSCO_ALLOWED_IPS: voce non valida %r", voce)
    return False


@require_GET
@risposta_pubblica_con_form
def pagina(request):
    if not postazione_ammessa(request):
        logger.warning("Chiosco: postazione non ammessa %s", client_ip(request))
        return render(request, "fornitori/chiosco/non_ammesso.html", status=403)
    referenti, disponibile = [], chiosco.configurato()
    # Nella pagina solo id, nome e reparto: l'email del referente resta sul server.
    if disponibile:
        try:
            referenti = [{"id": r["id"], "nome": r["nome"], "reparto": r["reparto"]} for r in chiosco.referenti()]
        except chiosco.ChioscoNonDisponibile:
            disponibile = False
    return render(request, "fornitori/chiosco/chiosco.html", {
        "referenti": referenti,
        "categorie": chiosco.categorie(),
        "disponibile": disponibile,
    })


def _testo(dati: dict, chiave: str) -> str:
    return str(dati.get(chiave) or "").strip()[:MAX_CAMPO]


def _intero(dati: dict, chiave: str) -> int | None:
    valore = str(dati.get(chiave) or "").strip()
    return int(valore) if valore.isdigit() else None


def _errore(testo: str, status: int = 200, **altro) -> JsonResponse:
    return JsonResponse({"success": False, "error": testo, **altro}, status=status)


def _ditta_non_in_regola(azienda: str, ditta_id: int | None = None) -> bool:
    """Interruttore in Reception → Impostazioni, spento di default. Non deve mai fermare un ingresso."""
    from core.models import SiteConfig

    if not azienda or SiteConfig.get("chiosco_avviso_requisiti", "0") != "1":
        return False
    try:
        from .guestportal import Accesso
        from .requisiti import ESITO_NON_IN_REGOLA, abbina_fornitori, stati_per_fornitori

        accesso = Accesso(0, "", "", "", azienda, "", "", "", None, None, ditta_gp_id=ditta_id)
        abbina_fornitori([accesso])
        if not accesso.fornitore_id:
            return False
        stato = stati_per_fornitori([accesso.fornitore_id]).get(accesso.fornitore_id)
        return bool(stato and stato.esito == ESITO_NON_IN_REGOLA)
    except Exception:  # noqa: BLE001
        logger.exception("Chiosco: controllo dei requisiti della ditta fallito")
        return False


def _esito_ingresso(stato: int, esito: dict, azienda: str = "", ditta_id: int | None = None) -> JsonResponse:
    """Esito di un check-in: solo i dati per lo schermo. Gli errori tecnici del GuestPortal
    e il nome di chi usa già un'email non arrivano al visitatore."""
    if esito.get("success"):
        risposta = {"success": True, "badge_number": esito.get("badge_number"),
                    "guest_name": esito.get("guest_name"), "host_employee": esito.get("host_employee")}
        if _ditta_non_in_regola(azienda, ditta_id):
            risposta["passa_reception"] = True
        return JsonResponse(risposta)
    if esito.get("already_in"):
        return _errore("Sei già registrato come presente in azienda.", already_in=True)
    if esito.get("no_badges"):
        return _errore("Nessun cartellino disponibile.", no_badges=True)
    if esito.get("email_conflict"):
        return _errore("Questa email è già associata a un'altra persona: usane una diversa o lasciala vuota.")
    if stato == 422 or stato == 200:
        return _errore("Controlla i dati inseriti e riprova." if stato == 422 else (esito.get("error") or NON_DISPONIBILE))
    logger.warning("Chiosco: check-in non riuscito, HTTP %s", stato)
    return _errore(NON_DISPONIBILE)


def _ospite(dati: dict) -> JsonResponse:
    email = _testo(dati, "email").lower()
    if not _EMAIL.match(email):
        return JsonResponse({"found": False})
    _stato, esito = chiosco.chiama("guest_lookup", {"email": email})
    if not esito.get("found"):
        return JsonResponse({"found": False})
    ospite = esito.get("guest") or {}
    return JsonResponse({"found": True, "guest": {
        "first_name": ospite.get("FirstName") or "", "last_name": ospite.get("LastName") or "",
        "email": ospite.get("Email") or "", "phone": ospite.get("Phone") or "", "company": ospite.get("Company") or "",
    }})


def _ingresso(dati: dict, ip: str) -> JsonResponse:
    if dati.get("gdpr_consent") is not True:
        return _errore("Per continuare conferma di aver letto l'informativa.")
    host = chiosco.referente(_intero(dati, "referente_id"))
    motivo = _testo(dati, "motivo")
    if host is None:
        return _errore("Scegli il dipendente che vieni a trovare.")
    if motivo not in {c["nome"] for c in chiosco.categorie()}:
        return _errore("Scegli il motivo della visita.")
    nome, cognome = _testo(dati, "first_name"), _testo(dati, "last_name")
    if not nome or not cognome:
        return _errore("Nome e cognome sono obbligatori.")
    email = _testo(dati, "email").lower()
    if email and not _EMAIL.match(email):
        return _errore("L'indirizzo email non è valido.")
    stato, esito = chiosco.chiama("checkin_submit", {
        "first_name": nome, "last_name": cognome, "email": email, "phone": _testo(dati, "phone"),
        "company": _testo(dati, "company"), "host_employee": host["nome"], "host_email": host["email"],
        "purpose": motivo, "gdpr_consent": True,
    }, ip=ip)
    return _esito_ingresso(stato, esito, azienda=_testo(dati, "company"))


def _ingresso_fornitore(dati: dict, ip: str) -> JsonResponse:
    # Anche il fornitore accreditato legge l'informativa: il GuestPortal registra comunque ConsentGDPR=1.
    if dati.get("gdpr_consent") is not True:
        return _errore("Per continuare conferma di aver letto l'informativa.")
    azienda_id, nominativo_id = _intero(dati, "azienda_id"), _intero(dati, "nominativo_id")
    azienda = next((a for a in chiosco.aziende() if a["id"] == azienda_id), None)
    if azienda is None:
        return _errore("Scegli l'azienda.")
    persona = next((c for c in chiosco.nominativi(azienda["id"]) if c["id"] == nominativo_id), None)
    if persona is None:
        return _errore("Scegli il nominativo.")
    host = chiosco.referente(_intero(dati, "referente_id"))
    if host is None:
        return _errore("Scegli il referente interno.")
    stato, esito = chiosco.chiama("supplier_checkin", {
        "supplier_id": azienda["id"], "contact_id": persona["id"], "company_name": azienda["nome"],
        "first_name": persona["nome"], "last_name": persona["cognome"],
        "host_employee": host["nome"], "host_email": host["email"],
    }, ip=ip)
    return _esito_ingresso(stato, esito, azienda=azienda["nome"], ditta_id=azienda["id"])


def _cerca_uscita(dati: dict) -> JsonResponse:
    badge, codice = _testo(dati, "badge"), _testo(dati, "code").upper()
    if badge:
        richiesta = {"badge": badge.zfill(2)}
    elif len(codice) == 8:
        richiesta = {"code": codice}
    else:
        return _errore("Inserisci il numero del cartellino.")
    _stato, esito = chiosco.chiama("checkout_lookup", richiesta)
    visite = esito.get("visits") or []
    if not esito.get("success") or not visite:
        return _errore("Nessun check-in attivo trovato.")
    return JsonResponse({"success": True, "visits": [
        {k: v.get(k) for k in ("visit_id", "badge_number", "guest_name", "checkin_time")} for v in visite
    ]})


def _uscita(dati: dict) -> JsonResponse:
    visita, badge = _intero(dati, "visit_id"), _testo(dati, "badge")
    if not visita or not badge:
        return _errore("Dati mancanti.")
    _stato, esito = chiosco.chiama("checkout_submit", {"visit_id": visita, "badge": badge})
    if not esito.get("success"):
        return _errore("Check-out non riuscito: la visita è già conclusa o il cartellino non corrisponde.")
    return JsonResponse({"success": True, "duration": esito.get("duration") or ""})


def _prereg_cerca(dati: dict) -> JsonResponse:
    codice = _testo(dati, "code").upper()
    if len(codice) != 8:
        return _errore("Il codice deve avere 8 caratteri.")
    _stato, esito = chiosco.chiama("prereg_lookup", {"code": codice})
    if not esito.get("success"):
        return _errore("Codice non valido, scaduto o già utilizzato.")
    p = esito.get("prereg") or {}
    return JsonResponse({"success": True, "prereg": {
        "guest_name": p.get("guest_name") or "", "guest_company": p.get("guest_company") or "",
        "host_employee": p.get("host_employee") or "", "purpose": p.get("purpose") or "",
    }})


def _prereg_entra(dati: dict, ip: str) -> JsonResponse:
    codice = _testo(dati, "code").upper()
    if len(codice) != 8:
        return _errore("Il codice deve avere 8 caratteri.")
    if dati.get("gdpr_consent") is not True:
        return _errore("Per continuare conferma di aver letto l'informativa.")
    stato, esito = chiosco.chiama("prereg_checkin", {"code": codice}, ip=ip)
    if not esito.get("success") and stato == 200:
        return _errore("Codice non valido, scaduto o già utilizzato.")
    return _esito_ingresso(stato, esito)


def _aziende(_dati: dict) -> JsonResponse:
    return JsonResponse({"success": True, "aziende": chiosco.aziende()})


def _nominativi(dati: dict) -> JsonResponse:
    azienda_id = _intero(dati, "azienda_id")
    if azienda_id is None:
        return _errore("Scegli l'azienda.")
    return JsonResponse({"success": True, "nominativi": chiosco.nominativi(azienda_id)})


AZIONI = {
    "ospite": _ospite,
    "ingresso": _ingresso,
    "aziende": _aziende,
    "nominativi": _nominativi,
    "ingresso-fornitore": _ingresso_fornitore,
    "cerca-uscita": _cerca_uscita,
    "uscita": _uscita,
    "prereg-cerca": _prereg_cerca,
    "prereg-entra": _prereg_entra,
}


CON_IP = {_ingresso, _ingresso_fornitore, _prereg_entra}


@require_POST
@risposta_pubblica_con_form
def api(request, azione):
    if not postazione_ammessa(request):
        return _errore("Postazione non abilitata.", status=403)
    gestore = AZIONI.get(azione)
    if gestore is None:
        return _errore("Azione non valida.", status=404)
    try:
        dati = json.loads(request.body or b"{}")
    except ValueError:
        return _errore("Dati non validi.", status=400)
    if not isinstance(dati, dict):
        return _errore("Dati non validi.", status=400)
    try:
        if gestore in CON_IP:
            return gestore(dati, client_ip(request) or "")
        return gestore(dati)
    except chiosco.ChioscoNonDisponibile:
        return _errore(NON_DISPONIBILE, status=503)
