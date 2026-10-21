"""Authorized snapshots only: opening an asset must never poll a device."""
from decimal import Decimal
from urllib.parse import urlencode

from django.db import DatabaseError
from django.db.models import OuterRef, Subquery
from django.urls import reverse
from django.utils import timezone

from core.middleware import acl_allows_path

LINK_LIMIT = 10
READING_LIMIT = 30
READING_STATE_LABELS = {"OK": "Regolare", "WARNING": "Attenzione", "ERROR": "Critico o non letto"}
STATE_LABELS = {"OK": "Risposta ricevuta", "WARNING": "Con avvisi", "ERROR": "Errore", "MAI": "Mai interrogato"}


def can_view_monitoring(request, path):
    if not getattr(request.user, "is_authenticated", False):
        return False
    try:
        return acl_allows_path(path, django_user=request.user,
                               legacy_user=getattr(request, "legacy_user", None), request=request)
    except DatabaseError:
        return False


def _format_reading(number, unit):
    """Numero leggibile in italiano: migliaia con punto, al massimo 2 decimali, durate in g/h."""
    unit = (unit or "").strip()
    if unit == "s" and number >= 0:
        days, rest = divmod(int(number), 86400)
        hours, rest = divmod(rest, 3600)
        return f"{days} g {hours} h" if days else f"{hours} h {rest // 60} min"
    rounded = number.quantize(Decimal("1") if abs(number) >= 100 else Decimal("0.01")).normalize()
    integer, _, decimals = format(rounded, "f").partition(".")
    sign = "-" if integer.startswith("-") else ""
    text = sign + f"{int(integer.lstrip('-') or 0):,}".replace(",", ".")
    if decimals:
        text += "," + decimals
    return f"{text} {unit}".strip()


def _probe_readings(snapshot_ids, declared_macs=None):
    """Valori delle sonde dell'ultima rilevazione, senza i messaggi d'errore tecnici.

    Con ``declared_macs`` (MAC dei punti rete dell'asset) il MAC letto via SNMP viene
    confrontato con quello dichiarato: ``mac_check`` = ``same`` | ``different`` | ``undeclared``.
    """
    from contatori.models import SondaSNMP, ValoreSNMP, etichetta_valore

    out = {}
    rows = ValoreSNMP.objects.filter(rilevazione_id__in=snapshot_ids).order_by(
        "rilevazione_id", "sonda__ordine", "sonda__nome",
    ).values("rilevazione_id", "sonda__nome", "sonda__unita", "sonda__etichette", "sonda__tipo_valore",
             "valore_numero", "valore_testo", "stato")
    for row in rows:
        readings = out.setdefault(row["rilevazione_id"], [])
        if len(readings) >= READING_LIMIT:
            continue
        label = etichetta_valore(row["sonda__etichette"], row["valore_numero"])
        if label:
            value = label
        elif row["valore_numero"] is not None:
            value = _format_reading(row["valore_numero"], row["sonda__unita"])
        else:
            value = row["valore_testo"] or "Non disponibile"
        reading = {
            "name": row["sonda__nome"], "value": value, "state": row["stato"],
            "state_label": READING_STATE_LABELS.get(row["stato"], "Esito non noto"),
        }
        if declared_macs is not None and row["sonda__tipo_valore"] == SondaSNMP.TipoValore.MAC and row["valore_testo"]:
            mac = row["valore_testo"].lower()
            reading["mac_check"] = "same" if mac in declared_macs else ("different" if declared_macs else "undeclared")
        readings.append(reading)
    return out


def has_snmp_monitoring(asset) -> bool:
    """Asset fuori dai profili IT che Contatori IT osserva o puo' osservare (es. videosorveglianza, UPS)."""
    from contatori.forms_wizard import TIPO_DA_ASSET
    from contatori.models import DispositivoSNMP, Macchina

    if asset.asset_type in TIPO_DA_ASSET:
        return True
    return DispositivoSNMP.objects.filter(asset=asset).exists() or Macchina.objects.filter(asset=asset).exists()


def monitoring_for_asset(request, asset, *, printer=False, endpoint_ips=()):
    central_url = reverse("contatori:snmp_centrale")
    if not can_view_monitoring(request, central_url):
        return None
    from contatori.models import DispositivoSNMP, LetturaMensileContatori, Macchina, RilevazioneSNMP

    latest = RilevazioneSNMP.objects.filter(dispositivo_id=OuterRef("pk")).order_by("-rilevata_il", "-pk")
    devices = list(DispositivoSNMP.objects.filter(asset=asset).order_by("nome", "pk").annotate(
        snapshot_id=Subquery(latest.values("pk")[:1]),
    ).values("id", "nome", "host", "attivo", "snmp_stato", "snmp_ultimo_controllo", "firmware", "snapshot_id",
             "categoria", "sys_object_id", "sys_uptime_seconds")[:LINK_LIMIT])
    categorie = dict(DispositivoSNMP.Categoria.choices)
    permitted = []
    for device in devices:
        device["url"] = reverse("contatori:snmp_dispositivo", args=[device["id"]])
        if can_view_monitoring(request, device["url"]):
            permitted.append(device)
    snapshot_ids = [row["snapshot_id"] for row in permitted if row["snapshot_id"]]
    snapshots = {row["id"]: row for row in RilevazioneSNMP.objects.filter(
        pk__in=snapshot_ids,
    ).values("id", "rilevata_il", "stato", "dati_stampante")}
    declared_macs = {mac.lower() for mac in asset.endpoints.exclude(mac="").values_list("mac", flat=True)} if snapshot_ids else set()
    readings_by_snapshot = _probe_readings(snapshot_ids, declared_macs)
    for device in permitted:
        device["state_label"] = STATE_LABELS.get(device["snmp_stato"], "Esito non noto")
        device["categoria_label"] = categorie.get(device["categoria"], "")
        # NVR TVT: il modello sta nel sysObjectID. Telecamere: l'uptime e' del servizio SNMP, non si mostra.
        device["modello_tvcc"] = device["sys_object_id"] if device["categoria"] == DispositivoSNMP.Categoria.TVCC_NVR else ""
        uptime = device["sys_uptime_seconds"]
        device["acceso_giorni"] = (uptime // 86400 if uptime is not None
                                   and device["categoria"] != DispositivoSNMP.Categoria.TVCC_TELECAMERA else None)
        snapshot = snapshots.get(device["snapshot_id"])
        if snapshot:
            snapshot["state_label"] = STATE_LABELS.get(snapshot["stato"], "Esito non noto")
        device["snapshot"] = snapshot
        device["readings"] = readings_by_snapshot.get(device["snapshot_id"], [])
        payload = snapshot.get("dati_stampante") if snapshot else {}
        payload = payload if isinstance(payload, dict) else {}
        counters = payload.get("contatori") or []
        supplies = payload.get("consumabili") or []
        device["counters"] = [row for row in counters[:20] if isinstance(row, dict)] if isinstance(counters, list) else []
        device["supplies"] = [row for row in supplies[:20] if isinstance(row, dict)] if isinstance(supplies, list) else []
        device["partial"] = bool(payload.get("errori"))
        # Explicit unknowns, including 0% vs None; never turn unknown into zero.
        for supply in device["supplies"]:
            pct = supply.get("pct")
            supply["display_pct"] = pct if type(pct) in (int, float) and 0 <= pct <= 100 else None

    last_reading = LetturaMensileContatori.objects.filter(macchina_id=OuterRef("pk")).order_by("-rilevata_il", "-pk")
    machines = list(Macchina.objects.filter(asset=asset).order_by("reparto", "pk").annotate(
        reading_id=Subquery(last_reading.values("pk")[:1]),
    ).values("id", "reparto", "matricola", "modello", "host", "contratto", "fornitore", "attiva", "snmp_stato",
             "snmp_ultimo_controllo", "snmp_ultimo_errore", "reading_id")[:LINK_LIMIT])
    permitted_machines = []
    # «Leggi adesso» scrive nello storico: solo con la gestione Contatori (job asincrono).
    from contatori.permessi import puo_gestire

    can_read_now = puo_gestire(request) if machines else False
    for machine in machines:
        machine["url"] = reverse("contatori:macchina", args=[machine["id"]])
        if can_view_monitoring(request, machine["url"]):
            supplies_url = reverse("contatori:macchina_consumabili", args=[machine["id"]])
            machine["supplies_url"] = supplies_url if machine["host"] and machine["attiva"] and can_read_now else ""
            permitted_machines.append(machine)
    readings = {row["id"]: row for row in LetturaMensileContatori.objects.filter(
        pk__in=[row["reading_id"] for row in permitted_machines if row["reading_id"]],
    ).values("id", "mese", "rilevata_il", "a4_bn", "a3_bn", "a4_col", "a3_col")}
    for row in readings.values():
        row["totale"] = row["a4_bn"] + row["a3_bn"] + row["a4_col"] + row["a3_col"]
    from .mfc_stats import candidati_collegamento, statistiche_mfc

    stats = statistiche_mfc(permitted_machines)
    from contatori.models import LetturaContatori
    from contatori.services import righe_letture_macchina

    # Una query per tutte le MFC del riquadro (limite di query della scheda).
    trimestrali = {}
    if permitted_machines:
        for lettura in LetturaContatori.objects.filter(
                macchina_id__in=[m["id"] for m in permitted_machines]).order_by("trimestre"):
            trimestrali.setdefault(lettura.macchina_id, []).append(lettura)
    for machine in permitted_machines:
        machine["state_label"] = STATE_LABELS.get(machine["snmp_stato"], "Esito non noto")
        machine["reading"] = readings.get(machine["reading_id"])
        machine["stats"] = stats.get(machine["id"])
        # Letture di riconciliazione: le ultime 4 righe, lacune comprese (mai copie inventate).
        machine["trimestrali"] = righe_letture_macchina(
            None, letture=trimestrali.get(machine["id"], []))[:4]
        machine["registro_url"] = reverse("contatori:letture_registro")
    # Stampante senza MFC collegata: lo si dice, con le MFC candidate da collegare.
    unlinked = None
    if printer and not machines:
        candidates = candidati_collegamento(asset, list(endpoint_ips))
        # Stesso controllo della riconciliazione (_link): modifica dell'MFC in Contatori.
        probe = reverse("contatori:macchina_edit", args=[candidates[0]["id"]]) if candidates else reverse("contatori:macchine")
        unlinked = {
            "candidates": candidates,
            "reconcile_url": reverse("assets:it_reconciliation"),
            "can_link": can_view_monitoring(request, probe),
        }
    return {"devices": permitted, "machines": permitted_machines, "central_url": central_url,
            "mfc_unlinked": unlinked, "add_url": _wizard_url(request, asset) if not devices and not machines else ""}


def _wizard_url(request, asset):
    """«Monitora via SNMP»: wizard «Nuovo apparato» con l'asset gia' scelto (solo chi gestisce Contatori)."""
    from contatori.forms_wizard import TIPO_DA_ASSET
    from contatori.permessi import puo_gestire

    url = reverse("contatori:wizard_avvia", args=["apparato"])
    if not puo_gestire(request) or not can_view_monitoring(request, url):
        return ""
    query = {"asset": asset.pk}
    if TIPO_DA_ASSET.get(asset.asset_type):
        query["tipo_apparato"] = TIPO_DA_ASSET[asset.asset_type]
    return f"{url}?{urlencode(query)}"


# Gravita' per il pallino della lista: per piu' dispositivi sullo stesso asset vince il peggiore.
_DOT_ORDER = {"OK": 0, "MAI": 1, "WARNING": 2, "ERROR": 3}
_DOT_CLASS = {"OK": "ok", "MAI": "mai", "WARNING": "warning", "ERROR": "critical"}


def monitoring_dots(request, asset_ids):
    """Stato SNMP salvato (nessuna interrogazione) degli asset in pagina: ``{asset_id: dot}``.

    Solo per chi puo' aprire il Monitor SNMP; i dispositivi disattivati non contano.
    """
    asset_ids = [pk for pk in asset_ids if pk]
    if not asset_ids or not can_view_monitoring(request, reverse("contatori:snmp_centrale")):
        return {}
    from contatori.models import DispositivoSNMP

    dots = {}
    rows = DispositivoSNMP.objects.filter(asset_id__in=asset_ids, attivo=True).values_list(
        "asset_id", "nome", "snmp_stato", "snmp_ultimo_controllo",
    )
    for asset_id, nome, stato, controllo in rows:
        stato = stato if stato in _DOT_ORDER else "MAI"
        dot = dots.setdefault(asset_id, {"state": "OK", "lines": []})
        if _DOT_ORDER[stato] > _DOT_ORDER[dot["state"]]:
            dot["state"] = stato
        quando = f" · ultimo controllo {timezone.localtime(controllo):%d/%m/%Y %H:%M}" if controllo else ""
        dot["lines"].append(f"{nome}: {STATE_LABELS.get(stato, stato)}{quando}")
    for dot in dots.values():
        dot["css"] = _DOT_CLASS[dot["state"]]
        dot["title"] = "Monitor SNMP — " + "; ".join(dot["lines"])
    return dots
