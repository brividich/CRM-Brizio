"""Postazioni condivise: un PC usato a turno con un solo account (es. «zeiss»).

L'account della postazione entra dal login normale (LDAP). Da quel momento la
sessione è «in attesa»: si apre solo ``/postazione/``, dove l'operatore sceglie
il proprio nome fra i membri del gruppo della postazione e digita il proprio PIN.
Con il PIN giusto la sessione diventa **dell'operatore** (``login()`` vero:
permessi, audit, 2FA e firme sono i suoi); nella sessione resta il segno della
postazione, così «Cambio operatore» e l'inattività riportano alla scelta senza
chiedere di nuovo la password dell'account condiviso.

Regole di sicurezza:

- il PIN vale solo dentro una sessione aperta con l'account della postazione;
  fuori da lì non è una credenziale;
- si salva solo l'hash; dopo ``MAX_TENTATIVI`` errori di fila il PIN si blocca;
- il PIN si imposta con la propria password (``authenticate`` con axes);
- amministratori e superuser non entrano mai con il PIN;
- il 2FA dell'operatore resta quello della policy, come a un login normale.
"""
from __future__ import annotations

import logging
import time

from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.hashers import check_password, make_password
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

SESSIONE = "postazione_condivisa"
MAX_TENTATIVI = 5
PIN_MIN, PIN_MAX = 4, 8
# Throttle della scrittura dell'ultima attività dell'operatore nella sessione.
ATTIVITA_THROTTLE_SECONDI = 30
BACKEND_OPERATORE = "django.contrib.auth.backends.ModelBackend"

# Cosa può aprire l'account della postazione finché nessun operatore è entrato.
_PERCORSI_IN_ATTESA = ("/postazione/", "/logout", "/2fa/", "/static/", "/media/", "/favicon",
                       "/health", "/healthz", "/readyz", "/version")


# ── PIN ───────────────────────────────────────────────────────────────────────

def errore_pin(pin: str) -> str:
    """Messaggio d'errore se il PIN non è accettabile, altrimenti stringa vuota."""
    pin = str(pin or "")
    if not pin.isdigit() or not (PIN_MIN <= len(pin) <= PIN_MAX):
        return f"Il PIN deve avere da {PIN_MIN} a {PIN_MAX} cifre."
    if len(set(pin)) == 1:
        return "Il PIN non può essere una cifra ripetuta."
    cifre = [int(c) for c in pin]
    passi = {b - a for a, b in zip(cifre, cifre[1:], strict=False)}
    if passi in ({1}, {-1}):
        return "Il PIN non può essere una sequenza (es. 1234 o 4321)."
    return ""


def imposta_pin(legacy_user_id: int, pin: str):
    """Salva il PIN (hash) e lo sblocca. Il chiamante ha già verificato ``errore_pin``."""
    from core.models import PinPostazione

    record, _ = PinPostazione.objects.update_or_create(
        legacy_user_id=int(legacy_user_id),
        defaults={"pin_hash": make_password(pin), "tentativi_falliti": 0, "bloccato_il": None},
    )
    return record


def verifica_pin(legacy_user_id: int, pin: str) -> dict:
    """Ritorna ``{"esito": "ok"|"errato"|"bloccato"|"assente", "restanti": int}``.

    ``appena_bloccato`` è True solo nella richiesta che ha fatto scattare il blocco.
    """
    from core.models import PinPostazione

    record = PinPostazione.objects.filter(legacy_user_id=int(legacy_user_id)).first()
    if record is None:
        return {"esito": "assente", "restanti": 0}
    if record.bloccato_il is not None:
        return {"esito": "bloccato", "restanti": 0}
    if check_password(str(pin or ""), record.pin_hash):
        if record.tentativi_falliti:
            PinPostazione.objects.filter(pk=record.pk).update(tentativi_falliti=0)
        return {"esito": "ok", "restanti": MAX_TENTATIVI}
    PinPostazione.objects.filter(pk=record.pk).update(tentativi_falliti=F("tentativi_falliti") + 1)
    record.refresh_from_db(fields=["tentativi_falliti"])
    if record.tentativi_falliti >= MAX_TENTATIVI:
        appena = PinPostazione.objects.filter(pk=record.pk, bloccato_il__isnull=True).update(bloccato_il=timezone.now())
        return {"esito": "bloccato", "restanti": 0, "appena_bloccato": bool(appena)}
    return {"esito": "errato", "restanti": MAX_TENTATIVI - record.tentativi_falliti}


# ── Postazione e operatori ────────────────────────────────────────────────────

def legacy_di(user):
    from core.legacy_utils import get_legacy_user

    try:
        return get_legacy_user(user)
    except Exception:  # noqa: BLE001
        return None


def e_amministratore(user=None, legacy_user=None) -> bool:
    """Superuser, staff o amministratore legacy: non entra mai con il PIN."""
    from core.legacy_utils import is_legacy_admin

    if user is not None and (getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)):
        return True
    return bool(legacy_user is not None and is_legacy_admin(legacy_user))


def postazione_dell_account(user):
    """La postazione attiva di cui ``user`` è l'account condiviso, se esiste."""
    from core.models import PostazioneCondivisa

    legacy = legacy_di(user)
    if legacy is None:
        return None
    return PostazioneCondivisa.objects.filter(account_legacy_user_id=int(legacy.id), attiva=True).first()


def operatori(postazione) -> list:
    """Membri attivi del gruppo della postazione che possono entrare con il PIN (UtenteLegacy)."""
    from core.legacy_models import UtenteLegacy
    from core.models import AccessGroupMembership, Profile

    if postazione is None or not postazione.gruppo.is_active:
        return []
    oggi = timezone.localdate()
    ids = set(
        AccessGroupMembership.objects.filter(group_id=postazione.gruppo_id)
        .filter(Q(scade_il__isnull=True) | Q(scade_il__gte=oggi))
        .values_list("legacy_user_id", flat=True)
    )
    ids.discard(int(postazione.account_legacy_user_id))
    if not ids:
        return []
    utenti = list(UtenteLegacy.objects.filter(id__in=ids, attivo=True).order_by("nome", "id"))
    # Gli account Django privilegiati (superuser/staff) restano fuori anche se nel gruppo.
    privilegiati = set(
        Profile.objects.filter(legacy_user_id__in=[u.id for u in utenti])
        .filter(Q(user__is_superuser=True) | Q(user__is_staff=True))
        .values_list("legacy_user_id", flat=True)
    )
    return [u for u in utenti if u.id not in privilegiati and not e_amministratore(legacy_user=u)]


def operatore_della_postazione(postazione, legacy_user_id):
    """L'UtenteLegacy scelto, solo se è davvero fra gli operatori della postazione."""
    try:
        target = int(legacy_user_id)
    except (TypeError, ValueError):
        return None
    return next((u for u in operatori(postazione) if int(u.id) == target), None)


def stato(request) -> dict:
    valore = getattr(request, "session", {}).get(SESSIONE)
    return valore if isinstance(valore, dict) else {}


def registra_audit(request, azione: str, dettaglio: dict) -> None:
    try:
        from core.audit import log_action

        log_action(request, azione, "core", dettaglio)
    except Exception:  # noqa: BLE001
        logger.warning("audit %s non registrato", azione, exc_info=True)


def _ancora_attivita(request) -> None:
    from core.session_middleware import SessionIdleTimeoutMiddleware

    request.session[SessionIdleTimeoutMiddleware.SESSION_KEY] = int(time.time())


def passa_a_operatore(request, postazione, operatore_legacy) -> bool:
    """La sessione dell'account condiviso diventa dell'operatore. Ritorna False se non si può."""
    from core.legacy_utils import sync_django_user_from_legacy

    corrente = stato(request)
    if not corrente or corrente.get("operatore") or int(corrente.get("postazione") or 0) != postazione.pk:
        return False
    utente = sync_django_user_from_legacy(operatore_legacy)
    if utente is None or not utente.is_active or e_amministratore(utente, operatore_legacy):
        return False
    account_id = int(corrente["account"])
    account_backend = corrente.get("account_backend") or BACKEND_OPERATORE
    account_2fa = request.session.get("twofa_verified_until")
    request.postazione_cambio_in_corso = True
    # login() con un utente diverso svuota la sessione (flush): il segno si riscrive dopo.
    login(request, utente, backend=BACKEND_OPERATORE)
    request.session[SESSIONE] = {
        "postazione": postazione.pk,
        "account": account_id,
        "account_backend": account_backend,
        "account_2fa": account_2fa,
        "operatore": utente.pk,
        "attivita": int(time.time()),
    }
    _ancora_attivita(request)
    registra_audit(request, "postazione_operatore_entra", {
        "postazione": postazione.nome, "postazione_id": postazione.pk, "operatore": utente.get_username(),
    })
    return True


def torna_alla_postazione(request, motivo: str = "cambio") -> bool:
    """Chiude la sessione dell'operatore e riapre la scelta. False se la postazione non c'è più."""
    from core.models import PostazioneCondivisa

    corrente = stato(request)
    if not corrente.get("operatore"):
        return False
    postazione = PostazioneCondivisa.objects.filter(pk=corrente.get("postazione"), attiva=True).first()
    account = get_user_model().objects.filter(pk=corrente.get("account"), is_active=True).first()
    registra_audit(request, "postazione_operatore_esce", {
        "postazione": getattr(postazione, "nome", ""), "postazione_id": corrente.get("postazione"),
        "operatore": request.user.get_username() if request.user.is_authenticated else "",
        "motivo": motivo,
    })
    if postazione is None or account is None or postazione_dell_account(account) != postazione:
        logout(request)
        return False
    request.postazione_cambio_in_corso = True
    login(request, account, backend=corrente.get("account_backend") or BACKEND_OPERATORE)
    request.session[SESSIONE] = {
        "postazione": postazione.pk, "account": account.pk,
        "account_backend": corrente.get("account_backend") or BACKEND_OPERATORE, "operatore": None,
    }
    # Il 2FA eventualmente superato dall'account condiviso resta valido fino alla sua scadenza.
    if corrente.get("account_2fa"):
        request.session["twofa_verified_until"] = corrente["account_2fa"]
    _ancora_attivita(request)
    return True


# ── Segnale di login e middleware ─────────────────────────────────────────────

def _al_login(sender, request, user, **kwargs):
    """Login dell'account di una postazione: la sessione parte «in attesa di operatore»."""
    if request is None or not hasattr(request, "session"):
        return
    if getattr(request, "postazione_cambio_in_corso", False):
        return
    try:
        postazione = postazione_dell_account(user)
    except Exception:  # noqa: BLE001 - mai bloccare un login per questo
        logger.exception("Postazione condivisa: verifica account non riuscita")
        return
    if postazione is None:
        request.session.pop(SESSIONE, None)
        return
    request.session[SESSIONE] = {
        "postazione": postazione.pk, "account": user.pk,
        "account_backend": getattr(user, "backend", "") or BACKEND_OPERATORE, "operatore": None,
    }


def collega_segnale() -> None:
    from django.contrib.auth.signals import user_logged_in

    user_logged_in.connect(_al_login, dispatch_uid="core.postazioni.al_login")


def _e_attivita(request) -> bool:
    """Una richiesta fatta dalla persona (non un aggiornamento automatico in background)."""
    if request.method != "GET":
        return True
    # Le GET HTMX/fetch possono essere aggiornamenti periodici (es. centro notifiche ogni 60 s):
    # conta solo la navigazione vera.
    if request.headers.get("HX-Request"):
        return False
    if request.headers.get("Sec-Fetch-Mode"):
        return request.headers.get("Sec-Fetch-Mode") == "navigate"
    return "text/html" in (request.headers.get("Accept") or "").lower()


def _vuole_json(request) -> bool:
    accept = (request.headers.get("Accept") or "").lower()
    return request.path.startswith("/api/") or ("application/json" in accept and "text/html" not in accept)


class PostazioneCondivisaMiddleware:
    """Tiene l'account condiviso sulla scelta dell'operatore e fa scadere l'operatore inattivo.

    Va dopo ``AuthenticationMiddleware`` e prima di ``SessionIdleTimeoutMiddleware``:
    l'inattività dell'operatore riporta alla postazione invece di chiudere tutto.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.postazione_condivisa = None
        corrente = stato(request)
        if not corrente or not request.user.is_authenticated:
            return self.get_response(request)

        from core.models import PostazioneCondivisa

        postazione = PostazioneCondivisa.objects.filter(pk=corrente.get("postazione"), attiva=True).first()
        if postazione is None:
            # Postazione spenta o cancellata: la sessione nata da lì non vale più.
            logout(request)
            if _vuole_json(request):
                return JsonResponse({"ok": False, "reason": "postazione_disattivata"}, status=401)
            return redirect(f"{reverse('login')}?reason=logout")

        operatore_id = corrente.get("operatore")
        if operatore_id:
            if int(operatore_id) != request.user.pk:
                request.session.pop(SESSIONE, None)
                return self.get_response(request)
            # «Esci» dell'operatore chiude solo la sua sessione, non quella della postazione
            # (per chiudere la postazione c'è «Chiudi la postazione» su «Chi sei?»).
            if request.path in ("/logout", "/logout/") and request.META.get("HTTP_SEC_FETCH_SITE", "") != "cross-site":
                if torna_alla_postazione(request, motivo="esci"):
                    return redirect("postazione_home")
                return redirect(f"{reverse('login')}?reason=logout")
            ora = int(time.time())
            ultima = int(corrente.get("attivita") or ora)
            if ora - ultima > int(postazione.minuti_inattivita) * 60:
                torna_alla_postazione(request, motivo="inattivita")
                if _vuole_json(request):
                    return JsonResponse({"ok": False, "reason": "postazione_inattivita",
                                         "redirect": reverse("postazione_home")}, status=401)
                return redirect(f"{reverse('postazione_home')}?motivo=inattivita")
            if _e_attivita(request) and ora - ultima >= ATTIVITA_THROTTLE_SECONDI:
                corrente["attivita"] = ora
                request.session[SESSIONE] = corrente
            request.postazione_condivisa = {
                "nome": postazione.nome,
                "minuti_inattivita": int(postazione.minuti_inattivita),
                "operatore": request.user.get_full_name() or request.user.get_username(),
            }
            return self.get_response(request)

        if int(corrente.get("account") or 0) != request.user.pk:
            request.session.pop(SESSIONE, None)
            return self.get_response(request)
        if any(request.path.startswith(p) for p in _PERCORSI_IN_ATTESA):
            return self.get_response(request)
        if _vuole_json(request):
            return JsonResponse({"ok": False, "reason": "postazione_condivisa",
                                 "redirect": reverse("postazione_home")}, status=403)
        return redirect("postazione_home")
