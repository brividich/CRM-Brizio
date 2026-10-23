"""«Visto da»: le fonti che conoscono questo dispositivo, in una riga in testa alla scheda asset.

Sola lettura, poche query. Ogni fonte dice se vede l'asset e quando l'ha visto l'ultima volta:

- Microsoft Intune (``DispositivoIntune`` collegato): sincronizzazione e problemi aperti;
- inventario software WatchGuard / Defender (``SoftwareInstallation`` ancora rilevate);
- dispositivi del Security Center (``SecurityAsset`` collegati): ultimo fatto ricevuto;
- monitoraggio SNMP del modulo contatori (``DispositivoSNMP`` collegato);
- WatchGuard via API (``WatchGuardDispositivo``): stato della protezione e patch mancanti, prima dell'inventario;
- switch e porta a cui il PC è collegato (tabella MAC letta via SNMP, ``contatori.tabella_mac``).

Le fonti SOC compaiono solo a chi vede il Security Center. Per i PC (postazioni e server) le
fonti che mancano si mostrano tratteggiate: un PC non in Intune o senza inventario è il dato utile.

Stati: ``ok`` visto di recente, ``old`` visto ma non di recente, ``ko`` visto con un problema,
``no`` non visto da questa fonte.
"""
from __future__ import annotations

from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

GIORNI_RECENTE = 7
PROFILI_PC = ("workstation", "server", "vm")


def _stato_data(quando, oggi, giorni=GIORNI_RECENTE):
    if quando is None:
        return "old"
    data = quando.date() if hasattr(quando, "date") else quando
    return "ok" if (oggi - data).days <= giorni else "old"


def _fonte(nome, stato, dettaglio="", url="", quando=None):
    return {"nome": nome, "stato": stato, "dettaglio": dettaglio, "url": url, "quando": quando}


def _intune(asset, oggi):
    from assets.models import DispositivoIntune

    disp = DispositivoIntune.objects.filter(asset=asset).order_by("-presente", "-ultima_sync").first()
    if disp is None or not disp.presente:
        return None
    if disp.problemi:
        return _fonte("Intune", "ko", ", ".join(disp.problemi_label), "#asset-it-intune-title", disp.ultima_sync)
    return _fonte("Intune", _stato_data(disp.ultima_sync, oggi), "sincronizzato", "#asset-it-intune-title", disp.ultima_sync)


def _inventario(asset, oggi):
    """{fonte: ultima data inventario} delle installazioni ancora rilevate sul PC."""
    from security.models import SoftwareInstallation
    from security.services.cve_impact import freshness_days

    ultime = {}
    for fonti, origine, data in SoftwareInstallation.objects.filter(hub_asset=asset, still_detected=True).values_list(
        "fonti", "source_kind", "last_inventory_date"
    ).iterator():
        for fonte in fonti or [origine]:
            if data and (fonte not in ultime or data > ultime[fonte]):
                ultime[fonte] = data
    out = {}
    for fonte, nome in (("watchguard", "WatchGuard"), ("defender", "Defender")):
        if fonte in ultime:
            out[fonte] = _fonte(nome, _stato_data(ultime[fonte], oggi, freshness_days()), "inventario software",
                                "#asset-software", ultime[fonte])
    return out


def _watchguard_api(asset, oggi):
    """WatchGuard letto dall'API: protezione, ultima connessione, patch mancanti. None se l'API non lo vede."""
    from security.models import WatchGuardDispositivo, WatchGuardPatch

    disp = WatchGuardDispositivo.objects.filter(hub_asset=asset, presente=True).order_by("-gestito", "-ultima_connessione").first()
    if disp is None:
        return None
    url = reverse("security:watchguard_pc")
    if not disp.gestito:
        return _fonte("WatchGuard", "ko", "in rete senza agente", url, disp.ultima_connessione)
    patch = WatchGuardPatch.objects.filter(hub_asset=asset, presente=True).count()
    dettaglio = "protezione attiva" if disp.protetto else f"protezione: {disp.protezione_label.lower()}"
    if disp.protezione == 1 and disp.motore_aggiornato is False:
        dettaglio = "protezione non aggiornata"
    if patch:
        dettaglio += f" · {patch} patch mancant{'e' if patch == 1 else 'i'}"
    stato = "ko" if not disp.protetto else _stato_data(disp.ultima_connessione, oggi)
    return _fonte("WatchGuard", stato, dettaglio, url, disp.ultima_connessione)


def _switch(asset):
    from contatori.tabella_mac import porte_di_asset

    porte = [p for p in porte_di_asset(asset) if p.porta_accesso]
    if not porte:
        return None
    p = porte[0]
    url = reverse("contatori:snmp_dispositivo", args=[p.dispositivo_id])
    return _fonte("Rete", "ok", f"{p.dispositivo.nome} · {p.porta}", url, p.letto_il)


def _soc(asset, oggi):
    from security.models import SecurityAsset

    dispositivi = list(SecurityAsset.objects.filter(hub_asset=asset).select_related("source"))
    if not dispositivi:
        return None
    from security.models import SecurityEventRecord

    ultimo = SecurityEventRecord.objects.filter(asset__in=dispositivi).aggregate(u=Max("occurred_at"))["u"]
    fonti = sorted({d.source.name for d in dispositivi if d.source_id})
    url = reverse("security:pc_detail") + "?nome=" + dispositivi[0].hostname
    return _fonte("Security Center", _stato_data(ultimo, oggi) if ultimo else "old",
                  ", ".join(fonti[:3]) or "dispositivo collegato", url, ultimo)


def _snmp(asset, oggi):
    from contatori.models import DispositivoSNMP, StatoSNMP

    disp = DispositivoSNMP.objects.filter(asset=asset, attivo=True).order_by("-snmp_ultimo_controllo").first()
    if disp is None:
        return None
    url = reverse("contatori:snmp_dispositivo", args=[disp.pk])
    if disp.snmp_stato == StatoSNMP.ERROR:
        return _fonte("SNMP", "ko", "non risponde", url, disp.snmp_ultimo_controllo)
    if disp.snmp_stato == StatoSNMP.WARNING:
        return _fonte("SNMP", "old", "da controllare", url, disp.snmp_ultimo_controllo)
    return _fonte("SNMP", _stato_data(disp.snmp_ultimo_controllo, oggi, 2), "monitoraggio", url, disp.snmp_ultimo_controllo)


def per_asset(asset, *, profilo=None, soc=False, oggi=None):
    """Elenco delle fonti per la striscia «Visto da»; vuoto se nessuna fonte vede l'asset e non è un PC."""
    oggi = oggi or timezone.localdate()
    pc = profilo in PROFILI_PC
    out = []
    intune = _intune(asset, oggi)
    if intune:
        out.append(intune)
    elif pc and profilo != "vm":
        out.append(_fonte("Intune", "no", "non gestito"))
    if soc:
        inventario = _inventario(asset, oggi)
        wg_api = _watchguard_api(asset, oggi)
        if wg_api:
            inventario["watchguard"] = wg_api
        for fonte, nome in (("watchguard", "WatchGuard"), ("defender", "Defender")):
            if fonte in inventario:
                out.append(inventario[fonte])
            elif pc:
                out.append(_fonte(nome, "no", "non nell'inventario"))
        soc_dev = _soc(asset, oggi)
        if soc_dev:
            out.append(soc_dev)
    snmp = _snmp(asset, oggi)
    if snmp:
        out.append(snmp)
    switch = _switch(asset)
    if switch:
        out.append(switch)
    if not any(f["stato"] != "no" for f in out) and not pc:
        return []
    return out

