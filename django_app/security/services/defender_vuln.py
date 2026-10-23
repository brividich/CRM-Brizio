"""Vulnerabilità viste da Microsoft Defender for Endpoint, per confrontarle con il calcolo del SOC.

Ogni mattina (con «Confronta le CVE con Defender» acceso in ``/soc/impostazioni/``) legge
``vulnerabilities/machinesVulnerabilities`` (CVE per PC, prodotto, versione, KB che la corregge) e
``machines`` (nome del PC). Le righe finiscono in ``DefenderVulnerabilita``: non aprono alert, servono
al pannello CVE per dire «Defender la vede anche lui» o «Defender non la vede su questo PC».

Permessi applicativi dell'API «WindowsDefenderATP», con consenso amministratore:
``Vulnerability.Read.All`` e ``Machine.Read.All``.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from security.models import DefenderVulnerabilita
from security.services import soc_settings

logger = logging.getLogger(__name__)

PERMESSO = "Vulnerability.Read.All e Machine.Read.All (API WindowsDefenderATP)"
URL_VULN = "https://api.securitycenter.microsoft.com/api/vulnerabilities/machinesVulnerabilities"
URL_PC = "https://api.securitycenter.microsoft.com/api/machines"
CHUNK = 500


def leggi() -> tuple[list[dict], list[dict]]:
    from core import m365_graph

    pc = m365_graph.get_all(URL_PC, permesso=PERMESSO, max_pages=20)
    righe = m365_graph.get_all(URL_VULN, permesso=PERMESSO, max_pages=60)
    return pc, righe


def sincronizza(*, pc: list[dict] | None = None, righe: list[dict] | None = None) -> dict:
    from security.services.software_inventory import normalize_host

    if pc is None or righe is None:
        pc, righe = leggi()
    nomi = {str(m.get("id")): str(m.get("computerDnsName") or "") for m in pc if m.get("id")}
    now = timezone.now()
    nuove = {}
    for r in righe:
        nome = nomi.get(str(r.get("machineId") or ""), "")
        cve = str(r.get("cveId") or "").strip().upper()
        if not nome or not cve.startswith("CVE-"):
            continue
        host = normalize_host(nome)
        chiave = (host, cve, str(r.get("productName") or "")[:255], str(r.get("productVersion") or "")[:120])
        nuove.setdefault(chiave, DefenderVulnerabilita(
            host=host, host_display=nome.split(".")[0][:255], cve_id=cve[:32], prodotto=chiave[2],
            produttore=str(r.get("productVendor") or "")[:255], versione=chiave[3],
            kb=str(r.get("fixingKbId") or "")[:40], severita=str(r.get("severity") or "")[:20], letta_il=now))
    if not nuove and righe:
        return {"righe": len(righe), "salvate": 0, "saltato": "nessun PC riconosciuto"}
    with transaction.atomic():
        DefenderVulnerabilita.objects.all().delete()
        oggetti = list(nuove.values())
        for i in range(0, len(oggetti), CHUNK):
            DefenderVulnerabilita.objects.bulk_create(oggetti[i:i + CHUNK], batch_size=CHUNK)
    return {"righe": len(righe), "salvate": len(nuove), "pc": len({k[0] for k in nuove})}


def per_cve(cve_id: str) -> set[str]:
    """Host su cui Defender vede la CVE."""
    return set(DefenderVulnerabilita.objects.filter(cve_id=cve_id).values_list("host", flat=True))


def dati_presenti() -> bool:
    return DefenderVulnerabilita.objects.exists()


def host_in_defender(hosts) -> set[str]:
    """Quali host Defender conosce (hanno software letto da Defender): solo su questi il confronto ha senso."""
    from security.models import SoftwareInstallation

    out = set()
    hosts = list(hosts)
    for i in range(0, len(hosts), CHUNK):
        for host, fonti, kind in SoftwareInstallation.objects.filter(
                host__in=hosts[i:i + CHUNK], still_detected=True).values_list("host", "fonti", "source_kind"):
            if kind == "defender" or "defender" in (fonti or []):
                out.add(host)
    return out


def confronto_cve(cve_id: str, nostri_host: set[str]) -> dict | None:
    """Confronto per la scheda breve. «solo_soc» conta solo i PC che Defender conosce. None se Defender non è letto."""
    if not soc_settings.value("defender.vulnerabilita.attivo") or not dati_presenti():
        return None
    loro = per_cve(cve_id)
    noti = host_in_defender(nostri_host)
    return {"comuni": len(loro & nostri_host), "solo_soc": sorted((nostri_host & noti) - loro),
            "fuori_defender": len(nostri_host - noti), "solo_defender": sorted(loro - nostri_host), "defender": loro}


def confronto_asset(host: str, nostre_cve: set[str]) -> dict | None:
    """Confronto per il pannello di un PC."""
    if not host or not soc_settings.value("defender.vulnerabilita.attivo") or not dati_presenti():
        return None
    righe = list(DefenderVulnerabilita.objects.filter(host=host))
    if not righe and not host_in_defender([host]):
        return None
    loro = {r.cve_id for r in righe}
    return {"comuni": len(loro & nostre_cve), "solo_soc": sorted(nostre_cve - loro),
            "solo_defender": sorted(loro - nostre_cve)[:40], "solo_defender_n": len(loro - nostre_cve),
            "letto": bool(righe), "defender": loro}


def run() -> dict:
    from core import m365_graph

    if not soc_settings.value("defender.vulnerabilita.attivo"):
        return {"attivo": False}
    if not m365_graph.configurato():
        return {"ok": False, "motivo": "Graph non configurato"}
    try:
        return {"ok": True, **sincronizza()}
    except m365_graph.GraphError as exc:
        logger.warning("Defender vulnerabilità: %s", exc)
        return {"ok": False, "errore": str(exc)[:300]}
