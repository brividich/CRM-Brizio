"""Vulnerabilità sugli asset: inventario software, normalizzazione/CPE, impatto CVE.

Lettura (cruscotto, dettaglio CVE): permesso di vista del SOC. Import, alias, mappature
CPE, API key e ricalcoli: permesso di configurazione (rotte sotto ``/soc/admin/config/``).
Nessuna chiamata di rete qui: NVD/KEV/EPSS girano solo nei job django-q.
"""
import logging
import re
from pathlib import Path

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.upload_mime import UploadMimeValidationError, safe_filename, validate_extension_and_mime

from .models import (
    SecurityCveImpact,
    SecurityCveRecord,
    SoftwareAlias,
    SoftwareCpeMapping,
    SoftwareImportPreset,
    SoftwareInstallation,
    SoftwareInventoryImport,
    SoftwareSourceKind,
)
from .permissions import can_view_security_center
from .services import cve_impact, software_inventory
from .services.configuration import audit_config_change, can_manage_security_config
from .services.cve_feeds import nvd_api_key, set_nvd_api_key

logger = logging.getLogger(__name__)
CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,7}$")


def _denied(request):
    from .views import _security_center_denied

    return _security_center_denied(request)


def _config_denied(request):
    messages.error(request, "Serve il permesso di configurazione del SOC.")
    return redirect("security:vulnerabilities")


# --- Lettura ---------------------------------------------------------------------------------

def vulnerabilities_dashboard(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    latest = cve_impact.latest_inventory_date()
    return render(request, "security/vuln_dashboard.html", {
        "cves": cve_impact.impacting_cves(),
        "hosts": cve_impact.most_exposed_hosts(),
        "unmapped": cve_impact.unmapped_software(limit=30),
        "inventory_date": latest,
        "inventory_fresh": bool(latest and latest >= cve_impact.fresh_since()),
        "freshness_days": cve_impact.freshness_days(),
        "totals": {
            "cves": SecurityCveRecord.objects.count(),
            "kev": SecurityCveRecord.objects.filter(kev=True).count(),
            "installations": SoftwareInstallation.objects.filter(still_detected=True).count(),
            "hosts": SoftwareInstallation.objects.filter(still_detected=True).values("host").distinct().count(),
        },
        "can_edit": can_manage_security_config(request.user),
    })


def cve_detail(request, cve_id):
    if not can_view_security_center(request.user):
        return _denied(request)
    cve_id = cve_id.upper()
    if not CVE_RE.match(cve_id):
        raise Http404
    record = get_object_or_404(SecurityCveRecord, cve_id=cve_id)
    impacts = record.impacts.select_related("hub_asset", "installation").order_by("outcome", "host")
    outcome = request.GET.get("esito", "")
    if outcome in dict(SecurityCveImpact.OUTCOME_CHOICES):
        impacts = impacts.filter(outcome=outcome)
    return render(request, "security/vuln_cve_detail.html", {
        "record": record, "summary": cve_impact.summary(record), "impacts": impacts[:500], "outcome": outcome,
        "outcomes": SecurityCveImpact.OUTCOME_CHOICES,
    })


# --- Inventario: upload → mappatura → anteprima → import -------------------------------------

def inventory_page(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    if not can_manage_security_config(request.user):
        return _config_denied(request)
    if request.method == "POST":
        return _inventory_upload(request)
    return render(request, "security/vuln_inventory.html", {
        "imports": SoftwareInventoryImport.objects.select_related("preset", "uploaded_by")[:30],
        "presets": SoftwareImportPreset.objects.all(),
        "source_kinds": SoftwareSourceKind.choices,
        "max_mb": software_inventory.MAX_UPLOAD_BYTES // (1024 * 1024),
    })


def _inventory_upload(request):
    uploaded = request.FILES.get("file")
    if not uploaded:
        messages.error(request, "Scegli un file CSV o XLSX.")
        return redirect("security:inventory")
    try:
        validate_extension_and_mime(
            uploaded, allowed_extensions=software_inventory.ALLOWED_EXTENSIONS, allowed_mimes=software_inventory.ALLOWED_MIMES,
            max_bytes=software_inventory.MAX_UPLOAD_BYTES, label=safe_filename(uploaded.name) or "Inventario", allow_empty=False,
        )
        data = uploaded.read()
        table = software_inventory.read_table(data, uploaded.name)
    except (UploadMimeValidationError, software_inventory.InventoryFileError) as exc:
        messages.error(request, str(exc))
        return redirect("security:inventory")
    source_kind = request.POST.get("source_kind", SoftwareSourceKind.OTHER)
    source_kind = source_kind if source_kind in dict(SoftwareSourceKind.choices) else SoftwareSourceKind.OTHER
    preset = SoftwareImportPreset.objects.filter(pk=request.POST.get("preset") or 0).first()
    sha = software_inventory.file_sha256(data)
    column_map = preset.column_map if preset else software_inventory.suggest_mapping(table.headers)
    item = SoftwareInventoryImport.objects.create(
        source_kind=preset.source_kind if preset else source_kind, preset=preset, original_name=safe_filename(uploaded.name)[:255],
        file_sha256=sha, headers=table.headers, column_map={k: v for k, v in column_map.items() if v in table.headers},
        uploaded_by=request.user, rows_total=len(table.rows),
    )
    item.stored_name = software_inventory.store_upload(data, sha, Path(uploaded.name).suffix.lower())
    item.save(update_fields=["stored_name"])
    previous = SoftwareInventoryImport.objects.filter(file_sha256=sha, status=SoftwareInventoryImport.STATUS_IMPORTED).exclude(pk=item.pk).first()
    if previous:
        messages.info(request, f"Questo file è già stato importato il {timezone.localtime(previous.imported_at):%d/%m/%Y %H:%M}: "
                               "reimportarlo non crea duplicati, aggiorna solo «ultimo rilevamento».")
    if table.truncated:
        messages.warning(request, f"Il file supera {software_inventory.MAX_ROWS} righe: verranno lette solo le prime.")
    return redirect("security:inventory_map", pk=item.pk)


def _load_import(pk):
    item = get_object_or_404(SoftwareInventoryImport, pk=pk)
    if item.status != SoftwareInventoryImport.STATUS_PREVIEW:
        raise Http404
    return item


def inventory_map(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    if not can_manage_security_config(request.user):
        return _config_denied(request)
    item = _load_import(pk)
    errors = []
    if request.method == "POST":
        column_map = {name: request.POST.get(f"col_{name}", "") for name in software_inventory.FIELD_LABELS}
        column_map = {k: v for k, v in column_map.items() if v}
        errors = software_inventory.validate_mapping(item.headers, column_map)
        date_format = request.POST.get("date_format", "").strip()[:40]
        if not errors:
            item.column_map = column_map
            item.save(update_fields=["column_map"])
            if request.POST.get("preset_name", "").strip():
                _save_preset(request, item, column_map, date_format)
            if request.POST.get("do") == "import":
                return _inventory_run(request, item, date_format)
    try:
        table = software_inventory.read_table(software_inventory.load_stored(item), item.original_name)
    except software_inventory.InventoryFileError as exc:
        messages.error(request, str(exc))
        return redirect("security:inventory")
    preview = None
    if not software_inventory.validate_mapping(item.headers, item.column_map):
        preview = software_inventory.build_preview(table, item.column_map, request.POST.get("date_format", "") if request.method == "POST" else "")
    return render(request, "security/vuln_inventory_map.html", {
        "item": item, "fields": software_inventory.FIELD_LABELS, "required": SoftwareImportPreset.REQUIRED_FIELDS,
        "headers": item.headers, "errors": errors, "preview": preview,
        "sample_rows": [row[: len(item.headers)] for row in table.rows[:5]],
        "valid_sample": preview.valid[:15] if preview else [], "skipped_sample": preview.skipped[:50] if preview else [],
        "date_format": request.POST.get("date_format", "") if request.method == "POST" else "",
    })


def _save_preset(request, item, column_map, date_format):
    name = request.POST["preset_name"].strip()[:120]
    preset, created = SoftwareImportPreset.objects.update_or_create(
        name=name, defaults={"source_kind": item.source_kind, "column_map": column_map, "date_format": date_format, "created_by": request.user},
    )
    audit_config_change(request.user, "create" if created else "update", preset, field_name="column_map", new_value=column_map, request=request)
    item.preset = preset
    item.save(update_fields=["preset"])
    messages.success(request, f"Mappatura salvata come preset «{preset.name}».")


def _inventory_run(request, item, date_format):
    try:
        table = software_inventory.read_table(software_inventory.load_stored(item), item.original_name)
    except software_inventory.InventoryFileError as exc:
        messages.error(request, str(exc))
        return redirect("security:inventory")
    preview = software_inventory.build_preview(table, item.column_map, date_format)
    inventory_date = request.POST.get("inventory_date", "")
    try:
        item.inventory_date = timezone.datetime.fromisoformat(inventory_date).date() if inventory_date else timezone.localdate()
    except ValueError:
        item.inventory_date = timezone.localdate()
    software_inventory.run_import(item, preview)
    software_inventory.discard_stored(item)
    audit_config_change(request.user, "import", item, field_name="rows_imported", new_value=item.rows_imported, request=request)
    _queue_recompute()
    messages.success(request, f"Importate {item.rows_imported} righe ({item.rows_new} nuove) da {item.hosts_count} host; "
                              f"{item.rows_skipped} scartate; {item.rows_marked_missing} installazioni non più rilevate.")
    return redirect("security:inventory")


@require_POST
def inventory_discard(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    if not can_manage_security_config(request.user):
        return _config_denied(request)
    item = _load_import(pk)
    software_inventory.discard_stored(item)
    item.status = SoftwareInventoryImport.STATUS_FAILED
    item.save(update_fields=["status"])
    messages.info(request, "Import annullato: il file caricato è stato eliminato.")
    return redirect("security:inventory")


def _queue_recompute():
    """Ricalcolo degli impatti in coda django-q (fuori dalla request); senza cluster resta al job orario."""
    try:
        from django_q.tasks import async_task

        async_task("security.services.cve_impact.recompute_all", timeout=110)
    except Exception:  # noqa: BLE001 - la coda non disponibile non deve far fallire l'import
        logger.exception("Ricalcolo impatti CVE non accodato")


# --- Normalizzazione e mappatura CPE ---------------------------------------------------------

def software_mapping(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    if not can_manage_security_config(request.user):
        return _config_denied(request)
    if request.method == "POST":
        return _software_mapping_post(request)
    q = request.GET.get("q", "").strip()
    products = (
        SoftwareInstallation.objects.filter(still_detected=True).values("vendor", "product").order_by()
        .annotate(hosts=Count("host", distinct=True)).order_by("-hosts", "vendor", "product")
    )
    if q:
        products = products.filter(Q(vendor__icontains=q) | Q(product__icontains=q))
    page = Paginator(list(products), 50).get_page(request.GET.get("page"))
    mappings = {(m.vendor, m.product): m for m in SoftwareCpeMapping.objects.all()}
    known = _local_cpe_pairs()
    for row in page.object_list:
        row["mapping"] = mappings.get((row["vendor"], row["product"]))
        row["local_suggestions"] = _local_suggestions(row["product"], known)
    return render(request, "security/vuln_software.html", {
        "page": page, "q": q, "aliases": SoftwareAlias.objects.all()[:300], "alias_kinds": SoftwareAlias.KIND_CHOICES,
        "has_nvd_key": bool(nvd_api_key()),
    })


def _local_cpe_pairs():
    pairs = set()
    for configurations in SecurityCveRecord.objects.exclude(configurations=[]).values_list("configurations", flat=True)[:2000]:
        for c in configurations or []:
            if c.get("vendor") and c.get("product"):
                pairs.add((c["vendor"], c["product"]))
    return pairs


def _local_suggestions(product, known):
    key = re.sub(r"[^a-z0-9]+", "", product.lower())
    if not key:
        return []
    out = [f"{v}:{p}" for v, p in known if key in re.sub(r"[^a-z0-9]+", "", p.lower()) or re.sub(r"[^a-z0-9]+", "", p.lower()) in key]
    return sorted(out)[:5]


def _software_mapping_post(request):
    action = request.POST.get("action", "")
    if action == "alias":
        kind = request.POST.get("kind", "")
        raw = request.POST.get("raw", "").strip().lower()[:160]
        canonical = request.POST.get("canonical", "").strip().lower()[:160]
        if kind not in dict(SoftwareAlias.KIND_CHOICES) or not raw or not canonical:
            messages.error(request, "Alias: servono tipo, valore originale e valore normalizzato.")
        else:
            alias, created = SoftwareAlias.objects.update_or_create(kind=kind, raw=raw, defaults={"canonical": canonical})
            audit_config_change(request.user, "create" if created else "update", alias, field_name="canonical", new_value=canonical, request=request)
            updated = _apply_alias(alias)
            _queue_recompute()
            messages.success(request, f"Alias salvato: {raw} → {canonical} ({updated} installazioni aggiornate).")
    elif action == "alias_delete":
        alias = SoftwareAlias.objects.filter(pk=request.POST.get("alias_id") or 0).first()
        if alias:
            audit_config_change(request.user, "delete", alias, old_value=f"{alias.raw} → {alias.canonical}", request=request)
            alias.delete()
            messages.success(request, "Alias eliminato (vale dai prossimi import).")
    elif action in {"cpe_confirm", "cpe_not_applicable", "cpe_reset"}:
        vendor = request.POST.get("vendor", "")[:120]
        product = request.POST.get("product", "")[:160]
        if not product:
            messages.error(request, "Prodotto mancante.")
            return redirect(request.get_full_path())
        mapping, _ = SoftwareCpeMapping.objects.get_or_create(vendor=vendor, product=product)
        old = f"{mapping.cpe_vendor}:{mapping.cpe_product} confermata={mapping.confirmed}"
        if action == "cpe_confirm":
            cpe = request.POST.get("cpe", "").strip().lower()
            if not re.match(r"^[a-z0-9_.\-~%!]+:[a-z0-9_.\-~%!]+$", cpe):
                messages.error(request, "CPE nel formato vendor:product (es. 7-zip:7-zip).")
                return redirect(request.get_full_path())
            mapping.cpe_vendor, mapping.cpe_product = cpe.split(":", 1)
            mapping.confirmed, mapping.not_applicable = True, False
        elif action == "cpe_not_applicable":
            mapping.confirmed, mapping.not_applicable = False, True
        else:
            mapping.confirmed, mapping.not_applicable = False, False
        mapping.confirmed_by, mapping.confirmed_at = request.user, timezone.now()
        mapping.save()
        audit_config_change(request.user, "update", mapping, field_name="cpe", old_value=old,
                            new_value=f"{mapping.cpe_vendor}:{mapping.cpe_product} confermata={mapping.confirmed} n/a={mapping.not_applicable}", request=request)
        _queue_recompute()
        messages.success(request, f"Mappatura di «{product}» aggiornata: impatti in ricalcolo.")
    elif action == "cpe_suggest":
        vendor = request.POST.get("vendor", "")[:120]
        product = request.POST.get("product", "")[:160]
        try:
            from django_q.tasks import async_task

            async_task("security.tasks.suggest_cpe_task", vendor, product, timeout=110)
            messages.info(request, "Ricerca nel dizionario CPE NVD accodata: i suggerimenti compaiono qui fra poco.")
        except Exception:  # noqa: BLE001
            logger.exception("Ricerca CPE non accodata")
            messages.error(request, "Coda dei job non disponibile: riprova più tardi.")
    elif action == "nvd_key":
        set_nvd_api_key(request.POST.get("nvd_key", "").strip()[:200], actor=request.user)
        messages.success(request, "API key NVD salvata (cifrata)." if request.POST.get("nvd_key", "").strip() else "API key NVD rimossa.")
    elif action == "recompute":
        _queue_recompute()
        messages.info(request, "Ricalcolo degli impatti accodato.")
    else:
        messages.error(request, "Azione non supportata.")
    return redirect(request.get_full_path())


def _apply_alias(alias):
    """Applica subito l'alias alle installazioni esistenti (vendor o prodotto normalizzati)."""
    field = "vendor" if alias.kind == SoftwareAlias.KIND_VENDOR else "product"
    raw_field = "vendor_raw" if alias.kind == SoftwareAlias.KIND_VENDOR else "product_raw"
    return SoftwareInstallation.objects.filter(Q(**{f"{field}__iexact": alias.raw}) | Q(**{f"{raw_field}__iexact": alias.raw})).update(**{field: alias.canonical})
