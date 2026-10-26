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
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.upload_mime import UploadMimeValidationError, safe_filename, validate_extension_and_mime

from .models import (
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityPropostaAi,
    SoftwareAlias,
    SoftwareCpeMapping,
    SoftwareImportPreset,
    SoftwareInstallation,
    SoftwareInventoryImport,
    SoftwareNaRule,
    SoftwareSourceKind,
)
from .permissions import can_view_security_center
from .services import cpe_ai, cve_impact, software_inventory
from .services.configuration import audit_config_change, can_manage_security_config
from .services.cve_feeds import nvd_api_key, set_nvd_api_key

logger = logging.getLogger(__name__)
CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,7}$")
CPE_PAIR_RE = re.compile(r"^[a-z0-9_.\-~%!]+:[a-z0-9_.\-~%!]+$")


def _denied(request):
    from .views import _security_center_denied

    return _security_center_denied(request)


def _config_denied(request):
    messages.error(request, "Serve il permesso di configurazione del SOC.")
    return redirect("security:vulnerabilities")


# --- Lettura ---------------------------------------------------------------------------------

def _con_apparati_snmp(hosts):
    """Gli host che sono apparati di Contatori IT (firmware) si aprono nella loro scheda, non in «PC»."""
    from django.urls import reverse

    try:
        from contatori.models import DispositivoSNMP

        nomi = {str(h["host"]).lower() for h in hosts}
        apparati = {host.lower(): (pk, nome) for pk, host, nome in DispositivoSNMP.objects.filter(
            host__in=nomi).values_list("pk", "host", "nome")}
    except Exception:  # noqa: BLE001 - senza Contatori IT i link restano quelli dei PC
        logger.exception("Apparati SNMP non abbinati agli host esposti")
        return hosts
    for h in hosts:
        apparato = apparati.get(str(h["host"]).lower())
        if apparato:
            h["snmp_url"] = reverse("contatori:snmp_dispositivo", args=[apparato[0]])
            h["snmp_nome"] = apparato[1]
    return hosts


def vulnerabilities_dashboard(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    latest = cve_impact.latest_inventory_date()
    return render(request, "security/vuln_dashboard.html", {
        "cves": cve_impact.impacting_cves(),
        "hosts": _con_apparati_snmp(cve_impact.most_exposed_hosts()),
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
        "software_policy": _software_policy_summary(),
        "ciclo": _ciclo_cve(),
    })


def _ciclo_cve():
    try:
        from .services.cve_chiusura import metriche

        return metriche()
    except Exception:  # noqa: BLE001 - il riquadro è accessorio: la pagina vulnerabilità resta leggibile
        logger.exception("Metriche di chiusura delle CVE non disponibili")
        return None


def _software_policy_summary():
    try:
        from .services.software_policy import summary

        return summary()
    except Exception:  # noqa: BLE001 - il riquadro è accessorio: la pagina vulnerabilità resta leggibile
        logger.exception("Riepilogo software non conforme non disponibile")
        return []


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
    impacts = list(impacts[:500])
    proposte = cpe_ai.proposte_esito_aperte(record)
    for imp in impacts:
        imp.ai = proposte.get(imp.host) if imp.outcome == SecurityCveImpact.TO_VERIFY else None
    return render(request, "security/vuln_cve_detail.html", {
        "record": record, "summary": cve_impact.summary(record), "impacts": impacts, "outcome": outcome,
        "outcomes": SecurityCveImpact.OUTCOME_CHOICES, "can_edit": can_manage_security_config(request.user),
        "proposte_ai": len(proposte),
    })


# --- Proposte dell'AI locale (CPE ed esiti da verificare) -------------------------------------

def _redirect_sicuro(request, default):
    from django.utils.http import url_has_allowed_host_and_scheme

    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect(default)


@require_POST
def proposta_ai_decidi(request, pk):
    """«Accetta» o «Rifiuta» una proposta dell'AI: accettare passa dallo stesso percorso della conferma a mano."""
    from core.audit import log_action

    if not can_view_security_center(request.user):
        return _denied(request)
    if not can_manage_security_config(request.user):
        return _config_denied(request)
    proposta = get_object_or_404(SecurityPropostaAi, pk=pk)
    default = reverse("security:cve_detail", args=[proposta.cve.cve_id]) if proposta.cve_id else reverse("security:software_mapping")
    decisione = request.POST.get("decisione", "")
    if proposta.stato != SecurityPropostaAi.APERTA:
        messages.error(request, "Questa proposta è già stata decisa o è superata.")
        return _redirect_sicuro(request, default)
    if decisione not in {"accetta", "rifiuta"}:
        messages.error(request, "Azione non supportata.")
        return _redirect_sicuro(request, default)
    if decisione == "accetta" and not proposta.applicabile:
        messages.error(request, "L'AI non ha preso posizione («resta da verificare»): non c'è nulla da applicare. Puoi solo rifiutarla.")
        return _redirect_sicuro(request, default)
    dettaglio = {"tipo": proposta.tipo, "proposta": proposta.proposta, "confidenza": proposta.confidenza,
                 "vendor": proposta.vendor, "product": proposta.product, "cve": proposta.cve.cve_id if proposta.cve_id else "",
                 "host": proposta.host, "motivazione": proposta.motivazione[:300]}
    if decisione == "rifiuta":
        cpe_ai.segna_decisa(proposta, request.user, accettata=False)
        log_action(request, "soc_proposta_ai_rifiutata", "security", dettaglio, oggetto=proposta)
        messages.success(request, "Proposta rifiutata: l'AI non la ripropone finché i dati del caso non cambiano.")
        return _redirect_sicuro(request, default)
    if proposta.tipo == SecurityPropostaAi.TIPO_CPE:
        nota = f"proposta AI #{proposta.pk} accettata (confidenza {proposta.confidenza}%)"
        if proposta.proposta == SecurityPropostaAi.NON_APPLICABILE:
            _set_mapping(request, proposta.vendor, proposta.product, note=nota)
            testo = f"«{proposta.product}» segnato non applicabile"
        else:
            _set_mapping(request, proposta.vendor, proposta.product, cpe=proposta.proposta, note=nota)
            testo = f"«{proposta.product}» collegato a {proposta.proposta}"
    else:
        testo = f"{proposta.cve.cve_id} su {proposta.host}: {proposta.proposta_label.lower()}"
    cpe_ai.segna_decisa(proposta, request.user, accettata=True)
    log_action(request, "soc_proposta_ai_accettata", "security", dettaglio, oggetto=proposta)
    _queue_recompute()
    messages.success(request, f"Proposta accettata: {testo}. Impatti in ricalcolo.")
    return _redirect_sicuro(request, default)


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
        # Il firmware arriva dal monitoraggio SNMP, non da un file.
        "source_kinds": [c for c in SoftwareSourceKind.choices if c[0] != SoftwareSourceKind.SNMP_FIRMWARE],
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
    if source_kind not in dict(SoftwareSourceKind.choices) or source_kind == SoftwareSourceKind.SNMP_FIRMWARE:
        source_kind = SoftwareSourceKind.OTHER
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
    date_format = request.POST.get("date_format", "") if request.method == "POST" else (item.preset.date_format if item.preset else "")
    if not software_inventory.validate_mapping(item.headers, item.column_map):
        preview = software_inventory.build_preview(table, item.column_map, date_format)
    return render(request, "security/vuln_inventory_map.html", {
        "item": item, "fields": software_inventory.FIELD_LABELS, "required": SoftwareImportPreset.REQUIRED_FIELDS,
        "headers": item.headers, "errors": errors, "preview": preview,
        "sample_rows": [row[: len(item.headers)] for row in table.rows[:5]],
        "valid_sample": preview.valid[:15] if preview else [], "skipped_sample": preview.skipped[:50] if preview else [],
        "date_format": date_format,
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
    _auto_link_cpe()
    _apply_na_rules()
    _queue_recompute()
    _run_software_policy()
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


def _auto_link_cpe():
    """Collega da solo i software dal nome identico a un CPE delle CVE note; un errore non blocca l'import."""
    try:
        from .services.cpe_auto import auto_link

        return auto_link()
    except Exception:  # noqa: BLE001
        logger.exception("Collegamento automatico CPE non eseguito")
        return 0


def _apply_na_rules():
    """Regole «non applicabile» sui prodotti nuovi: un import non fallisce per questo."""
    try:
        from .services.cpe_rules import apply_rules

        return sum(apply_rules().values())
    except Exception:  # noqa: BLE001
        logger.exception("Regole non applicabile CPE non eseguite")
        return 0


def _run_software_policy():
    """Software non conforme (Catalogo software del modulo Asset): un import non fallisce per questo controllo."""
    try:
        from .services.software_policy import run

        return run()
    except Exception:  # noqa: BLE001
        logger.exception("Controllo software non conforme non eseguito dopo l'import")
        return 0


def _queue_recompute():
    """Ricalcolo degli impatti in coda django-q (fuori dalla request); senza cluster resta al job orario."""
    from .services.cve_feeds import queue_recompute

    return queue_recompute()


# --- Normalizzazione e mappatura CPE ---------------------------------------------------------

def software_mapping(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    if not can_manage_security_config(request.user):
        return _config_denied(request)
    if request.method == "POST":
        return _software_mapping_post(request)
    q = request.GET.get("q", "").strip()
    state = _state(request.GET.get("stato", ""))
    rows, known = _mapping_rows(q)
    counts = {
        "automatici": sum(1 for r in rows if _is_auto(r)),
        "confermati": sum(1 for r in rows if r["mapping"] and r["mapping"].confirmed and not _is_auto(r)),
        "proposte": sum(1 for r in rows if _needs_decision(r)),
        "senza_cve": sum(1 for r in rows if _without_cve(r)),
        "non_applicabili": sum(1 for r in rows if _is_na(r)),
        "ai": sum(1 for r in rows if r["ai"]),
    }
    rows = _filter_rows(rows, state)
    page = Paginator(rows, 50).get_page(request.GET.get("page"))
    from .services import letture, soc_settings

    return render(request, "security/vuln_software.html", {
        "page": page, "q": q, "stato": state, "counts": counts, "known_cpes": len(known),
        "ai_attiva": soc_settings.value("ai.cpe.attivo"), "ai_manca": cpe_ai.configurata(),
        "ai_in_corso": bool(letture.in_corso("cpe_ai")),
        "unique_proposals": sum(1 for r in rows if _needs_decision(r) and len(r["local_suggestions"]) == 1),
        "open_in_view": sum(1 for r in rows if _is_open(r)),
        "aliases": SoftwareAlias.objects.all()[:300], "alias_kinds": SoftwareAlias.KIND_CHOICES,
        "na_rules": SoftwareNaRule.objects.annotate(n=Count("mappings")).order_by("pattern", "vendor"),
        "has_nvd_key": bool(nvd_api_key()),
    })


def _state(raw):
    # «da_mappare» era tutto ciò che non era deciso: oggi il lavoro vero è «Da decidere».
    return "proposte" if raw == "da_mappare" else raw


def _mapping_rows(q=""):
    """Prodotti dell'inventario (vendor+prodotto) con mappatura e proposte locali, i più diffusi prima."""
    from .services.cpe_auto import known_cpe_pairs, proposals

    products = (
        SoftwareInstallation.objects.filter(still_detected=True).values("vendor", "product").order_by()
        .annotate(hosts=Count("host", distinct=True)).order_by("-hosts", "vendor", "product")
    )
    if q:
        products = products.filter(Q(vendor__icontains=q) | Q(product__icontains=q))
    mappings = {(m.vendor, m.product): m for m in SoftwareCpeMapping.objects.select_related("na_rule")}
    known = known_cpe_pairs()
    proposte_ai = cpe_ai.proposte_cpe_aperte()
    rows = list(products)
    for row in rows:
        row["mapping"] = mappings.get((row["vendor"], row["product"]))
        row["local_suggestions"] = proposals(row["vendor"], row["product"], known)
        # Una proposta dell'AI vale solo finché il software è ancora da decidere.
        row["ai"] = proposte_ai.get((row["vendor"], row["product"])) if _is_open(row) or _excluded_by_rule(row) else None
    return rows, known


def _filter_rows(rows, state):
    if state == "ai":
        return [r for r in rows if r["ai"]]
    if state == "proposte":
        return [r for r in rows if _needs_decision(r)]
    if state == "senza_cve":
        return [r for r in rows if _without_cve(r)]
    if state == "automatici":
        return [r for r in rows if _is_auto(r)]
    if state == "non_applicabili":
        return [r for r in rows if _is_na(r)]
    return rows


def _is_open(row):
    """Né confermato né non applicabile: c'è ancora da decidere."""
    mapping = row["mapping"]
    return not mapping or not (mapping.confirmed or mapping.not_applicable)


def _is_auto(row):
    mapping = row["mapping"]
    return bool(mapping and mapping.confirmed and mapping.origin == SoftwareCpeMapping.ORIGIN_AUTO)


def _excluded_by_rule(row):
    mapping = row["mapping"]
    return bool(mapping and mapping.not_applicable and mapping.origin == SoftwareCpeMapping.ORIGIN_RULE)


def _needs_decision(row):
    """Aperto con una CVE dal nome simile, o escluso da una regola ma con una CVE arrivata dopo."""
    return bool(row["local_suggestions"]) and (_is_open(row) or _excluded_by_rule(row))


def _without_cve(row):
    """Aperto, ma nessuna CVE presente nel sistema ha un nome simile: oggi non c'è nulla da decidere."""
    return _is_open(row) and not row["local_suggestions"]


def _is_na(row):
    return bool(row["mapping"] and row["mapping"].not_applicable) and not _needs_decision(row)


def _set_mapping(request, vendor, product, *, cpe=None, note=""):
    """Conferma (``cpe`` = "vendor:product") o segna non applicabile (``cpe`` None), con audit."""
    mapping, _ = SoftwareCpeMapping.objects.get_or_create(vendor=vendor[:120], product=product[:160])
    old = f"{mapping.cpe_vendor}:{mapping.cpe_product} confermata={mapping.confirmed} n/a={mapping.not_applicable}"
    if cpe:
        mapping.cpe_vendor, mapping.cpe_product = cpe.split(":", 1)
        mapping.confirmed, mapping.not_applicable = True, False
    else:
        mapping.confirmed, mapping.not_applicable = False, True
    mapping.origin, mapping.na_rule = SoftwareCpeMapping.ORIGIN_MANUAL, None
    mapping.confirmed_by, mapping.confirmed_at = request.user, timezone.now()
    mapping.save()
    new = f"{mapping.cpe_vendor}:{mapping.cpe_product} confermata" if cpe else "non applicabile"
    audit_config_change(request.user, "update", mapping, field_name="cpe", old_value=old,
                        new_value=f"{new} {note}".strip(), request=request)


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
            if not CPE_PAIR_RE.match(cpe):
                messages.error(request, "CPE nel formato vendor:product (es. 7-zip:7-zip).")
                return redirect(request.get_full_path())
            mapping.cpe_vendor, mapping.cpe_product = cpe.split(":", 1)
            mapping.confirmed, mapping.not_applicable = True, False
            mapping.origin = SoftwareCpeMapping.ORIGIN_MANUAL
        elif action == "cpe_not_applicable":
            mapping.confirmed, mapping.not_applicable = False, True
            mapping.origin = SoftwareCpeMapping.ORIGIN_MANUAL
        else:
            # Annullare un collegamento automatico lo segna come rifiutato: il sistema non lo rifà.
            mapping.origin = (SoftwareCpeMapping.ORIGIN_AUTO_REJECTED if mapping.origin == SoftwareCpeMapping.ORIGIN_AUTO
                              else mapping.origin if mapping.origin == SoftwareCpeMapping.ORIGIN_AUTO_REJECTED else SoftwareCpeMapping.ORIGIN_MANUAL)
            mapping.confirmed, mapping.not_applicable = False, False
        mapping.na_rule = None
        mapping.confirmed_by, mapping.confirmed_at = request.user, timezone.now()
        mapping.save()
        audit_config_change(request.user, "update", mapping, field_name="cpe", old_value=old,
                            new_value=f"{mapping.cpe_vendor}:{mapping.cpe_product} confermata={mapping.confirmed} n/a={mapping.not_applicable}", request=request)
        _queue_recompute()
        messages.success(request, f"Mappatura di «{product}» aggiornata: impatti in ricalcolo.")
    elif action == "ai_proponi":
        from .services import letture

        ok, testo = letture.accoda("cpe_ai", request.user)
        (messages.success if ok else messages.error)(request, testo)
        return redirect(reverse("security:software_mapping") + "?stato=ai")
    elif action == "cpe_auto":
        linked = _auto_link_cpe()
        if linked:
            _queue_recompute()
        messages.success(request, f"Collegamento automatico: {linked} software collegat{'o' if linked == 1 else 'i'}" + (", impatti in ricalcolo." if linked else "."))
    elif action in {"cpe_confirm_bulk", "cpe_na_bulk"}:
        done = 0
        for item in request.POST.getlist("bulk")[:500]:
            vendor, _sep, rest = item.partition("|||")
            product, _sep, cpe = rest.partition("|||")
            cpe = cpe.strip().lower()
            if not product:
                continue
            if action == "cpe_na_bulk":
                _set_mapping(request, vendor, product, note="in blocco")
            elif CPE_PAIR_RE.match(cpe):
                _set_mapping(request, vendor, product, cpe=cpe, note="in blocco")
            else:
                continue  # riga senza proposta: non c'è nulla da confermare
            done += 1
        if done:
            _queue_recompute()
        verb = "Segnati non applicabili" if action == "cpe_na_bulk" else "Confermate"
        messages.success(request, f"{verb} {done} software" + (": impatti in ricalcolo." if done else "."))
    elif action in {"cpe_confirm_unique", "cpe_na_search"}:
        q = request.POST.get("q", "").strip()
        if action == "cpe_na_search" and len(q) < 3:
            messages.error(request, "Per segnare in blocco serve una ricerca di almeno 3 caratteri.")
            return redirect(request.get_full_path())
        rows = _filter_rows(_mapping_rows(q)[0], _state(request.POST.get("stato", "")))
        done = 0
        for row in rows:
            if action == "cpe_confirm_unique":
                if _needs_decision(row) and len(row["local_suggestions"]) == 1:
                    _set_mapping(request, row["vendor"], row["product"], cpe=row["local_suggestions"][0], note="in blocco (candidato unico)")
                    done += 1
            elif _is_open(row):
                _set_mapping(request, row["vendor"], row["product"], note=f"in blocco (ricerca «{q[:60]}»)")
                done += 1
        if done:
            _queue_recompute()
        if action == "cpe_confirm_unique":
            messages.success(request, f"Confermate {done} proposte a candidato unico" + (": impatti in ricalcolo." if done else "."))
        else:
            messages.success(request, f"Segnati non applicabili {done} software che contengono «{q}»" + (": impatti in ricalcolo." if done else "."))
    elif action == "na_rule":
        from .services.cpe_rules import MIN_PATTERN_LEN, apply_rules, normalize_pattern

        pattern = normalize_pattern(request.POST.get("pattern"))[:160]
        vendor = normalize_pattern(request.POST.get("vendor"))[:120]
        if len(pattern) < MIN_PATTERN_LEN:
            messages.error(request, f"La regola vuole un testo di almeno {MIN_PATTERN_LEN} caratteri.")
            return redirect(request.get_full_path())
        rule, created = SoftwareNaRule.objects.get_or_create(
            vendor=vendor, pattern=pattern,
            defaults={"note": request.POST.get("note", "").strip()[:200], "created_by": request.user},
        )
        applied = apply_rules([rule]).get(rule.pk, 0)
        audit_config_change(request.user, "create" if created else "update", rule, field_name="software_esclusi",
                            new_value=applied, request=request)
        if applied:
            _queue_recompute()
        messages.success(request, f"Regola «{rule}» {'salvata' if created else 'riapplicata'}: {applied} software segnati non applicabili "
                                  "(quelli con una CVE dal nome simile restano da decidere).")
    elif action == "na_rule_delete":
        from .services.cpe_rules import release_rule

        rule = SoftwareNaRule.objects.filter(pk=request.POST.get("rule_id") or 0).first()
        if rule:
            reopened = release_rule(rule)
            audit_config_change(request.user, "delete", rule, old_value=str(rule), new_value=f"riaperti {reopened}", request=request)
            rule.delete()
            if reopened:
                _queue_recompute()
            messages.success(request, f"Regola eliminata: {reopened} software tornano da valutare.")
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
        key = request.POST.get("nvd_key", "").strip()[:200]
        if not key:
            messages.error(request, "Incolla la API key NVD (per toglierla usa «Rimuovi»).")
        else:
            set_nvd_api_key(key, actor=request.user)
            messages.success(request, "API key NVD salvata (cifrata).")
    elif action == "nvd_key_remove":
        set_nvd_api_key("", actor=request.user)
        messages.success(request, "API key NVD rimossa.")
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
    n = SoftwareInstallation.objects.filter(Q(**{f"{field}__iexact": alias.raw}) | Q(**{f"{raw_field}__iexact": alias.raw})).update(**{field: alias.canonical})
    # Lo stesso software visto da due fonti con nomi diversi ora coincide: una riga sola.
    software_inventory.unifica_installazioni()
    return n


# --- Pannello laterale delle CVE (inventario software, scheda asset) ----------------------------

def _pannello_negato():
    from django.http import JsonResponse

    return JsonResponse({"error": "Serve l'accesso al Security Center per vedere le CVE."}, status=403)


def _ritorno(request):
    """Link «torna all'elenco» del pannello: solo un altro elenco del pannello, mai un indirizzo esterno."""
    from django.urls import reverse

    back = request.GET.get("da", "")
    base = reverse("security:cve_pannello_programma").rsplit("programma/", 1)[0]
    return back if back.startswith(base) and "//" not in back else ""


def cve_pannello_programma(request):
    """Elenco CVE di un programma dell'inventario (tutti i nomi che lo formano)."""
    if not can_view_security_center(request.user):
        return _pannello_negato()
    from .services import cve_pannello, software_catalog

    key = request.GET.get("k", "")
    if "|" not in key:
        raise Http404
    vendor, product = software_catalog.families().get(software_catalog.split_key(key), software_catalog.split_key(key))
    nome = (SoftwareInstallation.objects.filter(vendor=vendor, product=product).exclude(product_raw="")
            .values_list("product_raw", flat=True).first() or product)
    return render(request, "security/partials/cve_pannello_elenco.html", {
        "titolo": nome, "sottotitolo": "CVE sui PC che hanno oggi il programma",
        "dati": cve_pannello.per_programma(key), "qui": request.get_full_path(),
    })


def cve_pannello_asset(request, asset_id):
    """Elenco CVE di un PC, raggruppate per software installato."""
    if not can_view_security_center(request.user):
        return _pannello_negato()
    from assets.models import Asset

    from .services import cve_pannello

    asset = get_object_or_404(Asset, pk=asset_id)
    dati = cve_pannello.per_asset(asset)
    # ?sw=<chiave>: aperto dalla riga di un software, quel software in cima e solo lui espanso
    sw = request.GET.get("sw", "")
    if sw and any(s["key"] == sw for s in dati["software"]):
        dati["software"].sort(key=lambda s: s["key"] != sw)
    return render(request, "security/partials/cve_pannello_asset.html", {
        "asset": asset, "dati": dati, "sw": sw, "qui": request.get_full_path(),
    })


def cve_pannello_cve(request, cve_id):
    """Scheda breve di una CVE dentro il pannello, con il ritorno all'elenco da cui si arriva."""
    if not can_view_security_center(request.user):
        return _pannello_negato()
    from .services import cve_pannello

    cve_id = cve_id.upper()
    if not CVE_RE.match(cve_id):
        raise Http404
    asset = None
    if request.GET.get("asset", "").isdigit():
        from assets.models import Asset

        asset = Asset.objects.filter(pk=int(request.GET["asset"])).first()
    dati = cve_pannello.dettaglio(cve_id, asset=asset)
    if dati is None:
        raise Http404
    return render(request, "security/partials/cve_pannello_cve.html", {"d": dati, "ritorno": _ritorno(request)})
