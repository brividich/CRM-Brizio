"""Accessi da un dispositivo nuovo (browser/PC mai usato dalla persona).

A ogni login (segnale ``user_logged_in``: password, login Windows, LDAP) il
portale cerca il cookie firmato ``nh_dev`` del browser. Se manca o non è di
questa persona, il dispositivo è **nuovo**: viene registrato in
``DispositivoAccesso`` e il browser riceve un cookie nuovo (lo scrive
``DispositivoCookieMiddleware``, perché il segnale non ha la risposta).

Per un dispositivo nuovo, se la persona ne aveva già almeno uno:

- notifica alla persona, categoria «Sicurezza dell'account» (campanella e push
  secondo le sue Impostazioni notifiche) e mail se ``sicurezza_mail`` è acceso;
- evento ``accesso_nuovo_dispositivo`` nel SOC (sorgente «Portale · accessi»),
  solo KPI.

Il primo dispositivo in assoluto si registra senza avvisi (altrimenti, al primo
avvio della funzione, tutti riceverebbero un avviso). Dalla pagina Impostazioni
notifiche la persona vede i suoi accessi e con «Non ero io» chiude la sessione
di quel dispositivo e apre un alert alto nel SOC.

Con la policy 2FA «Da rete esterna e da dispositivi nuovi» il codice si chiede
dalla rete interna solo se il browser non è **fidato**: fidato = la persona ci ha
superato il secondo fattore negli ultimi ``FIDUCIA_2FA_GIORNI`` giorni e non l'ha
segnalato con «Non ero io».

Nel cookie c'è solo un numero casuale: nel database se ne tiene l'impronta
SHA-256, mai il valore.
"""
from __future__ import annotations

import hashlib
import logging
import secrets

from django.core import signing
from django.utils import timezone

logger = logging.getLogger(__name__)

COOKIE = "nh_dev"
COOKIE_SALT = "core.dispositivi"
COOKIE_ANNI = 2
EVENTO_NUOVO = "accesso_nuovo_dispositivo"
EVENTO_NON_RICONOSCIUTO = "accesso_non_riconosciuto"
FONTE_SOC = "Portale · accessi"  # = core.eventi_sicurezza.FONTE_SOC
FIDUCIA_2FA_GIORNI = 90
_SESSIONE_FIDATO = "twofa_dispositivo_fidato"


def _impronta(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def etichetta(user_agent: str) -> str:
    """«Chrome su Windows», «Safari su iPhone»… dal solo user agent."""
    ua = str(user_agent or "")
    if "Edg/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Chrome/" in ua or "CriOS/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = "Browser"
    if "iPhone" in ua:
        sistema = "iPhone"
    elif "iPad" in ua:
        sistema = "iPad"
    elif "Android" in ua:
        sistema = "Android"
    elif "Windows" in ua:
        sistema = "Windows"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        sistema = "Mac"
    elif "Linux" in ua:
        sistema = "Linux"
    else:
        sistema = "sistema sconosciuto"
    return f"{browser} su {sistema}"


def _ip(request) -> str:
    try:
        from core.audit import _get_client_ip

        return str(_get_client_ip(request) or "")[:60]
    except Exception:  # noqa: BLE001
        return str(request.META.get("REMOTE_ADDR") or "")[:60]


def _token_dal_cookie(request) -> str:
    grezzo = request.COOKIES.get(COOKIE, "")
    if not grezzo:
        return ""
    try:
        return signing.loads(grezzo, salt=COOKIE_SALT, max_age=COOKIE_ANNI * 366 * 86400)
    except signing.BadSignature:
        return ""


def dispositivo_fidato(request, user) -> bool:
    """True se questo browser ha superato il 2FA della persona da meno di ``FIDUCIA_2FA_GIORNI``."""
    from datetime import timedelta

    from core.models import DispositivoAccesso

    token = _token_dal_cookie(request) if request is not None else ""
    if not token or not getattr(user, "pk", None):
        return False
    impronta = _impronta(token)
    sessione = getattr(request, "session", None)
    if sessione is not None and sessione.get(_SESSIONE_FIDATO) == impronta:
        return True
    fidato = DispositivoAccesso.objects.filter(
        user=user, token_hash=impronta, non_riconosciuto=False,
        verificato_2fa_il__gte=timezone.now() - timedelta(days=FIDUCIA_2FA_GIORNI),
    ).exists()
    if fidato and sessione is not None:
        sessione[_SESSIONE_FIDATO] = impronta
    return fidato


def segna_verificato(request, user) -> None:
    """Il secondo fattore è stato superato da questo browser: diventa fidato."""
    from core.models import DispositivoAccesso

    token = _token_dal_cookie(request)
    if not token or not getattr(user, "pk", None):
        return
    DispositivoAccesso.objects.filter(user=user, token_hash=_impronta(token), non_riconosciuto=False).update(
        verificato_2fa_il=timezone.now())


def registra_accesso(request, user) -> dict:
    """Chiamato al login. Ritorna ``{"nuovo": bool, "avvisato": bool, "dispositivo": id}``."""
    from core.models import DispositivoAccesso

    if request is None or user is None or not getattr(user, "pk", None):
        return {"nuovo": False, "avvisato": False}
    if getattr(request, "impersonation_active", False):
        return {"nuovo": False, "avvisato": False}  # un amministratore che impersona: non è un accesso della persona
    ora = timezone.now()
    ua = str(request.META.get("HTTP_USER_AGENT") or "")[:300]
    ip = _ip(request)
    session_key = getattr(getattr(request, "session", None), "session_key", "") or ""
    token = _token_dal_cookie(request)
    disp = DispositivoAccesso.objects.filter(user=user, token_hash=_impronta(token)).first() if token else None
    if disp is not None:
        disp.ultimo_accesso, disp.ip_ultimo, disp.session_key = ora, ip, session_key
        disp.user_agent = ua or disp.user_agent
        disp.save(update_fields=["ultimo_accesso", "ip_ultimo", "session_key", "user_agent"])
        return {"nuovo": False, "avvisato": False, "dispositivo": disp.pk}
    aveva_dispositivi = DispositivoAccesso.objects.filter(user=user).exists()
    token = token or secrets.token_urlsafe(32)
    disp = DispositivoAccesso.objects.create(
        user=user, token_hash=_impronta(token), etichetta=etichetta(ua), user_agent=ua,
        ip_primo=ip, ip_ultimo=ip, primo_accesso=ora, ultimo_accesso=ora, session_key=session_key,
    )
    request._nh_dev_cookie = signing.dumps(token, salt=COOKIE_SALT)
    if not aveva_dispositivi:
        return {"nuovo": True, "avvisato": False, "dispositivo": disp.pk}
    try:
        avvisa(user, disp)
    except Exception:  # noqa: BLE001 - un avviso non riuscito non blocca il login
        logger.exception("Dispositivo nuovo: avviso non inviato (user %s)", user.pk)
    return {"nuovo": True, "avvisato": True, "dispositivo": disp.pk}


def _legacy_id(user) -> int | None:
    try:
        from core.legacy_utils import get_legacy_user

        lu = get_legacy_user(user)
        return int(lu.id) if lu else None
    except Exception:  # noqa: BLE001
        return None


def avvisa(user, disp) -> None:
    from core.models import NotificaCanali
    from core.notifiche import invia_notifica

    quando = timezone.localtime(disp.primo_accesso)
    testo = (f"Nuovo accesso al portale da {disp.etichetta} (IP {disp.ip_primo or 'sconosciuto'}) "
             f"il {quando:%d/%m/%Y} alle {quando:%H:%M}. Se non eri tu, apri la notifica e premi «Non ero io».")
    url = "/notifiche/impostazioni/#ni-accessi"
    legacy_id = _legacy_id(user)
    if legacy_id:
        invia_notifica(legacy_id, EVENTO_NUOVO, testo, url)
    canali = NotificaCanali.objects.filter(user=user).first()
    if canali is None or canali.sicurezza_mail:
        _mail(user, testo)
    evento_soc(EVENTO_NUOVO, user, disp)


def _mail(user, testo: str) -> None:
    from core.email_utils import send_hub_mail
    from dashboard.scadenze_digest import _email_utente

    email = _email_utente(user)
    if email:
        send_hub_mail("Nuovo accesso al portale da un dispositivo", testo, [email],
                      title="Accesso da un nuovo dispositivo", email_type="Sicurezza")


def evento_soc(tipo: str, user, disp) -> None:
    """Evento nel SOC (canale unico ``core.eventi_sicurezza``): uno per persona e dispositivo."""
    from core.eventi_sicurezza import segnala

    segnala(tipo, utente=user, chiave=(user.pk, disp.pk), una_volta=True,
            extra={"dispositivo": disp.etichetta, "ip": disp.ip_ultimo or disp.ip_primo,
                   "primo_accesso": disp.primo_accesso.isoformat()})


def non_ero_io(request, disp) -> None:
    """La persona non riconosce l'accesso: chiude quella sessione e avvisa il SOC."""
    from django.contrib.sessions.models import Session

    from core.audit import log_action

    if disp.session_key and disp.session_key != getattr(request.session, "session_key", None):
        Session.objects.filter(session_key=disp.session_key).delete()
    disp.non_riconosciuto = True
    disp.segnalato_il = timezone.now()
    disp.save(update_fields=["non_riconosciuto", "segnalato_il"])
    evento_soc(EVENTO_NON_RICONOSCIUTO, request.user, disp)  # valutato subito: l'alert si apre ora
    log_action(request, "accesso_non_riconosciuto", "core",
               {"dispositivo": disp.etichetta, "ip": disp.ip_ultimo, "dispositivo_id": disp.pk})


class DispositivoCookieMiddleware:
    """Scrive il cookie del dispositivo deciso in ``registra_accesso`` (il segnale non ha la risposta)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        valore = getattr(request, "_nh_dev_cookie", None)
        if valore:
            response.set_cookie(COOKIE, valore, max_age=COOKIE_ANNI * 365 * 86400, httponly=True,
                                secure=request.is_secure(), samesite="Lax")
        return response


def _al_login(sender, request, user, **kwargs):
    try:
        registra_accesso(request, user)
    except Exception:  # noqa: BLE001 - mai bloccare un login per questo
        logger.exception("Dispositivo: registrazione accesso non riuscita")


def collega_segnale() -> None:
    from django.contrib.auth.signals import user_logged_in

    user_logged_in.connect(_al_login, dispatch_uid="core.dispositivi.al_login")
