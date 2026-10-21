import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import DatabaseError, models
from django.urls import NoReverseMatch, reverse

from core.hub_bacheca_storage import HubLinkStorage


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
    """Voce di navigazione gestita da Django (topbar o altre sezioni UI).

    REGOLA PER LE MIGRATION DI SEED:
    - Usare SEMPRE get_or_create(code=..., defaults={...}) — imposta i campi solo alla
      creazione del record; non sovrascrive mai le personalizzazioni fatte dal NavBuilder.
    - NON usare update_or_create: riscrive tutti i defaults su record esistenti, cancellando
      label, icona, ordine e visibilità che l'utente ha configurato via NavBuilder UI.
    - Per aggiornare un singolo campo strutturale su record esistenti (es. route_name
      rinominata, required_permission_code aggiunto) usare:
          NavigationItem.objects.filter(code="...").update(campo=valore)
      in modo da toccare solo il campo necessario.

    Campi "di codice" (aggiornabili in migration): route_name, url_path, section,
      required_permission_code, active_patterns.
    Campi "dell'utente" (solo get_or_create, mai update_or_create): label, icon,
      description, order, group, is_visible, is_enabled, open_in_new_tab.
    """

    code = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    section = models.CharField(max_length=40, default="topbar", db_index=True)
    parent_code = models.CharField(
        max_length=80, blank=True, default="", db_index=True,
        help_text="Solo per section='subnav': codice del gruppo (es. 'dashboard', 'assenze', 'anagrafica').",
    )
    route_name = models.CharField(max_length=120, blank=True, default="")
    url_path = models.CharField(max_length=500, blank=True, default="")
    required_permission_code = models.CharField(
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Permission code canonico richiesto per mostrare la voce. "
            "Se vuoto, il registry prova a ricavarlo da route_name/url_path."
        ),
    )
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
        ("anomalia_da_gestire", "Anomalia da gestire (OP da controllare)"),
        ("dpi_approvata", "DPI approvata"),
        ("dpi_rifiutata", "DPI rifiutata"),
        ("dpi_consegnata", "DPI consegnata"),
        ("dpi_scadenza", "DPI in scadenza"),
        ("ticket_sla", "SLA ticket scaduto"),
        ("asset_scadenza", "Scadenza asset"),
        ("generico", "Generico"),
    ]

    ARCHIVIO_MOTIVI = [
        ("scadenza_non_letta", "Non letta entro la scadenza"),
        ("scadenza_letta", "Letta da tempo"),
        ("utente", "Archiviata dall'utente"),
        ("admin", "Archiviata dall'amministratore"),
    ]

    legacy_user_id = models.IntegerField(db_index=True)
    tipo = models.CharField(max_length=50, choices=TIPI, default="generico")
    messaggio = models.CharField(max_length=500)
    url_azione = models.CharField(max_length=255, blank=True, default="")
    letta = models.BooleanField(default=False)
    letta_il = models.DateTimeField(null=True, blank=True)
    popup_shown = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # Archivio: la notifica esce da campanella/badge/banner ma resta consultabile
    # in «Notifiche → Archiviate» (vedi core.notifiche_archivio).
    archiviata = models.BooleanField(default=False, db_index=True)
    archiviata_il = models.DateTimeField(null=True, blank=True)
    archiviata_motivo = models.CharField(max_length=30, choices=ARCHIVIO_MOTIVI, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["legacy_user_id", "archiviata", "letta"], name="core_notif_user_stato_idx"),
        ]

    def __str__(self) -> str:
        return f"Notifica<user={self.legacy_user_id} tipo={self.tipo} letta={self.letta}>"


class NotificaCanali(models.Model):
    """Dove recapitare le notifiche oltre alla campanella, scelto dall'utente.

    La campanella (``Notifica``) resta sempre: qui l'utente aggiunge la notifica
    push sul telefono/PC per categoria e il riepilogo mattutino delle scadenze
    via mail. Le categorie sono ``core.notifiche_meta.CATEGORIE``: una categoria
    spenta (dall'admin o dall'utente) non produce né campanella né push.
    Record creato al primo salvataggio; fino ad allora tutto spento.
    """

    DIGEST_GIORNI_CHOICES = [(7, "Scadute e prossimi 7 giorni"), (30, "Scadute e prossimi 30 giorni")]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifiche_canali",
    )
    push_categorie = models.JSONField(
        default=list,
        blank=True,
        help_text="Categorie (core.notifiche_meta.CATEGORIE) per cui inviare anche la notifica push.",
    )
    digest_scadenze = models.BooleanField(default=False)
    digest_giorni = models.PositiveSmallIntegerField(default=7, choices=DIGEST_GIORNI_CHOICES)
    digest_ultimo_invio = models.DateField(null=True, blank=True)
    # Le scadenze dello Scadenzario in un calendario Outlook della persona
    # (dashboard/scadenze_outlook.py): id del calendario, ultimo allineamento, ultimo errore.
    outlook_scadenze = models.BooleanField(default=False)
    outlook_calendario_id = models.CharField(max_length=255, blank=True, default="")
    outlook_ultimo_sync = models.DateTimeField(null=True, blank=True)
    outlook_errore = models.CharField(max_length=300, blank=True, default="")
    # Avviso di accesso da un dispositivo nuovo (core/dispositivi.py) anche per mail.
    sicurezza_mail = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_notificacanali"
        verbose_name = "Canali notifiche utente"
        verbose_name_plural = "Canali notifiche utenti"

    def __str__(self) -> str:
        return f"NotificaCanali(user={self.user_id}, push={self.push_categorie}, digest={self.digest_scadenze})"

    def push_per_categoria(self, categoria: str) -> bool:
        cats = self.push_categorie if isinstance(self.push_categorie, list) else []
        return str(categoria or "") in cats


class DispositivoAccesso(models.Model):
    """Un browser/PC da cui la persona è entrata nel portale (``core.dispositivi``).

    ``token_hash`` è l'impronta SHA-256 del numero casuale nel cookie ``nh_dev``:
    il valore non si salva. ``non_riconosciuto``: la persona ha premuto «Non ero io».
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dispositivi_accesso")
    token_hash = models.CharField(max_length=64)
    etichetta = models.CharField(max_length=80, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")
    ip_primo = models.CharField(max_length=60, blank=True, default="")
    ip_ultimo = models.CharField(max_length=60, blank=True, default="")
    primo_accesso = models.DateTimeField()
    ultimo_accesso = models.DateTimeField()
    session_key = models.CharField(max_length=40, blank=True, default="")
    non_riconosciuto = models.BooleanField(default=False)
    segnalato_il = models.DateTimeField(null=True, blank=True)
    # Ultimo secondo fattore superato da questo browser (policy 2FA «dispositivi nuovi»).
    verificato_2fa_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_dispositivoaccesso"
        ordering = ["-ultimo_accesso"]
        constraints = [models.UniqueConstraint(fields=["user", "token_hash"], name="uniq_dispositivo_user_token")]
        verbose_name = "Dispositivo di accesso"
        verbose_name_plural = "Dispositivi di accesso"

    def __str__(self) -> str:
        return f"{self.user_id}: {self.etichetta}"


class ScadenzaOutlook(models.Model):
    """Una scadenza dello Scadenzario copiata come evento nel calendario Outlook di una persona.

    ``chiave`` identifica la voce (fonte, tipo, soggetto, titolo, link) senza la data:
    una scadenza spostata aggiorna lo stesso evento. ``impronta`` dice se l'evento va
    riscritto. ``rimosso_da_utente``: la persona l'ha cancellato in Outlook, quindi il
    portale non lo ricrea (si riazzera se la scadenza cambia data).
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scadenze_outlook")
    chiave = models.CharField(max_length=64)
    event_id = models.CharField(max_length=512, blank=True, default="")
    data_scadenza = models.DateField()
    impronta = models.CharField(max_length=64, blank=True, default="")
    rimosso_da_utente = models.BooleanField(default=False)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_scadenzaoutlook"
        constraints = [models.UniqueConstraint(fields=["user", "chiave"], name="uniq_scadenza_outlook_user_chiave")]
        verbose_name = "Scadenza nel calendario Outlook"
        verbose_name_plural = "Scadenze nel calendario Outlook"

    def __str__(self) -> str:
        return f"{self.user_id}:{self.chiave[:12]}"


class PushIscrizione(models.Model):
    """Un browser (telefono o PC) iscritto alle notifiche push di un utente.

    Le push partono **senza contenuto**: il servizio del produttore del browser
    (Google, Mozilla, Microsoft, Apple) riceve solo il segnale «c'è qualcosa»;
    il testo lo legge il browser dal portale, con la sessione dell'utente.
    L'``endpoint`` è accettato solo verso i servizi push noti (``core.push``).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_iscrizioni",
    )
    endpoint = models.TextField()
    # SHA-256 dell'endpoint: unico. L'endpoint (fino a ~800 caratteri) non può
    # stare in un indice univoco su SQL Server (limite 1700 byte della chiave).
    endpoint_hash = models.CharField(max_length=64, unique=True)
    dispositivo = models.CharField(max_length=200, blank=True, default="")
    attiva = models.BooleanField(default=True, db_index=True)
    errori_consecutivi = models.PositiveSmallIntegerField(default=0)
    ultimo_invio_ok = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_pushiscrizione"
        ordering = ["-created_at"]
        verbose_name = "Iscrizione push"
        verbose_name_plural = "Iscrizioni push"

    def __str__(self) -> str:
        return f"PushIscrizione(user={self.user_id}, attiva={self.attiva}, {self.dispositivo[:40]})"


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
    ("preposto_ispezione", "Ispezione periodica preposto"),
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

    # Aggancio al record toccato. Senza questi due campi l'audit risponde solo a
    # "chi ha fatto cosa, in quale modulo", mai a "cosa è successo a QUESTO
    # record" — la domanda che si fa davanti a una scheda. Sono testo e non una
    # FK generica di proposito: buona parte del portale lavora su tabelle legacy
    # senza modello Django, e un `ContentType` le lascerebbe fuori.
    oggetto_tipo = models.CharField(
        max_length=100, blank=True, default="", db_index=True,
        help_text="Etichetta del modello (es. «tickets.ticket») o chiave legacy concordata.",
    )
    oggetto_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True,
        help_text="Chiave primaria del record, come testo (le tabelle legacy non usano solo interi).",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # La query dello storico è sempre "questo oggetto, dal più recente":
            # senza l'indice composito diventa una scansione al crescere del log.
            models.Index(
                fields=["oggetto_tipo", "oggetto_id", "-created_at"],
                name="core_audit_oggetto_recenti",
            ),
        ]

    def __str__(self) -> str:
        return f"AuditLog<{self.azione} {self.modulo} user={self.legacy_user_id}>"


class AuditSigillo(models.Model):
    """Sigillo mensile dell'audit: catena di hash, un anello per mese.

    Copre le azioni esplicite (``log_action``, accessi, approvazioni, impostazioni),
    non le righe tecniche ``auto_*`` che la politica di archiviazione
    (``core.audit_archive``) può legittimamente ridurre o cancellare. Ogni sigillo
    contiene l'hash del precedente: cambiare o togliere una riga di un mese
    sigillato rompe quel sigillo e tutti i successivi (vedi ``core.audit_sigilli``).
    """

    mese = models.CharField(max_length=7, unique=True, help_text="AAAA-MM")
    righe = models.PositiveIntegerField(default=0)
    id_min = models.BigIntegerField(null=True, blank=True)
    id_max = models.BigIntegerField(null=True, blank=True)
    hash_righe = models.CharField(max_length=64)
    hash_precedente = models.CharField(max_length=64)
    hash_sigillo = models.CharField(max_length=64, unique=True)
    versione = models.PositiveSmallIntegerField(default=1)
    creato_il = models.DateTimeField(auto_now_add=True)
    export_ok = models.BooleanField(default=False)
    export_il = models.DateTimeField(null=True, blank=True)
    export_percorso = models.CharField(max_length=500, blank=True, default="")
    export_errore = models.CharField(max_length=500, blank=True, default="")
    verificato_il = models.DateTimeField(null=True, blank=True)
    verifica_ok = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ["mese"]
        verbose_name = "Sigillo audit mensile"
        verbose_name_plural = "Sigilli audit mensili"

    def __str__(self) -> str:
        return f"AuditSigillo<{self.mese} {self.righe} righe {self.hash_sigillo[:12]}>"


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
    THEME_MODE_CHOICES = [("light", "Chiaro"), ("dark", "Scuro")]
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
    theme_mode = models.CharField(max_length=5, choices=THEME_MODE_CHOICES, default="light")
    font_scale = models.CharField(max_length=6, choices=FONT_SCALE_CHOICES, default="normal")
    sidebar_collapsed = models.BooleanField(default=False)
    sidebar_footer_actions = models.JSONField(
        default=None,
        null=True,
        blank=True,
        help_text="Ordine personalizzato delle azioni rapide nel footer della sidebar. Null = ordine predefinito.",
    )
    # Home personalizzata (dashboard/views_home_portale.py): moduli preferiti,
    # stanza di apertura, riquadri nascosti, tour di benvenuto già visto.
    home_prefs = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "core_useruipreference"
        verbose_name = "Preferenza interfaccia"
        verbose_name_plural = "Preferenze interfaccia"

    def __str__(self) -> str:
        return (
            f"UserUiPreference(user={self.user_id}, nav={self.nav_mode}, "
            f"theme={self.theme_mode}, scale={self.font_scale})"
        )


class UserTablePreference(models.Model):
    """Preferenze per-utente per una tabella `fm-table` del portale.

    `table_id` è una stringa stabile assegnata via `data-table-id` sul `<table>`.
    Convenzione kebab/dot: `formazione.corsi.list`, `anagrafica.dipendenti.list`, ecc.

    `state_json` è il blob completo dello stato salvato dal JS fm-table-enhanced:
        {
          "visible": ["codice", "titolo", "stato"],      // colonne visibili (in ordine)
          "order":   ["codice", "titolo", "stato", ...], // ordine colonne (incl. nascoste)
          "sort":    [["titolo", "asc"], ["created_at", "desc"]],
          "filters": {"stato": "ATTIVO", "obbligatorio": "1"},
          "q":       "ricerca globale"
        }

    Vedi `docs/ai/TABELLE_PERSONALIZZABILI.md`.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="table_prefs",
    )
    table_id   = models.CharField(max_length=100, db_index=True)
    state_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_usertablepreference"
        unique_together = [("user", "table_id")]
        verbose_name = "Preferenza tabella"
        verbose_name_plural = "Preferenze tabelle"
        indexes = [models.Index(fields=["user", "table_id"])]

    def __str__(self) -> str:
        return f"UserTablePreference(user={self.user_id}, table={self.table_id})"


class UserOnboarding(models.Model):
    """Traccia il completamento del wizard di primo accesso per-utente.

    Il wizard raccoglie email di contatto, cellulare e preferenze notifiche.
    Può essere resettato da un admin per far riapparire il wizard all'utente.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="onboarding",
    )
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    skipped = models.BooleanField(
        default=False,
        help_text="Se True, il wizard non viene mostrato (utente esentato dall'admin).",
    )
    reset_at = models.DateTimeField(null=True, blank=True)
    reset_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    # Dati raccolti dal wizard
    email_contatto = models.EmailField(blank=True, default="")
    cellulare_contatto = models.CharField(max_length=50, blank=True, default="")
    # Preferenze notifiche: dict tipo → bool, es. {"assenze": True, "comunicazioni": False}
    # Tipi standard: "assenze", "comunicazioni", "scadenzari", "ticket"
    # Aggiungere nuovi tipi qui non richiede migration, solo il toggle nel wizard.
    notifiche_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Preferenze notifiche email per tipo. Es: {\"assenze\": true, \"ticket\": false}",
    )

    class Meta:
        db_table = "core_useronboarding"
        verbose_name = "Onboarding utente"
        verbose_name_plural = "Onboarding utenti"

    def __str__(self) -> str:
        stato = "completato" if self.completed else ("esentato" if self.skipped else "pending")
        return f"UserOnboarding(user={self.user_id}, stato={stato})"

    @classmethod
    def get_or_create_for(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj

    def is_done(self) -> bool:
        """True se l'utente non deve più vedere il wizard."""
        return self.completed or self.skipped

    def get_notifica(self, tipo: str, default: bool = True) -> bool:
        """Restituisce la preferenza per un tipo di notifica (default True se non impostato)."""
        cfg = self.notifiche_config if isinstance(self.notifiche_config, dict) else {}
        return bool(cfg.get(tipo, default))

    @classmethod
    def should_send_email(cls, user, tipo: str, default: bool = True) -> bool:
        """Controlla se inviare un'email di tipo `tipo` all'utente Django dato.

        Restituisce True (invia) se:
        - non esiste un record UserOnboarding per l'utente (fail-open)
        - l'onboarding non è stato completato (l'utente non ha espresso preferenze)
        - la preferenza per `tipo` è True o non impostata

        Restituisce False (non inviare) solo se l'utente ha esplicitamente
        disabilitato quel tipo di notifica durante il wizard.
        """
        try:
            onb = cls.objects.filter(user=user).first()
            if onb is None or not onb.completed:
                return default
            return onb.get_notifica(tipo, default)
        except Exception:
            return default  # fail-open: in caso di errore DB, invia sempre


class ActionItem(models.Model):
    """Azione Correttiva/Preventiva (CAPA) trasversale ai moduli.

    Collega un'azione di rimedio a un evento di origine (incidente, near-miss,
    segnalazione preposto, anomalia, ticket, ispezione, ...) tramite la coppia
    ``(source_code, source_pk)`` — lo stesso schema usato da
    ``automation_event_queue``. Vive in ``core`` per evitare dipendenze cicliche
    tra i moduli di dominio che la generano e la consultano.

    Workflow: APERTA → IN_CORSO → CHIUSA (con evidenza) → VERIFICATA.
    La chiusura (chi esegue) è volutamente separata dalla verifica (chi controlla):
    sono due passi e due persone diverse (principio dei quattro occhi).
    """

    TIPO_CORRETTIVA = "CORRETTIVA"
    TIPO_PREVENTIVA = "PREVENTIVA"
    TIPO_CHOICES = [
        (TIPO_CORRETTIVA, "Correttiva"),
        (TIPO_PREVENTIVA, "Preventiva"),
    ]

    STATO_APERTA = "APERTA"
    STATO_IN_CORSO = "IN_CORSO"
    STATO_CHIUSA = "CHIUSA"
    STATO_VERIFICATA = "VERIFICATA"
    STATO_ANNULLATA = "ANNULLATA"
    STATO_CHOICES = [
        (STATO_APERTA, "Aperta"),
        (STATO_IN_CORSO, "In corso"),
        (STATO_CHIUSA, "Chiusa (da verificare)"),
        (STATO_VERIFICATA, "Verificata"),
        (STATO_ANNULLATA, "Annullata"),
    ]
    # Stati che NON contano più come "azione aperta" (no scadenza, no reminder).
    STATI_CONCLUSI = (STATO_VERIFICATA, STATO_ANNULLATA)

    # Etichette leggibili per le origini note. Il valore = `source_code`
    # coerente con automazioni/source_registry; "manuale" per gli inserimenti
    # diretti dalla lista CAPA.
    ORIGINE_MANUALE = "manuale"
    ORIGINE_LABELS = {
        "rilevazione_incidenti": "Incidente / Near-miss",
        "diario_preposto": "Segnalazione preposto",
        "anomalie": "Anomalia",
        "tickets": "Ticket",
        "audit": "Audit / Ispezione",
        ORIGINE_MANUALE: "Inserimento manuale",
    }

    titolo = models.CharField(max_length=255)
    descrizione = models.TextField(blank=True, default="")
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_CORRETTIVA)
    stato = models.CharField(max_length=20, choices=STATO_CHOICES, default=STATO_APERTA, db_index=True)

    # Origine: coppia (source_code, source_pk) come automation_event_queue.
    # source_pk è testuale per accogliere sia pk interi sia id SharePoint stringa.
    source_code = models.CharField(max_length=64, blank=True, default=ORIGINE_MANUALE, db_index=True)
    source_pk = models.CharField(max_length=64, blank=True, default="")
    source_label = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Descrizione leggibile dell'origine (snapshot al momento della creazione).",
    )
    source_url = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Link al record di origine nel modulo sorgente.",
    )

    responsabile = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="capa_assegnate",
    )
    reparto = models.CharField(max_length=200, blank=True, default="")
    data_scadenza = models.DateField(null=True, blank=True, db_index=True)

    # Chiusura (esecuzione del rimedio) — richiede evidenza.
    evidenza_chiusura = models.TextField(
        blank=True, default="",
        help_text="Descrizione di cosa è stato fatto per risolvere (obbligatoria alla chiusura).",
    )
    chiusa_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="capa_chiuse",
    )
    data_chiusura = models.DateTimeField(null=True, blank=True)

    # Verifica di efficacia — passo separato, persona diversa.
    verificata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="capa_verificate",
    )
    data_verifica = models.DateTimeField(null=True, blank=True)
    note_verifica = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="capa_create",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_actionitem"
        ordering = ["-created_at"]
        verbose_name = "Azione correttiva/preventiva (CAPA)"
        verbose_name_plural = "Azioni correttive/preventive (CAPA)"
        indexes = [
            models.Index(fields=["source_code", "source_pk"]),
            models.Index(fields=["stato", "data_scadenza"]),
        ]

    def __str__(self) -> str:
        return f"CAPA#{self.pk} [{self.stato}] {self.titolo}"

    @property
    def is_conclusa(self) -> bool:
        return self.stato in self.STATI_CONCLUSI

    @property
    def is_aperta(self) -> bool:
        """True se l'azione è ancora da lavorare (concorre a scadenze/reminder)."""
        return self.stato in (self.STATO_APERTA, self.STATO_IN_CORSO, self.STATO_CHIUSA)

    @property
    def origine_label(self) -> str:
        return self.ORIGINE_LABELS.get(self.source_code, self.source_code or "—")


class HubLinkCategory(models.Model):
    """Categoria della bacheca 'Documenti & Collegamenti' (gestita da admin).

    ``sezione`` decide dove la categoria compare nella home: tra i documenti
    aziendali o nello scaffale «Risorse self-help» (guide, manuali, video),
    dove ogni voce ha una copertina col ``colore`` della categoria.
    """

    SEZIONE_DOCUMENTI = "documenti"
    SEZIONE_SELF_HELP = "self_help"
    SEZIONE_CHOICES = [
        (SEZIONE_DOCUMENTI, "Documenti & collegamenti"),
        (SEZIONE_SELF_HELP, "Risorse self-help"),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    icon = models.CharField(max_length=500, blank=True, default="",
                            help_text="Emoji, alias SVG o URL immagine.")
    description = models.CharField(max_length=255, blank=True, default="")
    sezione = models.CharField(max_length=16, choices=SEZIONE_CHOICES, default=SEZIONE_DOCUMENTI)
    colore = models.CharField(max_length=7, blank=True, default="",
                              help_text="Colore delle copertine self-help, es. #1f4f86.")
    order = models.IntegerField(default=100)
    is_visible = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="hub_categories_created")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="hub_categories_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name", "id"]

    def __str__(self) -> str:
        return f"HubCat<{self.slug}>"


class HubLink(models.Model):
    """Voce della bacheca: documento caricato, collegamento esterno o scorciatoia interna."""

    KIND_FILE = "file"
    KIND_URL = "url"
    KIND_INTERNAL = "internal"
    KIND_CHOICES = [
        (KIND_FILE, "Documento"),
        (KIND_URL, "Collegamento esterno"),
        (KIND_INTERNAL, "Scorciatoia interna"),
    ]

    category = models.ForeignKey(HubLinkCategory, on_delete=models.CASCADE, related_name="links")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=300, blank=True, default="")
    icon = models.CharField(max_length=500, blank=True, default="")
    sigla = models.CharField(max_length=8, blank=True, default="",
                             help_text="Testo grande della copertina self-help (es. VPN, 2FA). Vuoto = dal titolo.")
    # target per kind:
    url = models.CharField(max_length=500, blank=True, default="")            # kind=url
    route_name = models.CharField(max_length=160, blank=True, default="")     # kind=internal
    route_kwargs = models.JSONField(default=dict, blank=True)                 # kind=internal (opzionale)
    file = models.FileField(storage=HubLinkStorage(), upload_to="hub_links/%Y/%m",
                            blank=True, null=True)                            # kind=file
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file_size = models.PositiveIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=120, blank=True, default="")
    open_in_new_tab = models.BooleanField(default=False)
    order = models.IntegerField(default=100)
    is_visible = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="hub_links_created")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="hub_links_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title", "id"]

    def __str__(self) -> str:
        return f"HubLink<{self.kind}:{self.title}>"

    def clean(self):
        if self.kind == self.KIND_URL:
            if not (self.url or "").strip():
                raise ValidationError({"url": "URL obbligatorio per un collegamento esterno."})
        elif self.kind == self.KIND_INTERNAL:
            if not (self.route_name or "").strip():
                raise ValidationError({"route_name": "Nome route obbligatorio per una scorciatoia interna."})
        elif self.kind == self.KIND_FILE:
            if not self.file:
                raise ValidationError({"file": "File obbligatorio per un documento."})
        else:
            raise ValidationError({"kind": "Tipo non valido."})

    @property
    def sigla_copertina(self) -> str:
        """Sigla scritta sulla copertina: quella impostata, altrimenti le iniziali del titolo."""
        if (self.sigla or "").strip():
            return self.sigla.strip()[:8]
        parole = [p for p in (self.title or "").replace("-", " ").split() if p[:1].isalnum()]
        if not parole:
            return "?"
        if len(parole) == 1:
            return parole[0][:4].upper()
        return "".join(p[0] for p in parole[:3]).upper()

    def resolve_href(self) -> str:
        if self.kind == self.KIND_URL:
            return self.url or "#"
        if self.kind == self.KIND_INTERNAL:
            try:
                return reverse(self.route_name, kwargs=self.route_kwargs or None)
            except NoReverseMatch:
                return "#"
        if self.kind == self.KIND_FILE:
            try:
                return reverse("hub_link_download", args=[self.pk])
            except NoReverseMatch:
                return "#"
        return "#"


class HubLinkRoleAccess(models.Model):
    """Visibilità per ruolo di una voce bacheca (come NavigationRoleAccess).

    Nessun record per una voce ⇒ visibile a TUTTI i ruoli.
    """

    link = models.ForeignKey(HubLink, on_delete=models.CASCADE, related_name="role_accesses")
    legacy_role_id = models.IntegerField(db_index=True)
    can_view = models.BooleanField(default=True)

    class Meta:
        unique_together = [("link", "legacy_role_id")]

    def __str__(self) -> str:
        return f"HubLinkAccess<link={self.link_id} role={self.legacy_role_id}>"


# ---------------------------------------------------------------------------
# Gruppi di accesso (ACL v2) - appartenenza multipla con indice di priorita'
# ---------------------------------------------------------------------------

ACCESS_GROUP_CODE_VALIDATOR = RegexValidator(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    "Codice gruppo: minuscole, cifre e separatori . _ - (es. 'manutenzione').",
)


class AccessGroup(models.Model):
    """Gruppo di accesso: una persona puo' appartenere a piu' gruppi.

    Il ruolo legacy (``UtenteLegacy.ruolo_id``) resta uno solo per persona e non
    basta piu' quando gli stessi permessi vanno dati a insiemi trasversali
    (manutenzione, caporeparto, ...). ``priority`` e' l'indice di chi conta di
    piu': fra i gruppi che si esprimono sullo stesso permesso decide quello con
    priorita' piu' alta; a parita' vince il diniego.
    """

    code = models.CharField(max_length=80, unique=True, validators=[ACCESS_GROUP_CODE_VALIDATOR], db_index=True)
    label = models.CharField(max_length=160)
    description = models.CharField(max_length=500, blank=True, default="")
    priority = models.IntegerField(
        default=100,
        db_index=True,
        help_text="Piu' alto = pesa di piu' quando due gruppi dicono cose diverse.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    # Ruoli del portale (core.permessi): un gruppo e' un ruolo, ``priority`` e'
    # il suo ordine. I due flag valgono per tutti i moduli, presenti e futuri.
    amministratore = models.BooleanField(
        default=False,
        help_text="Chi ha questo ruolo e' amministratore del portale: vede e fa tutto.",
    )
    vede_tutto = models.BooleanField(
        default=False,
        help_text="Vede ed esporta i dati di tutti i moduli (es. Direzione), senza poter modificare.",
    )
    preset = models.CharField(
        max_length=40,
        blank=True,
        default="",
        db_index=True,
        help_text="Preset da cui nasce il ruolo (vuoto = ruolo creato a mano).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "label", "id"]
        verbose_name = "Gruppo di accesso"
        verbose_name_plural = "Gruppi di accesso"

    def __str__(self) -> str:
        return f"{self.label} ({self.code})"

    def clean(self):
        super().clean()
        self.code = str(self.code or "").strip().lower()


class AccessGroupMembership(models.Model):
    """Appartenenza di un utente legacy a un gruppo di accesso."""

    group = models.ForeignKey(AccessGroup, on_delete=models.CASCADE, related_name="memberships")
    legacy_user_id = models.IntegerField(db_index=True)
    note = models.CharField(max_length=255, blank=True, default="")
    # Utenti esterni (RSPP, medico, ente di certificazione): dal giorno dopo il
    # ruolo non conta piu' (core.permessi.scadenze). Vuoto = senza scadenza.
    scade_il = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("group", "legacy_user_id")]
        ordering = ["group_id", "legacy_user_id"]
        verbose_name = "Appartenenza a gruppo"
        verbose_name_plural = "Appartenenze a gruppi"

    def __str__(self) -> str:
        return f"Membership<group={self.group_id} user={self.legacy_user_id}>"


class GroupPermissionGrant(models.Model):
    """Grant canonico gruppo -> permission_code.

    Stesso schema di :class:`RolePermissionGrant`: ``enabled=False`` e' un
    diniego esplicito, l'assenza di riga e' silenzio (il gruppo non si esprime).
    """

    group = models.ForeignKey(AccessGroup, on_delete=models.CASCADE, related_name="permission_grants")
    permission = models.ForeignKey(
        PermissionDefinition,
        to_field="code",
        db_column="permission_code",
        on_delete=models.CASCADE,
        related_name="group_grants",
    )
    enabled = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("group", "permission")]
        ordering = ["group_id", "permission_id"]
        verbose_name = "Grant permesso di gruppo"
        verbose_name_plural = "Grant permessi di gruppo"

    def __str__(self) -> str:
        return f"GroupGrant<group={self.group_id} code={self.permission_id} enabled={self.enabled}>"


class RuoloPermessoModulo(models.Model):
    """Una cella della matrice dei ruoli: ruolo x modulo x azione -> visibilita'.

    Stessa regola dei grant: la riga che esiste e' una decisione (``consentito``
    True o False), l'assenza e' silenzio. Fra i ruoli di una persona decide
    quello con ordine (``AccessGroup.priority``) piu' alto che si esprime.
    """

    AMBITO_PROPRI = "propri"
    AMBITO_TEAM = "team"
    AMBITO_TUTTI = "tutti"
    AMBITO_CHOICES = [
        (AMBITO_PROPRI, "Propri"),
        (AMBITO_TEAM, "Propri e del team"),
        (AMBITO_TUTTI, "Tutti"),
    ]

    ruolo = models.ForeignKey(AccessGroup, on_delete=models.CASCADE, related_name="permessi_modulo")
    modulo = models.CharField(max_length=80, db_index=True)
    azione = models.CharField(max_length=40)
    ambito = models.CharField(max_length=10, choices=AMBITO_CHOICES, default=AMBITO_TUTTI)
    consentito = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("ruolo", "modulo", "azione")]
        ordering = ["ruolo_id", "modulo", "azione"]
        verbose_name = "Permesso di ruolo sul modulo"
        verbose_name_plural = "Permessi di ruolo sui moduli"

    def __str__(self) -> str:
        stato = self.ambito if self.consentito else "no"
        return f"RuoloPermesso<ruolo={self.ruolo_id} {self.modulo}.{self.azione}={stato}>"


class AclDenialEvent(models.Model):
    """Un accesso negato dall'ACL, una riga per persona e permesso (o pagina).

    Serve all'amministratore per vedere chi e' rimasto fuori e decidere da un
    posto solo: consentire o confermare il diniego, sul ruolo o sulla persona.
    Solo identificativi, niente contenuti: il dettaglio della decisione si
    ricalcola dal resolver al momento di guardarlo.
    """

    STATUS_OPEN = "open"
    STATUS_ALLOWED = "allowed"
    STATUS_DENIED = "denied"
    STATUS_IGNORED = "ignored"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Da decidere"),
        (STATUS_ALLOWED, "Consentito"),
        (STATUS_DENIED, "Diniego confermato"),
        (STATUS_IGNORED, "Ignorato"),
    ]

    legacy_user_id = models.IntegerField(db_index=True)
    legacy_role_id = models.IntegerField(null=True, blank=True)
    # "perm:<codice>" se la pagina ha un permesso canonico, altrimenti "path:<path>".
    dedup_key = models.CharField(max_length=300)
    permission_code = models.CharField(max_length=120, blank=True, default="", db_index=True)
    path = models.CharField(max_length=500, blank=True, default="")
    route_name = models.CharField(max_length=160, blank=True, default="")
    decision_source = models.CharField(max_length=60, blank=True, default="")
    reason = models.CharField(max_length=500, blank=True, default="")
    hits = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        unique_together = [("legacy_user_id", "dedup_key")]
        ordering = ["-last_seen_at", "-id"]
        verbose_name = "Accesso negato"
        verbose_name_plural = "Accessi negati"

    def __str__(self) -> str:
        return f"AclDenial<user={self.legacy_user_id} key={self.dedup_key} status={self.status}>"


class PresetPermessiModulo(models.Model):
    """Insieme di permessi di pagina di un modulo, salvato con un nome.

    Serve a dare a un ruolo «l'Operatore di Assets» senza riselezionare ogni
    volta gli stessi interruttori nella pagina Accessi. Applicarlo muove solo
    gli interruttori del modulo: i grant si scrivono col normale «Salva».
    I codici sono un elenco JSON in un TextField (niente JSONField: su SQL Server
    diventa ISJSON e rompe i filtri).
    """

    modulo = models.CharField(max_length=80, db_index=True)
    nome = models.CharField(max_length=80)
    descrizione = models.CharField(max_length=300, blank=True, default="")
    codici_json = models.TextField(default="[]")
    creato_da = models.CharField(max_length=150, blank=True, default="")
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["modulo", "nome"]
        constraints = [
            models.UniqueConstraint(fields=["modulo", "nome"], name="uniq_preset_permessi_modulo_nome"),
        ]
        verbose_name = "Preset permessi di modulo"
        verbose_name_plural = "Preset permessi di modulo"

    def __str__(self) -> str:
        return f"{self.modulo}: {self.nome}"

    @property
    def codici(self) -> list[str]:
        import json

        try:
            dati = json.loads(self.codici_json or "[]")
        except ValueError:
            return []
        return [str(c) for c in dati] if isinstance(dati, list) else []


# ── Centro report ─────────────────────────────────────────────────────────────

class ReportEmissione(models.Model):
    """Un file di report scaricato dal portale (registro trasversale).

    Lo scrive :class:`core.report_centro.registro.ReportEmissioneMiddleware` per
    ogni risposta che porta un documento generato. Conserva solo metadati e
    impronta SHA-256: il file non viene mai salvato qui, quindi il registro non
    diventa una seconda copia dei dati personali. L'impronta permette comunque
    di riconoscere, a posteriori, se un file in circolazione è uscito dal portale.
    """

    FORMATO_CHOICES = [
        ("pdf", "PDF"),
        ("xlsx", "Excel"),
        ("csv", "CSV"),
        ("docx", "Word"),
        ("zip", "ZIP"),
        ("altro", "Altro"),
    ]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    legacy_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    utente_display = models.CharField(max_length=200, blank=True, default="")
    impersonato_display = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Persona impersonata al momento dello scaricamento (chi agiva è utente_display).",
    )
    report_chiave = models.CharField(
        max_length=120, blank=True, default="", db_index=True,
        help_text="Chiave della voce di catalogo; vuota = route non ancora catalogata.",
    )
    modulo = models.CharField(max_length=80, blank=True, default="", db_index=True)
    titolo = models.CharField(max_length=200, blank=True, default="")
    route_name = models.CharField(max_length=160, blank=True, default="", db_index=True)
    path = models.CharField(max_length=500, blank=True, default="")
    formato = models.CharField(max_length=10, choices=FORMATO_CHOICES, default="altro", db_index=True)
    nome_file = models.CharField(max_length=255, blank=True, default="")
    dimensione_byte = models.BigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    parametri = models.JSONField(default=dict, blank=True)
    dati_personali = models.BooleanField(default=False, db_index=True)
    profilo_layout = models.CharField(max_length=100, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Emissione report"
        verbose_name_plural = "Emissioni report"
        indexes = [
            models.Index(fields=["report_chiave", "-created_at"], name="core_reportem_chiave_recenti"),
        ]

    def __str__(self) -> str:
        return f"ReportEmissione<{self.report_chiave or self.route_name} {self.formato}>"


class ReportProfiloLayout(models.Model):
    """Profilo di stampa riutilizzabile per i PDF/Excel costruiti con ``core.pdf``.

    I campi vuoti ereditano il template PDF globale (Amministrazione → Template
    PDF). Un profilo si applica a un intero modulo o a una singola voce del
    catalogo tramite :class:`ReportAssegnazioneLayout`.
    """

    hex_validator = RegexValidator(r"^(#[0-9A-Fa-f]{6})?$", "Colore nel formato #RRGGBB.")

    nome = models.CharField(max_length=100, unique=True)
    descrizione = models.CharField(max_length=300, blank=True, default="")
    logo_url = models.CharField(
        max_length=300, blank=True, default="",
        help_text="Percorso /media/… di un PNG o JPG; vuoto = logo del template globale.",
    )
    colore_primario = models.CharField(max_length=7, blank=True, default="", validators=[hex_validator])
    colore_accento = models.CharField(max_length=7, blank=True, default="", validators=[hex_validator])
    piede_pagina = models.CharField(max_length=200, blank=True, default="")
    filigrana = models.CharField(
        max_length=40, blank=True, default="",
        help_text="Testo in diagonale su ogni pagina, es. BOZZA o COPIA NON CONTROLLATA.",
    )
    mostra_data_generazione = models.BooleanField(default=True)
    mostra_numero_pagina = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Profilo layout report"
        verbose_name_plural = "Profili layout report"

    def __str__(self) -> str:
        return self.nome


class ReportAssegnazioneLayout(models.Model):
    """Lega un profilo a un modulo o a una voce del catalogo (la voce vince)."""

    AMBITO_MODULO = "modulo"
    AMBITO_VOCE = "voce"
    AMBITO_CHOICES = [(AMBITO_MODULO, "Modulo"), (AMBITO_VOCE, "Singolo report")]

    ambito = models.CharField(max_length=10, choices=AMBITO_CHOICES)
    chiave = models.CharField(max_length=120)
    profilo = models.ForeignKey(ReportProfiloLayout, on_delete=models.CASCADE, related_name="assegnazioni")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ambito", "chiave"]
        verbose_name = "Assegnazione layout report"
        verbose_name_plural = "Assegnazioni layout report"
        constraints = [
            models.UniqueConstraint(fields=["ambito", "chiave"], name="uniq_report_layout_ambito_chiave"),
        ]

    def __str__(self) -> str:
        return f"{self.ambito}:{self.chiave} → {self.profilo_id}"


class ReportPianificazione(models.Model):
    """Report del catalogo generato e inviato per mail a intervalli regolari.

    Il file si genera eseguendo la route della variante **per conto del
    proprietario** (i controlli della vista e dell'ACL valgono come se lo
    scaricasse lui); ogni destinatario lo riceve solo se può aprire lo stesso
    report. Motore in :mod:`core.report_centro.pianificazione`.
    """

    FREQ_SETTIMANALE = "settimanale"
    FREQ_MENSILE = "mensile"
    FREQ_CHOICES = [(FREQ_SETTIMANALE, "Ogni settimana"), (FREQ_MENSILE, "Ogni mese")]

    ESITO_OK = "ok"
    ESITO_PARZIALE = "parziale"
    ESITO_ERRORE = "errore"
    ESITO_CHOICES = [(ESITO_OK, "Inviato"), (ESITO_PARZIALE, "Inviato in parte"), (ESITO_ERRORE, "Errore")]

    nome = models.CharField(max_length=120)
    voce_chiave = models.CharField(max_length=120, db_index=True)
    variante = models.CharField(max_length=40)
    frequenza = models.CharField(max_length=12, choices=FREQ_CHOICES, default=FREQ_MENSILE)
    giorno_settimana = models.PositiveSmallIntegerField(default=0, help_text="0 = lunedì … 6 = domenica")
    giorno_mese = models.PositiveSmallIntegerField(default=1, help_text="1–28")
    ora = models.PositiveSmallIntegerField(default=7, help_text="0–23")
    proprietario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    destinatari = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    attiva = models.BooleanField(default=True, db_index=True)
    prossima_esecuzione = models.DateTimeField(null=True, blank=True, db_index=True)
    ultima_esecuzione = models.DateTimeField(null=True, blank=True)
    ultimo_esito = models.CharField(max_length=10, choices=ESITO_CHOICES, blank=True, default="")
    ultimo_messaggio = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome", "id"]
        verbose_name = "Report pianificato"
        verbose_name_plural = "Report pianificati"

    def __str__(self) -> str:
        return self.nome
