"""Copertura del monitoraggio per gli asset IT: chi li osserva (SNMP, SOC) e come stanno.

Solo letture sui dati gia' raccolti, in blocco per una pagina di elenco: aprire
l'inventario non interroga mai un dispositivo. La visibilita' segue i permessi
dei moduli (centrale SNMP via ACL di percorso, SOC via permesso Security Center).
"""
from __future__ import annotations

from datetime import timedelta

from django.db import DatabaseError
from django.db.models import Count, Exists, Max, OuterRef, Q
from django.urls import reverse
from django.utils import timezone

# Oltre questa soglia un dispositivo che non risponde (o non viene interrogato)
# e' "muto": il dato che mostriamo e' vecchio e va detto.
SILENT_AFTER = timedelta(days=3)

COVERAGE_FILTERS = {
    "": "Tutti",
    "scoperti": "Senza monitoraggio",
    "problemi": "Con problemi",
    "monitorati": "Monitorati",
}


def can_view_snmp(request) -> bool:
    from assets.services.it_monitoring import can_view_monitoring

    return can_view_monitoring(request, reverse("contatori:snmp_centrale"))


def can_view_soc(request) -> bool:
    try:
        from security.permissions import can_view_security_center

        return bool(can_view_security_center(request.user))
    except Exception:
        return False


def monitored_q() -> Q:
    """Asset osservati da almeno un modulo (dispositivo/MFC SNMP o dispositivo SOC)."""
    from contatori.models import DispositivoSNMP, Macchina
    from security.models import SecurityAsset

    return Q(
        Exists(DispositivoSNMP.objects.filter(asset=OuterRef("pk")))
        | Exists(Macchina.objects.filter(asset=OuterRef("pk")))
        | Exists(SecurityAsset.objects.filter(hub_asset=OuterRef("pk")))
    )


def problems_q() -> Q:
    """Asset con un dispositivo SNMP in errore/muto o un alert SOC aperto."""
    from contatori.models import DispositivoSNMP, Macchina
    from security.models import SecurityAlert
    from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

    stale = timezone.now() - SILENT_AFTER
    bad_snmp = Q(snmp_stato="ERROR") | Q(snmp_ultimo_controllo__lt=stale)
    return Q(
        Exists(DispositivoSNMP.objects.filter(bad_snmp, asset=OuterRef("pk"), attivo=True))
        | Exists(Macchina.objects.filter(bad_snmp, asset=OuterRef("pk"), attiva=True))
        | Exists(SecurityAlert.objects.filter(event__asset__hub_asset=OuterRef("pk"), status__in=ACTIVE_ALERT_STATUSES))
    )


def apply_coverage_filter(queryset, value: str):
    try:
        if value == "scoperti":
            return queryset.exclude(monitored_q())
        if value == "monitorati":
            return queryset.filter(monitored_q())
        if value == "problemi":
            return queryset.filter(problems_q())
    except DatabaseError:
        return queryset
    return queryset


def _snmp_row(state: str, last, now) -> dict:
    silent = last is None or now - last > SILENT_AFTER
    if state == "ERROR":
        level, label = "bad", "SNMP in errore"
    elif last is None:
        level, label = "warn", "SNMP mai interrogato"
    elif silent:
        level, label = "warn", f"SNMP muto da {(now - last).days} gg"
    elif state == "WARNING":
        level, label = "warn", "SNMP con avvisi"
    else:
        level, label = "ok", "SNMP regolare"
    return {"level": level, "label": label, "last": last}


def coverage_for_assets(request, asset_ids) -> dict[int, dict]:
    """``{asset_id: {"snmp": {...}|None, "soc": {...}|None, "monitored": bool}}`` per una pagina."""
    asset_ids = [pk for pk in asset_ids if pk]
    out = {pk: {"snmp": None, "soc": None, "monitored": False} for pk in asset_ids}
    if not asset_ids:
        return out
    now = timezone.now()
    rank = {"ok": 0, "warn": 1, "bad": 2}

    try:
        from contatori.models import DispositivoSNMP, Macchina

        show_snmp = can_view_snmp(request)
        rows = list(DispositivoSNMP.objects.filter(asset_id__in=asset_ids, attivo=True)
                    .values_list("asset_id", "snmp_stato", "snmp_ultimo_controllo"))
        rows += list(Macchina.objects.filter(asset_id__in=asset_ids, attiva=True)
                     .values_list("asset_id", "snmp_stato", "snmp_ultimo_controllo"))
        for asset_id, state, last in rows:
            out[asset_id]["monitored"] = True
            if not show_snmp:
                continue
            row = _snmp_row(state, last, now)
            current = out[asset_id]["snmp"]
            # Piu' dispositivi sullo stesso asset: conta il peggiore.
            if current is None or rank[row["level"]] > rank[current["level"]]:
                out[asset_id]["snmp"] = row
    except DatabaseError:
        pass

    try:
        from security.models import SecurityAlert, SecurityAsset
        from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

        linked = dict(
            SecurityAsset.objects.filter(hub_asset_id__in=asset_ids)
            .values("hub_asset_id").annotate(last=Max("signals__occurred_at"))
            .values_list("hub_asset_id", "last")
        )
        alerts = dict(
            SecurityAlert.objects.filter(event__asset__hub_asset_id__in=asset_ids, status__in=ACTIVE_ALERT_STATUSES)
            .values("event__asset__hub_asset_id").annotate(n=Count("id"))
            .values_list("event__asset__hub_asset_id", "n")
        )
        show_soc = can_view_soc(request)
        for asset_id, last in linked.items():
            out[asset_id]["monitored"] = True
            if not show_soc:
                continue
            open_alerts = alerts.get(asset_id, 0)
            out[asset_id]["soc"] = {
                "level": "bad" if open_alerts else "ok",
                "label": f"SOC: {open_alerts} alert aperti" if open_alerts else "SOC collegato",
                "open_alerts": open_alerts,
                "last": last,
            }
    except DatabaseError:
        pass
    return out


def coverage_totals(queryset) -> dict[str, int]:
    """Conteggi per i filtri rapidi dell'inventario IT."""
    try:
        total = queryset.count()
        monitored = queryset.filter(monitored_q()).count()
        problems = queryset.filter(problems_q()).count()
    except DatabaseError:
        return {}
    return {"monitorati": monitored, "scoperti": total - monitored, "problemi": problems}
