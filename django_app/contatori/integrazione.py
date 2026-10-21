"""Contatori IT ↔ modulo Asset ↔ SOC: un solo posto per i collegamenti fra i tre moduli.

- ``allineamento_asset``: dove apparato e asset collegato non dicono la stessa cosa
  (seriale, modello, IP, posizione, stato di vita). Nessuna scrittura automatica:
  i dati si allineano dalla scheda asset, con audit.
- ``crea_asset_da_apparato``: l'apparato senza asset diventa un asset dell'inventario,
  con i dati letti via SNMP e un punto rete con il suo IP.
- ``sicurezza_apparato``: cosa sa il SOC di questo apparato (firmware nell'inventario,
  CVE che lo impattano, alert aperti) e la configurazione SNMP debole.
- ``quadro_integrazione``: i numeri per la Centrale.

Solo dati gia' salvati: aprire una pagina non interroga mai un apparato.
"""
from __future__ import annotations

import logging

from django.db import DatabaseError, transaction
from django.urls import reverse

from .models import DispositivoSNMP, ImpostazioniSNMP, Macchina

logger = logging.getLogger(__name__)

# Tipo dell'asset da creare per ogni categoria di apparato (le MFC sono sempre stampanti).
TIPO_ASSET_DA_CATEGORIA = {
    DispositivoSNMP.Categoria.STAMPANTE: "STAMPANTE",
    DispositivoSNMP.Categoria.FIREWALL: "FIREWALL",
    DispositivoSNMP.Categoria.SERVER: "SERVER",
    DispositivoSNMP.Categoria.RETE: "HW",
    DispositivoSNMP.Categoria.STORAGE: "HW",
    DispositivoSNMP.Categoria.UPS: "HW",
    DispositivoSNMP.Categoria.TVCC_NVR: "CCTV",
    DispositivoSNMP.Categoria.TVCC_TELECAMERA: "CCTV",
}

# Community note a chiunque: con SNMPv1/v2c chi le conosce legge l'apparato.
COMMUNITY_PREDEFINITE = {"public", "private", "community", "snmp", "admin"}

LIMITE_ELENCO = 8


def _modello_apparato(tipo):
    return {"mfc": Macchina, "snmp": DispositivoSNMP}.get(tipo)


def tipo_di(apparato) -> str:
    return "mfc" if isinstance(apparato, Macchina) else "snmp"


def nome_apparato(apparato) -> str:
    return apparato.reparto if isinstance(apparato, Macchina) else apparato.nome


def url_apparato(apparato) -> str:
    if isinstance(apparato, Macchina):
        return reverse("contatori:macchina", args=[apparato.pk])
    return reverse("contatori:snmp_dispositivo", args=[apparato.pk])


def _attivo(apparato) -> bool:
    return apparato.attiva if isinstance(apparato, Macchina) else apparato.attivo


def _norm(valore, campo=""):
    from assets.services.it_identity_diff import _norm as norm

    return norm(valore, campo)


# --- Allineamento con l'asset ---------------------------------------------------

def allineamento_asset(apparato) -> list[dict]:
    """Differenze fra apparato e asset collegato, dalla piu' grave.

    Ogni riga: ``dato``, ``apparato``, ``asset``, ``livello`` (danger|warn|info), ``nota``.
    """
    asset = apparato.asset
    if asset is None:
        return []
    righe = []
    attivo = _attivo(apparato)
    if asset.status == asset.STATUS_RETIRED and attivo:
        righe.append({"dato": "Stato", "apparato": "Monitorato", "asset": "Dismesso", "livello": "danger",
                      "nota": "L'asset è dismesso ma l'apparato è ancora interrogato: disattivalo o correggi lo stato dell'asset."})
    elif not attivo and asset.status == asset.STATUS_IN_USE:
        righe.append({"dato": "Stato", "apparato": "Monitoraggio disattivato", "asset": "In uso", "livello": "info",
                      "nota": "Se l'apparato è stato tolto dalla rete, aggiorna lo stato dell'asset."})

    produttore = "" if isinstance(apparato, Macchina) else apparato.produttore
    for dato, valore, campo, attuale in (
        ("Numero di serie", apparato.matricola, "serial_number", asset.serial_number),
        ("Produttore", produttore, "manufacturer", asset.manufacturer),
        ("Modello", apparato.modello, "model", asset.model),
    ):
        valore = " ".join(str(valore or "").split())
        if valore and _norm(valore, campo) != _norm(attuale, campo):
            righe.append({"dato": dato, "apparato": valore, "asset": attuale or "", "livello": "warn" if attuale else "info",
                          "nota": "Diverso dall'inventario: si allinea dalla scheda asset («Applica»)." if attuale
                          else "Vuoto nell'inventario: si copia dalla scheda asset («Applica»)."})

    if apparato.host:
        ips = [ep.ip.strip() for ep in asset.endpoints.all() if (ep.ip or "").strip()]
        if apparato.host not in ips:
            righe.append({"dato": "Indirizzo IP", "apparato": apparato.host, "asset": ", ".join(ips),
                          "livello": "warn" if ips else "info",
                          "nota": "L'IP interrogato non è tra i punti rete dell'asset: aggiungilo dalla scheda asset."
                          if ips else "L'asset non ha punti rete: aggiungi l'IP dalla scheda asset."})

    posizione = apparato.reparto if isinstance(apparato, Macchina) else apparato.posizione
    luoghi = [x for x in (asset.assignment_location, asset.assignment_reparto, asset.reparto) if (x or "").strip()]
    if posizione and luoghi and all(_norm(posizione) not in _norm(x) and _norm(x) not in _norm(posizione) for x in luoghi):
        righe.append({"dato": "Reparto / posizione", "apparato": posizione, "asset": luoghi[0], "livello": "info",
                      "nota": "Posizione diversa: verifica se l'apparato è stato spostato."})
    ordine = {"danger": 0, "warn": 1, "info": 2}
    return sorted(righe, key=lambda r: ordine[r["livello"]])


# --- Creazione dell'asset dall'apparato -------------------------------------------

def tipo_asset_per(apparato) -> str:
    if isinstance(apparato, Macchina):
        return "STAMPANTE"
    return TIPO_ASSET_DA_CATEGORIA.get(apparato.categoria, "OTHER")


def dati_asset_proposti(apparato) -> dict:
    """Campi del nuovo asset: solo cio' che l'apparato sa davvero, niente inventato."""
    if isinstance(apparato, Macchina):
        nome = f"MFC {apparato.reparto}".strip()
        return {"name": nome[:255], "asset_type": "STAMPANTE", "model": apparato.modello or None,
                "serial_number": apparato.matricola or None, "reparto": apparato.reparto[:120],
                "manufacturer": None, "assignment_location": ""}
    return {"name": (apparato.nome or apparato.sys_name or apparato.host)[:255], "asset_type": tipo_asset_per(apparato),
            "model": apparato.modello or None, "manufacturer": apparato.produttore or None,
            "serial_number": apparato.matricola or None, "reparto": "",
            "assignment_location": (apparato.posizione or "")[:200]}


def crea_asset_da_apparato(apparato):
    """Crea l'asset, il punto rete con l'IP e collega l'apparato. Ritorna l'asset.

    Solleva ``ValueError`` se l'apparato ha gia' un asset.
    """
    from assets.models import Asset, AssetEndpoint

    with transaction.atomic():
        bloccato = type(apparato).objects.select_for_update().get(pk=apparato.pk)
        if bloccato.asset_id:
            raise ValueError("L'apparato è già collegato a un asset.")
        dati = dati_asset_proposti(bloccato)
        asset = Asset.objects.create(
            status=Asset.STATUS_IN_USE,
            notes=f"Creato da Contatori IT ({nome_apparato(bloccato)}).",
            **dati,
        )
        if bloccato.host:
            AssetEndpoint.objects.create(asset=asset, endpoint_name="Monitoraggio SNMP", ip=bloccato.host)
        bloccato.asset = asset
        campi = ["asset", "aggiornato_il"] if isinstance(bloccato, DispositivoSNMP) else ["asset"]
        bloccato.save(update_fields=campi)
    apparato.asset = asset
    return asset


# --- Sicurezza: SOC e configurazione SNMP ----------------------------------------

def postura_snmp(apparato) -> list[dict]:
    """Configurazione SNMP debole dell'apparato. Mai il valore della community."""
    from .services import _community_snmp, _parametri_snmp
    from .snmp import SNMPError

    cfg = ImpostazioniSNMP.get_solo()
    _porta, _timeout, versione = _parametri_snmp(apparato, cfg)
    if versione == "v3":
        return []
    righe = [{"livello": "warn", "titolo": f"SNMP{versione} senza cifratura",
              "dettaglio": "Community e valori viaggiano in chiaro sulla rete: dove l'apparato lo supporta, passa a SNMPv3."}]
    try:
        community = (_community_snmp(apparato, cfg) or "").strip().lower()
    except SNMPError:
        community = ""
    if community in COMMUNITY_PREDEFINITE:
        righe.insert(0, {"livello": "danger", "titolo": "Community predefinita",
                         "dettaglio": "L'apparato risponde a una community nota a chiunque: cambiala sull'apparato e nel catalogo community."})
    return righe


def _puo_vedere_soc(request) -> bool:
    try:
        from security.permissions import can_view_security_center

        return bool(can_view_security_center(getattr(request, "user", None)))
    except Exception:  # noqa: BLE001 - senza SOC la scheda resta consultabile
        logger.exception("Permesso SOC non verificabile")
        return False


def sicurezza_apparato(request, apparato) -> dict:
    """Riquadro «Sicurezza» delle schede apparato.

    La configurazione SNMP la vede chi vede la scheda; firmware nell'inventario, CVE
    e alert solo chi vede anche il Security Center.
    """
    out = {"postura": postura_snmp(apparato), "soc": None}
    if not apparato.host or not _puo_vedere_soc(request):
        return out
    try:
        from security.models import SecurityAlert, SecurityCveImpact, SoftwareInstallation, SoftwareSourceKind
        from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

        from .soc import dedup_irraggiungibile

        host = apparato.host.strip().lower()
        firmware = (SoftwareInstallation.objects.filter(source_kind=SoftwareSourceKind.SNMP_FIRMWARE, host=host,
                                                        still_detected=True)
                    .values("product_raw", "version_raw", "last_seen_at").first())
        impatti = list(SecurityCveImpact.objects.filter(
            host=host, outcome__in=[SecurityCveImpact.IMPACTS, SecurityCveImpact.TO_VERIFY],
        ).select_related("cve").order_by("-cve__kev", "-cve__cvss", "cve__cve_id")[:LIMITE_ELENCO + 1])
        alert = None
        if isinstance(apparato, DispositivoSNMP):
            dedup = dedup_irraggiungibile(apparato, crea_fonte=False)
            if dedup:
                alert = (SecurityAlert.objects.filter(dedup_hash=dedup, status__in=ACTIVE_ALERT_STATUSES)
                         .order_by("-created_at").first())
        out["soc"] = {
            "firmware": firmware,
            "impatti": impatti[:LIMITE_ELENCO],
            "impatti_altri": len(impatti) > LIMITE_ELENCO,
            "impatta": sum(1 for i in impatti if i.outcome == SecurityCveImpact.IMPACTS),
            "alert": alert,
            "vuln_url": reverse("security:vulnerabilities"),
        }
    except DatabaseError:
        logger.exception("Dati SOC non disponibili per l'apparato %s", apparato.pk)
    return out


# --- Quadro per la Centrale -------------------------------------------------------

def quadro_integrazione(request=None) -> dict:
    """Problemi di integrazione Asset/SOC per la colonna «Da fare» della Centrale.

    Query a numero fisso, liste corte: l'elenco completo sta nella riconciliazione IT.
    """
    from assets.models import Asset

    macchine = Macchina.objects.filter(attiva=True)
    dispositivi = DispositivoSNMP.objects.filter(attivo=True)
    senza_asset = ([("mfc", m) for m in macchine.filter(asset__isnull=True).order_by("reparto")[:LIMITE_ELENCO]]
                   + [("snmp", d) for d in dispositivi.filter(asset__isnull=True)
                      .exclude(categoria=DispositivoSNMP.Categoria.TVCC_TELECAMERA).order_by("nome")[:LIMITE_ELENCO]])
    n_senza_asset = (macchine.filter(asset__isnull=True).count()
                     + dispositivi.filter(asset__isnull=True).exclude(
                         categoria=DispositivoSNMP.Categoria.TVCC_TELECAMERA).count())
    dismessi = ([("mfc", m) for m in macchine.filter(asset__status=Asset.STATUS_RETIRED).select_related("asset")]
                + [("snmp", d) for d in dispositivi.filter(asset__status=Asset.STATUS_RETIRED).select_related("asset")])
    righe = lambda coppie: [{"tipo": t, "oggetto": o, "nome": nome_apparato(o), "url": url_apparato(o)}  # noqa: E731
                            for t, o in coppie]
    out = {
        "senza_asset": righe(senza_asset)[:LIMITE_ELENCO],
        "n_senza_asset": n_senza_asset,
        "dismessi": righe(dismessi)[:LIMITE_ELENCO],
        "n_dismessi": len(dismessi),
        "riconciliazione_url": reverse("assets:it_reconciliation"),
        "firmware_cve": None,
        "irraggiungibili_soc": None,
    }
    # Telecamere escluse: decine di apparati senza asset proprio sommergerebbero l'elenco.
    if request is not None and _puo_vedere_soc(request):
        try:
            from security.models import SecurityCveImpact

            host_monitorati = {h.lower() for h in dispositivi.values_list("host", flat=True)}
            impatti = (SecurityCveImpact.objects.filter(outcome=SecurityCveImpact.IMPACTS,
                                                        installation__source_kind="snmp_firmware",
                                                        installation__still_detected=True)
                       .values_list("host", flat=True))
            out["firmware_cve"] = len({h for h in impatti if h in host_monitorati})
            from .soc import alert_aperti_irraggiungibili

            out["irraggiungibili_soc"] = alert_aperti_irraggiungibili()
        except DatabaseError:
            logger.exception("Quadro SOC della Centrale non disponibile")
    return out
