"""Catalogo software (``/assets/software/``): i prodotti dell'inventario e le decisioni dell'azienda.

L'inventario arriva dal SOC (export WatchGuard/BusinessLog). Qui si decide cosa farne:
classificazione (consentito, da rimuovere, non autorizzato), se è a pagamento, la versione
minima accettata. Leggere: chi vede le licenze software (binding ACL, migrazione 0130).
Modificare: amministratori del modulo Asset, come per le licenze.
"""
from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action

from .models import Asset, SoftwareCatalogEntry, SoftwareLicense, SoftwareProduttoreConsentito

FILTERS = [
    ("all", "Tutti"),
    ("da_classificare", "Da classificare"),
    ("nuovi", "Nuovi"),
    ("non_autorizzato", "Non autorizzati"),
    ("da_rimuovere", "Da rimuovere"),
    ("senza_licenza", "A pagamento senza licenza"),
    ("vecchi", "Sotto la versione minima"),
    ("cve", "Con CVE"),
    ("non_controllato", "CVE non controllate"),
]


def _can_edit(request: HttpRequest) -> bool:
    from .views import _is_assets_admin

    return _is_assets_admin(request)


def _can_see_cve(request: HttpRequest) -> bool:
    from security.permissions import can_view_security_center

    return can_view_security_center(request.user)


def _can_configure_soc(request: HttpRequest) -> bool:
    from security.services.configuration import can_configure_soc

    return can_configure_soc(request)


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


def _produttore_regola(etichetta: str) -> str:
    """La parola che identifica il produttore: «Microsoft Corporation» → «microsoft»."""
    from security.services.software_inventory import _token

    parole = _token(etichetta)
    return parole[0][:120] if parole else ""


def catalog_rows(*, with_cve: bool, today=None) -> list[dict]:
    """Una riga per prodotto presente: PC, versioni, decisioni, licenza collegata, CVE."""
    from security.services import software_catalog as sc, software_nuovo
    from security.services.software_inventory import nome_programma

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
    indice = sc.indice_famiglie()
    stati_cve = sc.stati_cve(indice) if with_cve else {}
    consentiti = set(SoftwareProduttoreConsentito.objects.values_list("produttore", flat=True))
    entry_keys = sc.chiavi_per_programma(entries, indice)
    license_keys = sc.chiavi_per_programma({*states, *seats}, indice)
    comparse = software_nuovo.prime_comparse(indice)
    soglia_nuovo = timezone.now() - timedelta(days=software_nuovo.giorni())
    rows = []
    for item in sc.catalog():
        key = item["key"]
        # decisioni e licenze possono essere legate a un altro nome del programma, anche uno sparito
        # dall'inventario dopo un aggiornamento: vale quella sul nome canonico, poi la prima trovata
        entry = entries.get(key) or next((entries[m] for m in entry_keys.get(key, [])), None)
        members = sorted({*(item.get("member_keys") or [key]), *license_keys.get(key, [])})
        classification = entry.classification if entry else SoftwareCatalogEntry.CLASS_UNREVIEWED
        produttore = _produttore_regola(item["vendor_label"])
        # La regola decide solo ciò che nessuno ha deciso: la scelta sul singolo programma vince sempre.
        da_regola = classification == SoftwareCatalogEntry.CLASS_UNREVIEWED and produttore in consentiti
        if da_regola:
            classification = SoftwareCatalogEntry.CLASS_ALLOWED
        licensing = entry.licensing if entry else SoftwareCatalogEntry.LICENSING_UNKNOWN
        min_version = entry.min_version if entry else ""
        old, unknown = sc.below_min_version(versions.get(key, {}), min_version)
        member_states = [states[m] for m in members if m in states]
        license_state = "coperta" if "coperta" in member_states else (member_states[0] if member_states else "")
        member_seats = sum(seats.get(m, 0) for m in members) or None
        comparso = comparse.get(key)
        rows.append({
            "key": key,
            "nuovo_dal": comparso if comparso and comparso >= soglia_nuovo and classification == SoftwareCatalogEntry.CLASS_UNREVIEWED else None,
            "url": _detail_url(key),
            "name": nome_programma(entry.display_name) if entry and entry.display_name and not item.get("separato") else item["label"],
            "vendor": (entry.vendor_name if entry and entry.vendor_name else item["vendor_label"]),
            "hosts": item["hosts"],
            "versions": len(versions.get(key, {})),
            "classification": classification,
            "da_regola": da_regola,
            "produttore": produttore,
            "classification_label": dict(SoftwareCatalogEntry.CLASSIFICATION_CHOICES)[classification],
            "licensing": licensing,
            "licensing_label": dict(SoftwareCatalogEntry.LICENSING_CHOICES)[licensing],
            "license_state": license_state,
            "seats": member_seats,
            "over_seats": bool(member_seats and item["hosts"] > member_seats),
            "names": len(item.get("member_keys") or [key]),
            "cerca": item.get("cerca", ""),
            "paid_without_license": licensing == SoftwareCatalogEntry.LICENSING_PAID and license_state != "coperta",
            "min_version": min_version,
            "outdated": old,
            "not_comparable": unknown,
            "cves": cves.get(key, 0),
            "cve_stato": stati_cve.get(key, sc.NON_CONTROLLATO) if with_cve else "",
        })
    return rows


def _compatto(testo: str) -> str:
    return re.sub(r"[\W_]+", "", testo.casefold())


def _filter(rows: list[dict], code: str, q: str) -> list[dict]:
    if q:
        # Ogni parola, senza badare a spazi e trattini: «7zip» trova «7-Zip», «acro writer» trova «CutePDF Writer» di
        # «Acro Software»; si cerca anche nei nomi originali raggruppati («26.05», «x64»).
        parole = [_compatto(p) for p in q.split() if _compatto(p)]
        rows = [r for r in rows if all(p in _compatto(f"{r['name']} {r['vendor'] or ''} {r.get('cerca', '')}") for p in parole)]
    if code in {"da_classificare", "non_autorizzato", "da_rimuovere"}:
        return [r for r in rows if r["classification"] == code]
    if code == "nuovi":
        return [r for r in rows if r["nuovo_dal"]]
    if code == "senza_licenza":
        return [r for r in rows if r["paid_without_license"]]
    if code == "vecchi":
        return [r for r in rows if r["outdated"]]
    if code == "cve":
        return [r for r in rows if r["cves"]]
    if code == "non_controllato":
        return [r for r in rows if r.get("cve_stato") == "non_controllato"]
    return rows


def _classifica_in_blocco(request: HttpRequest) -> HttpResponse:
    """La stessa decisione su più programmi: una voce di registro con tutte le chiavi, il SOC ricontrolla una volta."""
    from security.services import software_catalog as sc

    classification = request.POST.get("classification") or ""
    licensing = request.POST.get("licensing") or ""
    chiavi = {k.strip()[:300] for k in request.POST.getlist("k")[:1000] if k.strip()}
    if classification not in dict(SoftwareCatalogEntry.CLASSIFICATION_CHOICES) or (licensing and licensing not in dict(SoftwareCatalogEntry.LICENSING_CHOICES)):
        messages.error(request, "Scegli una classificazione valida.")
        return redirect(request.get_full_path())
    righe = {r["key"]: r for r in catalog_rows(with_cve=False)}
    chiavi &= set(righe)
    if not chiavi:
        messages.error(request, "Seleziona almeno un programma.")
        return redirect(request.get_full_path())
    entries = {e.inventory_key: e for e in SoftwareCatalogEntry.objects.all()}
    per_programma = sc.chiavi_per_programma(entries)
    with transaction.atomic():
        for key in sorted(chiavi):
            riga = righe[key]
            entry = entries.get(key) or next((entries[m] for m in per_programma.get(key, [])), None) or SoftwareCatalogEntry(inventory_key=key)
            entry.classification = classification
            if licensing:
                entry.licensing = licensing
            entry.display_name = entry.display_name or riga["name"]
            entry.vendor_name = entry.vendor_name or (riga["vendor"] or "")
            entry.updated_by = request.user
            entry.save()
    log_action(request, "update_software_catalog_blocco", "assets", {"chiavi": sorted(chiavi), "classification": classification, "licensing": licensing})
    alerts = _run_software_policy()
    messages.success(request, f"{len(chiavi)} programmi classificati come «{dict(SoftwareCatalogEntry.CLASSIFICATION_CHOICES)[classification]}»."
                     + (f" Il SOC ha segnalato {alerts} nuov{'o' if alerts == 1 else 'i'} problem{'a' if alerts == 1 else 'i'}." if alerts else ""))
    return redirect(request.get_full_path())


def _regola_produttore(request: HttpRequest, azione: str) -> HttpResponse:
    if azione == "consenti_produttore":
        produttore = _produttore_regola(request.POST.get("produttore") or "")
        if not produttore:
            messages.error(request, "Scegli un produttore.")
            return redirect(request.get_full_path())
        etichetta = (request.POST.get("produttore") or "").strip()[:255]
        _regola, creata = SoftwareProduttoreConsentito.objects.get_or_create(produttore=produttore, defaults={"etichetta": etichetta, "creato_da": request.user})
        if creata:
            log_action(request, "software_catalog_produttore_consentito", "assets", {"produttore": produttore})
        messages.success(request, f"«{etichetta}»: i programmi ancora da classificare ora risultano consentiti, anche i nuovi.")
    else:
        valore = (request.POST.get("regola") or "").strip()
        regola = SoftwareProduttoreConsentito.objects.filter(pk=valore if valore.isdigit() else 0).first()
        if regola is not None:
            log_action(request, "software_catalog_produttore_rimosso", "assets", {"produttore": regola.produttore})
            regola.delete()
            messages.success(request, "Regola tolta: i suoi programmi tornano da classificare.")
    return redirect(request.get_full_path())


def _produttori_da_proporre(rows: list[dict]) -> list[dict]:
    """I produttori del catalogo con i programmi ancora da classificare, dai più numerosi."""
    gruppi = {}
    for riga in rows:
        if riga["produttore"] and riga["classification"] == SoftwareCatalogEntry.CLASS_UNREVIEWED:
            gruppo = gruppi.setdefault(riga["produttore"], {"etichette": {}, "n": 0})
            gruppo["n"] += 1
            gruppo["etichette"][riga["vendor"]] = gruppo["etichette"].get(riga["vendor"], 0) + 1
    out = [{"etichetta": max(g["etichette"], key=g["etichette"].get), "n": g["n"]} for g in gruppi.values()]
    return sorted(out, key=lambda g: (-g["n"], g["etichetta"].casefold()))


@login_required
def software_catalog(request: HttpRequest) -> HttpResponse:
    from security.services.software_catalog import latest_inventory_date

    from .views import _assets_shell_context

    if request.method == "POST":
        if not _can_edit(request):
            messages.error(request, "Solo gli amministratori del modulo Asset possono classificare il software.")
            return redirect(request.get_full_path())
        azione = request.POST.get("azione")
        if azione == "classifica":
            return _classifica_in_blocco(request)
        if azione in {"consenti_produttore", "togli_produttore"}:
            return _regola_produttore(request, azione)
        if azione in {"dotazione_aggiungi", "dotazione_togli"}:
            return _regola_dotazione(request, azione)
        messages.error(request, "Azione non valida.")
        return redirect(request.get_full_path())
    with_cve = _can_see_cve(request)
    all_rows = catalog_rows(with_cve=with_cve)
    # Lo stato delle CVE lo vede solo chi vede il SOC, come la colonna.
    filtri = [f for f in FILTERS if with_cve or f[0] != "non_controllato"]
    code = request.GET.get("f") or "all"
    code = code if code in dict(filtri) else "all"
    q = (request.GET.get("q") or "").strip()[:100]
    rows = _filter(all_rows, code, q)
    counts = {c: len(_filter(all_rows, c, "")) for c, _label in filtri}
    return render(request, "assets/pages/software_catalog.html", {
        **_assets_shell_context(request, search_placeholder="Cerca software"),
        "page_title": "Catalogo software",
        "rows": rows,
        "filters": [{"code": c, "label": label, "count": counts[c], "active": c == code} for c, label in filtri],
        "q": q,
        "filter_code": code,
        "show_cve": with_cve,
        "cve_panel_url": reverse("security:cve_pannello_programma") if with_cve else "",
        "inventory_date": latest_inventory_date(),
        "can_edit": _can_edit(request),
        "avanzamento": _avanzamento(all_rows),
        "classification_choices": SoftwareCatalogEntry.CLASSIFICATION_CHOICES,
        "licensing_choices": SoftwareCatalogEntry.LICENSING_CHOICES,
        "produttori_regola": SoftwareProduttoreConsentito.objects.all(),
        "produttori_proposti": _produttori_da_proporre(all_rows),
        **_dotazione_contesto(all_rows),
    })


def _dotazione_contesto(rows: list[dict]) -> dict:
    """Regole della dotazione attesa con i PC dove manca il programma, e le scelte per aggiungerne una."""
    from .models import SoftwareDotazioneAttesa
    from .services.software_dotazione import scostamenti

    try:
        regole = scostamenti()
    except Exception:  # noqa: BLE001 - la scheda è un di più del catalogo
        import logging

        logging.getLogger(__name__).exception("Dotazione attesa non calcolata")
        regole = []
    reparti = sorted({r for r in Asset.objects.filter(asset_type__in=SoftwareDotazioneAttesa.TIPI_PER_AMBITO["tutti"])
                      .exclude(reparto="").values_list("reparto", flat=True).distinct()}, key=str.casefold)
    return {
        "dotazione": regole,
        "dotazione_mancanti": sum(len(r["mancanti"]) for r in regole),
        "dotazione_scelte": [(r["key"], f"{r['name']} · {r['vendor'] or 'produttore n/d'} ({r['hosts']} PC)") for r in rows],
        "dotazione_ambiti": SoftwareDotazioneAttesa.AMBITO_CHOICES,
        "dotazione_reparti": reparti,
    }


def _regola_dotazione(request: HttpRequest, azione: str) -> HttpResponse:
    from .models import SoftwareDotazioneAttesa

    if azione == "dotazione_togli":
        regola = SoftwareDotazioneAttesa.objects.filter(pk=request.POST.get("regola")).first()
        if regola:
            log_action(request, "software_dotazione_togli", "assets", {"programma": regola.programma, "ambito": regola.ambito, "reparto": regola.reparto})
            regola.delete()
            messages.success(request, f"Regola tolta: {regola}.")
        return redirect(f"{request.path}#dotazione")
    key = (request.POST.get("programma") or "").strip()[:300]
    ambito = request.POST.get("ambito") or SoftwareDotazioneAttesa.AMBITO_PC
    reparto = (request.POST.get("reparto") or "").strip()[:120]
    nota = (request.POST.get("nota") or "").strip()[:255]
    etichetta = next((r["name"] for r in catalog_rows(with_cve=False) if r["key"] == key), "")
    if not key or not etichetta or ambito not in dict(SoftwareDotazioneAttesa.AMBITO_CHOICES):
        messages.error(request, "Scegli un programma del catalogo e un ambito.")
        return redirect(f"{request.path}#dotazione")
    regola, creata = SoftwareDotazioneAttesa.objects.get_or_create(
        programma=key, ambito=ambito, reparto=reparto, defaults={"etichetta": etichetta, "nota": nota, "creato_da": request.user})
    if creata:
        log_action(request, "software_dotazione_aggiungi", "assets", {"programma": key, "ambito": ambito, "reparto": reparto})
        messages.success(request, f"Dotazione attesa: {regola}.")
    else:
        messages.info(request, "Questa regola c'era già.")
    return redirect(f"{request.path}#dotazione")


def _avanzamento(rows: list[dict]) -> dict:
    """Quanto è deciso: per programmi e pesato sui PC (un programma su 80 PC conta più di uno su 1)."""
    decisi = [r for r in rows if r["classification"] != SoftwareCatalogEntry.CLASS_UNREVIEWED]
    tot, tot_pc = len(rows), sum(r["hosts"] for r in rows)
    pc = sum(r["hosts"] for r in decisi)
    return {"decisi": len(decisi), "programmi": tot, "percento_pc": round(100 * pc / tot_pc) if tot_pc else 0}


def _azione_raggruppamento(request: HttpRequest, key: str) -> HttpResponse:
    """Correzioni a mano del raggruppamento: separa un nome, unisci a un altro programma, annulla."""
    from security.models import SoftwareProgrammaRegola
    from security.services import software_catalog as sc

    azione = request.POST.get("azione")
    destinazione = key
    if azione == "separa":
        membro = (request.POST.get("membro") or "").strip()[:300]
        if membro not in sc.member_keys(key):
            messages.error(request, "Questo nome non fa parte del programma.")
            return redirect(_detail_url(key))
        resto = sc.separa_dal_programma(membro, request.user)
        if resto is None:
            messages.error(request, "Il programma ha un solo nome: non c'è niente da separare.")
            return redirect(_detail_url(key))
        log_action(request, "software_catalog_separa", "assets", {"membro": membro, "programma": key})
        messages.success(request, "Nome separato: ora è un programma a sé, da classificare. Decisione e licenze restano al gruppo.")
        destinazione = resto if membro == key else key
    elif azione == "unisci":
        altra = (request.POST.get("altro") or "").strip()[:300]
        if altra not in {r["key"] for r in catalog_rows(with_cve=False)} or altra == key:
            messages.error(request, "Scegli un altro programma del catalogo.")
            return redirect(_detail_url(key))
        eliminata = sc.unisci_programmi(key, altra, request.user)
        log_action(request, "software_catalog_unisci", "assets", {"programma": key, "altro": altra, "decisione_eliminata": eliminata})
        messages.success(request, "Programmi uniti." + (" Avevano entrambi una decisione: vale quella di questa pagina, controllala." if eliminata else ""))
    elif azione == "annulla_regola":
        valore = (request.POST.get("regola") or "").strip()
        regola = SoftwareProgrammaRegola.objects.filter(pk=valore if valore.isdigit() else 0).first()
        if regola is None:
            messages.error(request, "Correzione non trovata.")
            return redirect(_detail_url(key))
        log_action(request, "software_catalog_annulla_regola", "assets", {"tipo": regola.tipo, "chiave": regola.chiave, "chiave_altra": regola.chiave_altra})
        chiave = regola.chiave
        regola.delete()
        messages.success(request, "Correzione annullata: vale di nuovo il raggruppamento automatico.")
        destinazione = chiave
    else:
        messages.error(request, "Azione non valida.")
        return redirect(_detail_url(key))
    # Le decisioni ora coprono PC diversi: il SOC ricontrolla subito.
    _run_software_policy()
    return redirect(_detail_url(destinazione))


@login_required
def software_catalog_detail(request: HttpRequest) -> HttpResponse:
    from security.services import software_catalog as sc

    from .views import _assets_shell_context

    richiesta = (request.GET.get("k") or request.POST.get("k") or "").strip()[:300]
    # Un link a un altro nome o a una release vecchia porta al programma; la decisione è una sola per programma.
    indice = sc.indice_famiglie()
    key = sc.chiave_canonica(richiesta, indice)
    with_cve = _can_see_cve(request)
    row = next((r for r in catalog_rows(with_cve=with_cve) if r["key"] == key), None)
    entries = {e.inventory_key: e for e in SoftwareCatalogEntry.objects.all()}
    entry = entries.get(key) or next((entries[m] for m in sc.chiavi_per_programma(entries, indice).get(key, [])), None)
    if row is None and entry is None:
        raise Http404("Software non presente nell'inventario.")
    can_edit = _can_edit(request)
    if request.method == "POST":
        if not can_edit:
            messages.error(request, "Solo gli amministratori del modulo Asset possono classificare il software.")
            return redirect(_detail_url(key))
        if request.POST.get("azione"):
            return _azione_raggruppamento(request, key)
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
    chiavi_licenze = SoftwareLicense.objects.exclude(inventory_key="").values_list("inventory_key", flat=True)
    licenses = SoftwareLicense.objects.filter(
        inventory_key__in=[*sc.member_keys(key), *sc.chiavi_per_programma(chiavi_licenze, indice).get(key, [])]
    ).order_by("-is_active", "-expiry_date")
    # «Esplosione» per versione: quante PC hanno ciascuna versione e da quali fonti arriva
    per_version = {}
    for inst in hosts:
        # «26.05», «26.05.0.0» e «26.05.00.0» sono la stessa versione scritta da fonti diverse
        riga = per_version.setdefault(sc.versione_chiave(inst.version_raw), {"scritte": set(), "hosts": set(), "fonti": set(), "outdated": 0})
        riga["scritte"].add(inst.version_raw or "")
        riga["hosts"].add(inst.host)
        riga["fonti"].update(inst.fonti_etichette)
        riga["outdated"] += 1 if inst.pk in outdated else 0
    cve_versioni = {}
    if with_cve:
        from security.services import cve_pannello

        cve_versioni = cve_pannello.cve_per_versione(key)
    version_rows = [
        {"version": sc.versione_da_mostrare(r["scritte"]) or "—", "hosts": len(r["hosts"]), "fonti": sorted(r["fonti"]), "outdated": bool(r["outdated"]),
         "cves": max(cve_versioni.get(v, 0) for v in r["scritte"])}
        for r in per_version.values()
    ]
    version_rows.sort(key=lambda r: (-r["hosts"], r["version"]))
    # Sotto quali nomi le fonti riportano il programma: chi legge vede cosa è stato raggruppato.
    nomi = {}
    for inst in hosts:
        riga = nomi.setdefault(sc.inventory_key(inst.vendor, inst.product), {"nomi": set(), "vendor": set(), "hosts": set()})
        riga["nomi"].add(inst.product_raw or inst.product)
        riga["vendor"].add(inst.vendor_raw or inst.vendor)
        riga["hosts"].add(inst.host)
    name_rows = [
        {"key": k, "name": ", ".join(sorted(r["nomi"])), "vendor": ", ".join(sorted(v for v in r["vendor"] if v)), "hosts": len(r["hosts"])}
        for k, r in sorted(nomi.items(), key=lambda x: (-len(x[1]["hosts"]), x[0]))
    ]
    altri_programmi = [r for r in catalog_rows(with_cve=False) if r["key"] != key] if can_edit else []
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
        "name_rows": name_rows,
        "regole": sc.regole_del_programma(key, indice),
        "altri_programmi": altri_programmi,
        "host_count": len({i.host for i in hosts}),
        "licenses": licenses,
        "classification_choices": SoftwareCatalogEntry.CLASSIFICATION_CHOICES,
        "licensing_choices": SoftwareCatalogEntry.LICENSING_CHOICES,
        "can_edit": can_edit,
        "show_cve": with_cve,
        "cve_count": (row or {}).get("cves", 0),
        "cve_stato": (row or {}).get("cve_stato", ""),
        "cpe_url": f"{reverse('security:software_mapping')}?{urlencode({'q': sc.split_key(key)[1]})}" if with_cve and _can_configure_soc(request) else "",
        "cve_panel_url": f"{reverse('security:cve_pannello_programma')}?{urlencode({'k': key})}" if with_cve else "",
        "catalog_url": reverse("assets:software_catalog"),
        "licenses_url": reverse("assets:software_license_list"),
    })
