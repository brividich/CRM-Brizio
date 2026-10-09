from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from twofa.forms import SetupTOTPConfirmForm, VerifyOTPForm
from twofa.utils import (
    clear_totp_failures,
    decrypt_totp_secret,
    email_otp_send_allowed,
    encrypt_totp_secret,
    generate_email_otp,
    generate_totp_qr_svg,
    generate_totp_secret,
    get_client_ip,
    get_totp_uri,
    initiate_2fa,
    is_2fa_verified,
    mark_2fa_verified,
    needs_totp_setup,
    register_totp_failure,
    send_otp_email,
    should_require_2fa,
    totp_lock_remaining,
    verify_email_otp,
    verify_totp,
    verify_totp_once,
)

logger = logging.getLogger(__name__)

# SEC: lockout anti brute-force e anti-replay della verifica TOTP e limite ai
# codici email: contatori per utente in cache (audit M1), vedi twofa.utils.


def _get_next(request) -> str:
    """URL di destinazione post-verifica."""
    stored = request.session.get("twofa_next") or ""
    return stored or reverse("dashboard_home")


def _real_user(request):
    """Utente che ha fatto login: durante l'impersonazione è l'admin, non il target.

    Il 2FA protegge la sessione di chi si è autenticato (audit A1): la verifica e
    l'enrollment non devono mai agire sul fattore dell'utente impersonato.
    """
    return getattr(request, "impersonator_user", None) or request.user


def _has_established_factor(u2f) -> bool:
    """True se l'utente ha già un secondo fattore attivo e confermato.

    In questo caso l'enrollment self-service di un nuovo TOTP non è ammesso
    (audit C1): sostituirlo con la sola password azzererebbe il 2FA. La
    sostituzione passa dal reset admin (``force_setup``).
    """
    if u2f is None or getattr(u2f, "pk", None) is None:
        return False
    if not u2f.is_active or u2f.force_setup:
        return False
    if u2f.method == "totp":
        return bool(u2f.totp_confirmed and u2f.totp_secret_enc)
    return True  # metodo email configurato


def _notify_totp_enrolled(user) -> None:
    """Avvisa l'utente che sul suo account è stato registrato un autenticatore."""
    from core.security_notify import notify_security_event

    notify_security_event(
        user,
        "Nuovo autenticatore registrato",
        "Sul tuo account è stata appena configurata un'app Authenticator per l'autenticazione a due fattori.",
    )


@never_cache
@login_required(login_url="login")
def verify(request):
    """Pagina di verifica 2FA. Accessibile solo se twofa_pending in sessione."""
    user = _real_user(request)

    if not request.session.get("twofa_pending") and not should_require_2fa(request, user):
        return redirect(_get_next(request))

    if is_2fa_verified(request):
        request.session.pop("twofa_pending", None)
        return redirect(_get_next(request))

    # Utente deve configurare il 2FA per la prima volta
    if needs_totp_setup(user):
        return redirect(reverse("twofa:setup_totp"))

    try:
        u2f = user.twofa
    except Exception:
        # Nessuna configurazione: redirect setup
        return redirect(reverse("twofa:setup_totp"))

    method = u2f.method
    error = ""
    email_sent = request.session.get("twofa_email_sent", False)

    # Invio automatico del codice email se si arriva qui da un percorso che non ha
    # chiamato initiate_2fa (es. SSO Windows): ora il middleware è autorevole e può
    # reindirizzare alla verifica qualunque sessione non verificata. Evita che
    # l'utente resti su una pagina senza codice. Inviato una sola volta per sessione.
    if request.method == "GET" and method == "email" and not email_sent and email_otp_send_allowed(user):
        code = generate_email_otp(user, get_client_ip(request))
        if send_otp_email(user, code):
            request.session["twofa_email_sent"] = True
            email_sent = True

    if request.method == "POST":
        form = VerifyOTPForm(request.POST)
        action = request.POST.get("action", "verify")

        if action == "resend" and method == "email":
            if not email_otp_send_allowed(user):
                messages.error(request, "Troppi codici richiesti. Riprova tra qualche minuto.")
                return redirect(reverse("twofa:verify"))
            code = generate_email_otp(user, get_client_ip(request))
            send_otp_email(user, code)
            request.session["twofa_email_sent"] = True
            messages.success(request, "Nuovo codice inviato via email.")
            return redirect(reverse("twofa:verify"))

        if form.is_valid():
            code = form.cleaned_data["code"]
            ok = False

            if method == "totp":
                if totp_lock_remaining(user):
                    ok = False
                    error = "Troppi tentativi. Riprova tra qualche minuto."
                else:
                    try:
                        secret = decrypt_totp_secret(u2f.totp_secret_enc)
                        ok = verify_totp_once(user, secret, code)
                    except Exception:
                        ok = False
                    if ok:
                        clear_totp_failures(user)
                    else:
                        remaining, locked_for = register_totp_failure(user)
                        if locked_for:
                            error = "Troppi tentativi. Riprova tra qualche minuto."
                            try:
                                from core.audit import log_action
                                log_action(request, "2fa_totp_locked", "twofa", {"seconds": locked_for})
                            except Exception:
                                pass
                        else:
                            error = f"Codice non valido. Tentativi rimanenti: {remaining}."
            else:  # email
                ok, error = verify_email_otp(user, code)

            if ok:
                from twofa.models import TwoFactorPolicy
                policy = TwoFactorPolicy.get()
                mark_2fa_verified(request, policy.session_validity_seconds)
                request.session.pop("twofa_pending", None)
                request.session.pop("twofa_email_sent", None)

                # aggiorna last_used_at
                from django.utils import timezone
                u2f.last_used_at = timezone.now()
                u2f.save(update_fields=["last_used_at"])

                try:
                    from core.audit import log_action
                    log_action(request, "2fa_ok", "twofa", {"method": method})
                except Exception:
                    pass

                next_url = _get_next(request)
                request.session.pop("twofa_next", None)
                return redirect(next_url)
        else:
            error = "Inserisci un codice valido."
    else:
        form = VerifyOTPForm()

    return render(request, "twofa/pages/verify.html", {
        "form": form,
        "method": method,
        "error": error,
        "email_sent": email_sent,
        "otp_email": u2f.get_otp_email() if method == "email" else "",
    })


@never_cache
@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def setup_totp(request):
    """Configurazione TOTP self-service (QR code + conferma primo codice).

    Ammessa solo per il primo enrollment o dopo un reset admin (``force_setup``).
    Con un fattore già attivo la richiesta viene rimandata alla verifica.
    """
    user = _real_user(request)

    try:
        u2f = user.twofa
    except Exception:
        from twofa.models import UserTwoFactor
        u2f = UserTwoFactor(user=user, method="totp")

    if _has_established_factor(u2f):
        request.session.pop("twofa_totp_setup_secret", None)
        try:
            from core.audit import log_action
            log_action(request, "2fa_totp_setup_denied", "twofa", {"method": u2f.method})
        except Exception:
            pass
        if is_2fa_verified(request):
            messages.info(
                request,
                "Il secondo fattore è già configurato. Per sostituire l'autenticatore chiedi un reset all'amministratore.",
            )
            return redirect(_get_next(request))
        return redirect(reverse("twofa:verify"))

    # Usa secret già generato in sessione o ne crea uno nuovo
    pending_secret = request.session.get("twofa_totp_setup_secret")
    if not pending_secret:
        pending_secret = generate_totp_secret()
        request.session["twofa_totp_setup_secret"] = pending_secret

    uri = get_totp_uri(pending_secret, user.email or user.username)
    qr_svg = generate_totp_qr_svg(uri)

    error = ""
    if request.method == "POST":
        form = SetupTOTPConfirmForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"]
            if verify_totp(pending_secret, code):
                u2f.method = "totp"
                u2f.totp_secret_enc = encrypt_totp_secret(pending_secret)
                u2f.totp_confirmed = True
                u2f.force_setup = False
                u2f.save()
                request.session.pop("twofa_totp_setup_secret", None)

                # Verifica immediata — non chiedere di nuovo il codice
                from twofa.models import TwoFactorPolicy
                policy = TwoFactorPolicy.get()
                mark_2fa_verified(request, policy.session_validity_seconds)
                request.session.pop("twofa_pending", None)

                try:
                    from core.audit import log_action
                    log_action(request, "2fa_totp_setup", "twofa")
                except Exception:
                    pass
                _notify_totp_enrolled(user)

                messages.success(request, "Autenticazione a due fattori configurata correttamente.")
                next_url = _get_next(request)
                request.session.pop("twofa_next", None)
                return redirect(next_url)
            else:
                error = "Codice non valido. Riprova ad inquadrare il QR code e inserisci il codice attuale."
        else:
            error = "Inserisci un codice valido."
    else:
        form = SetupTOTPConfirmForm()

    return render(request, "twofa/pages/setup_totp.html", {
        "form": form,
        "qr_svg": qr_svg,
        "totp_uri": uri,
        "secret_plain": pending_secret,
        "error": error,
    })


@never_cache
@login_required(login_url="login")
@require_http_methods(["POST"])
def resend_otp(request):
    """Reinvia OTP email (AJAX/POST)."""
    user = _real_user(request)
    try:
        u2f = user.twofa
        if u2f.method != "email":
            from django.http import JsonResponse
            return JsonResponse({"ok": False, "error": "Metodo non email."}, status=400)
    except Exception:
        from django.http import JsonResponse
        return JsonResponse({"ok": False, "error": "Configurazione 2FA non trovata."}, status=400)

    from django.http import JsonResponse
    if not email_otp_send_allowed(user):
        return JsonResponse({"ok": False, "error": "Troppi codici richiesti. Riprova tra qualche minuto."}, status=429)
    code = generate_email_otp(user, get_client_ip(request))
    sent = send_otp_email(user, code)
    return JsonResponse({"ok": sent})
