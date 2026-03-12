from __future__ import annotations

import calendar
import re
import uuid
from pathlib import Path
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, models
from django.utils import timezone
from django.utils.text import slugify


class Asset(models.Model):
    TYPE_PC = "PC"
    TYPE_NOTEBOOK = "NOTEBOOK"
    TYPE_SERVER = "SERVER"
    TYPE_VM = "VM"
    TYPE_FIREWALL = "FIREWALL"
    TYPE_STAMPANTE = "STAMPANTE"
    TYPE_HW = "HW"
    TYPE_CNC = "CNC"
    TYPE_WORK_MACHINE = "WORK_MACHINE"
    TYPE_CCTV = "CCTV"
    TYPE_OTHER = "OTHER"

    TYPE_CHOICES = [
        (TYPE_PC, "PC"),
        (TYPE_NOTEBOOK, "Portatile"),
        (TYPE_SERVER, "Server"),
        (TYPE_VM, "Macchina virtuale"),
        (TYPE_FIREWALL, "Firewall"),
        (TYPE_STAMPANTE, "Stampante"),
        (TYPE_HW, "Dispositivo"),
        (TYPE_CNC, "CNC"),
        (TYPE_WORK_MACHINE, "Macchina di lavoro"),
        (TYPE_CCTV, "Videosorveglianza"),
        (TYPE_OTHER, "Altro"),
    ]

    STATUS_IN_STOCK = "IN_STOCK"
    STATUS_IN_USE = "IN_USE"
    STATUS_IN_REPAIR = "IN_REPAIR"
    STATUS_RETIRED = "RETIRED"
    STATUS_CHOICES = [
        (STATUS_IN_STOCK, "In magazzino"),
        (STATUS_IN_USE, "In uso"),
        (STATUS_IN_REPAIR, "In riparazione"),
        (STATUS_RETIRED, "Dismesso"),
    ]

    asset_tag = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_OTHER)
    asset_category = models.ForeignKey(
        "AssetCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets",
    )
    reparto = models.CharField(max_length=120, blank=True, default="")
    manufacturer = models.CharField(max_length=120, null=True, blank=True)
    model = models.CharField(max_length=120, null=True, blank=True)
    serial_number = models.CharField(max_length=120, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_USE)
    notes = models.TextField(blank=True, default="")
    sharepoint_folder_url = models.CharField(max_length=1000, blank=True, default="")
    sharepoint_folder_path = models.CharField(max_length=500, blank=True, default="")
    extra_columns = models.JSONField(default=dict, blank=True)
    source_key = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    assigned_legacy_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    assignment_to = models.CharField(max_length=200, blank=True, default="")
    assignment_reparto = models.CharField(max_length=120, blank=True, default="")
    assignment_location = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "asset_tag", "id"]

    def __str__(self) -> str:
        return f"{self.asset_tag} - {self.name}"

    @property
    def category_label(self) -> str:
        if self.asset_category_id and getattr(self.asset_category, "label", ""):
            return self.asset_category.label
        return self.get_asset_type_display()

    @property
    def category_initial(self) -> str:
        label = self.category_label
        return label[:1].upper() if label else "A"

    def _asset_tag_prefix(self) -> str:
        if self.asset_type in {
            self.TYPE_PC,
            self.TYPE_NOTEBOOK,
            self.TYPE_SERVER,
            self.TYPE_VM,
            self.TYPE_FIREWALL,
            self.TYPE_STAMPANTE,
            self.TYPE_HW,
        }:
            return "IT"
        if self.asset_type == self.TYPE_CNC:
            return "CNC"
        if self.asset_type == self.TYPE_WORK_MACHINE:
            return "ML"
        if self.asset_type == self.TYPE_CCTV:
            return "CCTV"
        return "AST"

    def _generate_asset_tag(self) -> str:
        prefix = self._asset_tag_prefix()
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{6}})$")
        max_num = 0
        for tag in Asset.objects.filter(asset_tag__startswith=f"{prefix}-").values_list("asset_tag", flat=True):
            match = pattern.match(tag or "")
            if not match:
                continue
            max_num = max(max_num, int(match.group(1)))
        for offset in range(1, 5000):
            candidate = f"{prefix}-{max_num + offset:06d}"
            if not Asset.objects.filter(asset_tag=candidate).exists():
                return candidate
        return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

    def save(self, *args, **kwargs):
        if self.source_key == "":
            self.source_key = None
        if self.asset_tag:
            return super().save(*args, **kwargs)
        for _ in range(3):
            self.asset_tag = self._generate_asset_tag()
            try:
                return super().save(*args, **kwargs)
            except IntegrityError as exc:
                if "asset_tag" not in str(exc).lower():
                    raise
                self.asset_tag = ""
        return super().save(*args, **kwargs)


class AssetCustomField(models.Model):
    TYPE_TEXT = "TEXT"
    TYPE_NUMBER = "NUMBER"
    TYPE_DATE = "DATE"
    TYPE_BOOL = "BOOL"
    TYPE_CHOICES = [
        (TYPE_TEXT, "Testo"),
        (TYPE_NUMBER, "Numero"),
        (TYPE_DATE, "Data"),
        (TYPE_BOOL, "Si/No"),
    ]

    code = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    field_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_TEXT)
    sort_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "label", "id"]

    def __str__(self) -> str:
        return f"{self.label} ({self.code})"


class AssetCategory(models.Model):
    code = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    base_asset_type = models.CharField(max_length=20, choices=Asset.TYPE_CHOICES, default=Asset.TYPE_OTHER, db_index=True)
    description = models.TextField(blank=True, default="")
    detail_specs_title = models.CharField(max_length=120, blank=True, default="")
    detail_profile_title = models.CharField(max_length=120, blank=True, default="")
    detail_assignment_title = models.CharField(max_length=120, blank=True, default="")
    detail_timeline_title = models.CharField(max_length=120, blank=True, default="")
    detail_maintenance_title = models.CharField(max_length=120, blank=True, default="")
    sort_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "label", "id"]

    def __str__(self) -> str:
        return self.label


class AssetListOption(models.Model):
    FIELD_REPARTO = "reparto"
    FIELD_MANUFACTURER = "manufacturer"
    FIELD_MODEL = "model"
    FIELD_ASSIGNMENT_TO = "assignment_to"
    FIELD_ASSIGNMENT_REPARTO = "assignment_reparto"
    FIELD_ASSIGNMENT_LOCATION = "assignment_location"

    FIELD_CHOICES = [
        (FIELD_REPARTO, "Reparto"),
        (FIELD_MANUFACTURER, "Produttore"),
        (FIELD_MODEL, "Modello"),
        (FIELD_ASSIGNMENT_TO, "Assegnato a"),
        (FIELD_ASSIGNMENT_REPARTO, "Reparto assegnazione"),
        (FIELD_ASSIGNMENT_LOCATION, "Posizione assegnazione"),
    ]

    field_key = models.CharField(max_length=50, choices=FIELD_CHOICES, db_index=True)
    value = models.CharField(max_length=200)
    sort_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["field_key", "sort_order", "value", "id"]
        constraints = [
            models.UniqueConstraint(fields=["field_key", "value"], name="uniq_asset_listoption_field_value"),
        ]

    def __str__(self) -> str:
        return f"{self.get_field_key_display()}: {self.value}"


class AssetActionButton(models.Model):
    ZONE_HEADER = "HEADER"
    ZONE_QUICK = "QUICK"
    ZONE_CHOICES = [
        (ZONE_HEADER, "Intestazione"),
        (ZONE_QUICK, "Azioni rapide"),
    ]

    TYPE_LINK = "LINK"
    TYPE_PRINT = "PRINT"
    TYPE_REFRESH = "REFRESH"
    ACTION_CHOICES = [
        (TYPE_LINK, "Collegamento"),
        (TYPE_PRINT, "Stampa"),
        (TYPE_REFRESH, "Aggiorna"),
    ]

    STYLE_DEFAULT = "DEFAULT"
    STYLE_PRIMARY = "PRIMARY"
    STYLE_SECONDARY = "SECONDARY"
    STYLE_DANGER = "DANGER"
    STYLE_CHOICES = [
        (STYLE_DEFAULT, "Predefinito"),
        (STYLE_PRIMARY, "Primario"),
        (STYLE_SECONDARY, "Secondario"),
        (STYLE_DANGER, "Pericolo"),
    ]

    code = models.SlugField(max_length=80, unique=True)
    zone = models.CharField(max_length=20, choices=ZONE_CHOICES, default=ZONE_QUICK, db_index=True)
    label = models.CharField(max_length=120)
    action_type = models.CharField(max_length=20, choices=ACTION_CHOICES, default=TYPE_LINK)
    target = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="URL/path con placeholder: {asset_id}, {asset_tag}, {asset_name}",
    )
    style = models.CharField(max_length=20, choices=STYLE_CHOICES, default=STYLE_DEFAULT)
    sort_order = models.IntegerField(default=100)
    open_in_new_tab = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["zone", "sort_order", "label", "id"]

    def __str__(self) -> str:
        return f"{self.get_zone_display()} - {self.label}"


class AssetDetailField(models.Model):
    SECTION_METRICS = "METRICS"
    SECTION_SPECS = "SPECS"
    SECTION_PROFILE = "PROFILE"
    SECTION_ASSIGNMENT = "ASSIGNMENT"
    SECTION_CHOICES = [
        (SECTION_METRICS, "Metriche evidenza"),
        (SECTION_SPECS, "Specifiche tecniche"),
        (SECTION_PROFILE, "Profilo asset"),
        (SECTION_ASSIGNMENT, "Responsabile attuale"),
    ]

    SCOPE_ALL = "ALL"
    SCOPE_STANDARD = "STANDARD"
    SCOPE_WORK_MACHINE = "WORK_MACHINE"
    SCOPE_CHOICES = [
        (SCOPE_ALL, "Tutti gli asset"),
        (SCOPE_STANDARD, "Asset standard"),
        (SCOPE_WORK_MACHINE, "Macchine di lavoro"),
    ]

    FORMAT_AUTO = "AUTO"
    FORMAT_TEXT = "TEXT"
    FORMAT_BOOL = "BOOL"
    FORMAT_DATE = "DATE"
    FORMAT_MM = "MM"
    FORMAT_BAR = "BAR"
    FORMAT_CHOICES = [
        (FORMAT_AUTO, "Automatico"),
        (FORMAT_TEXT, "Testo"),
        (FORMAT_BOOL, "Si/No"),
        (FORMAT_DATE, "Data"),
        (FORMAT_MM, "Millimetri"),
        (FORMAT_BAR, "Bar"),
    ]
    CARD_THIRD = "THIRD"
    CARD_HALF = "HALF"
    CARD_WIDE = "WIDE"
    CARD_FULL = "FULL"
    CARD_SIZE_CHOICES = [
        (CARD_THIRD, "Compatta"),
        (CARD_HALF, "Media"),
        (CARD_WIDE, "Ampia"),
        (CARD_FULL, "Piena"),
    ]

    code = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    section = models.CharField(max_length=20, choices=SECTION_CHOICES, default=SECTION_SPECS, db_index=True)
    asset_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_ALL, db_index=True)
    source_ref = models.CharField(
        max_length=120,
        help_text="Formato origine: asset:manufacturer, work_machine:x_mm, it:cpu, custom:rack, computed:travel_xyz",
    )
    value_format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default=FORMAT_AUTO)
    card_size = models.CharField(max_length=12, choices=CARD_SIZE_CHOICES, default=CARD_THIRD)
    sort_order = models.IntegerField(default=100)
    show_if_empty = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "asset_scope", "sort_order", "label", "id"]

    def __str__(self) -> str:
        return f"{self.get_section_display()} - {self.label}"


class AssetDetailSectionLayout(models.Model):
    SECTION_SPECS = "SPECS"
    SECTION_TIMELINE = "TIMELINE"
    SECTION_MAINTENANCE = "MAINTENANCE"
    SECTION_TICKETS = "TICKETS"
    SECTION_PROFILE = "PROFILE"
    SECTION_PERIODIC = "PERIODIC"
    SECTION_QR = "QR"
    SECTION_SHAREPOINT = "SHAREPOINT"
    SECTION_QUICK_ACTIONS = "QUICK_ACTIONS"
    SECTION_ASSIGNMENT = "ASSIGNMENT"
    SECTION_MAP = "MAP"
    SECTION_DOCUMENTS = "DOCUMENTS"
    SECTION_CHOICES = [
        (SECTION_SPECS, "Specifiche tecniche"),
        (SECTION_TIMELINE, "Timeline ciclo di vita"),
        (SECTION_MAINTENANCE, "Registro manutenzione"),
        (SECTION_TICKETS, "Ticket collegati"),
        (SECTION_PROFILE, "Profilo asset"),
        (SECTION_PERIODIC, "Verifiche periodiche"),
        (SECTION_QR, "QR asset"),
        (SECTION_SHAREPOINT, "Archivio SharePoint"),
        (SECTION_QUICK_ACTIONS, "Azioni rapide"),
        (SECTION_ASSIGNMENT, "Responsabile attuale"),
        (SECTION_MAP, "Posizione in officina"),
        (SECTION_DOCUMENTS, "Documenti"),
    ]

    SIZE_THIRD = AssetDetailField.CARD_THIRD
    SIZE_HALF = AssetDetailField.CARD_HALF
    SIZE_WIDE = AssetDetailField.CARD_WIDE
    SIZE_FULL = AssetDetailField.CARD_FULL
    SIZE_CHOICES = AssetDetailField.CARD_SIZE_CHOICES

    code = models.CharField(max_length=24, choices=SECTION_CHOICES, unique=True)
    grid_size = models.CharField(max_length=12, choices=SIZE_CHOICES, default=SIZE_HALF)
    sort_order = models.IntegerField(default=100)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.get_code_display()


class AssetListLayout(models.Model):
    CONTEXT_ALL = "all"
    CONTEXT_DEVICES = "devices"
    CONTEXT_SERVERS = "servers"
    CONTEXT_WORKSTATIONS = "workstations"
    CONTEXT_NETWORK = "network"
    CONTEXT_VIRTUAL_MACHINES = "virtual_machines"
    CONTEXT_CCTV = "cctv"
    CONTEXT_CHOICES = [
        (CONTEXT_ALL, "Inventario completo"),
        (CONTEXT_DEVICES, "Dispositivi"),
        (CONTEXT_SERVERS, "Server"),
        (CONTEXT_WORKSTATIONS, "Postazioni di lavoro"),
        (CONTEXT_NETWORK, "Rete"),
        (CONTEXT_VIRTUAL_MACHINES, "Macchine virtuali"),
        (CONTEXT_CCTV, "Videosorveglianza"),
    ]

    context_key = models.CharField(max_length=32, choices=CONTEXT_CHOICES, unique=True)
    visible_columns = models.JSONField(default=list, blank=True)
    sort_order = models.IntegerField(default=100)
    is_customized = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.get_context_key_display()


class AssetCategoryField(models.Model):
    TYPE_TEXT = "TEXT"
    TYPE_TEXTAREA = "TEXTAREA"
    TYPE_NUMBER = "NUMBER"
    TYPE_DATE = "DATE"
    TYPE_BOOL = "BOOL"
    TYPE_CHOICES = [
        (TYPE_TEXT, "Testo"),
        (TYPE_TEXTAREA, "Testo lungo"),
        (TYPE_NUMBER, "Numero"),
        (TYPE_DATE, "Data"),
        (TYPE_BOOL, "Si/No"),
    ]

    category = models.ForeignKey(AssetCategory, on_delete=models.CASCADE, related_name="category_fields")
    code = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    field_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_TEXT)
    detail_section = models.CharField(
        max_length=20,
        choices=AssetDetailField.SECTION_CHOICES,
        default=AssetDetailField.SECTION_SPECS,
        db_index=True,
    )
    detail_value_format = models.CharField(
        max_length=20,
        choices=AssetDetailField.FORMAT_CHOICES,
        default=AssetDetailField.FORMAT_AUTO,
    )
    detail_card_size = models.CharField(
        max_length=12,
        choices=AssetDetailField.CARD_SIZE_CHOICES,
        default=AssetDetailField.CARD_THIRD,
    )
    placeholder = models.CharField(max_length=160, blank=True, default="")
    help_text = models.CharField(max_length=255, blank=True, default="")
    sort_order = models.IntegerField(default=100)
    is_required = models.BooleanField(default=False)
    show_in_form = models.BooleanField(default=True)
    show_in_detail = models.BooleanField(default=True)
    show_if_empty = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__sort_order", "category__label", "sort_order", "label", "id"]

    def __str__(self) -> str:
        return f"{self.category.label} - {self.label}"


class AssetSidebarButton(models.Model):
    SECTION_MAIN = "MAIN"
    SECTION_ANALYTICS = "ANALYTICS"
    SECTION_OPERATIONS = "OPERATIONS"
    SECTION_CHOICES = [
        (SECTION_MAIN, "Navigazione principale"),
        (SECTION_ANALYTICS, "Analisi e rischio"),
        (SECTION_OPERATIONS, "Operativita"),
    ]

    code = models.SlugField(max_length=80, unique=True)
    section = models.CharField(max_length=20, choices=SECTION_CHOICES, default=SECTION_MAIN, db_index=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    label = models.CharField(max_length=120)
    target_url = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="URL o route prefissata con django: (es. django:assets:asset_list). Supporta {rows}.",
    )
    active_match = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Substring opzionale per marcare il pulsante come attivo (es. asset_type=SERVER).",
    )
    is_subitem = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=100)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "sort_order", "label", "id"]

    def __str__(self) -> str:
        return f"{self.get_section_display()} - {self.label}"

    def save(self, *args, **kwargs):
        if self.parent_id:
            parent = self.parent or AssetSidebarButton.objects.filter(pk=self.parent_id).only("section").first()
            if parent is not None:
                self.section = parent.section
                self.is_subitem = True
        super().save(*args, **kwargs)


class AssetEndpoint(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="endpoints")
    endpoint_name = models.CharField(max_length=255, blank=True, default="")
    vlan = models.PositiveIntegerField(null=True, blank=True)
    ip = models.CharField(max_length=80, null=True, blank=True)
    switch_name = models.CharField(max_length=120, blank=True, default="")
    switch_port = models.CharField(max_length=120, blank=True, default="")
    punto = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "endpoint_name", "vlan", "ip"],
                name="uniq_asset_endpoint",
            )
        ]
        ordering = ["asset_id", "endpoint_name", "vlan", "ip"]

    def __str__(self) -> str:
        parts = [self.endpoint_name or self.asset.name]
        if self.vlan is not None:
            parts.append(f"VLAN {self.vlan}")
        if self.ip:
            parts.append(self.ip)
        return " | ".join(parts)


class AssetITDetails(models.Model):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name="it_details")
    os = models.CharField(max_length=120, blank=True, default="")
    cpu = models.CharField(max_length=120, blank=True, default="")
    ram = models.CharField(max_length=120, blank=True, default="")
    disco = models.CharField(max_length=120, blank=True, default="")
    domain_joined = models.BooleanField(default=False)
    edr_enabled = models.BooleanField(default=False)
    ad360_managed = models.BooleanField(default=False)
    office_2fa_enabled = models.BooleanField(default=False)
    bios_pwd_set = models.BooleanField(default=False)
    vault_ref = models.CharField(max_length=200, blank=True, default="")

    def __str__(self) -> str:
        return f"ITDetails<{self.asset.asset_tag}>"


class WorkMachine(models.Model):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name="work_machine")
    source_key = models.CharField(max_length=64, unique=True, db_index=True)
    x_mm = models.PositiveIntegerField(null=True, blank=True)
    y_mm = models.PositiveIntegerField(null=True, blank=True)
    z_mm = models.PositiveIntegerField(null=True, blank=True)
    diameter_mm = models.PositiveIntegerField(null=True, blank=True)
    spindle_mm = models.PositiveIntegerField(null=True, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    tmc = models.PositiveIntegerField(null=True, blank=True)
    tcr_enabled = models.BooleanField(default=False)
    pressure_bar = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    cnc_controlled = models.BooleanField(default=False)
    five_axes = models.BooleanField(default=False)
    accuracy_from = models.CharField(max_length=120, blank=True, default="")
    next_maintenance_date = models.DateField(null=True, blank=True, db_index=True)
    maintenance_reminder_days = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset__name", "asset__asset_tag", "asset_id"]

    def __str__(self) -> str:
        return f"WorkMachine<{self.asset.asset_tag}>"


def _add_months(base_date, months: int):
    safe_months = max(0, int(months or 0))
    month_index = (base_date.month - 1) + safe_months
    year = base_date.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return base_date.replace(year=year, month=month, day=day)


class PeriodicVerification(models.Model):
    name = models.CharField(max_length=200)
    supplier = models.ForeignKey(
        "anagrafica.Fornitore",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="periodic_verifications",
    )
    frequency_months = models.PositiveIntegerField(default=12)
    last_verification_date = models.DateField(null=True, blank=True)
    next_verification_date = models.DateField(null=True, blank=True, db_index=True)
    assets = models.ManyToManyField(Asset, related_name="periodic_verifications", blank=True)
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_periodic_verifications",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "Verifica periodica"
        verbose_name_plural = "Verifiche periodiche"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if self.last_verification_date and not self.next_verification_date:
            self.next_verification_date = _add_months(self.last_verification_date, self.frequency_months)
        super().save(*args, **kwargs)


def _plant_layout_image_upload_to(instance, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()[:10]
    stem = slugify(Path(filename or "").stem)[:80] or "planimetria"
    token = uuid.uuid4().hex[:8]
    return f"assets_layouts/{token}_{stem}{suffix}"


class PlantLayout(models.Model):
    DEFAULT_CATEGORY = "Officina"

    category = models.CharField(max_length=80, default=DEFAULT_CATEGORY, db_index=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True, default="")
    image = models.ImageField(upload_to=_plant_layout_image_upload_to)
    is_active = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "-is_active", "name", "id"]

    def __str__(self) -> str:
        return f"{self.category} - {self.name}"

    def save(self, *args, **kwargs):
        previous_name = ""
        previous_storage = None
        self.category = (str(self.category or "").strip() or self.DEFAULT_CATEGORY)[:80]
        if self.pk:
            previous = PlantLayout.objects.filter(pk=self.pk).only("image").first()
            if previous and previous.image and previous.image.name != getattr(self.image, "name", ""):
                previous_name = previous.image.name
                previous_storage = previous.image.storage
        super().save(*args, **kwargs)
        if self.is_active:
            PlantLayout.objects.exclude(pk=self.pk).filter(is_active=True, category__iexact=self.category).update(is_active=False)
        if previous_storage and previous_name and previous_storage.exists(previous_name):
            previous_storage.delete(previous_name)

    def delete(self, *args, **kwargs):
        storage = self.image.storage if self.image else None
        file_name = self.image.name if self.image else ""
        super().delete(*args, **kwargs)
        if storage and file_name and storage.exists(file_name):
            storage.delete(file_name)


class PlantLayoutArea(models.Model):
    layout = models.ForeignKey(PlantLayout, on_delete=models.CASCADE, related_name="areas")
    name = models.CharField(max_length=120)
    reparto_code = models.CharField(max_length=120, blank=True, default="", db_index=True)
    color = models.CharField(max_length=7, default="#2563EB")
    notes = models.CharField(max_length=255, blank=True, default="")
    x_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    y_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    width_percent = models.DecimalField(max_digits=6, decimal_places=2, default=10)
    height_percent = models.DecimalField(max_digits=6, decimal_places=2, default=10)
    sort_order = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name", "id"]

    def __str__(self) -> str:
        return f"{self.layout.name} - {self.name}"


class PlantLayoutMarker(models.Model):
    layout = models.ForeignKey(PlantLayout, on_delete=models.CASCADE, related_name="markers")
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="plant_layout_markers")
    label = models.CharField(max_length=120, blank=True, default="")
    x_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    y_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    is_visible = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "asset__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["layout", "asset"], name="uniq_plant_layout_marker_layout_asset"),
        ]

    def __str__(self) -> str:
        return self.label or self.asset.asset_tag or f"Marker {self.pk}"


def _asset_document_upload_to(instance, filename: str) -> str:
    asset_tag = instance.asset.asset_tag if instance.asset_id and instance.asset and instance.asset.asset_tag else f"asset-{instance.asset_id or 'tmp'}"
    category = (instance.category or "SPECIFICHE").lower()
    suffix = Path(filename or "").suffix.lower()[:20]
    stem = slugify(Path(filename or "").stem)[:80] or "documento"
    stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    token = uuid.uuid4().hex[:8]
    return f"assets_documents/{asset_tag}/{category}/{stamp}_{token}_{stem}{suffix}"


class AssetDocument(models.Model):
    CATEGORY_SPECIFICHE = "SPECIFICHE"
    CATEGORY_INTERVENTI = "INTERVENTI"
    CATEGORY_MANUALI = "MANUALI"
    CATEGORY_CHOICES = [
        (CATEGORY_SPECIFICHE, "Specifiche"),
        (CATEGORY_INTERVENTI, "Interventi"),
        (CATEGORY_MANUALI, "Manuali"),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="documents")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_SPECIFICHE, db_index=True)
    file = models.FileField(upload_to=_asset_document_upload_to)
    original_name = models.CharField(max_length=255, blank=True, default="")
    notes = models.CharField(max_length=255, blank=True, default="")
    document_date = models.DateField(null=True, blank=True)
    sharepoint_url = models.CharField(max_length=1000, blank=True, default="")
    sharepoint_path = models.CharField(max_length=500, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_documents_uploaded",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["category", "-created_at", "-id"]

    def __str__(self) -> str:
        return f"AssetDocument<{self.asset.asset_tag}:{self.category}>"

    def save(self, *args, **kwargs):
        if not self.original_name and self.file:
            self.original_name = Path(self.file.name).name[:255]
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        storage = self.file.storage if self.file else None
        file_name = self.file.name if self.file else ""
        super().delete(*args, **kwargs)
        if storage and file_name and storage.exists(file_name):
            storage.delete(file_name)


def default_asset_label_body_fields() -> list[str]:
    return ["asset_type", "reparto", "serial_number"]


def _asset_label_logo_upload_to(instance, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()[:10]
    stem = slugify(Path(filename or "").stem)[:80] or "logo"
    token = uuid.uuid4().hex[:8]
    code = slugify(instance.code or "default")[:40] or "default"
    return f"assets_label_templates/{code}/{token}_{stem}{suffix}"


class AssetLabelTemplate(models.Model):
    SCOPE_DEFAULT = "DEFAULT"
    SCOPE_ASSET_TYPE = "ASSET_TYPE"
    SCOPE_ASSET = "ASSET"
    SCOPE_CHOICES = [
        (SCOPE_DEFAULT, "Generale"),
        (SCOPE_ASSET_TYPE, "Per tipologia asset"),
        (SCOPE_ASSET, "Per asset"),
    ]
    QR_POSITION_LEFT = "LEFT"
    QR_POSITION_RIGHT = "RIGHT"
    QR_POSITION_CHOICES = [
        (QR_POSITION_LEFT, "QR a sinistra"),
        (QR_POSITION_RIGHT, "QR a destra"),
    ]
    LOGO_ALIGNMENT_LEFT = "LEFT"
    LOGO_ALIGNMENT_CENTER = "CENTER"
    LOGO_ALIGNMENT_RIGHT = "RIGHT"
    LOGO_ALIGNMENT_CHOICES = [
        (LOGO_ALIGNMENT_LEFT, "Logo a sinistra"),
        (LOGO_ALIGNMENT_CENTER, "Logo centrato"),
        (LOGO_ALIGNMENT_RIGHT, "Logo a destra"),
    ]

    code = models.SlugField(max_length=40, unique=True, default="default")
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_DEFAULT, db_index=True)
    asset_type = models.CharField(max_length=20, choices=Asset.TYPE_CHOICES, blank=True, default="", db_index=True)
    asset = models.OneToOneField(
        Asset,
        on_delete=models.CASCADE,
        related_name="label_template_override",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=120, default="Etichetta predefinita")
    page_width_mm = models.PositiveIntegerField(default=100)
    page_height_mm = models.PositiveIntegerField(default=62)
    qr_size_mm = models.PositiveIntegerField(default=24)
    qr_position = models.CharField(max_length=10, choices=QR_POSITION_CHOICES, default=QR_POSITION_RIGHT)
    show_logo = models.BooleanField(default=False)
    logo_file = models.FileField(upload_to=_asset_label_logo_upload_to, blank=True, default="")
    logo_height_mm = models.PositiveIntegerField(default=10)
    logo_alignment = models.CharField(max_length=10, choices=LOGO_ALIGNMENT_CHOICES, default=LOGO_ALIGNMENT_LEFT)
    title_font_size_pt = models.PositiveIntegerField(default=16)
    body_font_size_pt = models.PositiveIntegerField(default=8)
    show_border = models.BooleanField(default=True)
    border_radius_mm = models.PositiveIntegerField(default=4)
    show_field_labels = models.BooleanField(default=True)
    show_target_label = models.BooleanField(default=True)
    show_help_text = models.BooleanField(default=True)
    show_target_url = models.BooleanField(default=True)
    background_color = models.CharField(max_length=7, default="#FFFFFF")
    border_color = models.CharField(max_length=7, default="#111827")
    text_color = models.CharField(max_length=7, default="#0F172A")
    accent_color = models.CharField(max_length=7, default="#1D4ED8")
    title_primary_field = models.CharField(max_length=40, default="asset_tag")
    title_secondary_field = models.CharField(max_length=40, default="name")
    body_fields = models.JSONField(default=default_asset_label_body_fields, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope", "asset_type", "code", "id"]

    def __str__(self) -> str:
        return f"AssetLabelTemplate<{self.code}>"

    def scope_display_label(self) -> str:
        if self.scope == self.SCOPE_ASSET and self.asset_id and self.asset:
            return f"Asset {self.asset.asset_tag}"
        if self.scope == self.SCOPE_ASSET_TYPE and self.asset_type:
            type_labels = dict(Asset.TYPE_CHOICES)
            return type_labels.get(self.asset_type, self.asset_type)
        return "Generale"

    def _computed_scope(self) -> str:
        if self.asset_id:
            return self.SCOPE_ASSET
        if self.asset_type:
            return self.SCOPE_ASSET_TYPE
        return self.SCOPE_DEFAULT

    def _computed_code(self) -> str:
        if self.scope == self.SCOPE_ASSET and self.asset_id:
            return f"asset-{self.asset_id}"
        if self.scope == self.SCOPE_ASSET_TYPE and self.asset_type:
            return f"type-{self.asset_type.lower()}"
        return "default"

    def _default_name(self) -> str:
        if self.scope == self.SCOPE_ASSET and self.asset_id and self.asset:
            asset_label = self.asset.asset_tag or self.asset.name or f"Asset {self.asset_id}"
            return f"Etichetta {asset_label}"
        if self.scope == self.SCOPE_ASSET_TYPE and self.asset_type:
            type_labels = dict(Asset.TYPE_CHOICES)
            return f"Etichetta {type_labels.get(self.asset_type, self.asset_type)}"
        return "Etichetta predefinita"

    def _logo_is_shared(self, file_name: str) -> bool:
        if not file_name:
            return False
        qs = AssetLabelTemplate.objects.filter(logo_file=file_name)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        return qs.exists()

    def save(self, *args, **kwargs):
        previous_name = ""
        previous_storage = None
        if self.pk:
            previous = AssetLabelTemplate.objects.filter(pk=self.pk).only("logo_file").first()
            if previous and previous.logo_file and previous.logo_file.name != getattr(self.logo_file, "name", ""):
                previous_name = previous.logo_file.name
                previous_storage = previous.logo_file.storage
        self.scope = self._computed_scope()
        if self.scope == self.SCOPE_ASSET:
            self.asset_type = ""
        elif self.scope == self.SCOPE_DEFAULT:
            self.asset_type = ""
            self.asset = None
        else:
            self.asset = None
        self.code = self._computed_code()
        if not (self.name or "").strip():
            self.name = self._default_name()
        super().save(*args, **kwargs)
        if previous_storage and previous_name and not self._logo_is_shared(previous_name) and previous_storage.exists(previous_name):
            previous_storage.delete(previous_name)

    def delete(self, *args, **kwargs):
        storage = self.logo_file.storage if self.logo_file else None
        file_name = self.logo_file.name if self.logo_file else ""
        super().delete(*args, **kwargs)
        if storage and file_name and not self._logo_is_shared(file_name) and storage.exists(file_name):
            storage.delete(file_name)


class AssetReportDefinition(models.Model):
    code = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True, default="")
    sort_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "label", "id"]

    def __str__(self) -> str:
        return self.label


def _asset_report_template_upload_to(instance, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()[:20]
    stem = slugify(Path(filename or "").stem)[:80] or "template-report"
    token = uuid.uuid4().hex[:8]
    report_code = slugify(instance.report_code or "generic")[:40] or "generic"
    return f"assets_report_templates/{report_code}/{token}_{stem}{suffix}"


class AssetReportTemplate(models.Model):
    REPORT_ASSET_DETAIL = "asset-detail"
    REPORT_WORK_MACHINE_MAINTENANCE = "work-machine-maintenance-month"

    report_code = models.SlugField(max_length=80, db_index=True)
    name = models.CharField(max_length=120)
    version = models.CharField(max_length=40, blank=True, default="")
    description = models.CharField(max_length=255, blank=True, default="")
    file = models.FileField(upload_to=_asset_report_template_upload_to)
    original_name = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_report_templates_uploaded",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["report_code", "-is_active", "-updated_at", "-id"]

    def __str__(self) -> str:
        return f"{self.report_code} - {self.name}"

    def save(self, *args, **kwargs):
        previous_name = ""
        previous_storage = None
        if self.pk:
            previous = AssetReportTemplate.objects.filter(pk=self.pk).only("file").first()
            if previous and previous.file and previous.file.name != getattr(self.file, "name", ""):
                previous_name = previous.file.name
                previous_storage = previous.file.storage
        if not self.original_name and self.file:
            self.original_name = Path(self.file.name).name[:255]
        super().save(*args, **kwargs)
        if self.is_active:
            AssetReportTemplate.objects.exclude(pk=self.pk).filter(
                report_code=self.report_code,
                is_active=True,
            ).update(is_active=False)
        if previous_storage and previous_name and previous_storage.exists(previous_name):
            previous_storage.delete(previous_name)

    def delete(self, *args, **kwargs):
        storage = self.file.storage if self.file else None
        file_name = self.file.name if self.file else ""
        super().delete(*args, **kwargs)
        if storage and file_name and storage.exists(file_name):
            storage.delete(file_name)


class WorkOrder(models.Model):
    KIND_PREVENTIVE = "PREVENTIVE"
    KIND_CORRECTIVE = "CORRECTIVE"
    KIND_SAFETY = "SAFETY"
    KIND_CALIBRATION = "CALIBRATION"
    KIND_OTHER = "OTHER"
    KIND_CHOICES = [
        (KIND_PREVENTIVE, "Preventiva"),
        (KIND_CORRECTIVE, "Correttiva"),
        (KIND_SAFETY, "Sicurezza"),
        (KIND_CALIBRATION, "Taratura"),
        (KIND_OTHER, "Altro"),
    ]

    STATUS_OPEN = "OPEN"
    STATUS_DONE = "DONE"
    STATUS_CANCELED = "CANCELED"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Aperta"),
        (STATUS_DONE, "Chiusa"),
        (STATUS_CANCELED, "Annullata"),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="workorders")
    periodic_verification = models.ForeignKey(
        PeriodicVerification,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorders",
    )
    supplier = models.ForeignKey(
        "anagrafica.Fornitore",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_workorders",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OTHER)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    resolution = models.TextField(blank=True, default="")
    downtime_minutes = models.PositiveIntegerField(default=0)
    cost_eur = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
    )

    class Meta:
        ordering = ["-opened_at", "-id"]

    def __str__(self) -> str:
        return f"WO#{self.id} {self.asset.asset_tag} {self.title}"

    def close(self, *, status: str = STATUS_DONE, resolution: str = "", downtime: int | None = None, cost: Decimal | None = None):
        self.status = status
        self.closed_at = timezone.now()
        if resolution:
            self.resolution = resolution
        if downtime is not None:
            self.downtime_minutes = max(0, int(downtime))
        if cost is not None:
            self.cost_eur = cost
        self.save(
            update_fields=[
                "status",
                "closed_at",
                "resolution",
                "downtime_minutes",
                "cost_eur",
            ]
        )


def _workorder_attachment_upload_to(instance, filename: str) -> str:
    asset_tag = "asset-tmp"
    if instance.work_order_id and instance.work_order and instance.work_order.asset_id:
        asset_tag = instance.work_order.asset.asset_tag or f"asset-{instance.work_order.asset_id}"
    suffix = Path(filename or "").suffix.lower()[:20]
    stem = slugify(Path(filename or "").stem)[:80] or "allegato"
    stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    token = uuid.uuid4().hex[:8]
    return f"assets_workorders/{asset_tag}/{instance.work_order_id or 'tmp'}/{stamp}_{token}_{stem}{suffix}"


class WorkOrderAttachment(models.Model):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=_workorder_attachment_upload_to)
    original_name = models.CharField(max_length=255, blank=True, default="")
    notes = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_workorder_attachments_uploaded",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"WOAttachment<{self.work_order_id}:{self.original_name or Path(self.file.name).name}>"

    def save(self, *args, **kwargs):
        if not self.original_name and self.file:
            self.original_name = Path(self.file.name).name[:255]
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        storage = self.file.storage if self.file else None
        file_name = self.file.name if self.file else ""
        super().delete(*args, **kwargs)
        if storage and file_name and storage.exists(file_name):
            storage.delete(file_name)


class WorkOrderLog(models.Model):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="logs")
    ts = models.DateTimeField(default=timezone.now)
    note = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_workorder_logs",
    )

    class Meta:
        ordering = ["-ts", "-id"]

    def __str__(self) -> str:
        return f"WOLog<{self.work_order_id} {self.ts:%Y-%m-%d %H:%M}>"


class AssetHeaderTool(models.Model):
    """Pulsanti strumento nella barra header dell'inventario asset (campana, widget, cloud)."""

    TOOL_AVVISI = "avvisi"
    TOOL_WIDGET = "widget"
    TOOL_SYNC = "sync"

    code = models.CharField(max_length=40, unique=True)
    label = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True, help_text="Se disattivo, il pulsante non appare a nessuno.")
    admin_only = models.BooleanField(
        default=False,
        help_text="Se attivo, visibile solo agli amministratori asset. Altrimenti visibile a tutti gli utenti autenticati.",
    )
    sort_order = models.IntegerField(default=100)

    class Meta:
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return f"{self.label} ({self.code})"
