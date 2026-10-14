"""Costi registrati su un asset negli ultimi 12 mesi, da tutte le fonti del portale.

Somma solo importi gia' scritti altrove, senza stime:

- rinnovi delle licenze software assegnate all'asset (``SoftwareLicenseRenewal.cost_eur``);
- interventi chiusi (``WorkOrder``: costo totale, oppure manodopera + materiali);
- adempimenti amministrativi completati (``AssetAdministrativeDeadlineCompletion.cost_eur``).

Il canone dei contratti di assistenza attivi si mostra a parte: non ha un periodo
esplicito, sommarlo darebbe un totale sbagliato. Per le MFC le fatture Copylab non
registrano importi: si mostrano le pagine fatturate nello stesso periodo.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

GIORNI = 365


def costi_asset(asset, oggi=None) -> dict:
    from assets.models import (
        AssetAdministrativeDeadlineCompletion,
        AssistanceContract,
        SoftwareLicenseRenewal,
        WorkOrder,
    )

    oggi = oggi or timezone.localdate()
    dal = oggi - timedelta(days=GIORNI)

    rinnovi = SoftwareLicenseRenewal.objects.filter(
        license__asset=asset, renewed_on__gte=dal, cost_eur__isnull=False)
    licenze = rinnovi.aggregate(t=Sum("cost_eur"))["t"] or Decimal("0")

    interventi, n_interventi = Decimal("0"), 0
    for wo in WorkOrder.objects.filter(asset=asset, status=WorkOrder.STATUS_DONE, closed_at__date__gte=dal).only(
            "cost_eur", "labor_cost_eur", "materials_cost_eur"):
        costo = wo.resolved_total_cost_eur
        if costo is not None:
            interventi += costo
            n_interventi += 1

    completamenti = AssetAdministrativeDeadlineCompletion.objects.filter(
        deadline__asset=asset, completed_on__gte=dal, cost_eur__isnull=False)
    adempimenti = completamenti.aggregate(t=Sum("cost_eur"))["t"] or Decimal("0")

    contratti = list(AssistanceContract.objects.filter(
        asset=asset, is_active=True, periodic_cost_eur__isnull=False).select_related("supplier")[:5])

    voci = [
        {"label": "Rinnovi licenze", "importo": licenze, "n": rinnovi.count()},
        {"label": "Interventi chiusi", "importo": interventi, "n": n_interventi},
        {"label": "Adempimenti", "importo": adempimenti, "n": completamenti.count()},
    ]
    return {
        "dal": dal,
        "al": oggi,
        "totale": licenze + interventi + adempimenti,
        "voci": voci,
        "vuoto": not any(v["n"] for v in voci) and not contratti,
        "contratti": contratti,
        "pagine_fatturate": _pagine_fatturate(asset, dal),
    }


def _pagine_fatturate(asset, dal):
    """Pagine nelle fatture Copylab del periodo per i contratti delle MFC collegate, o ``None``."""
    try:
        from contatori.models import Macchina, RigaFattura
    except ImportError:  # pragma: no cover - modulo non installato
        return None
    contratti = [c for c in Macchina.objects.filter(asset=asset).values_list("contratto", flat=True) if c]
    if not contratti:
        return None
    t = RigaFattura.objects.filter(contratto__in=contratti, fattura__data__gte=dal).aggregate(
        bn=Sum("a4_bn"), bn3=Sum("a3_bn"), col=Sum("a4_col"), col3=Sum("a3_col"))
    totale = sum(v or 0 for v in t.values())
    return {"totale": totale, "contratti": contratti} if totale else None
