"""Catalogo software (``/assets/software/``): i prodotti dell'inventario e le decisioni dell'azienda.

L'inventario arriva dal SOC (export WatchGuard/BusinessLog). Qui si decide cosa farne:
classificazione (consentito, da rimuovere, non autorizzato), se è a pagamento, la versione
minima accettata. Leggere: chi vede le licenze software (binding ACL, migrazione 0130).
Modificare: amministratori del modulo Asset, come per le licenze.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action

from .models import SoftwareCatalogEntry, SoftwareLicense

FILTERS = [
    ("all", "Tutti"),
    ("da_classificare", "Da classificare"),
    ("non_autorizzato", "Non autorizzati"),
    ("da_rimuovere", "Da rimuovere"),
    ("senza_licenza", "A pagamento senza licenza"),
    ("vecchi", "Sotto la versione minima"),
    ("cve", "Con CVE"),
]


def _can_edit(request: HttpRequest) -> bool:
    from .views import _is_assets_admin

    return _is_assets_admin(request)


def _can_see_cve(request: HttpRequest) -> bool:
    from security.permissions import can_view_security_center

    return can_view_security_center(request.user)


def _run_software_policy() -> int:
    """Il SOC confronta subito l'inventario con la nuova decisione; un errore lì non annulla il salvataggio."""
    import logging

    try:
        from security.services.software_policy import run

        return run()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Controllo software non conforme non eseguito")
        return 0


def _detail_url(key: str) -> str:
    from urllib.parse import urlencode

    return f"{reverse('assets:software_catalog_detail')}?{urlencode({'k': key})}"


def catalog_rows(*, with_cve: bool, today=None) -> list[dict]:
    """Una riga per prodotto presente: PC, versioni, decisioni, licenza collegata, CVE."""
    from security.services import software_catalog as sc

    today = today or timezone.localdate()
    entries = {e.inventory_key: e for e in SoftwareCatalogEntry.objects.all()}
    licenses = list(SoftwareLicense.objects.exclude(inventory_key=""))
    states = sc.license_states_for_keys(licenses, today=today)
    seats = {}
    for lic in licenses:
        valid = lic.is_active and (lic.expiry_date is None or lic.expiry_date >= today)
        if valid and lic.seats_total:
            seats[lic.inventory_key] = seats.get(lic.inventory_key, 0) + lic.seats_total
    versions = sc.versions_by_key()
    cves = sc.cve_by_key() if with_cve else {}
    rows = []
    for item in sc.catalog():
        key = item["key"]
        members = item.get("member_keys") or [key]
        # decisioni e licenze possono essere legate a uno qualsiasi dei nomi del programma: vale la prima trovata
        entry = entries.get(key) or next((entries[m] for m in members if m in entries), None)
        classification = entry.classification if entry else SoftwareCatalogEntry.CLASS_UNREVIEWED
        licensing = entry.licensing if entry else SoftwareCatalogEntry.LICENSING_UNKNOWN
        min_version = entry.min_version if entry else ""
        old, unknown = sc.below_min_version(versions.get(key, {}), min_version)
        member_states = [states[m] for m in members if m in states]
        license_state = "coperta" if "coperta" in member_states else (member_states[0] if member_states else "")
        member_seats = sum(seats.get(m, 0) for m in members) or None
        rows.append({
            "key": key,
            "url": _detail_url(key),
            "name": (entry.display_name if entry and entry.display_name else item["label"]),
            "vendor": (entry.vendor_name if entry and entry.vendor_name else item["vendor_label"]),
            "hosts": item["hosts"],
            "versions": len(versions.get(key, {})),
            "classification": classification,
            "classification_label": dict(SoftwareCatalogEntry.CLASSIFICATION_CHOICES)[classification],
            "licensing": licensing,
            "licensing_label": dict(SoftwareCatalogEntry.LICENSING_CHOICES)[licensing],
            "license_state": license_state,
            "seats": member_seats,
            "over_seats": bool(member_seats and item["hosts"] > member_seats),
            "names": len(members),
            "paid_without_license": licensing == SoftwareCatalogEntry.LICENSING_PAID and license_state != "coperta",
            "min_version": min_version,
            "outdated": old,
            "not_comparable": unknown,
            "cves": cves.get(key, 0),
        })
    return rows


def _filter(rows: list[dict], code: str, q: str) -> list[dict]:
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r["name"].lower() or needle in (r["vendor"] or "").lower()]
    if code in {"da_classificare", "non_autorizzato", "da_rimuovere"}:
        return [r for r in rows if r["classification"] == code]
    if code == "senza_licenza":
        return [r for r in rows if r["paid_without_license"]]
    if code == "vecchi":
        return [r for r in rows if r["outdated"]]
    if code == "cve":
        return [r for r in rows if r["cves"]]
    return rows


@login_required
def software_catalog(request: HttpRequest) -> HttpResponse:
    from security.services.software_catalog import latest_inventory_date

    from .views import _assets_shell_context

    with_cve = _can_see_cve(request)
    all_rows = catalog_rows(with_cve=with_cve)
    code = request.GET.get("f") or "all"
    code = code if code in dict(FILTERS) else "all"
    q = (request.GET.get("q") or "").strip()[:100]
    rows = _filter(all_rows, code, q)
    counts = {c: len(_filter(all_rows, c, "")) for c, _label in FILTERS}
    return render(request, "assets/pages/software_catalog.html", {
        **_assets_shell_context(request, search_placeholder="Cerca software"),
        "page_title": "Catalogo software",
        "rows": rows,
        "filters": [{"code": c, "label": label, "count": counts[c], "active": c == code} for c, label in FILTERS],
        "q": q,
        "filter_code": code,
        "show_cve": with_cve,
        "inventory_date": latest_inventory_date(),
        "can_edit": _can_edit(request),
    })


@login_required
def software_catalog_detail(request: HttpRequest) -> HttpResponse:
    from security.services import software_catalog as sc

    from .views import _assets_shell_context

    key = (request.GET.get("k") or request.POST.get("k") or "").strip()[:300]
    with_cve = _can_see_cve(request)
    row = next((r for r in catalog_rows(with_cve=with_cve) if r["key"] == key), None)
    entry = SoftwareCatalogEntry.objects.filter(inventory_key=key).first()
    if row is None and entry is None:
        raise Http404("Software non presente nell'inventario.")
    can_edit = _can_edit(request)
    if request.method == "POST":
        if not can_edit:
            messages.error(request, "Solo gli amministratori del modulo Asset possono classificare il software.")
            return redirect(_detail_url(key))
        classification = request.POST.get("classification") or SoftwareCatalogEntry.CLASS_UNREVIEWED
        licensing = request.POST.get("licensing") or SoftwareCatalogEntry.LICENSING_UNKNOWN
        if classification not in dict(SoftwareCatalogEntry.CLASSIFICATION_CHOICES) or licensing not in dict(SoftwareCatalogEntry.LICENSING_CHOICES):
            messages.error(request, "Valore non valido.")
            return redirect(_detail_url(key))
        entry = entry or SoftwareCatalogEntry(inventory_key=key)
        before = (entry.classification, entry.licensing, entry.min_version) if entry.pk else None
        entry.classification = classification
        entry.licensing = licensing
        entry.min_version = (request.POST.get("min_version") or "").strip()[:120]
        entry.notes = (request.POST.get("notes") or "").strip()[:4000]
        if row:
            entry.display_name = entry.display_name or row["name"]
            entry.vendor_name = entry.vendor_name or (row["vendor"] or "")
        entry.updated_by = request.user
        entry.save()
        log_action(request, "update_software_catalog", "assets", {
            "inventory_key": key, "before": before,
            "after": (entry.classification, entry.licensing, entry.min_version),
        })
        alerts = _run_software_policy()
        messages.success(request, "Software aggiornato." + (f" Il SOC ha segnalato {alerts} nuov{'o' if alerts == 1 else 'i'} problem{'a' if alerts == 1 else 'i'}." if alerts else ""))
        return redirect(_detail_url(key))
    hosts = sc.product_hosts(key)
    outdated = {i.pk for i in sc.outdated_hosts(key, entry.min_version)} if entry and entry.min_version else set()
    licenses = SoftwareLicense.objects.filter(inventory_key__in=sc.member_keys(key)).order_by("-is_active", "-expiry_date")
    # «Esplosione» per versione: quante PC hanno ciascuna versione e da quali fonti arriva
    per_version = {}
    for inst in hosts:
        riga = per_version.setdefault(inst.version_raw or "", {"version": inst.version_raw or "—", "hosts": set(), "fonti": set(), "outdated": 0})
        riga["hosts"].add(inst.host)
        riga["fonti"].update(inst.fonti_etichette)
        riga["outdated"] += 1 if inst.pk in outdated else 0
    version_rows = [
        {"version": r["version"], "hosts": len(r["hosts"]), "fonti": sorted(r["fonti"]), "outdated": bool(r["outdated"])}
        for r in sorted(per_version.values(), key=lambda r: (-len(r["hosts"]), r["version"]))
    ]
    return render(request, "assets/pages/software_catalog_detail.html", {
        **_assets_shell_context(request, search_placeholder="Cerca software"),
        "page_title": (row or {}).get("name") or key,
        # Calcolato qui: nel template `entry` è None per un software mai classificato e un filtro con
        # argomento `entry.vendor_name` alzava VariableDoesNotExist (500 su ogni software non classificato).
        "vendor_label": (row or {}).get("vendor") or (entry.vendor_name if entry else ""),
        "row": row,
        "entry": entry,
        "key": key,
        "hosts": [{"install": i, "outdated": i.pk in outdated} for i in hosts],
        "version_rows": version_rows,
        "host_count": len({i.host for i in hosts}),
        "licenses": licenses,
        "classification_choices": SoftwareCatalogEntry.CLASSIFICATION_CHOICES,
        "licensing_choices": SoftwareCatalogEntry.LICENSING_CHOICES,
        "can_edit": can_edit,
        "show_cve": with_cve,
        "catalog_url": reverse("assets:software_catalog"),
        "licenses_url": reverse("assets:software_license_list"),
    })
