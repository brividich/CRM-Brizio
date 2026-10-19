"""Software installato sui PC letto da Microsoft Defender for Endpoint (Defender for Business).

Ogni mattina (schedule ``defender_software_sync``), se acceso da
``/soc/impostazioni/`` («Alert di Microsoft Defender» › «Leggi il software dei PC»),
legge ``machines/SoftwareInventoryByMachine`` e lo importa nell'inventario
software del SOC come fonte «Microsoft Defender for Endpoint», con la stessa
procedura dei file caricati a mano (``software_inventory.run_import``): storico
degli import, collegamento agli asset, software «non più rilevato» per gli host
letti, poi mappatura CPE, regole «non applicabile», ricalcolo degli impatti CVE e
controllo del catalogo software.

Copre solo i PC collegati a Defender: gli altri restano agli import da file
(WatchGuard, BusinessLog). Permesso applicativo ``Software.Read.All`` dell'API
«WindowsDefenderATP» (non Graph), con consenso amministratore.
"""
from __future__ import annotations

import hashlib
import json
import logging

from django.utils import timezone

from security.models import SoftwareInventoryImport, SoftwareSourceKind
from security.services import soc_settings
from security.services.software_inventory import RowPreview, run_import

logger = logging.getLogger(__name__)

PERMESSO = "Software.Read.All (API WindowsDefenderATP)"
URL = "https://api.securitycenter.microsoft.com/api/machines/SoftwareInventoryByMachine"
NOME_IMPORT = "Microsoft Defender for Endpoint (API)"


def leggi() -> list[dict]:
    from core import m365_graph

    return m365_graph.get_all(URL, permesso=PERMESSO, params={"pageSize": "50000"}, max_pages=40)


def anteprima(righe: list[dict]) -> RowPreview:
    preview = RowPreview(total=len(righe))
    visti = set()
    for i, r in enumerate(righe, start=1):
        host = str(r.get("deviceName") or "").strip()
        prodotto = str(r.get("softwareName") or "").strip()
        versione = str(r.get("softwareVersion") or "").strip()
        vendor = str(r.get("softwareVendor") or "").strip()
        if not host or not prodotto:
            preview.skipped.append((i, "nome PC o prodotto vuoto"))
            continue
        if not versione:
            preview.skipped.append((i, "versione vuota (non confrontabile con i range CVE)"))
            continue
        chiave = (host.casefold(), vendor.casefold(), prodotto.casefold(), versione.casefold())
        if chiave in visti:
            continue
        visti.add(chiave)
        # Defender scrive i nomi in minuscolo con «_» («microsoft_365_apps»): li rendiamo leggibili.
        preview.valid.append({"host": host[:255], "vendor": vendor.replace("_", " ")[:255],
                              "product": prodotto.replace("_", " ")[:255], "version": versione[:120],
                              "detected_at": None})
    return preview


def _dopo_import() -> None:
    from security import views_vuln

    views_vuln._auto_link_cpe()
    views_vuln._apply_na_rules()
    views_vuln._queue_recompute()
    views_vuln._run_software_policy()


def sincronizza(*, righe: list[dict] | None = None) -> dict:
    if righe is None:
        righe = leggi()
    preview = anteprima(righe)
    impronta = hashlib.sha256(json.dumps(preview.valid, sort_keys=True, default=str).encode()).hexdigest()
    item = SoftwareInventoryImport.objects.create(
        source_kind=SoftwareSourceKind.DEFENDER, original_name=NOME_IMPORT, file_sha256=impronta,
        inventory_date=timezone.localdate(),
    )
    run_import(item, preview)
    try:
        _dopo_import()
    except Exception:  # noqa: BLE001 - l'import è fatto; i passi successivi hanno il loro job orario
        logger.exception("Defender software: passi dopo l'import non riusciti")
    return {"righe": item.rows_total, "importate": item.rows_imported, "nuove": item.rows_new,
            "pc": item.hosts_count, "non_piu_rilevate": item.rows_marked_missing}


def run() -> dict:
    """Task del mattino: non solleva sugli errori di Graph/Defender."""
    from core import m365_graph

    if not soc_settings.value("defender.software.attivo"):
        return {"attivo": False}
    if not m365_graph.configurato():
        return {"ok": False, "motivo": "Graph non configurato"}
    try:
        return {"ok": True, **sincronizza()}
    except m365_graph.GraphError as exc:
        logger.warning("Defender software: %s", exc)
        return {"ok": False, "errore": str(exc)[:300]}
