"""Sezioni «Impatto sugli asset» (alert/ticket CVE) e «Vulnerabilità» (pagina asset HUB)."""
from django import template

from security.permissions import can_view_security_center

register = template.Library()


@register.inclusion_tag("security/partials/cve_impact_summary.html", takes_context=True)
def cve_impact_panel(context, cve_id):
    from security.models import SecurityCveImpact, SecurityCveRecord
    from security.services.cve_impact import summary

    request = context.get("request")
    cve_id = str(cve_id or "").strip().upper()
    if not cve_id or not can_view_security_center(getattr(request, "user", None)):
        return {"record": None, "hide": True}
    record = SecurityCveRecord.objects.filter(cve_id=cve_id).first()
    if record is None:
        return {"record": None}
    impacts = list(record.impacts.exclude(outcome=SecurityCveImpact.NOT_IMPACTED).order_by("outcome", "host")[:10])
    return {"record": record, "summary": summary(record), "impacts": impacts}


@register.simple_tag
def soc_ai_web():
    """True se in Impostazioni è permesso all'AI di consultare le fonti web: mostra la casella «Cerca anche sul web»."""
    from security.services import ricerca_web

    try:
        return ricerca_web.attiva()
    except Exception:  # noqa: BLE001 - impostazioni non leggibili: casella nascosta
        return False
