from __future__ import annotations

import calendar
import logging
import re
import uuid
from pathlib import Path
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.utils import timezone
from django.utils.text import slugify

from .storage import PrivateAssetAdministrativeDeadlineStorage, PrivateAssetDocumentStorage

logger = logging.getLogger(__name__)


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
    TYPE_CARROPONTE = "CARROPONTE"
    TYPE_CCTV = "CCTV"
    TYPE_FONIA = "FONIA"
    TYPE_CHEMICAL = "PRODOTTO_CHIMICO"
    TYPE_OTHER = "OTHER"

    TYPE_CHOICES = [
        (TYPE_PC, "PC"),
        (TYPE_NOTEBOOK, "Portatile"),
        (TYPE_SERVER, "Server"),
        (TYPE_VM, "Macchina virtuale"),
        (TYPE_FIREWALL, "Firewall"),
        (TYPE_STAMPANTE, "Stampante"),
        (TYPE_HW, "Dispositivo"),
        (TYPE_FONIA, "Fonia"),
        (TYPE_CNC, "CNC"),
        (TYPE_WORK_MACHINE, "Macchina di lavoro"),
        (TYPE_CARROPONTE, "Carroponte"),
        (TYPE_CCTV, "Videosorveglianza"),
        (TYPE_CHEMICAL, "Prodotto chimico"),
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
    internal_number = models.CharField(max_length=64, blank=True, default="", db_index=True)
    name = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_OTHER)
    # Link 1:1 all'anagrafica chimica (fonte unica in schede_sicurezza) per gli asset
    # di tipo "Prodotto chimico". String-ref per evitare cicli di import.
    prodotto_chimico = models.OneToOneField(
        "schede_sicurezza.ProdottoChimico",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_container",
    )
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
    purchase_date = models.DateField(null=True, blank=True)
    production_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    foto_targhetta = models.ImageField(
        upload_to="assets/targhette/",
        null=True,
        blank=True,
        verbose_name="Foto targhetta",
        help_text="Foto della targhetta identificativa della macchina, mostrata in cima alla scheda dell'asset.",
    )
    part_145 = models.BooleanField(
        default=False,
        verbose_name="Rientra in PART 145",
        help_text="Indica se l'asset rientra nel regolamento aeronautico PART 145.",
    )
    sharepoint_folder_url = models.CharField(max_length=1000, blank=True, default="")
    sharepoint_folder_path = models.CharField(max_length=500, blank=True, default="")
    sharepoint_drive_id = models.CharField(max_length=255, blank=True, default="")
    sharepoint_item_id = models.CharField(max_length=255, blank=True, default="")
    sharepoint_public_url = models.CharField(max_length=1000, blank=True, default="")
    sharepoint_public_link_id = models.CharField(max_length=255, blank=True, default="")
    sharepoint_public_enabled = models.BooleanField(default=False)
    sharepoint_public_created_at = models.DateTimeField(null=True, blank=True)
    sharepoint_public_last_checked_at = models.DateTimeField(null=True, blank=True)
    sharepoint_public_error = models.TextField(blank=True, default="")
    public_qr_token = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    public_qr_enabled = models.BooleanField(default=True)
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

    @classmethod
    def default_chemical_category(cls) -> "AssetCategory | None":
        """Categoria asset da agganciare agli asset di tipo "Prodotto chimico".

        Senza asset_category, category_label ricade su get_asset_type_display()
        (l'etichetta del tipo, es. "Prodotto chimico" al singolare) invece della
        categoria reale creata in "Impostazioni asset" (es. "Prodotti chimici").

        Cerca prima per `base_asset_type` (fonte autoritativa se la categoria è
        stata configurata esplicitamente). Se nessuna categoria lo ha impostato
        — caso reale: `classify_asset_type` non riconosceva "chimic*" come
        parola chiave, quindi una categoria "Prodotti Chimici" creata prima di
        quel fix resta con `base_asset_type` di default ("Altro") — ripiega
        sul nome della categoria, per non lasciare l'asset senza categoria solo
        perché un campo di configurazione non è stato (o non poteva essere)
        impostato correttamente a monte.
        """
        by_type = (
            AssetCategory.objects.filter(is_active=True, base_asset_type=cls.TYPE_CHEMICAL)
            .order_by("sort_order", "label", "id")
            .first()
        )
        if by_type:
            return by_type
        return (
            AssetCategory.objects.filter(is_active=True, label__icontains="chimic")
            .order_by("sort_order", "label", "id")
            .first()
        )

    def _asset_tag_prefix(self) -> str:
        if self.asset_type in {
            self.TYPE_PC,
            self.TYPE_NOTEBOOK,
            self.TYPE_SERVER,
            self.TYPE_VM,
            self.TYPE_FIREWALL,
            self.TYPE_STAMPANTE,
            self.TYPE_HW,
            self.TYPE_FONIA,
        }:
            return "IT"
        if self.asset_type == self.TYPE_CNC:
            return "CNC"
        if self.asset_type == self.TYPE_WORK_MACHINE:
            return "ML"
        if self.asset_type == self.TYPE_CARROPONTE:
            return "CP"
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
        if self.public_qr_enabled and not self.public_qr_token:
            self.public_qr_token = uuid.uuid4().hex
        # N. interno opt-in: nessuna auto-assegnazione. Il progressivo si "prende"
        # su richiesta esplicita dal form (bottone "Assegna progressivo", endpoint
        # assets:internal_number_next). Campo vuoto → salva vuoto.
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

    # ── Completezza scheda ───────────────────────────────────────────────────
    # Campi anagrafici "core" sempre rilevanti per la completezza, con etichetta
    # leggibile. L'assegnatario è valutato a parte (più sorgenti possibili).
    _COMPLETENESS_CORE_FIELDS = (
        ("name", "Nome"),
        ("serial_number", "Numero di serie"),
        ("manufacturer", "Produttore"),
        ("model", "Modello"),
        ("reparto", "Reparto"),
        ("purchase_date", "Data acquisto"),
    )

    def _has_assignment(self) -> bool:
        return bool((self.assignment_to or "").strip()) or bool(self.assigned_legacy_user_id)

    def completeness(self, category_fields=None) -> dict:
        """Valuta la completezza della scheda: campi core + category field richiesti.

        Ritorna {"total", "filled", "pct", "missing": [label, ...]}. I campi
        BOOL dei category field sono esclusi (un Sì/No non è un "dato mancante").
        ``category_fields`` può essere passato già caricato (per liste/report) per
        evitare una query per asset; se omesso viene letto al volo (0 se nessuna
        categoria).
        """
        missing: list[str] = []
        total = 0
        filled = 0

        for attr, label in self._COMPLETENESS_CORE_FIELDS:
            total += 1
            value = getattr(self, attr, None)
            if value not in (None, ""):
                filled += 1
            else:
                missing.append(label)

        total += 1
        if self._has_assignment():
            filled += 1
        else:
            missing.append("Assegnatario")

        if category_fields is None:
            if self.asset_category_id:
                category_fields = [
                    f for f in self.asset_category.category_fields.all()
                    if f.is_active and f.is_required
                ]
            else:
                category_fields = []

        extra = self.extra_columns if isinstance(self.extra_columns, dict) else {}
        for field_def in category_fields:
            if not getattr(field_def, "is_required", False) or not getattr(field_def, "is_active", True):
                continue
            if field_def.field_type == AssetCategoryField.TYPE_BOOL:
                continue
            total += 1
            raw = extra.get(field_def.code)
            if str(raw or "").strip():
                filled += 1
            else:
                missing.append(field_def.label)

        pct = int(round(100 * filled / total)) if total else 100
        return {"total": total, "filled": filled, "pct": pct, "missing": missing}

    @property
    def completeness_pct(self) -> int:
        return self.completeness()["pct"]


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
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
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
        indexes = [
            models.Index(fields=["parent", "label"], name="assetcat_parent_label_idx"),
        ]

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
    SECTION_LICENSES = "LICENSES"
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
        (SECTION_LICENSES, "Licenze software"),
        (SECTION_PERIODIC, "Manutenzione periodica"),
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
        (SECTION_MAIN, "Navigazione"),
        (SECTION_ANALYTICS, "Analisi e rischio"),
        (SECTION_OPERATIONS, "Strumenti e gestione"),
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


class AssetComponent(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="components")
    code = models.CharField(max_length=80, blank=True, default="")
    name = models.CharField(max_length=200)
    component_type = models.CharField(max_length=120, blank=True, default="")
    serial_number = models.CharField(max_length=120, blank=True, default="")
    manufacturer = models.CharField(max_length=120, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    installed_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset__name", "-is_active", "name", "code", "id"]
        verbose_name = "Componente asset"
        verbose_name_plural = "Componenti asset"

    def __str__(self) -> str:
        if self.code:
            return f"{self.asset.asset_tag} - {self.code} - {self.name}"
        return f"{self.asset.asset_tag} - {self.name}"

    def clean(self):
        self.code = (self.code or "").strip()
        self.name = (self.name or "").strip()
        if not self.name:
            raise ValidationError({"name": "Inserisci il nome del componente."})
        if self.asset_id and self.code:
            duplicate_qs = AssetComponent.objects.filter(asset_id=self.asset_id, code__iexact=self.code)
            if self.pk:
                duplicate_qs = duplicate_qs.exclude(pk=self.pk)
            if duplicate_qs.exists():
                raise ValidationError({"code": "Esiste gia un componente con questo codice per questo asset."})


# Scadenze manuali amministrative o tecniche: convivono con PeriodicVerification
# ma non la sostituiscono, perche non gestiscono ricorrenze.
class AssetAdministrativeDeadline(models.Model):
    TYPE_REVISION = "REVISION"
    TYPE_CERTIFICATE = "CERTIFICATE"
    TYPE_ADMINISTRATIVE = "ADMINISTRATIVE"
    TYPE_TECHNICAL = "TECHNICAL"
    TYPE_OTHER = "OTHER"
    TYPE_CHOICES = [
        (TYPE_REVISION, "Revisione"),
        (TYPE_CERTIFICATE, "Certificato"),
        (TYPE_ADMINISTRATIVE, "Scadenza amministrativa"),
        (TYPE_TECHNICAL, "Scadenza tecnica"),
        (TYPE_OTHER, "Altro"),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="administrative_deadlines")
    component = models.ForeignKey(
        "AssetComponent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="administrative_deadlines",
    )
    deadline_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_ADMINISTRATIVE, db_index=True)
    title = models.CharField(max_length=200)
    reference_code = models.CharField(max_length=120, blank=True, default="")
    issuer = models.CharField(max_length=200, blank=True, default="")
    issued_on = models.DateField(null=True, blank=True)
    due_date = models.DateField(db_index=True)
    warning_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", "asset__name", "title", "id"]
        verbose_name = "Scadenza asset"
        verbose_name_plural = "Scadenze asset"

    def __str__(self) -> str:
        return f"{self.title} - {self.asset.asset_tag} ({self.due_date:%d-%m-%Y})"

    def clean(self):
        self.title = (self.title or "").strip()
        self.reference_code = (self.reference_code or "").strip()
        self.issuer = (self.issuer or "").strip()
        if not self.title:
            raise ValidationError({"title": "Inserisci un titolo per la scadenza."})
        if self.component_id and self.asset_id and self.component and self.component.asset_id != self.asset_id:
            raise ValidationError({"component": "Il componente selezionato non appartiene all'asset indicato."})

    def days_until_due(self, reference_date=None) -> int | None:
        if not self.due_date:
            return None
        current_day = reference_date or timezone.localdate()
        return (self.due_date - current_day).days


class AssetAdministrativeDeadlineCompletion(models.Model):
    deadline = models.ForeignKey(
        AssetAdministrativeDeadline,
        on_delete=models.CASCADE,
        related_name="completions",
    )
    completed_on = models.DateField(db_index=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_asset_administrative_deadlines",
    )
    cost_eur = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, default="")
    next_due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-completed_on", "-id"]
        verbose_name = "Esecuzione scadenza"
        verbose_name_plural = "Esecuzioni scadenze"

    def __str__(self) -> str:
        return f"Completamento {self.deadline_id} del {self.completed_on:%d-%m-%Y}"


def _admin_deadline_completion_attachment_upload_to(instance, filename: str) -> str:
    asset_tag = "asset-tmp"
    completion = getattr(instance, "completion", None)
    deadline = getattr(completion, "deadline", None) if completion else None
    asset = getattr(deadline, "asset", None) if deadline else None
    if asset is not None:
        asset_tag = asset.asset_tag or f"asset-{asset.id}"
    suffix = Path(filename or "").suffix.lower()[:20]
    stem = slugify(Path(filename or "").stem)[:80] or "allegato"
    stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    token = uuid.uuid4().hex[:8]
    completion_id = getattr(instance, "completion_id", None) or "tmp"
    return f"assets_admin_deadlines/{asset_tag}/{completion_id}/{stamp}_{token}_{stem}{suffix}"


class AssetAdministrativeDeadlineCompletionAttachment(models.Model):
    completion = models.ForeignKey(
        AssetAdministrativeDeadlineCompletion,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(
        upload_to=_admin_deadline_completion_attachment_upload_to,
        storage=PrivateAssetAdministrativeDeadlineStorage(),
    )
    original_name = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_admin_deadline_completion_attachments_uploaded",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"AdminDeadlineAttachment<{self.completion_id}:{self.original_name or Path(self.file.name).name}>"

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


class MaintenanceInterventionTemplate(models.Model):
    code = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    asset_category = models.ForeignKey(
        AssetCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_intervention_templates",
    )
    sort_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "label", "id"]
        verbose_name = "Template intervento manutenzione"
        verbose_name_plural = "Template interventi manutenzione"

    def __str__(self) -> str:
        if self.asset_category_id and self.asset_category:
            return f"{self.asset_category.label} - {self.label}"
        return self.label

    def clean(self):
        self.label = (self.label or "").strip()
        self.description = (self.description or "").strip()
        if not self.label:
            raise ValidationError({"label": "Inserisci il nome del template intervento."})


class MaintenanceChecklistStep(models.Model):
    """Step di checklist predefiniti collegati a un template intervento.
    Vengono copiati automaticamente come WorkOrderChecklist alla creazione dell'OdL."""

    intervention_template = models.ForeignKey(
        MaintenanceInterventionTemplate,
        on_delete=models.CASCADE,
        related_name="checklist_steps",
    )
    step_number = models.PositiveSmallIntegerField(default=10)
    description = models.CharField(max_length=255)

    class Meta:
        ordering = ["intervention_template", "step_number", "id"]
        verbose_name = "Step checklist template"
        verbose_name_plural = "Step checklist template"

    def __str__(self) -> str:
        return f"{self.intervention_template.label} - step {self.step_number}: {self.description}"


class MaintenanceRule(models.Model):
    THRESHOLD_DAYS = "DAYS"
    THRESHOLD_HOURS = "HOURS"
    THRESHOLD_KM = "KM"
    THRESHOLD_CYCLES = "CYCLES"
    THRESHOLD_TYPE_CHOICES = [
        (THRESHOLD_DAYS, "Giorni"),
        (THRESHOLD_HOURS, "Ore"),
        (THRESHOLD_KM, "Km"),
        (THRESHOLD_CYCLES, "Cicli"),
    ]

    MODE_INTERNAL = "INTERNAL"
    MODE_EXTERNAL = "EXTERNAL"
    EXECUTION_MODE_CHOICES = [
        (MODE_INTERNAL, "Interna"),
        (MODE_EXTERNAL, "Esterna (ditta terza)"),
    ]

    intervention_template = models.ForeignKey(
        "MaintenanceInterventionTemplate",
        on_delete=models.PROTECT,
        related_name="maintenance_rules",
    )
    asset_category = models.ForeignKey(
        AssetCategory,
        on_delete=models.CASCADE,
        related_name="maintenance_rules",
    )
    # In Step 2 i threshold a ore/km/cicli sono modellati ma non ancora pienamente operativi.
    threshold_type = models.CharField(max_length=20, choices=THRESHOLD_TYPE_CHOICES, default=THRESHOLD_DAYS, db_index=True)
    threshold_value = models.PositiveIntegerField()
    warning_days = models.PositiveIntegerField(default=15)
    # Interna (fatta dal team) o esterna (ditta terza). Il fornitore è opzionale:
    # una manutenzione può essere "esterna" anche prima di sapere quale ditta la esegue.
    execution_mode = models.CharField(
        max_length=20,
        choices=EXECUTION_MODE_CHOICES,
        default=MODE_INTERNAL,
        db_index=True,
    )
    supplier = models.ForeignKey(
        "anagrafica.Fornitore",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_rules",
        help_text="Ditta esterna che esegue l'intervento (solo per manutenzioni esterne).",
    )
    sort_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset_category__sort_order", "asset_category__label", "sort_order", "id"]
        verbose_name = "Regola manutenzione"
        verbose_name_plural = "Regole manutenzione"

    @property
    def is_external(self) -> bool:
        return self.execution_mode == self.MODE_EXTERNAL

    def __str__(self) -> str:
        return (
            f"{self.asset_category.label} - {self.intervention_template.label} "
            f"({self.threshold_value} {self.get_threshold_type_display()})"
        )

    def clean(self):
        self.notes = (self.notes or "").strip()
        # Coerenza interna/esterna: una manutenzione interna non ha ditta terza.
        if self.execution_mode == self.MODE_INTERNAL:
            self.supplier = None
        if not self.asset_category_id:
            raise ValidationError({"asset_category": "Seleziona una categoria asset."})
        if not self.intervention_template_id:
            raise ValidationError({"intervention_template": "Seleziona un template intervento."})
        template_category_id = getattr(self.intervention_template, "asset_category_id", None)
        if template_category_id and template_category_id != self.asset_category_id:
            raise ValidationError(
                {
                    "intervention_template": (
                        "Il template selezionato e legato a una categoria diversa rispetto alla regola."
                    )
                }
        )


class MaintenanceRuleAssetOverride(models.Model):
    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="maintenance_rule_overrides",
    )
    base_rule = models.ForeignKey(
        "MaintenanceRule",
        on_delete=models.CASCADE,
        related_name="asset_overrides",
    )
    override_threshold_type = models.CharField(
        max_length=20,
        choices=MaintenanceRule.THRESHOLD_TYPE_CHOICES,
        null=True,
        blank=True,
        db_index=True,
    )
    override_threshold_value = models.PositiveIntegerField(null=True, blank=True)
    override_intervention_template = models.ForeignKey(
        "MaintenanceInterventionTemplate",
        on_delete=models.PROTECT,
        related_name="asset_rule_overrides",
        null=True,
        blank=True,
    )
    is_disabled = models.BooleanField(default=False, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset__name", "asset__asset_tag", "base_rule__sort_order", "id"]
        verbose_name = "Override regola manutenzione asset"
        verbose_name_plural = "Override regole manutenzione asset"
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "base_rule"],
                name="uniq_maintenance_rule_asset_override",
            )
        ]

    def __str__(self) -> str:
        asset_label = getattr(self.asset, "asset_tag", self.asset_id)
        rule_label = getattr(getattr(self.base_rule, "intervention_template", None), "label", self.base_rule_id)
        return f"{asset_label} - {rule_label}"

    @property
    def has_effective_override(self) -> bool:
        return bool(
            self.is_disabled
            or self.override_threshold_type
            or self.override_threshold_value is not None
            or self.override_intervention_template_id
            or (self.notes or "").strip()
        )

    @property
    def is_redundant(self) -> bool:
        return not self.has_effective_override

    def clean(self):
        self.notes = (self.notes or "").strip()
        if not self.asset_id:
            raise ValidationError({"asset": "Seleziona un asset."})
        if not self.base_rule_id:
            raise ValidationError({"base_rule": "Seleziona una regola base."})

        asset_category_id = getattr(self.asset, "asset_category_id", None)
        base_rule_category_id = getattr(self.base_rule, "asset_category_id", None)
        if not asset_category_id:
            raise ValidationError(
                {"asset": "L'asset selezionato non ha una categoria compatibile con le regole standard."}
            )
        if asset_category_id != base_rule_category_id:
            raise ValidationError(
                {"base_rule": "La regola base non appartiene alla stessa categoria dell'asset selezionato."}
            )

        if self.override_threshold_type and self.override_threshold_value is None:
            raise ValidationError(
                {
                    "override_threshold_value": (
                        "Quando cambi il tipo soglia devi indicare anche il valore soglia dell'override."
                    )
                }
            )

        override_template_category_id = getattr(self.override_intervention_template, "asset_category_id", None)
        if override_template_category_id and override_template_category_id != base_rule_category_id:
            raise ValidationError(
                {
                    "override_intervention_template": (
                        "Il template override deve essere generale oppure della stessa categoria della regola base."
                    )
                }
            )


class AssistanceContract(models.Model):
    TYPE_FULL_SERVICE = "FULL_SERVICE"
    TYPE_ON_CALL = "ON_CALL"
    TYPE_WARRANTY = "WARRANTY"
    TYPE_RENTAL = "RENTAL"
    TYPE_OTHER = "OTHER"
    TYPE_CHOICES = [
        (TYPE_FULL_SERVICE, "Full service"),
        (TYPE_ON_CALL, "A chiamata"),
        (TYPE_WARRANTY, "Garanzia"),
        (TYPE_RENTAL, "Noleggio / service"),
        (TYPE_OTHER, "Altro"),
    ]

    supplier = models.ForeignKey(
        "anagrafica.Fornitore",
        on_delete=models.CASCADE,
        related_name="assistance_contracts",
    )
    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="assistance_contracts",
        null=True,
        blank=True,
    )
    asset_category = models.ForeignKey(
        AssetCategory,
        on_delete=models.CASCADE,
        related_name="assistance_contracts",
        null=True,
        blank=True,
    )
    document = models.ForeignKey(
        "anagrafica.FornitoreDocumento",
        on_delete=models.SET_NULL,
        related_name="assistance_contracts",
        null=True,
        blank=True,
    )
    code = models.CharField(max_length=80, blank=True, default="")
    title = models.CharField(max_length=200)
    contract_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_OTHER, db_index=True)
    start_date = models.DateField(default=timezone.localdate, db_index=True)
    end_date = models.DateField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    sla_description = models.CharField(max_length=255, blank=True, default="")
    coverage_summary = models.TextField(blank=True, default="")
    periodic_cost_eur = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "end_date", "supplier__ragione_sociale", "title", "id"]
        verbose_name = "Contratto assistenza"
        verbose_name_plural = "Contratti assistenza"

    def __str__(self) -> str:
        label = self.code or self.title
        return f"{self.supplier} - {label}"

    @property
    def target_label(self) -> str:
        if self.asset_id and self.asset:
            return f"Asset {self.asset.asset_tag}"
        if self.asset_category_id and self.asset_category:
            return f"Categoria {self.asset_category.label}"
        return "Generale"

    def is_current(self, reference_date=None) -> bool:
        current_day = reference_date or timezone.localdate()
        if not self.is_active:
            return False
        if self.start_date and self.start_date > current_day:
            return False
        if self.end_date and self.end_date < current_day:
            return False
        return True

    def applies_to_asset(self, asset: Asset | None) -> bool:
        if asset is None:
            return False
        if self.asset_id:
            return self.asset_id == asset.id
        if self.asset_category_id:
            return self.asset_category_id == getattr(asset, "asset_category_id", None)
        return True

    def clean(self):
        self.code = (self.code or "").strip()
        self.title = (self.title or "").strip()
        self.sla_description = (self.sla_description or "").strip()
        self.coverage_summary = (self.coverage_summary or "").strip()
        self.notes = (self.notes or "").strip()
        if not self.title:
            raise ValidationError({"title": "Inserisci un titolo contratto."})
        if self.asset_id and self.asset_category_id:
            raise ValidationError(
                {"asset_category": "Scegli un contratto generale, per categoria oppure per singolo asset, non entrambi."}
            )
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "La data fine non puo essere precedente alla data inizio."})
        if self.document_id and getattr(self.document, "fornitore_id", None) != self.supplier_id:
            raise ValidationError({"document": "Il documento selezionato appartiene a un fornitore diverso."})


class SoftwareLicense(models.Model):
    CATEGORY_SOFTWARE = "SOFTWARE"
    CATEGORY_ANTIVIRUS = "ANTIVIRUS"
    CATEGORY_OFFICE = "OFFICE"
    CATEGORY_CHOICES = [
        (CATEGORY_SOFTWARE, "Software"),
        (CATEGORY_ANTIVIRUS, "Antivirus"),
        (CATEGORY_OFFICE, "Office"),
    ]

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_SOFTWARE, db_index=True)
    vendor = models.CharField(max_length=120, blank=True, default="")
    product_name = models.CharField(max_length=200)
    edition = models.CharField(max_length=120, blank=True, default="")
    license_reference = models.CharField(max_length=120, blank=True, default="")
    account_email = models.CharField(max_length=200, blank=True, default="")
    asset = models.ForeignKey(
        Asset,
        on_delete=models.SET_NULL,
        related_name="software_licenses",
        null=True,
        blank=True,
    )
    assigned_anagrafica_id = models.IntegerField(null=True, blank=True, db_index=True)
    assigned_legacy_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    assigned_to_display = models.CharField(max_length=200, blank=True, default="")
    assigned_reparto = models.CharField(max_length=120, blank=True, default="")
    seats_total = models.PositiveIntegerField(null=True, blank=True)
    seats_used = models.PositiveIntegerField(default=1)
    purchase_date = models.DateField(null=True, blank=True)
    renewal_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    auto_renew = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "vendor", "product_name", "id"]
        verbose_name = "Licenza software"
        verbose_name_plural = "Licenze software"

    def __str__(self) -> str:
        label = " - ".join(part for part in [self.product_name, self.edition] if part)
        return label or self.license_reference or f"Licenza #{self.pk or 'new'}"

    @property
    def assignment_scope(self) -> str:
        if self.asset_id:
            return "asset"
        if self.assigned_anagrafica_id or self.assigned_legacy_user_id:
            return "user"
        return "unassigned"

    @property
    def assignment_label(self) -> str:
        if self.asset_id and self.asset:
            return f"{self.asset.asset_tag} - {self.asset.name}"
        return self.assigned_to_display or "Da assegnare"

    def clean(self):
        self.vendor = (self.vendor or "").strip()
        self.product_name = (self.product_name or "").strip()
        self.edition = (self.edition or "").strip()
        self.license_reference = (self.license_reference or "").strip()
        self.account_email = (self.account_email or "").strip()
        self.assigned_to_display = (self.assigned_to_display or "").strip()
        self.assigned_reparto = (self.assigned_reparto or "").strip()
        self.notes = (self.notes or "").strip()

        if not self.product_name:
            raise ValidationError({"product_name": "Inserisci il nome del prodotto o della licenza."})
        if self.asset_id and (self.assigned_anagrafica_id or self.assigned_legacy_user_id):
            raise ValidationError(
                {"assigned_to_display": "Assegna la licenza a un asset oppure a un dipendente, non entrambi."}
            )
        if (
            self.assigned_legacy_user_id
            and self.assigned_anagrafica_id is None
            and not self.assigned_to_display
        ):
            raise ValidationError({"assigned_to_display": "Completa il nominativo del dipendente assegnatario."})
        if self.seats_total is not None and self.seats_used > self.seats_total:
            raise ValidationError({"seats_used": "I posti utilizzati non possono superare i posti acquistati."})
        if self.expiry_date and self.renewal_date and self.renewal_date > self.expiry_date:
            raise ValidationError({"renewal_date": "Il rinnovo non puo essere successivo alla scadenza attuale."})


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
    photo = models.ImageField(upload_to="assets/work_machines/photos/", null=True, blank=True)
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
    # Deprecation marker: True = gestita via MaintenanceRule/generate_scheduled_workorders
    is_legacy = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Se True, il trigger temporale è gestito da MaintenanceRule. "
            "Questo record rimane come riferimento fornitore/contratto."
        ),
    )
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
        verbose_name = "Manutenzione periodica"
        verbose_name_plural = "Manutenzioni periodiche"

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
    # Codice della cartella documento: una delle CATEGORY_CHOICES di base oppure
    # lo slug di una AssetCategoryDocumentFolder extra configurata sulla categoria.
    category = models.CharField(max_length=60, choices=CATEGORY_CHOICES, default=CATEGORY_SPECIFICHE, db_index=True)
    file = models.FileField(upload_to=_asset_document_upload_to, storage=PrivateAssetDocumentStorage())
    original_name = models.CharField(max_length=255, blank=True, default="")
    relative_folder = models.CharField(
        max_length=400,
        blank=True,
        default="",
        help_text="Percorso relativo della cartella di origine (upload 'Carica cartella'); vuoto per i file singoli.",
    )
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


class AssetCategoryDocumentFolder(models.Model):
    """Cartella documento extra configurata su una AssetCategory.

    Si aggiunge alle tre cartelle di base (specifiche/interventi/manuali) e vale
    per tutti gli asset di quella categoria. Lo ``slug`` e la chiave stabile
    salvata in ``AssetDocument.category`` e usata come nome cartella SharePoint.
    Non e rinominabile; la disattivazione (soft-delete) e consentita solo se
    nessun documento la usa.
    """

    category = models.ForeignKey(
        AssetCategory,
        on_delete=models.CASCADE,
        related_name="document_folders",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name", "id"]
        unique_together = [("category", "slug")]

    def __str__(self) -> str:
        return f"AssetCategoryDocumentFolder<{self.category_id}:{self.slug}>"


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

    ORIGIN_PERIODIC = "PERIODIC"
    ORIGIN_MANUAL = "MANUAL"
    ORIGIN_TICKET = "TICKET"
    ORIGIN_CHOICES = [
        (ORIGIN_PERIODIC, "Periodica"),
        (ORIGIN_MANUAL, "Manuale"),
        (ORIGIN_TICKET, "Da ticket"),
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
    maintenance_rule = models.ForeignKey(
        "MaintenanceRule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorders",
    )
    assistance_contract = models.ForeignKey(
        "AssistanceContract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorders",
    )
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorders_generati",
        help_text="Ticket manutenzione che ha originato questo OdL (opzionale)",
    )
    covered_by_contract = models.BooleanField(default=False, db_index=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OTHER)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    origin = models.CharField(
        max_length=20,
        choices=ORIGIN_CHOICES,
        default=ORIGIN_MANUAL,
        db_index=True,
        help_text="Origine della manutenzione (periodica, manuale, da ticket)",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorders_assigned",
        help_text="Manutentore assegnato all'intervento",
    )
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorders_executed",
        help_text="Tecnico/manutentore che ha eseguito la manutenzione",
    )
    reference_batch = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Riferimento batch/regola per manutenzioni generate in blocco",
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    resolution = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="", help_text="Note aggiuntive sulla manutenzione")
    intervention_duration_minutes = models.PositiveIntegerField(default=0)
    downtime_minutes = models.PositiveIntegerField(default=0)
    labor_cost_eur = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
    )
    materials_cost_eur = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
    )
    cost_eur = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
    )
    meter_value_at_close = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        help_text="Valore del contatore (ore/km/cicli) al momento della chiusura dell'OdL. "
                  "Compilato automaticamente dalla view di chiusura se l'asset ha un AssetMeter.",
    )

    class Meta:
        ordering = ["-opened_at", "-id"]

    def __str__(self) -> str:
        return f"WO#{self.id} {self.asset.asset_tag} {self.title}"

    def clean(self):
        if not self.asset_id:
            return
        if self.periodic_verification_id and self.periodic_verification:
            if not self.periodic_verification.assets.filter(pk=self.asset_id).exists():
                raise ValidationError({"periodic_verification": "La verifica selezionata non appartiene a questo asset."})
        if self.maintenance_rule_id and self.maintenance_rule:
            if self.maintenance_rule.asset_category_id != getattr(self.asset, "asset_category_id", None):
                raise ValidationError({"maintenance_rule": "La regola selezionata non appartiene alla categoria dell'asset."})
        if self.assistance_contract_id and self.assistance_contract:
            if not self.assistance_contract.applies_to_asset(self.asset):
                raise ValidationError({"assistance_contract": "Il contratto selezionato non copre questo asset."})
            if self.periodic_verification_id and getattr(self.periodic_verification, "supplier_id", None):
                if self.periodic_verification.supplier_id != self.assistance_contract.supplier_id:
                    raise ValidationError(
                        {"assistance_contract": "Il contratto selezionato usa un fornitore diverso dalla verifica."}
                    )
            if self.supplier_id and self.supplier_id != self.assistance_contract.supplier_id:
                raise ValidationError({"assistance_contract": "Il contratto selezionato appartiene a un fornitore diverso."})

    @property
    def resolved_total_cost_eur(self) -> Decimal | None:
        if self.cost_eur is not None:
            return self.cost_eur
        total = Decimal("0")
        has_component_cost = False
        if self.labor_cost_eur is not None:
            total += self.labor_cost_eur
            has_component_cost = True
        if self.materials_cost_eur is not None:
            total += self.materials_cost_eur
            has_component_cost = True
        return total if has_component_cost else None

    def close(
        self,
        *,
        status: str = STATUS_DONE,
        resolution: str = "",
        downtime: int | None = None,
        cost: Decimal | None = None,
        labor_cost: Decimal | None = None,
        materials_cost: Decimal | None = None,
        intervention_duration: int | None = None,
        covered_by_contract: bool | None = None,
        assistance_contract: "AssistanceContract" | None = None,
    ):
        self.status = status
        self.closed_at = timezone.now()
        if resolution:
            self.resolution = resolution
        if intervention_duration is not None:
            self.intervention_duration_minutes = max(0, int(intervention_duration))
        if downtime is not None:
            self.downtime_minutes = max(0, int(downtime))
        if labor_cost is not None:
            self.labor_cost_eur = labor_cost
        if materials_cost is not None:
            self.materials_cost_eur = materials_cost
        if covered_by_contract is not None:
            self.covered_by_contract = bool(covered_by_contract)
        if assistance_contract is not None:
            self.assistance_contract = assistance_contract
            if self.supplier_id is None and assistance_contract.supplier_id:
                self.supplier = assistance_contract.supplier
        elif covered_by_contract is False:
            self.assistance_contract = None
        if (
            status == self.STATUS_DONE
            and self.meter_value_at_close is None
            and self.maintenance_rule_id
            and self.asset_id
        ):
            meter_type = {
                MaintenanceRule.THRESHOLD_HOURS: AssetMeter.METER_HOURS,
                MaintenanceRule.THRESHOLD_KM: AssetMeter.METER_KM,
                MaintenanceRule.THRESHOLD_CYCLES: AssetMeter.METER_CYCLES,
            }.get(self.maintenance_rule.threshold_type)
            if meter_type:
                meter = (
                    AssetMeter.objects
                    .filter(asset_id=self.asset_id, meter_type=meter_type)
                    .only("current_value")
                    .first()
                )
                if meter is not None:
                    self.meter_value_at_close = meter.current_value
        if cost is not None:
            self.cost_eur = cost
        elif labor_cost is not None or materials_cost is not None:
            self.cost_eur = self.resolved_total_cost_eur
        self.full_clean()
        self.save(
            update_fields=[
                "status",
                "closed_at",
                "resolution",
                "intervention_duration_minutes",
                "downtime_minutes",
                "assigned_to",
                "executed_by",
                "labor_cost_eur",
                "materials_cost_eur",
                "supplier",
                "covered_by_contract",
                "assistance_contract",
                "cost_eur",
                "meter_value_at_close",
            ]
        )
        # P1.3 — aggiorna next_maintenance_date sulla WorkMachine collegata quando l'OdL è periodico
        if (
            status == self.STATUS_DONE
            and self.origin == self.ORIGIN_PERIODIC
            and self.maintenance_rule_id
        ):
            from datetime import timedelta
            try:
                rule = self.maintenance_rule
                if rule.threshold_type == MaintenanceRule.THRESHOLD_DAYS and rule.threshold_value:
                    wm = getattr(self.asset, "work_machine", None)
                    if wm is not None:
                        closed_date = self.closed_at.date() if self.closed_at else timezone.localdate()
                        wm.next_maintenance_date = closed_date + timedelta(days=rule.threshold_value)
                        wm.save(update_fields=["next_maintenance_date"])
            except Exception:
                # La prossima manutenzione non viene ricalcolata: la macchina
                # sparisce dalle scadenze senza che nessuno lo noti.
                logger.exception("Assets: ricalcolo della prossima manutenzione fallito")


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
    file = models.FileField(upload_to=_workorder_attachment_upload_to, storage=PrivateAssetDocumentStorage())
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


class WorkOrderChecklist(models.Model):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="checklist_items")
    step_number = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=255)
    is_done = models.BooleanField(default=False, db_index=True)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorder_checklist_done",
    )

    class Meta:
        ordering = ["work_order", "step_number", "id"]
        verbose_name = "Step checklist OdL"
        verbose_name_plural = "Step checklist OdL"

    def __str__(self) -> str:
        return f"WOChecklist<wo={self.work_order_id} step={self.step_number}>"

    def toggle(self, user) -> None:
        from django.utils import timezone as tz
        if self.is_done:
            self.is_done = False
            self.done_at = None
            self.done_by = None
        else:
            self.is_done = True
            self.done_at = tz.now()
            self.done_by = user
        self.save(update_fields=["is_done", "done_at", "done_by_id"])


class AssetMaintenanceRuleState(models.Model):
    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="maintenance_rule_states",
    )
    base_rule = models.ForeignKey(
        "MaintenanceRule",
        on_delete=models.CASCADE,
        related_name="asset_states",
    )
    last_execution_date = models.DateField(null=True, blank=True, db_index=True)
    last_work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_rule_states",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset__name", "base_rule__sort_order", "id"]
        verbose_name = "Stato manutenzione asset"
        verbose_name_plural = "Stati manutenzione asset"
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "base_rule"],
                name="uniq_asset_maintenance_rule_state",
            )
        ]

    def __str__(self) -> str:
        asset_label = getattr(self.asset, "asset_tag", self.asset_id)
        rule_label = getattr(getattr(self.base_rule, "intervention_template", None), "label", self.base_rule_id)
        return f"{asset_label} - {rule_label}"

    def clean(self):
        self.notes = (self.notes or "").strip()
        if not self.asset_id:
            raise ValidationError({"asset": "Seleziona un asset."})
        if not self.base_rule_id:
            raise ValidationError({"base_rule": "Seleziona una regola base."})
        asset_category_id = getattr(self.asset, "asset_category_id", None)
        if asset_category_id != getattr(self.base_rule, "asset_category_id", None):
            raise ValidationError({"base_rule": "La regola selezionata non appartiene alla categoria dell'asset."})
        if self.last_work_order_id and getattr(self.last_work_order, "asset_id", None) != self.asset_id:
            raise ValidationError({"last_work_order": "Il work order collegato appartiene a un asset diverso."})


class AssetMeter(models.Model):
    METER_HOURS = "HOURS"
    METER_KM = "KM"
    METER_CYCLES = "CYCLES"
    METER_OTHER = "OTHER"
    METER_TYPE_CHOICES = [
        (METER_HOURS, "Ore"),
        (METER_KM, "Km"),
        (METER_CYCLES, "Cicli"),
        (METER_OTHER, "Altro"),
    ]

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="meters",
    )
    meter_type = models.CharField(max_length=20, choices=METER_TYPE_CHOICES, db_index=True)
    current_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_label = models.CharField(max_length=30, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_asset_meters",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["asset__name", "meter_type", "id"]
        verbose_name = "Contatore asset"
        verbose_name_plural = "Contatori asset"
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "meter_type"],
                name="uniq_asset_meter_type",
            )
        ]

    def __str__(self) -> str:
        label = self.unit_label or self.get_meter_type_display()
        return f"{self.asset} — {label}: {self.current_value}"

    def update_value(self, new_value, user) -> "AssetMeterHistory":
        old_value = self.current_value
        self.current_value = new_value
        self.updated_by = user
        self.save(update_fields=["current_value", "updated_by_id", "updated_at"])
        return AssetMeterHistory.objects.create(
            meter=self,
            old_value=old_value,
            new_value=new_value,
            recorded_by=user,
        )


class AssetMeterHistory(models.Model):
    meter = models.ForeignKey(
        AssetMeter,
        on_delete=models.CASCADE,
        related_name="history",
    )
    old_value = models.DecimalField(max_digits=12, decimal_places=2)
    new_value = models.DecimalField(max_digits=12, decimal_places=2)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_meter_history_entries",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at", "id"]
        verbose_name = "Storico contatore asset"
        verbose_name_plural = "Storico contatori asset"

    def __str__(self) -> str:
        return f"{self.meter} @ {self.recorded_at:%Y-%m-%d %H:%M}: {self.old_value} -> {self.new_value}"


class AssetCalendarEvent(models.Model):
    KIND_MAINTENANCE = "MAINTENANCE"
    KIND_ADMINISTRATIVE_DEADLINE = "ADMIN_DEADLINE"
    KIND_PERIODIC_VERIFICATION = "PERIODIC_VERIFICATION"
    KIND_ASSISTANCE_CONTRACT = "ASSISTANCE_CONTRACT"
    KIND_CHOICES = [
        (KIND_MAINTENANCE, "Manutenzione"),
        (KIND_ADMINISTRATIVE_DEADLINE, "Scadenza amministrativa"),
        (KIND_PERIODIC_VERIFICATION, "Verifica periodica"),
        (KIND_ASSISTANCE_CONTRACT, "Contratto assistenza"),
    ]

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="calendar_events",
    )
    event_kind = models.CharField(max_length=40, choices=KIND_CHOICES, default=KIND_MAINTENANCE, db_index=True)
    maintenance_rule = models.ForeignKey(
        "MaintenanceRule",
        on_delete=models.CASCADE,
        related_name="calendar_events",
        null=True,
        blank=True,
    )
    administrative_deadline = models.ForeignKey(
        "AssetAdministrativeDeadline",
        on_delete=models.CASCADE,
        related_name="calendar_events",
        null=True,
        blank=True,
    )
    periodic_verification = models.ForeignKey(
        "PeriodicVerification",
        on_delete=models.CASCADE,
        related_name="calendar_events",
        null=True,
        blank=True,
    )
    assistance_contract = models.ForeignKey(
        "AssistanceContract",
        on_delete=models.CASCADE,
        related_name="calendar_events",
        null=True,
        blank=True,
    )
    due_date = models.DateField(db_index=True)
    source_key = models.CharField(max_length=255, unique=True, db_index=True, default="")
    target_legacy_user_id = models.IntegerField(db_index=True)
    target_display_name = models.CharField(max_length=200, blank=True, default="")
    target_email = models.CharField(max_length=200)
    subject = models.CharField(max_length=255, blank=True, default="")
    transaction_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    graph_event_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    graph_event_web_link = models.CharField(max_length=1000, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_calendar_events_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", "target_display_name", "target_email", "id"]
        verbose_name = "Evento calendario asset"
        verbose_name_plural = "Eventi calendario asset"

    def __str__(self) -> str:
        asset_label = getattr(self.asset, "asset_tag", self.asset_id)
        source_label = self.source_object_label
        target_label = self.target_display_name or self.target_email or self.target_legacy_user_id
        return f"{asset_label} - {source_label} - {target_label}"

    @property
    def source_object_label(self) -> str:
        if self.event_kind == self.KIND_MAINTENANCE and self.maintenance_rule_id:
            return getattr(getattr(self.maintenance_rule, "intervention_template", None), "label", "") or "Manutenzione"
        if self.event_kind == self.KIND_ADMINISTRATIVE_DEADLINE and self.administrative_deadline_id:
            return getattr(self.administrative_deadline, "title", "") or "Scadenza amministrativa"
        if self.event_kind == self.KIND_PERIODIC_VERIFICATION and self.periodic_verification_id:
            return getattr(self.periodic_verification, "name", "") or "Verifica periodica"
        if self.event_kind == self.KIND_ASSISTANCE_CONTRACT and self.assistance_contract_id:
            return getattr(self.assistance_contract, "title", "") or "Contratto assistenza"
        return self.get_event_kind_display() or "Evento asset"

    def clean(self):
        self.source_key = (self.source_key or "").strip()
        self.target_display_name = (self.target_display_name or "").strip()
        self.target_email = (self.target_email or "").strip()
        self.subject = (self.subject or "").strip()
        self.transaction_id = (self.transaction_id or "").strip()
        self.graph_event_id = (self.graph_event_id or "").strip()
        self.graph_event_web_link = (self.graph_event_web_link or "").strip()
        if not self.asset_id:
            raise ValidationError({"asset": "Seleziona un asset."})
        if not self.due_date:
            raise ValidationError({"due_date": "La data scadenza e obbligatoria."})
        if not self.source_key:
            raise ValidationError({"source_key": "Chiave sorgente evento obbligatoria."})
        if not int(self.target_legacy_user_id or 0):
            raise ValidationError({"target_legacy_user_id": "Seleziona un utente destinazione."})
        if not self.target_email:
            raise ValidationError({"target_email": "L'utente selezionato non ha un identificatore Outlook valido."})
        source_fields = {
            self.KIND_MAINTENANCE: bool(self.maintenance_rule_id),
            self.KIND_ADMINISTRATIVE_DEADLINE: bool(self.administrative_deadline_id),
            self.KIND_PERIODIC_VERIFICATION: bool(self.periodic_verification_id),
            self.KIND_ASSISTANCE_CONTRACT: bool(self.assistance_contract_id),
        }
        if self.event_kind not in source_fields:
            raise ValidationError({"event_kind": "Tipo evento non valido."})
        if not source_fields[self.event_kind]:
            raise ValidationError({"event_kind": "Collega l'evento alla sorgente coerente con il tipo selezionato."})
        if sum(1 for value in source_fields.values() if value) != 1:
            raise ValidationError("Associa un solo tipo di sorgente per evento calendario asset.")
        if self.maintenance_rule_id:
            asset_category_id = getattr(self.asset, "asset_category_id", None)
            if asset_category_id != getattr(self.maintenance_rule, "asset_category_id", None):
                raise ValidationError({"maintenance_rule": "La regola selezionata non appartiene alla categoria dell'asset."})
        if self.administrative_deadline_id and getattr(self.administrative_deadline, "asset_id", None) != self.asset_id:
            raise ValidationError({"administrative_deadline": "La scadenza selezionata appartiene a un asset diverso."})
        if self.periodic_verification_id and not self.periodic_verification.assets.filter(pk=self.asset_id).exists():
            raise ValidationError({"periodic_verification": "La verifica selezionata non e collegata a questo asset."})
        if self.assistance_contract_id and not self.assistance_contract.applies_to_asset(self.asset):
            raise ValidationError({"assistance_contract": "Il contratto selezionato non si applica a questo asset."})


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


class AssetDashboardConfig(models.Model):
    """Configurazione widget dashboard per utente nel modulo Assets."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="asset_dashboard_config",
    )
    # Lista ordinata di codici widget abilitati (JSON array di stringhe)
    enabled_widgets = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configurazione dashboard asset"
        verbose_name_plural = "Configurazioni dashboard asset"

    def __str__(self) -> str:
        return f"DashboardConfig [{self.user}]"

    # Widget disponibili con ordine di default
    DEFAULT_WIDGETS: list[str] = [
        "totale_asset",
        "asset_in_uso",
        "asset_in_riparazione",
        "scadenze_scadute",
        "scadenze_30gg",
        "scadenze_90gg",
        "wo_aperte",
        "wo_chiuse_mese",
        "verifiche_scadute",
        "verifiche_30gg",
        "asset_per_stato",
        "asset_per_categoria",
    ]

    def get_enabled_widgets(self) -> list[str]:
        saved = self.enabled_widgets
        if not saved or not isinstance(saved, list):
            return list(self.DEFAULT_WIDGETS)
        # Mantieni solo widget validi nell'ordine salvato, aggiungi nuovi in coda
        valid = set(self.DEFAULT_WIDGETS)
        result = [w for w in saved if w in valid]
        for w in self.DEFAULT_WIDGETS:
            if w not in result:
                result.append(w)
        return result


class AssetMaintenanceBudget(models.Model):
    """Budget annuale di manutenzione per categoria asset (AS3)."""

    asset_category = models.ForeignKey(
        AssetCategory,
        on_delete=models.CASCADE,
        related_name="maintenance_budgets",
    )
    year = models.PositiveSmallIntegerField(db_index=True)
    budget_eur = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("asset_category", "year")]
        ordering = ["-year", "asset_category"]
        verbose_name = "Budget manutenzione categoria"
        verbose_name_plural = "Budget manutenzione categoria"

    def __str__(self) -> str:
        return f"Budget {self.asset_category} — {self.year}: €{self.budget_eur}"
