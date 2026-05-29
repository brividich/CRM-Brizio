from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


def _default_allowed_methods():
    return ["totp", "email"]


class TwoFactorPolicy(models.Model):
    """Singleton — configurazione globale del sistema 2FA."""

    WHEN_ALWAYS = "always"
    WHEN_EXTERNAL = "external_only"
    WHEN_CHOICES = [
        (WHEN_ALWAYS, "Sempre (interno + esterno)"),
        (WHEN_EXTERNAL, "Solo da rete esterna"),
    ]

    enabled = models.BooleanField(default=False)
    # IDs ruolo legacy (interi) dei ruoli soggetti a 2FA
    required_role_ids = models.JSONField(default=list, blank=True)
    when_required = models.CharField(max_length=20, choices=WHEN_CHOICES, default=WHEN_EXTERNAL)
    # Lista CIDR reti interne (es. ["192.168.0.0/16", "10.0.0.0/8"])
    internal_networks = models.JSONField(default=list, blank=True)
    # Metodi ammessi: sottoinsieme di ["totp", "email"]
    allowed_methods = models.JSONField(default=_default_allowed_methods)
    # Validità verifica 2FA nella sessione (secondi, default 8 ore)
    session_validity_seconds = models.IntegerField(default=28800)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "Policy 2FA"

    @classmethod
    def get(cls) -> "TwoFactorPolicy":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        status = "attivo" if self.enabled else "disattivo"
        return f"Policy 2FA ({status})"


class UserTwoFactor(models.Model):
    """Configurazione 2FA per singolo utente."""

    METHOD_TOTP = "totp"
    METHOD_EMAIL = "email"
    METHOD_CHOICES = [
        (METHOD_TOTP, "App Authenticator (TOTP)"),
        (METHOD_EMAIL, "Email"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="twofa",
    )
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default=METHOD_EMAIL)
    # TOTP secret crittografato con Fernet (vuoto se metodo email)
    totp_secret_enc = models.CharField(max_length=256, blank=True)
    # True solo dopo che l'utente ha confermato il primo codice TOTP
    totp_confirmed = models.BooleanField(default=False)
    # Se valorizzato, sovrascrive user.email per la spedizione OTP
    email_override = models.EmailField(blank=True)
    # Admin può disabilitare il 2FA per questo utente
    is_active = models.BooleanField(default=True)
    # Forza il ri-setup al prossimo accesso (es. dopo reset admin)
    force_setup = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "2FA utente"
        verbose_name_plural = "2FA utenti"

    def get_otp_email(self) -> str:
        return self.email_override or (self.user.email or "")

    def __str__(self) -> str:
        return f"2FA {self.user} ({self.get_method_display()})"


class TwoFactorChallenge(models.Model):
    """OTP via email in attesa di verifica."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="twofa_challenges",
    )
    code_hash = models.CharField(max_length=64)  # SHA-256 hex del codice in chiaro
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Challenge 2FA"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def __str__(self) -> str:
        return f"Challenge {self.user} @ {self.created_at:%Y-%m-%d %H:%M}"
