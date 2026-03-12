from django.db import models


class LegacyUnmanagedModel(models.Model):
    class Meta:
        abstract = True
        managed = False


class Ruolo(LegacyUnmanagedModel):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=100)

    class Meta(LegacyUnmanagedModel.Meta):
        db_table = "ruoli"
        app_label = "legacy_runtime"

    def __str__(self) -> str:
        return self.nome


class UtenteLegacy(LegacyUnmanagedModel):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=200)
    # login_id: UPN Active Directory (es. l.bova@example.local) usato come identificatore di login
    email = models.CharField(max_length=200, blank=True, null=True)
    password = models.CharField(max_length=500)
    ruolo = models.CharField(max_length=100, blank=True, null=True)
    attivo = models.BooleanField(default=True)
    deve_cambiare_password = models.BooleanField(default=False)
    ruolo_id = models.IntegerField(blank=True, null=True)

    class Meta(LegacyUnmanagedModel.Meta):
        db_table = "utenti"
        app_label = "legacy_runtime"

    def __str__(self) -> str:
        return self.email or self.nome or f"legacy:{self.id}"


class AnagraficaDipendente(LegacyUnmanagedModel):
    id = models.AutoField(primary_key=True)
    aliasusername = models.CharField(max_length=200, blank=True, null=True)
    nome = models.CharField(max_length=200, blank=True, null=True)
    cognome = models.CharField(max_length=200, blank=True, null=True)
    mansione = models.CharField(max_length=200, blank=True, null=True)
    reparto = models.CharField(max_length=200, blank=True, null=True)
    # login_id copiato da utenti.email — usato solo per match legacy, non per notifiche
    email = models.CharField(max_length=200, blank=True, null=True)
    # email reale per notifiche (es. l.bova@example.com)
    email_notifica = models.CharField(max_length=200, blank=True, null=True)
    # FK esplicita verso utenti.id
    utente = models.OneToOneField(
        UtenteLegacy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="utente_id",
        related_name="anagrafica",
    )

    class Meta(LegacyUnmanagedModel.Meta):
        db_table = "anagrafica_dipendenti"
        app_label = "legacy_runtime"

    def __str__(self) -> str:
        return f"{self.cognome} {self.nome}".strip() or self.aliasusername or f"anagrafica:{self.id}"


class Pulsante(LegacyUnmanagedModel):
    id = models.AutoField(primary_key=True)
    codice = models.CharField(max_length=100)
    nome_visibile = models.CharField(max_length=200, blank=True, null=True)
    icona = models.CharField(max_length=20, blank=True, null=True)
    modulo = models.CharField(max_length=100)
    url = models.CharField(max_length=500)

    class Meta(LegacyUnmanagedModel.Meta):
        db_table = "pulsanti"
        app_label = "legacy_runtime"

    @property
    def label(self) -> str:
        return (self.nome_visibile or self.codice or "").strip() or "N/D"


class Permesso(LegacyUnmanagedModel):
    id = models.AutoField(primary_key=True)
    modulo = models.CharField(max_length=100)
    azione = models.CharField(max_length=100)
    ruolo_id = models.IntegerField()
    consentito = models.IntegerField(blank=True, null=True)
    can_view = models.IntegerField(blank=True, null=True)
    can_edit = models.IntegerField(blank=True, null=True)
    can_delete = models.IntegerField(blank=True, null=True)
    can_approve = models.IntegerField(blank=True, null=True)

    class Meta(LegacyUnmanagedModel.Meta):
        db_table = "permessi"
        app_label = "legacy_runtime"

    @property
    def view_allowed(self) -> bool:
        return bool(self.can_view) or bool(self.consentito)
