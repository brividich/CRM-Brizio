"""Copertura dei PC: per ogni computer, quali fonti lo vedono (Intune, WatchGuard, Defender, backup).

Sola lettura. Il PC si riconosce dal nome host senza dominio e senza maiuscole («PC-01.dominio.local»
= «pc-01»): è lo stesso criterio con cui le fonti scrivono i nomi. Un PC che compare in una sola fonte
è il segnale utile: non gestito da Intune, senza antivirus, senza backup.
"""
from __future__ import annotations

from django.urls import reverse

FILTRI = [
    ("tutti", "Tutti"),
    ("problemi", "Problemi Intune"),
    ("non_intune", "Non in Intune"),
    ("senza_edr", "Senza WatchGuard"),
    ("senza_backup", "Senza backup"),
]


def norm(host):
    return (host or "").strip().lower().split(".")[0]


def _riga(nome):
    return {"nome": nome, "intune": None, "watchguard": False, "defender": False, "backup": None, "asset": None}


def righe():
    """Una riga per PC visto da almeno una fonte, con le fonti che lo vedono."""
    from assets.models import DispositivoIntune
    from security.models import SoftwareInstallation
    from security.services.backup_center import overview

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
    out = []
    for key, r in pcs.items():
        r["key"] = key
        r["url"] = reverse("security:pc_detail") + "?nome=" + r["nome"]
        r["fonti"] = sum(bool(x) for x in (r["intune"], r["watchguard"], r["defender"], r["backup"]))
        r["problemi"] = list(r["intune"].problemi_label) if r["intune"] else []
        out.append(r)
    # Prima chi ha qualcosa che non va: problemi Intune, poi chi è visto da meno fonti, poi per nome.
    out.sort(key=lambda r: (not r["problemi"], r["fonti"], r["nome"].casefold()))
    return out


def filtra(rows, codice):
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
