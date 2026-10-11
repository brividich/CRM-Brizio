"""Account portale del dipendente: step 3 del wizard di creazione e riquadro della scheda.

Endpoint AJAX (fetch dal wizard e dalla scheda): risposte JSON 401/403 quando l'accesso manca, mai
redirect HTML. La ricerca AD è in sola lettura; la scelta viene rivalidata al submit da
``services.account_portale``. Il riquadro «Account portale» della scheda collega o scollega l'utente
di una scheda già esistente con le stesse regole del wizard (email e CF letti dal DB, mai dal POST).
"""
from __future__ import annotations

import re
import uuid

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .services import account_portale

# Idempotenza della creazione: un token per form; il doppio submit trova il token già usato e
# porta alla scheda creata invece di creare un secondo dipendente.
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_TOKEN_TTL = 6 * 3600
_IN_CORSO = "in_corso"


def token_creazione(raw) -> str:
    raw = (raw or "").strip().lower()
    return raw if _TOKEN_RE.match(raw) else uuid.uuid4().hex


def _chiave(token: str, user_id=None) -> str:
    return f"anagrafica:dipendente_create:{user_id}:{token}"


def prenota_creazione(request, token: str):
    """None se la creazione può procedere, altrimenti la risposta per il submit duplicato."""
    chiave = _chiave(token, request.user.pk)
    if cache.add(chiave, _IN_CORSO, _TOKEN_TTL):
        return None
    esistente = cache.get(chiave)
    if isinstance(esistente, int) and esistente > 0:
        messages.info(request, "Il dipendente era già stato creato con questo modulo: nessun doppione.")
        return redirect("anagrafica:dipendente_detail", legacy_id=esistente)
    messages.warning(request, "La creazione di questo dipendente è già in corso: attendi qualche secondo e controlla l'elenco.")
    return redirect("anagrafica:dipendenti_list")


def completa_creazione(request, token: str, new_id: int) -> None:
    if new_id:
        cache.set(_chiave(token, request.user.pk), int(new_id), _TOKEN_TTL)


def annulla_creazione(request, token: str) -> None:
    chiave = _chiave(token, request.user.pk)
    if cache.get(chiave) == _IN_CORSO:
        cache.delete(chiave)


@require_POST
def account_portale_cerca(request):
    from .views import _is_anagrafica_admin

    if not getattr(request.user, "is_authenticated", False):
        return JsonResponse({"ok": False, "error": "Autenticazione richiesta."}, status=401)
    if not _is_anagrafica_admin(request):
        return JsonResponse({"ok": False, "error": "Non hai i permessi per gestire gli account portale dei dipendenti."}, status=403)

    email = (request.POST.get("email") or "").strip()[:200]
    nome = (request.POST.get("nome") or "").strip()[:100]
    cognome = (request.POST.get("cognome") or "").strip()[:100]
    codice_fiscale = (request.POST.get("codice_fiscale") or "").strip()[:16]
    portale = account_portale.cerca_utenti_portale(email=email, codice_fiscale=codice_fiscale)
    esito_ad = account_portale.cerca_ad(email=email, nome=nome, cognome=cognome)
    return render(request, "anagrafica/partials/_account_portale_risultati.html", {
        "portale": portale,
        "esito_ad": esito_ad,
        "ambiguo": esito_ad.stato == "ok" and len(esito_ad.risultati) > 1,
        "puo_confermare_privilegiati": bool(getattr(request.user, "is_superuser", False)),
        "cercato": bool(email or (nome and cognome) or codice_fiscale),
        "da_scheda": request.POST.get("contesto") == "scheda",
    })


# ── Riquadro «Account portale» della scheda dipendente ───────────────────────

def _dati_scheda(legacy_id: int) -> dict | None:
    """Dati della scheda letti dal DB: sono questi, non il POST, a decidere cosa si può collegare."""
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from .models import DipendenteAnagraficaCivile

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        return None
    dip = rows[0]
    cf = (DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id)
          .values_list("codice_fiscale", flat=True).first() or "")
    nome = str(dip.get("nome") or "").strip()
    cognome = str(dip.get("cognome") or "").strip()
    return {
        "id": int(dip["id"]),
        "nome": nome,
        "cognome": cognome,
        "nome_completo": naming.nome_completo(nome, cognome),
        "email": str(dip.get("email_notifica") or dip.get("email") or "").strip(),
        "codice_fiscale": str(cf).strip().upper(),
        "alias": str(dip.get("aliasusername") or "").strip(),
        "attivo": dip.get("attivo") not in {0, False, "0"},
        "utente_id": int(dip.get("utente_id") or 0) or None,
    }


def contesto_scheda(request, legacy_id: int) -> dict | None:
    """Contesto del riquadro per la scheda; None se l'operatore non amministra l'anagrafica."""
    from core.legacy_models import UtenteLegacy

    from .views import _is_anagrafica_admin

    if not _is_anagrafica_admin(request):
        return None
    dati = _dati_scheda(legacy_id)
    if dati is None:
        return None
    collegato = None
    if dati["utente_id"]:
        legacy = UtenteLegacy.objects.filter(pk=dati["utente_id"]).first()
        collegato = {
            "id": dati["utente_id"],
            "trovato": legacy is not None,
            "login": (legacy.email or "") if legacy else "",
            "nome": (legacy.nome or "") if legacy else "",
            "ad": bool(legacy) and (legacy.password or "") == account_portale.AD_MANAGED,
            "attivo": bool(legacy.attivo) if legacy else False,
        }
    return {
        "dati": dati,
        "collegato": collegato,
        "puo_confermare_privilegiati": bool(getattr(request.user, "is_superuser", False)),
    }


def _is_ajax(request) -> bool:
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _cancello_scheda(request, legacy_id: int):
    """None se l'operatore può gestire l'account della scheda, altrimenti la risposta di rifiuto."""
    from .views import _is_anagrafica_admin

    if not getattr(request.user, "is_authenticated", False):
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": "Autenticazione richiesta."}, status=401)
        return redirect_to_login(request.get_full_path())
    if not _is_anagrafica_admin(request):
        testo = "Non hai i permessi per gestire l'account portale del dipendente."
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": testo}, status=403)
        messages.error(request, testo)
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    return None


def _esito(request, legacy_id: int, livello: str, testo: str, *, ok: bool):
    if _is_ajax(request):
        return JsonResponse({"ok": ok, "livello": livello, "messaggio": testo}, status=200 if ok else 400)
    getattr(messages, livello)(request, testo)
    return redirect(reverse("anagrafica:dipendente_detail", kwargs={"legacy_id": legacy_id}) + "#account-portale")


@require_POST
def dipendente_account_portale(request, legacy_id: int):
    """Collega un account portale a una scheda esistente ancora senza utente (stesse regole del wizard)."""
    rifiuto = _cancello_scheda(request, legacy_id)
    if rifiuto is not None:
        return rifiuto
    dati = _dati_scheda(legacy_id)
    if dati is None:
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": "Dipendente non trovato."}, status=404)
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    if dati["utente_id"]:
        return _esito(request, legacy_id, "error",
                      "La scheda ha già un account portale collegato: scollegalo prima di collegarne un altro.", ok=False)
    scelta = account_portale.scelta_da_post(request.POST)
    errori = account_portale.valida_scelta(
        request, scelta, email=dati["email"], codice_fiscale=dati["codice_fiscale"], attivo=dati["attivo"],
        scheda_id=legacy_id,
    )
    if errori:
        return _esito(request, legacy_id, "error", " ".join(errori), ok=False)
    livello, testo = account_portale.applica_scelta(request, legacy_id, scelta, nome_completo=dati["nome_completo"],
                                                    da_scheda=True)
    return _esito(request, legacy_id, livello, testo, ok=livello == "success")


@require_POST
def dipendente_account_scollega(request, legacy_id: int):
    """Scollega l'utente portale dalla scheda (``utente_id = NULL``, audit): l'utente non si cancella."""
    rifiuto = _cancello_scheda(request, legacy_id)
    if rifiuto is not None:
        return rifiuto
    if request.POST.get("conferma") != "1":
        return _esito(request, legacy_id, "error", "Conferma lo scollegamento dell'account portale.", ok=False)
    livello, testo = account_portale.scollega(request, legacy_id)
    return _esito(request, legacy_id, livello, testo, ok=livello == "success")
