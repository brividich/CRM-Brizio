"""Notifiche push: service worker e API del browser (vedi ``core.push``).

Tutte le API sono per l'utente collegato e rispondono JSON (401 senza sessione):
iscrizione/revoca del dispositivo, prova, e lettura dell'ultima notifica per il
service worker. Stanno sotto ``/api/notifiche/`` (percorso condiviso ACL: ogni
utente gestisce solo i propri dispositivi e legge solo le proprie notifiche).
"""
from __future__ import annotations

import json
import logging

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action

logger = logging.getLogger(__name__)

_MAX_DISPOSITIVI = 10
_PROVA_KEY = "push_prova:{}"
_PROVA_TTL = 90  # secondi: il tempo che il segnale arrivi ai dispositivi


def _non_autenticato(request) -> JsonResponse | None:
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return JsonResponse({"ok": False, "reason": "unauthenticated"}, status=401)
    return None


def _url_interno(url: str) -> str:
    url = str(url or "").strip()
    if url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return "/notifiche/"


def _dispositivo(request) -> str:
    ua = str(request.META.get("HTTP_USER_AGENT", "") or "")
    for nome in ("Edg/", "Chrome/", "Firefox/", "Safari/"):
        if nome in ua:
            browser = {"Edg/": "Edge", "Chrome/": "Chrome", "Firefox/": "Firefox", "Safari/": "Safari"}[nome]
            break
    else:
        browser = "Browser"
    if "Android" in ua:
        sistema = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        sistema = "iPhone/iPad"
    elif "Windows" in ua:
        sistema = "Windows"
    elif "Mac OS" in ua:
        sistema = "Mac"
    else:
        sistema = ""
    return f"{browser} su {sistema}".strip() if sistema else browser


@require_GET
def service_worker(request):
    """Il service worker deve stare alla radice per poter controllare tutto il
    portale: la view lo serve con ``Service-Worker-Allowed: /``."""
    from core.branding import get_portal_branding

    try:
        icona = get_portal_branding().brand_favicon or ""
    except Exception:
        icona = ""
    body = render_to_string("core/push/sw-notifiche.js", {"icona": icona})
    resp = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp


@require_POST
def api_push_iscrizione(request):
    from core.models import PushIscrizione
    from core.push import endpoint_ammesso, endpoint_hash, push_configurato

    denied = _non_autenticato(request)
    if denied:
        return denied
    if not push_configurato():
        return JsonResponse({"ok": False, "reason": "push_non_configurate"}, status=409)
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "reason": "json_non_valido"}, status=400)
    endpoint = str((data or {}).get("endpoint") or "").strip()
    if not endpoint or len(endpoint) > 2000 or not endpoint_ammesso(endpoint):
        return JsonResponse({"ok": False, "reason": "endpoint_non_ammesso"}, status=400)

    digest = endpoint_hash(endpoint)
    iscrizione = PushIscrizione.objects.filter(endpoint_hash=digest).first()
    if iscrizione and iscrizione.user_id != request.user.id:
        # Stesso browser passato a un altro utente: l'iscrizione segue chi è collegato ora.
        iscrizione.delete()
        iscrizione = None
    if iscrizione is None:
        if PushIscrizione.objects.filter(user=request.user, attiva=True).count() >= _MAX_DISPOSITIVI:
            return JsonResponse({"ok": False, "reason": "troppi_dispositivi"}, status=409)
        iscrizione = PushIscrizione.objects.create(
            user=request.user, endpoint=endpoint, endpoint_hash=digest, dispositivo=_dispositivo(request),
        )
        log_action(request, "push_iscrizione", "core", {"id": iscrizione.id, "dispositivo": iscrizione.dispositivo})
    else:
        iscrizione.attiva = True
        iscrizione.errori_consecutivi = 0
        iscrizione.dispositivo = _dispositivo(request)
        iscrizione.save(update_fields=["attiva", "errori_consecutivi", "dispositivo"])
    return JsonResponse({"ok": True, "id": iscrizione.id})


@require_POST
def api_push_revoca(request):
    """Toglie un dispositivo: per endpoint (dal browser stesso) o per id (dalla lista)."""
    from core.models import PushIscrizione
    from core.push import endpoint_hash

    denied = _non_autenticato(request)
    if denied:
        return denied
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "reason": "json_non_valido"}, status=400)
    qs = PushIscrizione.objects.filter(user=request.user)
    if data.get("endpoint"):
        qs = qs.filter(endpoint_hash=endpoint_hash(str(data["endpoint"])))
    elif data.get("id"):
        try:
            qs = qs.filter(pk=int(data["id"]))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "reason": "id_non_valido"}, status=400)
    else:
        return JsonResponse({"ok": False, "reason": "manca_dispositivo"}, status=400)
    tolte, _ = qs.delete()
    if tolte:
        log_action(request, "push_revoca", "core", {"tolte": tolte})
    return JsonResponse({"ok": True, "tolte": tolte})


@require_POST
def api_push_prova(request):
    from core.models import PushIscrizione
    from core.push import invia_push_utente, push_configurato

    denied = _non_autenticato(request)
    if denied:
        return denied
    if not push_configurato():
        return JsonResponse({"ok": False, "reason": "push_non_configurate"}, status=409)
    if not PushIscrizione.objects.filter(user=request.user, attiva=True).exists():
        return JsonResponse({"ok": False, "reason": "nessun_dispositivo"}, status=409)
    # Per utente, non per sessione: il telefono che riceve la prova ha la sua.
    cache.set(_PROVA_KEY.format(request.user.id), True, _PROVA_TTL)
    ok = invia_push_utente(request.user.id)
    return JsonResponse({"ok": ok > 0, "inviate": ok})


@require_GET
def api_push_ultime(request):
    """Cosa mostrare quando arriva il segnale: l'ultima notifica non letta.

    Letta dal service worker con la sessione dell'utente; non segna niente come
    letto e non cambia lo stato del popup in pagina."""
    from core.models import Notifica
    from core.notifiche_meta import notifica_meta
    from core.views import _current_legacy_user_id

    denied = _non_autenticato(request)
    if denied:
        return denied
    if cache.get(_PROVA_KEY.format(request.user.id)):
        return JsonResponse({
            "ok": True, "titolo": "NOVICROM HUB · prova",
            "messaggio": "Le notifiche push funzionano su questo dispositivo.",
            "url": "/notifiche/impostazioni/", "non_lette": 0,
        })
    legacy_user_id = _current_legacy_user_id(request)
    if not legacy_user_id:
        return JsonResponse({"ok": False, "reason": "utente_non_trovato"}, status=403)
    qs = Notifica.objects.filter(legacy_user_id=legacy_user_id, archiviata=False, letta=False)
    ultima = qs.order_by("-created_at", "-id").first()
    if ultima is None:
        return JsonResponse({"ok": True, "titolo": "NOVICROM HUB", "messaggio": "Nessuna notifica nuova.",
                             "url": "/notifiche/", "non_lette": 0})
    meta = notifica_meta(ultima.tipo)
    non_lette = qs.count()
    messaggio = ultima.messaggio
    if non_lette > 1:
        messaggio = f"{messaggio} (+{non_lette - 1} altre)"
    return JsonResponse({
        "ok": True,
        "titolo": f"{meta['icona']} {meta['label']}",
        "messaggio": messaggio,
        "url": _url_interno(ultima.url_azione),
        "non_lette": non_lette,
    })
