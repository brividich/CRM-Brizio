"""Step «Account portale» della creazione dipendente: ricerca utenti portale e account AD.

Endpoint AJAX (fetch dal wizard): risposte JSON 401/403 quando l'accesso manca, mai redirect HTML.
La ricerca AD è in sola lettura; la scelta viene rivalidata al submit da ``services.account_portale``.
"""
from __future__ import annotations

import re
import uuid

from django.contrib import messages
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from .services import account_portale

# Idempotenza della creazione: un token per form; il doppio submit trova il token già usato e
# porta alla scheda creata invece di creare un secondo dipendente.
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_TOKEN_TTL = 6 * 3600
_IN_CORSO = "in_corso"


def token_creazione(raw) -> str:
    raw = (raw or "").strip().lower()
    return raw if _TOKEN_RE.match(raw) else uuid.uuid4().hex


def _chiave(token: str) -> str:
    return f"anagrafica:dipendente_create:{token}"


def prenota_creazione(request, token: str):
    """None se la creazione può procedere, altrimenti la risposta per il submit duplicato."""
    if cache.add(_chiave(token), _IN_CORSO, _TOKEN_TTL):
        return None
    esistente = cache.get(_chiave(token))
    if isinstance(esistente, int) and esistente > 0:
        messages.info(request, "Il dipendente era già stato creato con questo modulo: nessun doppione.")
        return redirect("anagrafica:dipendente_detail", legacy_id=esistente)
    messages.warning(request, "La creazione di questo dipendente è già in corso: attendi qualche secondo e controlla l'elenco.")
    return redirect("anagrafica:dipendenti_list")


def completa_creazione(token: str, new_id: int) -> None:
    if new_id:
        cache.set(_chiave(token), int(new_id), _TOKEN_TTL)


def annulla_creazione(token: str) -> None:
    if cache.get(_chiave(token)) == _IN_CORSO:
        cache.delete(_chiave(token))


@require_GET
def account_portale_cerca(request):
    from .views import _is_anagrafica_admin

    if not getattr(request.user, "is_authenticated", False):
        return JsonResponse({"ok": False, "error": "Autenticazione richiesta."}, status=401)
    if not _is_anagrafica_admin(request):
        return JsonResponse({"ok": False, "error": "Non hai i permessi per creare dipendenti."}, status=403)

    email = (request.GET.get("email") or "").strip()[:200]
    nome = (request.GET.get("nome") or "").strip()[:100]
    cognome = (request.GET.get("cognome") or "").strip()[:100]
    codice_fiscale = (request.GET.get("codice_fiscale") or "").strip()[:16]
    portale = account_portale.cerca_utenti_portale(email=email, codice_fiscale=codice_fiscale)
    esito_ad = account_portale.cerca_ad(email=email, nome=nome, cognome=cognome)
    return render(request, "anagrafica/partials/_account_portale_risultati.html", {
        "portale": portale,
        "esito_ad": esito_ad,
        "ambiguo": esito_ad.stato == "ok" and len(esito_ad.risultati) > 1,
        "puo_confermare_privilegiati": bool(getattr(request.user, "is_superuser", False)),
        "cercato": bool(email or (nome and cognome) or codice_fiscale),
    })
