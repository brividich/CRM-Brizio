"""Utility per 2FA: TOTP, OTP email, detection rete interna, crittografia secret."""
from __future__ import annotations

import base64
import hashlib
import html as _html
import ipaddress
import logging
import os
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
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


# ── Anti brute-force e anti-replay per utente (audit M1) ─────────────────────
# Contatori in cache condivisa (DatabaseCache in produzione), legati all'utente e
# non alla sessione: un nuovo login non azzera più i tentativi.
TOTP_MAX_ATTEMPTS = 5
TOTP_LOCK_BASE_SECONDS = 300
TOTP_LOCK_MAX_SECONDS = 3600
EMAIL_OTP_MAX_SENDS = 5
EMAIL_OTP_SEND_WINDOW_SECONDS = 900


def _cache():
    from django.core.cache import cache

    return cache


def totp_lock_remaining(user) -> int:
    """Secondi di blocco residui per la verifica TOTP dell'utente (0 = libero)."""
    import time

    until = float(_cache().get(f"twofa:totp_lock:{user.pk}") or 0)
    return max(0, int(until - time.time())) if until else 0


def register_totp_failure(user) -> tuple[int, int]:
    """Conta un codice errato. Ritorna (tentativi_rimasti, secondi_di_blocco).

    Al quinto errore scatta un blocco progressivo: 5, 10, 20... minuti (max 1 ora).
    """
    import time

    cache = _cache()
    fails_key = f"twofa:totp_fails:{user.pk}"
    fails = int(cache.get(fails_key) or 0) + 1
    if fails < TOTP_MAX_ATTEMPTS:
        cache.set(fails_key, fails, TOTP_LOCK_MAX_SECONDS)
        return TOTP_MAX_ATTEMPTS - fails, 0
    locks_key = f"twofa:totp_locks:{user.pk}"
    locks = int(cache.get(locks_key) or 0) + 1
    seconds = min(TOTP_LOCK_BASE_SECONDS * (2 ** (locks - 1)), TOTP_LOCK_MAX_SECONDS)
    cache.set(locks_key, locks, 86400)
    cache.set(f"twofa:totp_lock:{user.pk}", time.time() + seconds, seconds)
    cache.delete(fails_key)
    return 0, seconds


def clear_totp_failures(user) -> None:
    cache = _cache()
    cache.delete(f"twofa:totp_fails:{user.pk}")
    cache.delete(f"twofa:totp_lock:{user.pk}")
    cache.delete(f"twofa:totp_locks:{user.pk}")


def verify_totp_once(user, secret: str, code: str) -> bool:
    """Come ``verify_totp`` ma ogni intervallo da 30 s vale una sola volta.

    Un codice già usato (anche intercettato) non apre una seconda sessione nei
    ~90 secondi di validità della finestra.
    """
    import pyotp

    totp = pyotp.TOTP(secret)
    code = (code or "").strip()
    now = timezone.now()
    current_step = totp.timecode(now)
    matched_step = None
    for offset in (0, -1, 1):
        step = current_step + offset
        if totp.generate_otp(step) == code:
            matched_step = step
            break
    if matched_step is None:
        return False
    key = f"twofa:totp_last_step:{user.pk}"
    cache = _cache()
    last_step = cache.get(key)
    if last_step is not None and int(last_step) >= matched_step:
        return False
    cache.set(key, matched_step, 180)
    return True


def email_otp_send_allowed(user) -> bool:
    """Massimo EMAIL_OTP_MAX_SENDS codici email per utente ogni 15 minuti."""
    cache = _cache()
    key = f"twofa:email_sends:{user.pk}"
    sent = int(cache.get(key) or 0)
    if sent >= EMAIL_OTP_MAX_SENDS:
        return False
    cache.set(key, sent + 1, EMAIL_OTP_SEND_WINDOW_SECONDS)
    return True


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
    otp_html = (
        f'<p style="color:#475569;font-size:15px;line-height:1.7;">Il tuo codice di verifica per <strong>{_html.escape(portal_name)}</strong> è:</p>'
        f'<div style="margin:20px 0;padding:18px 24px;background:#f6f9fc;border-radius:12px;border:1px solid #d8e1ec;text-align:center;">'
        f'<span style="font-size:32px;font-weight:800;letter-spacing:.18em;color:#002b5c;">{_html.escape(code)}</span>'
        f'</div>'
        f'<p style="color:#64748b;font-size:13px;">Il codice scade tra {_OTP_TTL_MINUTES} minuti. Se non hai richiesto questo codice, ignora questa email.</p>'
    )
    try:
        from core.email_utils import send_hub_mail
        send_hub_mail(
            subject, body, [recipient],
            title="Codice di verifica",
            email_type="Accesso",
            body_html_fragment=otp_html,
            footer_note="Messaggio automatico di sicurezza. Non condividere questo codice.",
            fail_silently=False,
        )
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


def is_external_entrypoint(request, client_ip: str = "") -> bool:
    """True se la richiesta arriva da Internet via proxy/App Proxy (audit A5).

    Il connettore Entra sta in LAN: senza questo controllo il suo IP interno farebbe
    saltare il 2FA «solo da rete esterna» a chi si collega da fuori.
    """
    proxy_ips = set(getattr(settings, "TWOFA_EXTERNAL_PROXY_IPS", set()) or set())
    if client_ip and client_ip in proxy_ips:
        return True
    remote_addr = (request.META.get("REMOTE_ADDR") or "") if request is not None else ""
    if remote_addr and remote_addr in proxy_ips:
        return True
    try:
        host = (request.get_host() or "").split(":", 1)[0].lower().rstrip(".")
    except Exception:
        host = (request.META.get("HTTP_HOST") or "").split(":", 1)[0].lower() if request is not None else ""
    for raw in getattr(settings, "TWOFA_EXTERNAL_HOSTS", []) or []:
        pattern = str(raw or "").strip().lower().rstrip(".")
        if not pattern or not host:
            continue
        if (pattern.startswith("*.") and host.endswith(pattern[1:])) or host == pattern:
            return True
    return False


def get_client_ip(request) -> str:
    """Restituisce l'IP reale del client (rispetta X-Forwarded-For se proxy trusted)."""
    try:
        from core.audit import _get_client_ip
        return _get_client_ip(request) or ""
    except Exception:
        return request.META.get("REMOTE_ADDR") or ""


# ── Logica policy ─────────────────────────────────────────────────────────────

def is_privileged_account(user) -> bool:
    """Superuser e staff Django: soggetti al 2FA anche senza Profile/ruolo legacy."""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))


def should_require_2fa(request, user) -> bool:
    """True se l'utente deve completare il 2FA per questa richiesta."""
    from twofa.models import TwoFactorPolicy

    privileged = is_privileged_account(user)
    try:
        policy = TwoFactorPolicy.get()
    except Exception:
        # SEC (audit A2): fail-closed per gli account privilegiati; per gli altri
        # resta fail-open per non bloccare il portale su un errore di lettura.
        logger.exception("2FA: impossibile leggere la policy")
        return privileged

    if not policy.enabled:
        return False

    if not privileged:
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
        if not is_external_entrypoint(request, client_ip) and is_internal_ip(
            client_ip, policy.internal_networks or []
        ):
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
        if u2f.method == "email" and u2f.is_active and not u2f.force_setup and email_otp_send_allowed(user):
            code = generate_email_otp(user, get_client_ip(request))
            send_otp_email(user, code)
    except Exception:
        pass
    request.session["twofa_pending"] = True
    request.session.modified = True
