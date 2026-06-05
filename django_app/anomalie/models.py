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


class AnomalieListScope(models.TextChoices):
    ALL = "ALL", "Tutti gli OP"
    ASSIGNED = "ASSIGNED", "Solo OP in carico (capocommessa/CAR)"
    OWN_ANOMALIE = "OWN_ANOMALIE", "Solo OP con proprie anomalie create"


class AnomalieRoleDefinition(models.Model):
    """DEPRECATO: catalogo ruoli operativi locale del modulo anomalie.

    Sostituito da ``anagrafica.RuoloOperativo`` come fonte unica del catalogo.
    Conservato per la sola migrazione dati (lettura dei ruoli custom storici);
    non va piu' usato come fonte a runtime. Vedi ``core.operational_roles``.
    """

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
    """DEPRECATO: assegnazione utenti a ruoli operativi locali anomalie.

    Le assegnazioni utente->ruolo custom sono ora gestite in anagrafica
    (``DipendenteRuoloOperativo``). Conservato per la sola migrazione dati.
    """

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
    """Regola di accesso per ruolo operativo anomalie.

    Due tipi di regola, mutuamente esclusivi per riga:
    - ruolo di SISTEMA (CC/CAR): identificato da ``role_type`` (codice in
      ``AnomalieRoleType``), risolto dai campi dell'OP a runtime;
    - ruolo CUSTOM: identificato da ``ruolo_operativo`` (FK verso il catalogo
      unico ``anagrafica.RuoloOperativo``), con assegnazioni utente gestite in
      anagrafica (``DipendenteRuoloOperativo``).
    """

    role_type = models.CharField(max_length=32, blank=True, default="", db_index=True)
    ruolo_operativo = models.ForeignKey(
        "anagrafica.RuoloOperativo",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="anomalie_access_rules",
    )
    access_level = models.CharField(
        max_length=20,
        choices=AnomalieAccessLevel.choices,
        default=AnomalieAccessLevel.NONE,
        db_index=True,
    )
    list_scope = models.CharField(
        max_length=20,
        choices=AnomalieListScope.choices,
        default=AnomalieListScope.ALL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role_type", "ruolo_operativo_id"]
        verbose_name = "Regola accesso ruolo anomalie"
        verbose_name_plural = "Regole accesso ruoli anomalie"
        # Unicita' gestita a livello applicativo (update_or_create con chiavi
        # role_type / ruolo_operativo): i partial unique index con condizione
        # negata non sono portabili su SQL Server.

    def __str__(self) -> str:
        key = self.role_type or f"ruolo_op:{self.ruolo_operativo_id}"
        return f"AnomalieRoleAccessRule<{key}={self.access_level}>"


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
    list_scope = models.CharField(
        max_length=20,
        choices=AnomalieListScope.choices,
        default=AnomalieListScope.ALL,
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
    list_scope = models.CharField(
        max_length=20,
        choices=AnomalieListScope.choices,
        default=AnomalieListScope.ALL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["legacy_role_name", "legacy_role_id"]
        verbose_name = "Regola accesso ruolo aziendale anomalie"
        verbose_name_plural = "Regole accesso ruoli aziendali anomalie"

    def __str__(self) -> str:
        return f"AnomalieLegacyRoleAccessRule<role={self.legacy_role_id}={self.access_level}>"
