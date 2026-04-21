from __future__ import annotations

from django.conf import settings
from django.db import models


class AnomalieRoleType(models.TextChoices):
    CAPO_COMMESSA = "CC", "Capocommessa"
    CAR = "CAR", "CAR / Incaricato"


class AnomalieAccessLevel(models.TextChoices):
    NONE = "NONE", "Nessun accesso extra"
    READ_ALL = "READ_ALL", "Vede tutto"
    EDIT_ASSIGNED = "EDIT_ASSIGNED", "Modifica solo anomalie in carico"
    EDIT_ALL = "EDIT_ALL", "Modifica tutto"


class AnomalieRoleDefinition(models.Model):
    """Catalogo ruoli operativi usato dalla configurazione anomalie."""

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")
    is_system = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    order_index = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order_index", "name", "id"]
        verbose_name = "Ruolo operativo anomalie"
        verbose_name_plural = "Ruoli operativi anomalie"

    def __str__(self) -> str:
        return self.name


class AnomalieRoleAssignment(models.Model):
    """Assegnazione utenti a ruoli operativi anomalie."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="anomalie_role_assignments",
    )
    role_type = models.CharField(max_length=32, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "role_type")]
        ordering = ["role_type", "user__last_name", "user__first_name", "user_id"]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.role_type}"


class AnomalieRoleAccessRule(models.Model):
    """Regola di accesso per ruolo operativo anomalie."""

    role_type = models.CharField(max_length=32, unique=True, db_index=True)
    access_level = models.CharField(
        max_length=20,
        choices=AnomalieAccessLevel.choices,
        default=AnomalieAccessLevel.NONE,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role_type"]
        verbose_name = "Regola accesso ruolo anomalie"
        verbose_name_plural = "Regole accesso ruoli anomalie"

    def __str__(self) -> str:
        return f"AnomalieRoleAccessRule<{self.role_type}={self.access_level}>"


class AnomalieUserAccessRule(models.Model):
    """Override accesso globale modulo anomalie per singolo utente."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="anomalie_access_rule",
    )
    access_level = models.CharField(
        max_length=20,
        choices=AnomalieAccessLevel.choices,
        default=AnomalieAccessLevel.READ_ALL,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__last_name", "user__first_name", "user_id"]
        verbose_name = "Override accesso utente anomalie"
        verbose_name_plural = "Override accesso utenti anomalie"

    def __str__(self) -> str:
        return f"AnomalieUserAccessRule<user={self.user_id}={self.access_level}>"


class AnomalieLegacyRoleAccessRule(models.Model):
    """Regola accesso globale modulo anomalie per ruolo aziendale legacy."""

    legacy_role_id = models.IntegerField(unique=True, db_index=True)
    legacy_role_name = models.CharField(max_length=100, blank=True, default="")
    access_level = models.CharField(
        max_length=20,
        choices=AnomalieAccessLevel.choices,
        default=AnomalieAccessLevel.READ_ALL,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["legacy_role_name", "legacy_role_id"]
        verbose_name = "Regola accesso ruolo aziendale anomalie"
        verbose_name_plural = "Regole accesso ruoli aziendali anomalie"

    def __str__(self) -> str:
        return f"AnomalieLegacyRoleAccessRule<role={self.legacy_role_id}={self.access_level}>"
