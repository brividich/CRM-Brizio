import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import DatabaseError, models


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    legacy_user_id = models.IntegerField(unique=True)
    legacy_ruolo_id = models.IntegerField(null=True, blank=True)
    legacy_ruolo = models.CharField(max_length=100, blank=True, default="")

    def __str__(self) -> str:
        return f"Profile<{self.user_id}:{self.legacy_user_id}>"


class UserPermissionOverride(models.Model):
    """Override permessi per-utente. None = usa il ruolo, True/False = valore esplicito."""
    legacy_user_id = models.IntegerField(db_index=True)
    modulo = models.CharField(max_length=100)
    azione = models.CharField(max_length=100)
    can_view = models.BooleanField(null=True)
    can_edit = models.BooleanField(null=True)
    can_delete = models.BooleanField(null=True)
    can_approve = models.BooleanField(null=True)

    class Meta:
        unique_together = [("legacy_user_id", "modulo", "azione")]

    def __str__(self) -> str:
        return f"Override<user={self.legacy_user_id} {self.modulo}/{self.azione}>"

    def all_null(self) -> bool:
        return all(v is None for v in [self.can_view, self.can_edit, self.can_delete, self.can_approve])


PERMISSION_CODE_VALIDATOR = RegexValidator(
    regex=r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$",
    message="Usa solo lettere minuscole, numeri e separatori . _ : - (es. assenze.view).",
)
PERMISSION_CODE_CANONICAL_RE = re.compile(
    r"^[a-z0-9]+(?:_[a-z0-9]+)*(?:\.[a-z0-9]+(?:_[a-z0-9]+)*){2,}$"
)
PERMISSION_CODE_CONVENTION_HINT = (
    "Usa la convenzione modulo.risorsa.azione "
    "(es. admin_portale.users.view, assets.work_orders.manage)."
)


class PermissionDefinition(models.Model):
    """Catalogo canonico dei permessi applicativi."""

    code = models.CharField(max_length=120, unique=True, validators=[PERMISSION_CODE_VALIDATOR], db_index=True)
    label = models.CharField(max_length=160)
    module = models.CharField(max_length=80, db_index=True)
    description = models.CharField(max_length=500, blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module", "code"]
        verbose_name = "Permission Definition"
        verbose_name_plural = "Permission Definitions"

    def __str__(self) -> str:
        return f"{self.code} ({self.label})"

    def clean(self):
        super().clean()
        self.code = str(self.code or "").strip().lower()
        self.module = str(self.module or "").strip().lower()
        if self.code and not PERMISSION_CODE_CANONICAL_RE.match(self.code):
            raise ValidationError({"code": PERMISSION_CODE_CONVENTION_HINT})


class RolePermissionGrant(models.Model):
    """Grant canonico ruolo -> permission_code."""

    legacy_role_id = models.IntegerField(db_index=True)
    permission = models.ForeignKey(
        PermissionDefinition,
        to_field="code",
        db_column="permission_code",
        on_delete=models.CASCADE,
        related_name="role_grants",
    )
    enabled = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("legacy_role_id", "permission")]
        ordering = ["legacy_role_id", "permission_id"]
        verbose_name = "Role Permission Grant"
        verbose_name_plural = "Role Permission Grants"

    def __str__(self) -> str:
        return f"RoleGrant<role={self.legacy_role_id} code={self.permission_id} enabled={self.enabled}>"


class UserPermissionGrant(models.Model):
    """Override canonico per-utente su permission_code."""

    legacy_user_id = models.IntegerField(db_index=True)
    permission = models.ForeignKey(
        PermissionDefinition,
        to_field="code",
        db_column="permission_code",
        on_delete=models.CASCADE,
        related_name="user_grants",
    )
    enabled = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("legacy_user_id", "permission")]
        ordering = ["legacy_user_id", "permission_id"]
        verbose_name = "User Permission Grant"
        verbose_name_plural = "User Permission Grants"

    def __str__(self) -> str:
        return f"UserGrant<user={self.legacy_user_id} code={self.permission_id} enabled={self.enabled}>"


class RoutePermissionBinding(models.Model):
    """Mappa route/path applicative al permesso canonico richiesto."""

    MATCH_EXACT = "exact"
    MATCH_PREFIX = "prefix"
    MATCH_REGEX = "regex"
    MATCH_CHOICES = [
        (MATCH_EXACT, "Exact"),
        (MATCH_PREFIX, "Prefix"),
        (MATCH_REGEX, "Regex"),
    ]

    route_name = models.CharField(max_length=160, blank=True, default="", db_index=True)
    path_pattern = models.CharField(max_length=500, blank=True, default="", db_index=True)
    match_strategy = models.CharField(max_length=12, choices=MATCH_CHOICES, default=MATCH_EXACT, db_index=True)
    permission = models.ForeignKey(
        PermissionDefinition,
        to_field="code",
        db_column="permission_code",
        on_delete=models.CASCADE,
        related_name="route_bindings",
    )
    source_app = models.CharField(max_length=80, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")
    priority = models.PositiveIntegerField(default=100, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("route_name", "path_pattern")]
        ordering = ["priority", "route_name", "path_pattern", "id"]
        verbose_name = "Route Permission Binding"
        verbose_name_plural = "Route Permission Bindings"

    def __str__(self) -> str:
        target = self.route_name or self.path_pattern or "<?>"
        return f"RouteBinding<{target} -> {self.permission_id}>"

    def clean(self):
        route_name = (self.route_name or "").strip()
        path_pattern = (self.path_pattern or "").strip()
        if not route_name and not path_pattern:
            raise ValidationError("Specifica almeno route_name o path_pattern.")
        if path_pattern and not path_pattern.startswith("/") and self.match_strategy != self.MATCH_REGEX:
            raise ValidationError("path_pattern deve iniziare con '/'.")

class UserDashboardConfig(models.Model):
    """Visibilità pulsanti dashboard per-utente (override rispetto al ruolo)."""
    legacy_user_id = models.IntegerField(db_index=True)
    pulsante_id = models.IntegerField()
    visible = models.BooleanField(default=True)

    class Meta:
        unique_together = [("legacy_user_id", "pulsante_id")]

    def __str__(self) -> str:
        return f"DashConfig<user={self.legacy_user_id} pid={self.pulsante_id} visible={self.visible}>"


class UserModuleVisibility(models.Model):
    """Visibilità di un intero modulo dashboard per-utente.

    Se visible=False, tutti i pulsanti di quel modulo sono nascosti dalla dashboard.
    """
    legacy_user_id = models.IntegerField(db_index=True)
    modulo = models.CharField(max_length=100)
    visible = models.BooleanField(default=True)

    class Meta:
        unique_together = [("legacy_user_id", "modulo")]

    def __str__(self) -> str:
        return f"ModuleVis<user={self.legacy_user_id} modulo={self.modulo} visible={self.visible}>"


class UserDashboardLayout(models.Model):
    """Layout dashboard per-utente (ordine card e ordine moduli)."""

    legacy_user_id = models.IntegerField(unique=True, db_index=True)
    layout = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"DashLayout<user={self.legacy_user_id}>"


class ModuleCategory(models.Model):
    """Categoria per raggruppare moduli di navigazione con colore topbar dedicato."""

    key = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=80)
    icon = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Alias SVG (es. shield-check), emoji, testo breve o URL immagine (.ico, .png, .svg) mostrato nella sidebar per la categoria.",
    )
    topbar_color = models.CharField(
        max_length=20, default="#1e3a5f",
        help_text="Colore esadecimale background topbar (es. #1e3a5f).",
    )
    order = models.IntegerField(default=100)

    class Meta:
        ordering = ["order", "label"]
        verbose_name = "Categoria modulo"
        verbose_name_plural = "Categorie moduli"

    def __str__(self) -> str:
        return f"{self.label} ({self.key})"


class NavigationItem(models.Model):
    """Voce di navigazione gestita da Django (topbar o altre sezioni UI)."""

    code = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    section = models.CharField(max_length=40, default="topbar", db_index=True)
    parent_code = models.CharField(
        max_length=80, blank=True, default="", db_index=True,
        help_text="Solo per section='subnav': codice del gruppo (es. 'dashboard', 'assenze', 'anagrafica').",
    )
    route_name = models.CharField(max_length=120, blank=True, default="")
    url_path = models.CharField(max_length=500, blank=True, default="")
    order = models.IntegerField(default=100)
    is_visible = models.BooleanField(default=True)
    is_enabled = models.BooleanField(default=True)
    open_in_new_tab = models.BooleanField(default=False)
    icon = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Alias SVG (es. newspaper), emoji, testo breve o URL immagine (.ico, .png, .svg) mostrato accanto alla label.",
    )
    group = models.CharField(
        max_length=80, blank=True, default="",
        help_text="Gruppo visivo per separatori nella subnav (es. accessi, navigazione, hub). Voci con stesso gruppo sono raggruppate.",
    )
    active_patterns = models.CharField(
        max_length=500, blank=True, default="",
        help_text="View name Django separati da virgola per rilevamento stato attivo (es. admin_portale:utenti_list,admin_portale:utente_edit). Lascia vuoto per usare solo l'URL.",
    )
    description = models.CharField(max_length=500, blank=True, default="")
    category = models.ForeignKey(
        "ModuleCategory",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="nav_items",
        help_text="Categoria del modulo (determina il colore topbar quando questa voce è attiva).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nav_items_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nav_items_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "order", "label", "id"]

    def __str__(self) -> str:
        target = self.route_name or self.url_path or "-"
        return f"NavItem<{self.code}:{target}>"


class NavigationRoleAccess(models.Model):
    """Abilitazione voce menu per ruolo legacy.

    Se non esistono record per una voce, la voce e' visibile a tutti i ruoli.
    """

    item = models.ForeignKey(NavigationItem, on_delete=models.CASCADE, related_name="role_accesses")
    legacy_role_id = models.IntegerField(db_index=True)
    can_view = models.BooleanField(default=True)

    class Meta:
        unique_together = [("item", "legacy_role_id")]

    def __str__(self) -> str:
        return f"NavAccess<item={self.item_id} role={self.legacy_role_id} can_view={self.can_view}>"


class NavigationSnapshot(models.Model):
    """Snapshot pubblicato della configurazione menu per rollback veloce."""

    version = models.PositiveIntegerField(db_index=True)
    payload = models.JSONField(default=dict)
    note = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nav_snapshots_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-id"]

    def __str__(self) -> str:
        return f"NavSnapshot<v{self.version}>"


class UserNavigationOverride(models.Model):
    """Override visibilità navigazione per-utente, indipendente dal ruolo.

    enabled=True  → forza MOSTRA (anche se il ruolo non lo vede)
    enabled=False → forza NASCONDI (anche se il ruolo lo vede)
    Nessun record → eredita dalla configurazione di ruolo.
    """

    legacy_user_id = models.IntegerField(db_index=True)
    item = models.ForeignKey(
        NavigationItem,
        on_delete=models.CASCADE,
        related_name="user_overrides",
    )
    enabled = models.BooleanField()
    note = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("legacy_user_id", "item")]
        ordering = ["legacy_user_id", "item__section", "item__order"]

    def __str__(self) -> str:
        state = "SHOW" if self.enabled else "HIDE"
        return f"NavOverride<user={self.legacy_user_id} item={self.item_id} {state}>"


class LegacyRedirect(models.Model):
    """Mappa redirect configurabile da URL legacy a route/path Django."""

    legacy_path = models.CharField(max_length=300, unique=True)
    target_route_name = models.CharField(max_length=120, blank=True, default="")
    target_url_path = models.CharField(max_length=500, blank=True, default="")
    is_enabled = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["legacy_path"]

    def __str__(self) -> str:
        return f"LegacyRedirect<{self.legacy_path}>"


class Notifica(models.Model):
    """Notifica in-app per un utente legacy (assenza approvata/rifiutata, ecc.)."""

    TIPI = [
        ("assenza_approvata", "Assenza approvata"),
        ("assenza_rifiutata", "Assenza rifiutata"),
        ("assenza_in_attesa", "Assenza in attesa di approvazione"),
        ("anomalia_segnalata", "Anomalia segnalata al cliente"),
        ("anomalia_chiusa", "Anomalia chiusa"),
        ("dpi_approvata", "DPI approvata"),
        ("dpi_rifiutata", "DPI rifiutata"),
        ("dpi_consegnata", "DPI consegnata"),
        ("generico", "Generico"),
    ]

    legacy_user_id = models.IntegerField(db_index=True)
    tipo = models.CharField(max_length=50, choices=TIPI, default="generico")
    messaggio = models.CharField(max_length=500)
    url_azione = models.CharField(max_length=255, blank=True, default="")
    letta = models.BooleanField(default=False)
    popup_shown = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Notifica<user={self.legacy_user_id} tipo={self.tipo} letta={self.letta}>"


class UserExtraInfo(models.Model):
    """Informazioni anagrafiche aggiuntive per utente (reparto, caporeparto, macchina, contatti).

    reparto è editabile dall'admin (può differire da anagrafica_dipendenti).
    macchina è placeholder per la futura gestione asset.
    """
    legacy_user_id = models.IntegerField(unique=True, db_index=True)
    reparto        = models.CharField(max_length=200, blank=True, default="")
    caporeparto    = models.CharField(max_length=200, blank=True, default="")
    macchina       = models.CharField(max_length=200, blank=True, default="", help_text="Macchina di utilizzo principale")
    telefono       = models.CharField(max_length=50,  blank=True, default="")
    cellulare      = models.CharField(max_length=50,  blank=True, default="")
    note           = models.TextField(blank=True, default="")
    updated_at     = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"UserExtraInfo<user={self.legacy_user_id}>"


_TIPI_CHECKLIST = [
    ("checkin",  "Check-in (Onboarding)"),
    ("checkout", "Check-out (Offboarding)"),
]

_TIPI_CAMPO = [
    ("check",  "Checkbox (fatto/non fatto)"),
    ("testo",  "Testo libero"),
    ("data",   "Data"),
    ("select", "Scelta da lista"),
]


class ChecklistVoce(models.Model):
    """Voce/campo configurabile per un tipo di checklist (globale, vale per tutti gli utenti)."""
    tipo_checklist = models.CharField(max_length=20, choices=_TIPI_CHECKLIST, db_index=True)
    categoria      = models.CharField(max_length=100, blank=True, default="Generale")
    label          = models.CharField(max_length=300)
    tipo_campo     = models.CharField(max_length=20, choices=_TIPI_CAMPO, default="check")
    scelte         = models.JSONField(default=list, blank=True, help_text="Solo per tipo_campo=select: lista di stringhe")
    obbligatorio   = models.BooleanField(default=False)
    ordine         = models.IntegerField(default=100)
    is_active      = models.BooleanField(default=True)

    class Meta:
        ordering = ["tipo_checklist", "ordine", "id"]

    def __str__(self) -> str:
        return f"ChecklistVoce<{self.tipo_checklist} #{self.ordine}: {self.label}>"


class ChecklistEsecuzione(models.Model):
    """Registrazione di un check-in o check-out effettuato per un dipendente."""
    legacy_user_id   = models.IntegerField(db_index=True)
    utente_nome      = models.CharField(max_length=200, blank=True, default="")
    tipo_checklist   = models.CharField(max_length=20, choices=_TIPI_CHECKLIST)
    data_esecuzione  = models.DateTimeField(auto_now_add=True)
    eseguita_da_id   = models.IntegerField(null=True, blank=True)
    eseguita_da_nome = models.CharField(max_length=200, blank=True, default="")
    note             = models.TextField(blank=True, default="")
    completata       = models.BooleanField(default=True)

    class Meta:
        ordering = ["-data_esecuzione"]

    def __str__(self) -> str:
        return f"ChecklistEsecuzione<user={self.legacy_user_id} {self.tipo_checklist} {self.data_esecuzione:%Y-%m-%d}>"


class ChecklistRisposta(models.Model):
    """Risposta a una singola voce in un'esecuzione checklist (snapshot label/tipo al momento)."""
    esecuzione = models.ForeignKey(ChecklistEsecuzione, on_delete=models.CASCADE, related_name="risposte")
    voce_id    = models.IntegerField()
    voce_label = models.CharField(max_length=300)
    voce_tipo  = models.CharField(max_length=20)
    valore     = models.TextField(blank=True, default="")
    # Convenzioni valore: "1"/"0" per check, stringa ISO date per data, testo libero, stringa per select

    def __str__(self) -> str:
        return f"ChecklistRisposta<esec={self.esecuzione_id} voce={self.voce_id}: {self.valore[:30]}>"


class EmployeeBoardConfig(models.Model):
    """Layout e configurazione widget scheda infografica dipendente per utente.

    layout: lista ordinata di widget_id (es. ["profilo", "tasks", "assenze_future", ...])
    widget_configs: dict keyed by widget_id con parametri configurabili per ogni widget.
    """
    legacy_user_id = models.IntegerField(unique=True, db_index=True)
    layout = models.JSONField(default=list, blank=True)
    widget_configs = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"EmployeeBoardConfig<user={self.legacy_user_id}>"


class EmployeeBoardTemplate(models.Model):
    """Template iniziale della scheda dipendente definito dagli admin."""

    key = models.CharField(max_length=50, unique=True, default="default")
    name = models.CharField(max_length=100, default="Template iniziale admin")
    layout = models.JSONField(default=list, blank=True)
    widget_configs = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_board_templates_updated",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return f"EmployeeBoardTemplate<{self.key}>"


class AuditLog(models.Model):
    """Traccia le azioni rilevanti nel portale per scopi di audit."""

    legacy_user_id = models.IntegerField(db_index=True, null=True, blank=True)
    utente_display = models.CharField(max_length=200, blank=True, default="")
    azione = models.CharField(max_length=100, db_index=True)
    modulo = models.CharField(max_length=100, db_index=True)
    dettaglio = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"AuditLog<{self.azione} {self.modulo} user={self.legacy_user_id}>"


# ── Anagrafica configurabile ──────────────────────────────────────────────────

class OptioneConfig(models.Model):
    """Opzioni configurabili per i campi dropdown dell'anagrafica utente.

    tipo può essere 'reparto', 'caporeparto', 'macchina' o qualsiasi chiave custom.
    """
    tipo      = models.CharField(max_length=50, db_index=True)
    valore    = models.CharField(max_length=200)
    legacy_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    ordine    = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["tipo", "ordine", "valore"]

    def __str__(self) -> str:
        return f"OptioneConfig<{self.tipo}: {self.valore}>"


class AnagraficaVoce(models.Model):
    """Campo extra configurabile per l'anagrafica utente (analogo a ChecklistVoce).

    Permette all'admin di aggiungere campi personalizzati (testo, data, select, ecc.)
    che vengono visualizzati nel tab Anagrafica della scheda utente.
    """
    categoria    = models.CharField(max_length=100, blank=True, default="Campi extra")
    label        = models.CharField(max_length=300)
    tipo_campo   = models.CharField(max_length=20, choices=_TIPI_CAMPO, default="testo")
    scelte       = models.JSONField(default=list, blank=True, help_text="Solo per tipo_campo=select: lista di stringhe")
    obbligatorio = models.BooleanField(default=False)
    ordine       = models.IntegerField(default=100)
    is_active    = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "id"]

    def __str__(self) -> str:
        return f"AnagraficaVoce<#{self.ordine}: {self.label}>"


class AnagraficaRisposta(models.Model):
    """Valore di un campo extra anagrafica per un determinato utente."""
    legacy_user_id = models.IntegerField(db_index=True)
    voce           = models.ForeignKey(AnagraficaVoce, on_delete=models.CASCADE, related_name="risposte")
    valore         = models.TextField(blank=True, default="")
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("legacy_user_id", "voce")]

    def __str__(self) -> str:
        return f"AnagraficaRisposta<user={self.legacy_user_id} voce={self.voce_id}: {self.valore[:30]}>"


class RepartoCapoMapping(models.Model):
    """Associazione reparto → caporeparto (nome stringa).

    Quando un utente viene assegnato a un reparto, il portale usa questa
    tabella per auto-popolare il campo caporeparto in UserExtraInfo.
    Una stessa voce caporeparto può coprire più reparti.
    """
    reparto     = models.CharField(max_length=200, db_index=True)
    caporeparto = models.CharField(max_length=200)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["reparto"]
        unique_together = [("reparto", "caporeparto")]
        verbose_name = "Associazione reparto → capo reparto"
        verbose_name_plural = "Associazioni reparto → capo reparto"

    def __str__(self) -> str:
        return f"RepartoCapoMapping<{self.reparto} → {self.caporeparto}>"


class SiteConfig(models.Model):
    """Configurazione globale del portale (key-value).

    Usato per personalizzare aspetti come la pagina di login, il titolo del sito, ecc.
    senza toccare il codice. Le chiavi sono stringhe libere (es. 'login_titolo').
    """
    chiave      = models.CharField(max_length=100, unique=True, db_index=True)
    valore      = models.TextField(blank=True, default="")
    descrizione = models.CharField(max_length=300, blank=True, default="")
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chiave"]

    def __str__(self) -> str:
        return f"SiteConfig<{self.chiave}>"

    @classmethod
    def get_many(cls, defaults: dict[str, str]) -> dict[str, str]:
        result = dict(defaults or {})
        if not result:
            return result
        try:
            rows = list(
                cls.objects.filter(chiave__in=list(result.keys())).values_list("chiave", "valore")
            )
        except DatabaseError:
            return result
        for chiave, valore in rows:
            result[chiave] = valore
        return result

    @classmethod
    def get(cls, chiave: str, default: str = "") -> str:
        try:
            return cls.objects.get(chiave=chiave).valore
        except (cls.DoesNotExist, DatabaseError):
            return default

    @classmethod
    def set(cls, chiave: str, valore: str, descrizione: str = "") -> bool:
        try:
            cls.objects.update_or_create(
                chiave=chiave,
                defaults={"valore": valore, "descrizione": descrizione},
            )
        except DatabaseError:
            return False
        return True


class LoginBanner(models.Model):
    """Banner di avviso visualizzato nella pagina di login.

    Permette all'admin di mostrare messaggi colorati (info, warning, danger, success)
    ordinabili e attivabili/disattivabili singolarmente.
    """
    TIPO_CHOICES = [
        ("info",    "Informazione (blu)"),
        ("warning", "Attenzione (giallo)"),
        ("danger",  "Errore / blocco (rosso)"),
        ("success", "Successo / ok (verde)"),
    ]
    testo     = models.TextField()
    tipo      = models.CharField(max_length=20, choices=TIPO_CHOICES, default="info")
    ordine    = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordine", "id"]

    def __str__(self) -> str:
        return f"LoginBanner<{self.tipo}: {self.testo[:40]}>"


class UserUiPreference(models.Model):
    """Preferenze interfaccia per-utente: modalità navigazione, scala font, stato sidebar.

    Separata dal modello Profile per non mescolare dati anagrafici con configurazione UI.
    Record creato solo al primo salvataggio esplicito; fino ad allora si usano i default.
    """

    NAV_MODE_CHOICES = [("top", "Barra superiore"), ("side", "Barra laterale")]
    FONT_SCALE_CHOICES = [
        ("small", "Piccolo"),
        ("normal", "Normale"),
        ("large", "Grande"),
        ("xl", "Molto grande"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ui_prefs",
    )
    nav_mode = models.CharField(max_length=4, choices=NAV_MODE_CHOICES, default="top")
    font_scale = models.CharField(max_length=6, choices=FONT_SCALE_CHOICES, default="normal")
    sidebar_collapsed = models.BooleanField(default=False)
    sidebar_footer_actions = models.JSONField(
        default=None,
        null=True,
        blank=True,
        help_text="Ordine personalizzato delle azioni rapide nel footer della sidebar. Null = ordine predefinito.",
    )

    class Meta:
        db_table = "core_useruipreference"
        verbose_name = "Preferenza interfaccia"
        verbose_name_plural = "Preferenze interfaccia"

    def __str__(self) -> str:
        return f"UserUiPreference(user={self.user_id}, nav={self.nav_mode}, scale={self.font_scale})"
