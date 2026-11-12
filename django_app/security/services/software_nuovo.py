"""Programma mai visto prima: compare nell'inventario e nessuno ha ancora deciso cosa sia.

Un programma «nuovo» è un programma del Catalogo software (una riga per programma, nomi e release uniti) la cui
**prima comparsa** su un PC qualsiasi è negli ultimi ``software.nuovo.giorni`` giorni e che non ha una decisione
(né sul programma, né tramite una regola per produttore). È il segnale dello shadow IT: qualcuno ha installato
qualcosa fuori dalla dotazione.

Dopo ogni import dell'inventario nasce **un evento per programma**, una volta sola (dedup sul programma): il
motore regole ne fa un alert, che sta in Proposte AI insieme agli altri. Quando il programma riceve una decisione
nel catalogo (consentito, non autorizzato, da rimuovere) l'alert si chiude da solo; se è «non autorizzato» ci pensa
poi l'alert di conformità (``software_policy``). Il badge «nuovo» del catalogo e il filtro «Nuovi» usano la stessa
data di prima comparsa (``prime_comparse``).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from security.models import SecurityAlert, SecurityEventRecord, Severity, SoftwareInstallation
from security.services import soc_settings
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

EVENT_TYPE = "software_nuovo"
ETICHETTA = "Programma nuovo nell'inventario"


def giorni() -> int:
    return int(soc_settings.value("software.nuovo.giorni") or 14)


def prime_comparse(indice=None) -> dict[str, "timezone.datetime"]:
    """{chiave canonica del programma: prima volta vista su un PC}, su tutte le righe, anche quelle non più rilevate.

    Un programma aggiornato lascia la riga vecchia come «non più rilevata»: la sua data resta la prima comparsa vera.
    """
    from security.services import software_catalog as sc

    indice = indice or sc.indice_famiglie()
    canon = {}
    out = {}
    for vendor, product, visto in SoftwareInstallation.objects.values_list("vendor", "product", "seen_at").iterator():
        key = sc.inventory_key(vendor, product)
        if key not in canon:
            canon[key] = sc.chiave_canonica(key, indice)
        chiave = canon[key]
        if visto and (chiave not in out or visto < out[chiave]):
            out[chiave] = visto
    return out


def _decise(indice) -> set[str]:
    """Programmi con una decisione: voce di catalogo non «da classificare» su uno qualsiasi dei nomi, o produttore consentito."""
    from assets.models import SoftwareCatalogEntry, SoftwareProduttoreConsentito
    from assets.views_software import _produttore_regola
    from security.services import software_catalog as sc

    voci = {e.inventory_key: e for e in SoftwareCatalogEntry.objects.exclude(classification=SoftwareCatalogEntry.CLASS_UNREVIEWED)}
    decise = {sc.chiave_canonica(k, indice) for k in voci}
    consentiti = set(SoftwareProduttoreConsentito.objects.values_list("produttore", flat=True))
    if consentiti:
        for item in sc.catalog():
            if _produttore_regola(item["vendor_label"]) in consentiti:
                decise.add(item["key"])
    return decise


def programmi_nuovi(oggi=None, indice=None) -> list[dict]:
    """I programmi comparsi negli ultimi N giorni senza decisione: ``{"key","nome","vendor","hosts","dal"}``, i più recenti prima."""
    from security.services import software_catalog as sc

    adesso = oggi or timezone.now()
    indice = indice or sc.indice_famiglie()
    soglia = adesso - timedelta(days=giorni())
    comparse = prime_comparse(indice)
    decise = _decise(indice)
    out = []
    for item in sc.catalog():
        dal = comparse.get(item["key"])
        if dal is None or dal < soglia or item["key"] in decise:
            continue
        out.append({"key": item["key"], "nome": item["label"], "vendor": item["vendor_label"], "hosts": item["hosts"], "dal": dal})
    out.sort(key=lambda r: (r["dal"], r["nome"]), reverse=True)
    return out


def _dedup(source, key):
    return make_hash(source.pk, EVENT_TYPE, key)


def record_events(now=None) -> list:
    """Un evento per programma nuovo, una volta sola. Ritorna gli eventi creati."""
    if not soc_settings.value("software.nuovo.alert"):
        return []
    from security.services.software_policy import policy_source

    now = now or timezone.now()
    source = policy_source()
    creati = []
    hosts = defaultdict(set)
    nuovi = programmi_nuovi(now)
    if nuovi:
        from security.services import software_catalog as sc

        chiavi = {r["key"] for r in nuovi}
        for key in chiavi:
            hosts[key] = {i.host_display or i.host for i in sc.product_hosts(key)}
    for riga in nuovi:
        dedup = _dedup(source, riga["key"])
        if SecurityEventRecord.objects.filter(source=source, event_type=EVENT_TYPE, dedup_hash=dedup).exists():
            continue
        elenco = sorted(hosts.get(riga["key"], set()))
        payload = {
            "inventory_key": riga["key"], "product": riga["nome"], "vendor": riga["vendor"],
            "hosts": elenco[:300], "host_count": riga["hosts"], "dal": riga["dal"].isoformat(),
            "alert_candidate": True,
        }
        creati.append(SecurityEventRecord.objects.create(
            source=source, event_type=EVENT_TYPE, severity=Severity.WARNING, occurred_at=now,
            fingerprint=dedup, dedup_hash=dedup, payload=payload,
        ))
    return creati


def chiudi_decisi() -> int:
    """Chiude gli alert «programma nuovo» dei programmi che nel frattempo hanno una decisione o sono spariti."""
    from security.services import software_catalog as sc
    from security.services.auto_resolution import resolve_alert
    from security.services.software_policy import policy_source

    source = policy_source()
    alerts = list(SecurityAlert.objects.filter(source=source, status__in=ACTIVE_ALERT_STATUSES, event__event_type=EVENT_TYPE)
                  .select_related("event"))
    if not alerts:
        return 0
    indice = sc.indice_famiglie()
    decise = _decise(indice)
    presenti = {item["key"] for item in sc.catalog()}
    chiusi = 0
    for alert in alerts:
        key = (alert.event.payload or {}).get("inventory_key", "") if alert.event_id else ""
        canon = sc.chiave_canonica(key, indice) if key else ""
        if canon in decise:
            motivo = f"{(alert.event.payload or {}).get('product')}: il programma ha ricevuto una decisione nel Catalogo software."
        elif canon not in presenti:
            motivo = f"{(alert.event.payload or {}).get('product')}: il programma non è più su nessun PC."
        else:
            continue
        try:
            resolve_alert(alert, motivo, rule_code=EVENT_TYPE)
            chiusi += 1
        except Exception:  # noqa: BLE001 - una chiusura mancata si ritenta al giro dopo
            logger.exception("Chiusura dell'alert «programma nuovo» %s non riuscita", alert.pk)
    return chiusi
