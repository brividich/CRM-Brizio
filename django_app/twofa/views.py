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
    decrypt_totp_secret,
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
    send_otp_email,
    should_require_2fa,
    verify_email_otp,
    verify_totp,
)

logger = logging.getLogger(__name__)

# SEC: lockout anti brute-force per la verifica TOTP. Il ramo email ha già un
# contatore tentativi (TwoFactorChallenge.attempts); il TOTP no, e con un OTP a 6
# cifre senza limite il brute-force online è fattibile. Contatore in sessione.
_TOTP_MAX_ATTEMPTS = 5
_TOTP_LOCK_SECONDS = 300


def _get_next(request) -> str:
    """URL di destinazione post-verifica."""
    stored = request.session.get("twofa_next") or ""
    return stored or reverse("dashboard_home")


@never_cache
@login_required(login_url="login")
def verify(request):
    """Pagina di verifica 2FA. Accessibile solo se twofa_pending in sessione."""
    user = request.user

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
    if request.method == "GET" and method == "email" and not email_sent:
        code = generate_email_otp(user, get_client_ip(request))
        if send_otp_email(user, code):
            request.session["twofa_email_sent"] = True
            email_sent = True

    if request.method == "POST":
        form = VerifyOTPForm(request.POST)
        action = request.POST.get("action", "verify")

        if action == "resend" and method == "email":
            code = generate_email_otp(user, get_client_ip(request))
            send_otp_email(user, code)
            request.session["twofa_email_sent"] = True
            messages.success(request, "Nuovo codice inviato via email.")
            return redirect(reverse("twofa:verify"))

        if form.is_valid():
            code = form.cleaned_data["code"]
            ok = False

            if method == "totp":
                import time as _time
                now_ts = _time.time()
                lock_until = float(request.session.get("twofa_totp_lock_until", 0) or 0)
                if lock_until and now_ts < lock_until:
                    ok = False
                    error = "Troppi tentativi. Riprova tra qualche minuto."
                else:
                    try:
                        secret = decrypt_totp_secret(u2f.totp_secret_enc)
                        ok = verify_totp(secret, code)
                    except Exception:
                        ok = False
                    if ok:
                        request.session.pop("twofa_totp_fails", None)
                        request.session.pop("twofa_totp_lock_until", None)
                    else:
                        fails = int(request.session.get("twofa_totp_fails", 0) or 0) + 1
                        if fails >= _TOTP_MAX_ATTEMPTS:
                            request.session["twofa_totp_fails"] = 0
                            request.session["twofa_totp_lock_until"] = now_ts + _TOTP_LOCK_SECONDS
                            error = "Troppi tentativi. Riprova tra qualche minuto."
                        else:
                            request.session["twofa_totp_fails"] = fails
                            error = f"Codice non valido. Tentativi rimanenti: {_TOTP_MAX_ATTEMPTS - fails}."
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
    """Configurazione TOTP self-service (QR code + conferma primo codice)."""
    user = request.user

    try:
        u2f = user.twofa
    except Exception:
        from twofa.models import UserTwoFactor
        u2f = UserTwoFactor(user=user, method="totp")

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
    user = request.user
    try:
        u2f = user.twofa
        if u2f.method != "email":
            from django.http import JsonResponse
            return JsonResponse({"ok": False, "error": "Metodo non email."}, status=400)
    except Exception:
        from django.http import JsonResponse
        return JsonResponse({"ok": False, "error": "Configurazione 2FA non trovata."}, status=400)

    code = generate_email_otp(user, get_client_ip(request))
    sent = send_otp_email(user, code)
    from django.http import JsonResponse
    return JsonResponse({"ok": sent})
