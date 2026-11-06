"""Inventario software visto dalla gestione asset: catalogo dei prodotti, software di un PC, PC per licenza.

L'inventario è uno solo (``SoftwareInstallation``, importato nel SOC). Qui si legge soltanto:
la scheda asset mostra i software del PC, le licenze contano i PC che hanno il prodotto.
La chiave di collegamento è ``vendor|product`` normalizzati, la stessa della mappatura CPE.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from security.models import SecurityCveImpact, SoftwareInstallation, SoftwareProgrammaRegola


# Le app dello Store hanno come produttore il pacchetto: «msteams_26288», «claude_3», «5319275a».
_PRODUTTORE_PACCHETTO = re.compile(r"_\d+$|^[0-9a-f]{8}(?:-|$)", re.I)


def inventory_key(vendor, product):
    return f"{vendor or ''}|{product or ''}"[:300]


def split_key(key):
    vendor, _sep, product = (key or "").partition("|")
    return vendor, product


def _per_confronto(parole):
    # I nomi localizzati: «Browser per SQL Server 2022» = «Browser for SQL Server 2022».
    return tuple("for" if p == "per" else p for p in parole)


def _famiglia(vendor, product):
    """Il «programma»: produttore + nome senza release e senza le parole del produttore
    («chrome» = «google chrome», «7-zip 25.01 (x64 edition)» = «7-zip 26.05 (x64)»).

    Solo per mostrare: le decisioni, le licenze e la mappatura CPE restano legate a ``vendor|product``.
    """
    from security.services.software_inventory import _token, base_name, nome_programma

    return (_token(vendor)[:1] and _token(vendor)[0] or "", _per_confronto(base_name(vendor, nome_programma(product))))


def _firma_nome(product):
    """Il nome intero senza release, a prescindere dal produttore: le fonti scrivono lo stesso programma con
    produttori diversi («CutePDF Writer» di «Acro Software Inc.» e di «acrosoftware», «7-Zip» di «Igor Pavlov» e
    di «7-zip»). Il nome intero, non quello base: «Autodesk Access» e «Microsoft Access» restano due.
    ``None`` per i nomi non risolti delle app dello Store («ms-resource:…»), che non dicono quale programma sono."""
    from security.services.software_inventory import _token, nome_programma

    if str(product or "").lower().startswith("ms-resource:"):
        return None
    return _per_confronto(_token(nome_programma(product))) or None


def stesso_programma(v1, p1, v2, p2):
    if (v1, p1) == (v2, p2) or _famiglia(v1, p1) == _famiglia(v2, p2):
        return True
    firma = _firma_nome(p1)
    return firma is not None and firma == _firma_nome(p2)


def _etichette(vendor, product):
    firma = _firma_nome(product)
    return [("famiglia", _famiglia(vendor, product))] + ([("nome", firma)] if firma else [])


def _preferenza_canonico(riga):
    """Il nome che rappresenta il programma: il più stabile nel tempo, così la chiave non cambia a ogni
    aggiornamento. Prima senza release nel nome, poi con un produttore vero (non «msteams_26288»), poi il più diffuso."""
    from security.services.software_inventory import nome_programma

    return (
        nome_programma(riga["product"]).lower() != riga["product"].lower(),
        bool(_PRODUTTORE_PACCHETTO.search(riga["vendor"] or "")),
        -riga["hosts"], len(riga["product"]), riga["product"], riga["vendor"],
    )


def indice_famiglie(con_unioni=True):
    """(canonici, etichette, separati): {(vendor, product): canonico} dei prodotti presenti, {etichetta: canonico} per
    ritrovare il programma anche di una chiave non più presente (una decisione presa su «7-Zip 26.05» vale per
    «7-Zip 26.07») e le chiavi separate a mano. Due prodotti stanno insieme se hanno lo stesso produttore e nome base,
    oppure lo stesso nome intero; sopra questa regola valgono le correzioni a mano (``SoftwareProgrammaRegola``).
    ``con_unioni=False`` ignora le unioni a mano: il CPE non si estende da Windows 10 a Windows 11 solo perché
    qualcuno li ha uniti per vederli su una riga."""
    regole = list(SoftwareProgrammaRegola.objects.all())
    separati = {r.chiave for r in regole if r.tipo == SoftwareProgrammaRegola.TIPO_SEPARA}
    rows = list(
        SoftwareInstallation.objects.filter(still_detected=True)
        .values("vendor", "product").order_by().annotate(hosts=Count("host", distinct=True))
    )
    genitore = list(range(len(rows)))

    def radice(i):
        while genitore[i] != i:
            genitore[i] = genitore[genitore[i]]
            i = genitore[i]
        return i

    primo = {}
    posizione = {inventory_key(r["vendor"], r["product"]): i for i, r in enumerate(rows)}
    for i, row in enumerate(rows):
        if inventory_key(row["vendor"], row["product"]) in separati:
            continue
        for etichetta in _etichette(row["vendor"], row["product"]):
            if etichetta in primo:
                genitore[radice(i)] = radice(primo[etichetta])
            else:
                primo[etichetta] = i

    def riga_di(chiave):
        # il nome esatto, o uno dello stesso programma se quel nome è sparito dopo un aggiornamento
        if chiave in posizione or chiave in separati:
            return posizione.get(chiave)
        return next((primo[e] for e in _etichette(*split_key(chiave)) if e in primo), None)

    for regola in regole:
        if con_unioni and regola.tipo == SoftwareProgrammaRegola.TIPO_UNISCI:
            a, b = riga_di(regola.chiave), riga_di(regola.chiave_altra)
            if a is not None and b is not None:
                genitore[radice(a)] = radice(b)
    gruppi = defaultdict(list)
    for i, row in enumerate(rows):
        gruppi[radice(i)].append(row)
    canonici, per_etichetta = {}, {}
    for membri in gruppi.values():
        scelto = min(membri, key=_preferenza_canonico)
        canon = (scelto["vendor"], scelto["product"])
        for r in membri:
            canonici[(r["vendor"], r["product"])] = canon
            if inventory_key(r["vendor"], r["product"]) not in separati:
                for etichetta in _etichette(r["vendor"], r["product"]):
                    per_etichetta[etichetta] = canon
    return canonici, per_etichetta, separati


def families():
    """{(vendor, product): chiave canonica} per i prodotti presenti. Un prodotto da solo punta a sé stesso."""
    return indice_famiglie()[0]


def _canon(fam, vendor, product):
    return fam.get((vendor, product), (vendor, product))


def chiave_canonica(key, indice=None):
    """La chiave con cui il catalogo mostra il programma di ``key``, anche se ``key`` non è più nell'inventario."""
    canonici, per_etichetta, separati = indice or indice_famiglie()
    vendor, product = split_key(key)
    trovato = canonici.get((vendor, product))
    if trovato is None and key in separati:
        trovato = (vendor, product)
    if trovato is None:
        trovato = next((per_etichetta[e] for e in _etichette(vendor, product) if e in per_etichetta), (vendor, product))
    return inventory_key(*trovato)


def member_keys(key):
    """Tutte le chiavi dei nomi che formano lo stesso programma di ``key`` (compresa ``key``)."""
    indice = indice_famiglie()
    target = split_key(chiave_canonica(key, indice))
    keys = {inventory_key(*m) for m, c in indice[0].items() if c == target}
    keys.add(key)
    return keys


def membri_automatici(vendor, product, indice=None):
    """I (vendor, product) dello stesso programma per la regola automatica: un CPE vale per tutti loro."""
    canonici = (indice or indice_famiglie(con_unioni=False))[0]
    target = canonici.get((vendor, product))
    if target is None:
        return {(vendor, product)}
    return {m for m, c in canonici.items() if c == target} | {(vendor, product)}


NON_CONTROLLATO = "non_controllato"
CONTROLLATO = "controllato"
NON_APPLICABILE = "non_applicabile"


def stati_cve(indice=None):
    """{chiave del programma: stato} per chi legge le CVE. «Controllato»: almeno un nome ha un CPE confermato.
    «Non applicabile»: tutti i nomi sono dichiarati tali. Altrimenti il SOC non sa niente: «non controllato»."""
    from security.models import SoftwareCpeMapping

    canonici = (indice or indice_famiglie())[0]
    confermati, esclusi = set(), set()
    for vendor, product, confirmed, na in SoftwareCpeMapping.objects.values_list("vendor", "product", "confirmed", "not_applicable"):
        (confermati if confirmed else esclusi if na else set()).add((vendor, product))
    membri = defaultdict(set)
    for membro, canon in canonici.items():
        membri[canon].add(membro)
    out = {}
    for canon, nomi in membri.items():
        if nomi & confermati:
            stato = CONTROLLATO
        elif nomi <= esclusi:
            stato = NON_APPLICABILE
        else:
            stato = NON_CONTROLLATO
        out[inventory_key(*canon)] = stato
    return out


def riepilogo_cve(indice=None):
    """Quanti programmi il SOC controlla: la definizione unica del numero (vedi ``metriche.copertura_cpe``)."""
    conteggio = Counter(stati_cve(indice).values())
    return {"programmi": sum(conteggio.values()), "controllati": conteggio[CONTROLLATO],
            "non_applicabili": conteggio[NON_APPLICABILE], "non_controllati": conteggio[NON_CONTROLLATO]}


def copertura_asset(asset):
    """Di questo PC: quanti programmi il SOC controlla e quanti no."""
    indice = indice_famiglie()
    stati = stati_cve(indice)
    programmi = {inventory_key(*_canon(indice[0], v, p)) for v, p in
                 SoftwareInstallation.objects.filter(hub_asset=asset, still_detected=True).values_list("vendor", "product").distinct()}
    return {"programmi": len(programmi),
            "non_controllati": sum(1 for k in programmi if stati.get(k, NON_CONTROLLATO) == NON_CONTROLLATO)}


def separa_dal_programma(chiave, utente=None):
    """Toglie un nome dal suo programma. Decisione, licenze e unioni fatte su quel nome restano al resto del
    programma, che è quello per cui erano state prese. Ritorna la chiave del resto, ``None`` se è da solo."""
    from assets.models import SoftwareCatalogEntry, SoftwareLicense

    canon = chiave_canonica(chiave)
    resto = sorted(member_keys(canon) - {chiave})
    if not resto:
        return None
    altra = canon if canon != chiave else resto[0]
    with transaction.atomic():
        if not SoftwareCatalogEntry.objects.filter(inventory_key=altra).exists():
            SoftwareCatalogEntry.objects.filter(inventory_key=chiave).update(inventory_key=altra)
        SoftwareLicense.objects.filter(inventory_key=chiave).update(inventory_key=altra)
        unioni = SoftwareProgrammaRegola.objects.filter(tipo=SoftwareProgrammaRegola.TIPO_UNISCI)
        unioni.filter(chiave=chiave).update(chiave=altra)
        unioni.filter(chiave_altra=chiave).update(chiave_altra=altra)
        SoftwareProgrammaRegola.objects.get_or_create(
            tipo=SoftwareProgrammaRegola.TIPO_SEPARA, chiave=chiave, defaults={"creato_da": utente}
        )
    return altra


def unisci_programmi(chiave, chiave_altra, utente=None):
    """Unisce due programmi. Se entrambi hanno una decisione vale quella di ``chiave``: le note dell'altra si
    aggiungono e la riga si elimina, altrimenti il SOC continuerebbe ad applicarle tutte e due al programma.
    Ritorna la decisione eliminata, per il registro."""
    from assets.models import SoftwareCatalogEntry

    indice = indice_famiglie()
    canon, altra = chiave_canonica(chiave, indice), chiave_canonica(chiave_altra, indice)
    if canon == altra:
        return None
    entries = {e.inventory_key: e for e in SoftwareCatalogEntry.objects.all()}
    per_programma = chiavi_per_programma(entries, indice)
    mie, altre = per_programma.get(canon, []), per_programma.get(altra, [])
    eliminata = None
    with transaction.atomic():
        if mie and altre:
            tenuta, tolta = entries[mie[0]], entries[altre[0]]
            eliminata = {"inventory_key": tolta.inventory_key, "classification": tolta.classification,
                         "licensing": tolta.licensing, "min_version": tolta.min_version}
            if tolta.notes:
                tenuta.notes = f"{tenuta.notes}\n{tolta.notes}".strip()[:4000]
                tenuta.save(update_fields=["notes"])
            tolta.delete()
        SoftwareProgrammaRegola.objects.create(
            tipo=SoftwareProgrammaRegola.TIPO_UNISCI, chiave=canon, chiave_altra=altra, creato_da=utente
        )
    return eliminata


def regole_del_programma(key, indice=None):
    """Le correzioni a mano che riguardano il programma di ``key``: unioni e, se è separato, la separazione."""
    from security.services.software_inventory import nome_programma

    indice = indice or indice_famiglie()
    out = []
    for regola in SoftwareProgrammaRegola.objects.all():
        if chiave_canonica(regola.chiave, indice) != key:
            continue
        if regola.tipo == SoftwareProgrammaRegola.TIPO_UNISCI:
            nomi = [nome_programma(split_key(k)[1]) for k in (regola.chiave, regola.chiave_altra)]
            out.append({"pk": regola.pk, "testo": f"Uniti a mano: {nomi[0]} e {nomi[1]}", "azione": "Annulla l'unione"})
        else:
            out.append({"pk": regola.pk, "testo": f"Separato a mano: {nome_programma(split_key(regola.chiave)[1])}",
                        "azione": "Rimetti nel gruppo"})
    return out


def chiavi_per_programma(keys, indice=None):
    """{chiave canonica: [chiavi]} per decisioni e licenze: restano del programma anche quando il nome esatto su
    cui sono state prese è sparito dall'inventario (aggiornamento a una versione con un altro nome)."""
    indice = indice or indice_famiglie()
    out = defaultdict(list)
    for key in sorted({k for k in keys if k}):
        out[chiave_canonica(key, indice)].append(key)
    return out


def _etichetta_preferita(contatore, *, scarta=None):
    """La scritta più usata, meglio se con le maiuscole dell'originale («CutePDF Writer», non «cutepdf writer»)."""
    candidate = Counter({k: v for k, v in contatore.items() if k and not (scarta and scarta(k))}) or contatore
    con_maiuscole = Counter({k: v for k, v in candidate.items() if k != k.lower()})
    return (con_maiuscole or candidate).most_common(1)[0][0] if candidate else ""


def _produttore_finto(vendor, nomi):
    """Non un produttore: il pacchetto di un'app dello Store, una cartella o il nome stesso del programma."""
    from security.services.software_inventory import _token

    if _PRODUTTORE_PACCHETTO.search(vendor) or "\\" in vendor:
        return True
    return any("".join(_token(vendor)) == "".join(_token(nome)) for nome in nomi)


def catalog(limit=2000):
    """Programmi presenti oggi: i nomi e le release dello stesso programma sono una riga sola, col nome pulito
    («7-Zip») e quanti PC lo hanno. ``cerca`` tiene i nomi originali, per trovarlo con qualsiasi scritta."""
    from security.services.software_inventory import nome_programma

    indice = indice_famiglie()
    fam, separati = indice[0], indice[2]
    nomi = defaultdict(Counter)
    produttori = defaultdict(Counter)
    originali = defaultdict(set)
    hosts = defaultdict(set)
    members = defaultdict(set)
    for vendor, product, raw, vendor_raw, host in SoftwareInstallation.objects.filter(still_detected=True).values_list(
        "vendor", "product", "product_raw", "vendor_raw", "host"
    ):
        canon = _canon(fam, vendor, product)
        # separato a mano: tiene il nome intero, altrimenti «MUD 2025» e il resto si chiamerebbero entrambi «MUD»
        nomi[canon][(raw or product) if inventory_key(vendor, product) in separati else nome_programma(raw or product)] += 1
        produttori[canon][vendor_raw or vendor] += 1
        originali[canon].update({raw or product, vendor_raw or vendor})
        hosts[canon].add(host)
        members[canon].add(inventory_key(vendor, product))
    out = []
    for canon in sorted(hosts, key=lambda c: (nome_programma(c[1]), c[0]))[:limit]:
        vendor, product = canon
        out.append({
            "key": inventory_key(vendor, product),
            "label": _etichetta_preferita(nomi[canon]),
            "vendor_label": _etichetta_preferita(produttori[canon], scarta=lambda v, n=nomi[canon]: _produttore_finto(v, n)),
            "hosts": len(hosts[canon]),
            "member_keys": sorted(members[canon]),
            "separato": inventory_key(vendor, product) in separati,
            "cerca": " ".join(sorted(x for x in originali[canon] if x)),
        })
    return out


def catalog_choices():
    return [(item["key"], f"{item['label']} · {item['vendor_label'] or 'produttore n/d'} ({item['hosts']} PC)") for item in catalog()]


def hosts_by_key(keys):
    """{chiave: numero di PC che hanno oggi il programma} per le chiavi richieste (nomi dello stesso programma uniti)."""
    wanted = {k for k in keys if k}
    if not wanted:
        return {}
    indice = indice_famiglie()
    fam = indice[0]
    targets = {k: split_key(chiave_canonica(k, indice)) for k in wanted}
    hosts = defaultdict(set)
    for vendor, product, host in SoftwareInstallation.objects.filter(still_detected=True).values_list("vendor", "product", "host").distinct():
        hosts[_canon(fam, vendor, product)].add(host)
    return {k: len(hosts[t]) for k, t in targets.items() if t in hosts}


def latest_inventory_date():
    return SoftwareInstallation.objects.aggregate(last=Max("last_inventory_date"))["last"]


def _versioni_senza_doppioni(installazioni):
    gruppi = defaultdict(set)
    for i in installazioni:
        gruppi[versione_chiave(i.version_raw)].add(i.version_raw)
    return [versione_da_mostrare(v) for v in gruppi.values()]


def software_for_hub_asset(asset, *, with_cve=False, license_states=None):
    """Software del PC raggruppati per prodotto: versione attuale, versioni precedenti, CVE, licenza.

    ``license_states``: {chiave inventario: "coperta" | "scaduta"} dalle licenze del modulo Asset.
    """
    installs = list(SoftwareInstallation.objects.filter(hub_asset=asset).order_by("product", "vendor", "-last_seen_at"))
    if not installs:
        return {"rows": [], "present": 0, "removed": 0, "inventory_date": None}
    cve = defaultdict(lambda: {"impacts": [], "to_verify": 0})
    if with_cve:
        for inst_id, outcome, cve_id in SecurityCveImpact.objects.filter(
            installation__in=[i.pk for i in installs if i.still_detected],
            outcome__in=[SecurityCveImpact.IMPACTS, SecurityCveImpact.TO_VERIFY],
        ).values_list("installation_id", "outcome", "cve__cve_id"):
            if outcome == SecurityCveImpact.IMPACTS:
                cve[inst_id]["impacts"].append(cve_id)
            else:
                cve[inst_id]["to_verify"] += 1
    from security.services.software_inventory import nome_programma

    indice = indice_famiglie()
    fam, separati = indice[0], indice[2]
    groups = defaultdict(list)
    for inst in installs:
        groups[_canon(fam, inst.vendor, inst.product)].append(inst)
    rows = []
    for (vendor, product), items in groups.items():
        current = [i for i in items if i.still_detected]
        previous = [i for i in items if not i.still_detected]
        head = current[0] if current else items[0]
        impacts = sorted({c for i in current for c in cve[i.pk]["impacts"]})
        key = inventory_key(vendor, product)
        rows.append({
            "key": key,
            "name": head.product_raw if key in separati else nome_programma(head.product_raw),
            "vendor": head.vendor_raw or vendor,
            "versions": _versioni_senza_doppioni(current),
            "present": bool(current),
            "first_seen": min(i.seen_at for i in items),
            "last_seen": max(i.last_seen_at for i in items),
            "previous": [{"version": i.version_raw, "until": i.last_seen_at} for i in previous][:5],
            "cve_impacts": impacts,
            "cve_to_verify": sum(cve[i.pk]["to_verify"] for i in current),
            "license": (license_states or {}).get(key, ""),
        })
    rows.sort(key=lambda r: (not r["present"], -len(r["cve_impacts"]), r["name"].lower()))
    return {
        "rows": rows,
        "present": sum(1 for r in rows if r["present"]),
        "removed": sum(1 for r in rows if not r["present"]),
        "inventory_date": max(i.last_inventory_date for i in installs),
    }


def product_hosts(key):
    """PC che hanno oggi il programma (tutti i nomi che lo formano), con versione, asset collegato e ultima rilevazione."""
    pairs = {split_key(k) for k in member_keys(key)}
    vendors, products = {v for v, _p in pairs}, {p for _v, p in pairs}
    rows = SoftwareInstallation.objects.filter(still_detected=True, vendor__in=vendors, product__in=products).select_related("hub_asset")
    return sorted((i for i in rows if (i.vendor, i.product) in pairs), key=lambda i: (i.host, i.version_raw))


def versione_chiave(version):
    """La stessa versione scritta da fonti diverse: «26.05», «26.05.0.0», «26.05.00.0» → «26.05»."""
    testo = str(version or "").strip().casefold()
    return re.sub(r"(?:\.0+)+$", "", testo) or testo


def versione_da_mostrare(scritte):
    return min(scritte, key=lambda v: (len(v), v)) if scritte else ""


def versions_by_key():
    """{chiave: Counter(versione → PC)} dei prodotti presenti. Un PC visto da due fonti con la stessa
    versione scritta in due modi conta una volta."""
    fam = families()
    pc = defaultdict(lambda: defaultdict(set))
    scritte = defaultdict(lambda: defaultdict(set))
    for vendor, product, version, host in SoftwareInstallation.objects.filter(still_detected=True).values_list(
        "vendor", "product", "version_raw", "host"
    ).distinct():
        key = inventory_key(*_canon(fam, vendor, product))
        pc[key][versione_chiave(version)].add(host)
        scritte[key][versione_chiave(version)].add(version)
    return {
        key: Counter({versione_da_mostrare(scritte[key][v]): len(hosts) for v, hosts in per_versione.items()})
        for key, per_versione in pc.items()
    }


def cve_by_key():
    """{chiave: numero di CVE che impattano almeno un PC che ha oggi il programma} (lo stesso numero del pannello CVE)."""
    fam = families()
    out = defaultdict(set)
    for vendor, product, cve_id in SecurityCveImpact.objects.filter(
        outcome=SecurityCveImpact.IMPACTS, installation__still_detected=True,
    ).values_list("installation__vendor", "installation__product", "cve__cve_id"):
        out[inventory_key(*_canon(fam, vendor, product))].add(cve_id)
    return {key: len(ids) for key, ids in out.items()}


def below_min_version(versions, min_version):
    """PC con versione sotto la minima e PC con versione non confrontabile (contati a parte, mai «vecchi»)."""
    from security.services.versioning import compare

    old, unknown = 0, 0
    if not min_version:
        return 0, 0
    for version, hosts in versions.items():
        result = compare(version, min_version)
        if result is None:
            unknown += hosts
        elif result < 0:
            old += hosts
    return old, unknown


def outdated_hosts(key, min_version):
    """PC con il prodotto in una versione sicuramente inferiore alla minima."""
    from security.services.versioning import compare

    if not min_version:
        return []
    return [i for i in product_hosts(key) if (compare(i.version_raw, min_version) or 0) < 0]


def license_states_for_keys(licenses, today=None):
    """{chiave: "coperta" | "scaduta"} da licenze con ``inventory_key``; una licenza valida vince su una scaduta."""
    today = today or timezone.localdate()
    out = {}
    for lic in licenses:
        if not lic.inventory_key:
            continue
        valid = lic.is_active and (lic.expiry_date is None or lic.expiry_date >= today)
        if valid:
            out[lic.inventory_key] = "coperta"
        else:
            out.setdefault(lic.inventory_key, "scaduta")
    return out


def license_states_per_programma(licenses, today=None):
    """Come ``license_states_for_keys``, sulla chiave del programma: una licenza valida su un altro nome vale per tutti."""
    stati = license_states_for_keys(licenses, today=today)
    out = {}
    for canon, keys in chiavi_per_programma(stati).items():
        out[canon] = "coperta" if any(stati[k] == "coperta" for k in keys) else "scaduta"
    return out
