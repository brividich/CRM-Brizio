from django.contrib import admin

from .models import (
    Asset,
    AssetActionButton,
    AssetCategory,
    AssetCategoryField,
    AssetCustomField,
    AssetDetailField,
    AssetDetailSectionLayout,
    AssetDocument,
    AssetEndpoint,
    AssetITDetails,
    AssetLabelTemplate,
    AssetListLayout,
    AssetListOption,
    AssetSidebarButton,
    PeriodicVerification,
    PlantLayout,
    PlantLayoutArea,
    PlantLayoutMarker,
    WorkMachine,
    WorkOrder,
    WorkOrderLog,
)


class AssetEndpointInline(admin.TabularInline):
    model = AssetEndpoint
    extra = 0


class AssetITDetailsInline(admin.StackedInline):
    model = AssetITDetails
    extra = 0
    max_num = 1


class WorkMachineInline(admin.StackedInline):
    model = WorkMachine
    extra = 0
    max_num = 1


class AssetDocumentInline(admin.TabularInline):
    model = AssetDocument
    extra = 0
    fields = ("category", "file", "original_name", "notes", "document_date", "sharepoint_url", "uploaded_by", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("asset_tag", "name", "asset_type", "asset_category", "reparto", "status", "updated_at")
    list_filter = ("asset_type", "asset_category", "status", "reparto")
    search_fields = ("asset_tag", "name", "serial_number", "manufacturer", "model", "sharepoint_folder_url", "sharepoint_folder_path")
    inlines = [AssetEndpointInline, AssetITDetailsInline, WorkMachineInline, AssetDocumentInline]


@admin.register(AssetCustomField)
class AssetCustomFieldAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "field_type", "sort_order", "is_active")
    list_filter = ("field_type", "is_active")
    search_fields = ("label", "code")
    ordering = ("sort_order", "label")


@admin.register(AssetListOption)
class AssetListOptionAdmin(admin.ModelAdmin):
    list_display = ("field_key", "value", "sort_order", "is_active")
    list_filter = ("field_key", "is_active")
    search_fields = ("value",)
    ordering = ("field_key", "sort_order", "value")


@admin.register(AssetActionButton)
class AssetActionButtonAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "zone", "action_type", "style", "sort_order", "is_active")
    list_filter = ("zone", "action_type", "style", "is_active")
    search_fields = ("label", "code", "target")
    ordering = ("zone", "sort_order", "label")


@admin.register(AssetDetailField)
class AssetDetailFieldAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "section", "asset_scope", "source_ref", "value_format", "card_size", "sort_order", "is_active")
    list_filter = ("section", "asset_scope", "value_format", "card_size", "is_active")
    search_fields = ("label", "code", "source_ref")
    ordering = ("section", "asset_scope", "sort_order", "label")


@admin.register(AssetDetailSectionLayout)
class AssetDetailSectionLayoutAdmin(admin.ModelAdmin):
    list_display = ("code", "grid_size", "sort_order", "is_visible")
    list_filter = ("grid_size", "is_visible")
    ordering = ("sort_order", "id")


@admin.register(AssetListLayout)
class AssetListLayoutAdmin(admin.ModelAdmin):
    list_display = ("context_key", "sort_order", "is_customized", "updated_at")
    list_filter = ("context_key", "is_customized")
    ordering = ("sort_order", "id")


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "base_asset_type", "sort_order", "is_active")
    list_filter = ("base_asset_type", "is_active")
    search_fields = ("label", "code", "description")
    ordering = ("sort_order", "label")


@admin.register(AssetCategoryField)
class AssetCategoryFieldAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "code",
        "category",
        "field_type",
        "detail_section",
        "detail_value_format",
        "detail_card_size",
        "sort_order",
        "is_active",
    )
    list_filter = ("category", "field_type", "detail_section", "detail_value_format", "detail_card_size", "show_in_form", "show_in_detail", "is_active")
    list_select_related = ("category",)
    search_fields = ("label", "code", "category__label", "help_text")
    ordering = ("category__sort_order", "category__label", "sort_order", "label")


@admin.register(AssetSidebarButton)
class AssetSidebarButtonAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "section", "parent", "is_subitem", "sort_order", "is_visible")
    list_filter = ("section", "is_subitem", "is_visible")
    list_select_related = ("parent",)
    search_fields = ("label", "code", "target_url", "active_match")
    ordering = ("section", "sort_order", "label")


@admin.register(AssetEndpoint)
class AssetEndpointAdmin(admin.ModelAdmin):
    list_display = ("asset", "endpoint_name", "vlan", "ip", "switch_name", "switch_port", "punto")
    search_fields = ("asset__asset_tag", "asset__name", "endpoint_name", "ip", "switch_name")
    list_filter = ("vlan",)


@admin.register(AssetITDetails)
class AssetITDetailsAdmin(admin.ModelAdmin):
    list_display = (
        "asset",
        "os",
        "domain_joined",
        "edr_enabled",
        "ad360_managed",
        "office_2fa_enabled",
        "bios_pwd_set",
    )
    search_fields = ("asset__asset_tag", "asset__name", "os", "cpu")


@admin.register(AssetDocument)
class AssetDocumentAdmin(admin.ModelAdmin):
    list_display = ("asset", "category", "original_name", "document_date", "sharepoint_path", "uploaded_by", "created_at")
    list_filter = ("category", "created_at")
    search_fields = ("asset__asset_tag", "asset__name", "original_name", "notes", "sharepoint_path", "sharepoint_url")


@admin.register(AssetLabelTemplate)
class AssetLabelTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "scope",
        "asset_type",
        "asset",
        "name",
        "show_logo",
        "page_width_mm",
        "page_height_mm",
        "qr_position",
        "updated_at",
    )
    list_filter = ("scope", "asset_type", "show_logo", "qr_position")
    search_fields = ("code", "name", "asset__asset_tag", "asset__name")


@admin.register(PeriodicVerification)
class PeriodicVerificationAdmin(admin.ModelAdmin):
    list_display = ("name", "supplier", "frequency_months", "last_verification_date", "next_verification_date", "is_active")
    list_filter = ("is_active", "supplier")
    search_fields = ("name", "supplier__ragione_sociale", "notes")
    filter_horizontal = ("assets",)


@admin.register(PlantLayout)
class PlantLayoutAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active", "updated_at")
    list_filter = ("category", "is_active")
    search_fields = ("name", "category", "description")


@admin.register(PlantLayoutArea)
class PlantLayoutAreaAdmin(admin.ModelAdmin):
    list_display = ("layout", "name", "reparto_code", "sort_order")
    list_filter = ("layout__category",)
    search_fields = ("layout__name", "name", "reparto_code")


@admin.register(PlantLayoutMarker)
class PlantLayoutMarkerAdmin(admin.ModelAdmin):
    list_display = ("layout", "asset", "label", "sort_order", "is_visible")
    list_filter = ("layout__category", "is_visible")
    search_fields = ("layout__name", "asset__asset_tag", "asset__name", "label")


@admin.register(WorkMachine)
class WorkMachineAdmin(admin.ModelAdmin):
    list_display = (
        "asset",
        "year",
        "tmc",
        "tcr_enabled",
        "cnc_controlled",
        "five_axes",
        "pressure_bar",
    )
    list_filter = ("tcr_enabled", "cnc_controlled", "five_axes", "asset__reparto")
    search_fields = ("asset__asset_tag", "asset__name", "asset__manufacturer", "asset__model", "accuracy_from")


class WorkOrderLogInline(admin.TabularInline):
    model = WorkOrderLog
    extra = 0
    readonly_fields = ("ts", "author")


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "asset", "kind", "status", "opened_at", "closed_at", "downtime_minutes", "cost_eur")
    list_filter = ("kind", "status")
    search_fields = ("asset__asset_tag", "asset__name", "title", "description")
    inlines = [WorkOrderLogInline]


@admin.register(WorkOrderLog)
class WorkOrderLogAdmin(admin.ModelAdmin):
    list_display = ("work_order", "ts", "author")
    search_fields = ("work_order__asset__asset_tag", "work_order__title", "note", "author__username")
