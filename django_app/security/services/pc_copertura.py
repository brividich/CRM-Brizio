"""Dispositivi del SOC: un elenco solo, una riga per PC o server, con tutto ciò che lo riguarda.

Unisce le due pagine di prima («PC e fonti» e «Asset»): per ogni dispositivo quali fonti lo vedono
(Intune, WatchGuard, Defender), l'esito dei backup, le CVE che lo colpiscono e l'asset del registro
a cui è collegato (o quello proposto, da confermare). Backup e vulnerabilità sono attività del
dispositivo: qui si vedono sulla sua riga, il dettaglio sta nella scheda del dispositivo.

Sola lettura. Il dispositivo si riconosce dal nome host senza dominio e senza maiuscole
(«PC-01.dominio.local» = «pc-01»): è lo stesso criterio con cui le fonti scrivono i nomi.
"""
from __future__ import annotations

from django.urls import reverse

FILTRI = [
    ("tutti", "Tutti"),
    ("da_collegare", "Senza asset"),
    ("backup_ko", "Backup ko"),
    ("con_cve", "Con CVE"),
    ("problemi", "Problemi Intune"),
    ("non_intune", "Non in Intune"),
    ("senza_edr", "Senza WatchGuard"),
    ("senza_backup", "Senza backup"),
]


def norm(host):
    return (host or "").strip().lower().split(".")[0]


def _riga(nome):
    return {"nome": nome, "intune": None, "watchguard": False, "defender": False, "backup": None, "asset": None,
            "soc": [], "cve": None, "proposta": None, "motivo": ""}


def righe(proposte=True):
    """Una riga per dispositivo visto da almeno una fonte (Intune, inventario, backup, report SOC)."""
    from assets.models import DispositivoIntune
    from security.models import SecurityAsset, SoftwareInstallation
    from security.services.backup_center import overview
    from security.services.metriche import cve_per_pc

    pcs = {}
    for d in DispositivoIntune.objects.filter(presente=True).select_related("asset"):
        key = norm(d.nome) or norm(d.seriale)
        if not key:
            continue
        r = pcs.setdefault(key, _riga(d.nome))
        r["intune"], r["asset"] = d, d.asset
    for host, display, fonti in SoftwareInstallation.objects.filter(still_detected=True).values_list("host", "host_display", "fonti").iterator():
        key = norm(host)
        if not key or not fonti or set(fonti) <= {"snmp_firmware"}:
            continue  # i firmware letti via SNMP sono apparati di rete, non PC
        r = pcs.setdefault(key, _riga(display or host))
        r["watchguard"] = r["watchguard"] or "watchguard" in fonti
        r["defender"] = r["defender"] or "defender" in fonti
    for dev in overview(30)["devices"]:
        key = norm(dev["name"])
        if key:
            pcs.setdefault(key, _riga(dev["name"]))["backup"] = dev
    # Dispositivi citati dai report (backup, Endpoint Security): portano il collegamento all'asset del registro.
    for sa in SecurityAsset.objects.select_related("hub_asset").order_by("hostname"):
        key = norm(sa.hostname)
        if not key:
            continue
        r = pcs.setdefault(key, _riga(sa.hostname))
        r["soc"].append(sa)
        if not r["asset"] and sa.hub_asset_id:
            r["asset"] = sa.hub_asset
    for host, dati in cve_per_pc().items():
        key = norm(host)
        if key in pcs:
            prec = pcs[key]["cve"] or {"cves": 0, "kev": 0, "gravi": 0}
            pcs[key]["cve"] = {k: prec[k] + dati[k] for k in ("cves", "kev", "gravi")}
    try:
        from assets.services.rete_windows import rete_dei_dispositivi

        rete_asset, rete_nome = rete_dei_dispositivi()
    except Exception:  # noqa: BLE001 - la rete è un dettaglio della riga, non ferma l'elenco
        rete_asset, rete_nome = {}, {}
    out = []
    for key, r in pcs.items():
        r["key"] = key
        # Indirizzo dal DHCP/DNS: prima quello collegato all'asset, poi lo stesso nome host.
        rete = (rete_asset.get(r["asset"].pk) if r["asset"] else None) or rete_nome.get(key) or []
        r["rete"] = rete[0] if rete else None
        r["url"] = reverse("security:pc_detail") + "?nome=" + r["nome"]
        r["fonti"] = sum(bool(x) for x in (r["intune"], r["watchguard"], r["defender"], r["backup"]))
        r["problemi"] = list(r["intune"].problemi_label) if r["intune"] else []
        r["backup_ko"] = bool(r["backup"] and (r["backup"]["stale"] or r["backup"]["last_status"] == "failed"))
        # Il collegamento all'asset si conferma sul dispositivo SOC: senza, l'unica via è la riconciliazione Intune.
        r["soc_da_collegare"] = next((sa for sa in r["soc"] if not sa.hub_asset_id), None) if not r["asset"] else None
        out.append(r)
    if proposte:
        from security.services.asset_signals import suggest_hub_asset

        for r in out:
            if r["soc_da_collegare"]:
                r["proposta"], r["motivo"] = suggest_hub_asset(r["soc_da_collegare"])
    # Prima chi ha qualcosa che non va: backup ko, problemi Intune, CVE gravi; poi chi è visto da meno fonti.
    out.sort(key=lambda r: (not r["backup_ko"], not r["problemi"], not (r["cve"] and r["cve"]["gravi"]), r["fonti"], r["nome"].casefold()))
    return out


def filtra(rows, codice):
    if codice == "da_collegare":
        return [r for r in rows if not r["asset"]]
    if codice == "backup_ko":
        return [r for r in rows if r["backup_ko"]]
    if codice == "con_cve":
        return [r for r in rows if r["cve"]]
    if codice == "problemi":
        return [r for r in rows if r["problemi"]]
    if codice == "non_intune":
        return [r for r in rows if not r["intune"]]
    if codice == "senza_edr":
        return [r for r in rows if not r["watchguard"]]
    if codice == "senza_backup":
        return [r for r in rows if not r["backup"]]
    return rows


def conteggi(rows):
    return {codice: len(filtra(rows, codice)) for codice, _label in FILTRI}
