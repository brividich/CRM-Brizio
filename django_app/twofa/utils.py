"""Utility per 2FA: TOTP, OTP email, detection rete interna, crittografia secret."""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import logging
import os
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest

logger = logging.getLogger(__name__)

_OTP_LENGTH = 6
_OTP_TTL_MINUTES = 10
_MAX_ATTEMPTS = 5


# ── Crittografia TOTP secret ──────────────────────────────────────────────────

def _get_fernet():
    from cryptography.fernet import Fernet

    key_material = settings.SECRET_KEY.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(key_material).digest())
    return Fernet(key)


def encrypt_totp_secret(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_totp_secret(enc: str) -> str:
    return _get_fernet().decrypt(enc.encode()).decode()


# ── TOTP ──────────────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    import pyotp
    return pyotp.random_base32()


def get_totp_uri(secret: str, user_email: str) -> str:
    import pyotp
    issuer = getattr(settings, "INSTANCE_NAME", "NOVICROM HUB")
    return pyotp.TOTP(secret).provisioning_uri(name=user_email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    import pyotp
    totp = pyotp.TOTP(secret)
    # valid_window=1 accetta il codice del periodo precedente/successivo
    return totp.verify(code.strip(), valid_window=1)


def generate_totp_qr_svg(uri: str) -> str:
    """Restituisce il QR code come stringa SVG inline (no file su disco)."""
    import qrcode
    import qrcode.image.svg

    factory = qrcode.image.svg.SvgPathImage
    qr = qrcode.make(uri, image_factory=factory, box_size=6)
    import io
    buf = io.BytesIO()
    qr.save(buf)
    return buf.getvalue().decode("utf-8")


# ── OTP email ─────────────────────────────────────────────────────────────────

def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def generate_email_otp(user, ip_address: str | None = None) -> str:
    """Genera e salva un nuovo challenge OTP per l'utente, restituisce il codice in chiaro."""
    from twofa.models import TwoFactorChallenge

    # Invalida eventuali challenge attivi precedenti
    TwoFactorChallenge.objects.filter(user=user, used=False).update(used=True)

    code = "".join([str(secrets.randbelow(10)) for _ in range(_OTP_LENGTH)])
    TwoFactorChallenge.objects.create(
        user=user,
        code_hash=_hash_code(code),
        expires_at=timezone.now() + timedelta(minutes=_OTP_TTL_MINUTES),
        ip_address=ip_address,
    )
    return code


def send_otp_email(user, code: str) -> bool:
    """Invia il codice OTP via email. Restituisce True se la spedizione è riuscita."""
    try:
        u2f = user.twofa
        recipient = u2f.get_otp_email()
    except Exception:
        recipient = user.email or ""

    if not recipient:
        logger.warning("2FA OTP: nessun indirizzo email per l'utente %s", user.username)
        return False

    portal_name = getattr(settings, "INSTANCE_NAME", "NOVICROM HUB")
    subject = f"[{portal_name}] Codice di verifica: {code}"
    body = (
        f"Il tuo codice di verifica per {portal_name} è:\n\n"
        f"    {code}\n\n"
        f"Il codice scade tra {_OTP_TTL_MINUTES} minuti.\n\n"
        f"Se non hai richiesto questo codice, ignora questa email."
    )
    try:
        send_mail(subject, body, None, [recipient], fail_silently=False)
        return True
    except Exception as exc:
        logger.error("2FA OTP: errore invio email a %s: %s", recipient, exc)
        return False


def verify_email_otp(user, code: str) -> tuple[bool, str]:
    """
    Verifica il codice OTP email dell'utente.
    Restituisce (ok, messaggio_errore).
    """
    from twofa.models import TwoFactorChallenge

    challenge = (
        TwoFactorChallenge.objects.filter(user=user, used=False)
        .order_by("-created_at")
        .first()
    )
    if not challenge:
        return False, "Nessun codice attivo. Richiedi un nuovo codice."

    if challenge.is_expired:
        challenge.used = True
        challenge.save(update_fields=["used"])
        return False, "Il codice è scaduto. Richiedi un nuovo codice."

    if challenge.attempts >= _MAX_ATTEMPTS:
        return False, "Troppi tentativi. Richiedi un nuovo codice."

    challenge.attempts += 1
    if challenge.code_hash != _hash_code(code.strip()):
        challenge.save(update_fields=["attempts"])
        remaining = _MAX_ATTEMPTS - challenge.attempts
        return False, f"Codice non valido. Tentativi rimanenti: {remaining}."

    challenge.used = True
    challenge.save(update_fields=["used", "attempts"])
    return True, ""


# ── Rilevamento rete interna ──────────────────────────────────────────────────

def is_internal_ip(ip_str: str, cidr_list: list[str]) -> bool:
    """Verifica se l'IP è in uno dei CIDR considerati rete interna."""
    if not ip_str or not cidr_list:
        return False
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for cidr in cidr_list:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request) -> str:
    """Restituisce l'IP reale del client (rispetta X-Forwarded-For se proxy trusted)."""
    try:
        from core.audit import _get_client_ip
        return _get_client_ip(request) or ""
    except Exception:
        return request.META.get("REMOTE_ADDR") or ""


# ── Logica policy ─────────────────────────────────────────────────────────────

def should_require_2fa(request, user) -> bool:
    """True se l'utente deve completare il 2FA per questa richiesta."""
    from twofa.models import TwoFactorPolicy

    try:
        policy = TwoFactorPolicy.get()
    except Exception:
        return False

    if not policy.enabled:
        return False

    # Controlla ruolo legacy
    try:
        from core.legacy_utils import get_legacy_user
        legacy_user = get_legacy_user(user)
    except Exception:
        legacy_user = None

    if legacy_user is None:
        return False

    ruolo_id = getattr(legacy_user, "ruolo_id", None)
    if ruolo_id is None or int(ruolo_id) not in [int(r) for r in (policy.required_role_ids or [])]:
        return False

    # Controlla se disabilitato per questo utente
    try:
        u2f = user.twofa
        if not u2f.is_active:
            return False
    except Exception:
        pass  # utente senza record UserTwoFactor → deve configurare

    # Controlla rete interna
    if policy.when_required == TwoFactorPolicy.WHEN_EXTERNAL:
        client_ip = get_client_ip(request)
        if is_internal_ip(client_ip, policy.internal_networks or []):
            return False

    return True


def is_2fa_verified(request) -> bool:
    """True se la sessione corrente ha già completato la verifica 2FA."""
    verified_until = request.session.get("twofa_verified_until")
    if not verified_until:
        return False
    try:
        from django.utils.dateparse import parse_datetime
        dt = parse_datetime(verified_until)
        if dt and timezone.now() < dt:
            return True
    except Exception:
        pass
    # scaduta o invalida — pulisci
    request.session.pop("twofa_verified_until", None)
    return False


def mark_2fa_verified(request, validity_seconds: int | None = None) -> None:
    """Segna la sessione come 2FA verificato per `validity_seconds` secondi."""
    from twofa.models import TwoFactorPolicy
    if validity_seconds is None:
        try:
            validity_seconds = TwoFactorPolicy.get().session_validity_seconds
        except Exception:
            validity_seconds = 28800
    until = timezone.now() + timedelta(seconds=validity_seconds)
    request.session["twofa_verified_until"] = until.isoformat()
    request.session.modified = True


def needs_totp_setup(user) -> bool:
    """True se l'utente deve ancora configurare il TOTP (metodo totp, non confermato o force_setup)."""
    try:
        u2f = user.twofa
        if u2f.force_setup:
            return True
        if u2f.method == "totp" and not u2f.totp_confirmed:
            return True
    except Exception:
        pass
    return False


def initiate_2fa(request, user) -> None:
    """
    Prepara la sessione per il challenge 2FA.
    Se l'utente ha metodo email, genera e invia il codice OTP.
    """
    try:
        u2f = user.twofa
        if u2f.method == "email" and u2f.is_active and not u2f.force_setup:
            code = generate_email_otp(user, get_client_ip(request))
            send_otp_email(user, code)
    except Exception:
        pass
    request.session["twofa_pending"] = True
    request.session.modified = True
