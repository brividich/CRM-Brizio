"""Quali CVE sono sfruttate (catalogo CISA KEV) fra quelle date.

Le CVE KEV nel catalogo del SOC sono poche decine: si leggono tutte e si incrociano in memoria. Il
filtro ``cve_id__in=[migliaia di CVE]`` su SQL Server passa per una tabella temporanea riempita riga
per riga (mssql-django oltre 2.000 parametri) e costava 10 s a query su Patch e protezione e Report.
"""

from __future__ import annotations

from security.models import SecurityCveRecord


def kev_tra(cve_ids) -> set[str]:
    """Le CVE date (scritte come arrivano) che sono nel catalogo KEV."""
    cercate = {str(c) for c in cve_ids if c}
    if not cercate:
        return set()
    kev = {c.upper() for c in SecurityCveRecord.objects.filter(kev=True).values_list("cve_id", flat=True) if c}
    return {c for c in cercate if c.upper() in kev}
