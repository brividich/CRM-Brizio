"""Cruscotto degli audit interni ed export dei rilievi (prompt 08, obiettivo E)."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.audit import log_action
from core.excel_export import make_xlsx_response

from .acl_bootstrap import PERM_AUDIT_VIEW
from .models import Audit, AuditEsito
from .services import cruscotto as service
from .views import MODULE, _has_perm, _nega


def _anno(request) -> int:
    oggi = timezone.localdate()
    try:
        anno = int(request.GET.get("anno") or oggi.year)
        return anno if 2000 <= anno <= 2100 else oggi.year
    except (TypeError, ValueError):
        return oggi.year


@login_required
def cruscotto(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non puoi consultare il cruscotto degli audit.")
    dati = service.cruscotto(_anno(request))
    return render(request, "sistema_gestione/pages/audit_cruscotto.html", {"page_title": "Cruscotto audit", "c": dati})


@login_required
def rilievi_export(request):
    """Rilievi in xlsx (celle sempre testo, nessuna formula viva): per anno o per un audit."""
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non puoi esportare i rilievi.")
    audit_pk = request.GET.get("audit")
    if audit_pk and str(audit_pk).isdigit():
        audit = get_object_or_404(Audit, pk=int(audit_pk))
        esiti = (AuditEsito.objects.filter(audit=audit, esito__in=service.RILIEVI)
                 .select_related("audit", "processo", "ofi", "ofi__car_procedurale", "responsabile_azione"))
        titolo, filtri, nome = f"Rilievi dell'audit {audit.numero}", f"Audit {audit.numero}", f"rilievi_{audit.numero}"
    else:
        anno = _anno(request)
        esiti = service.rilievi_anno(anno)
        titolo, filtri, nome = f"Rilievi degli audit interni {anno}", f"Anno {anno}", f"rilievi_audit_{anno}"
    righe = service.righe_rilievi(esiti)
    log_action(request, "audit_rilievi_export", MODULE, {"filtri": filtri, "righe": len(righe)})
    return make_xlsx_response(
        filename=f"{nome}.xlsx", columns=service.COLONNE_RILIEVI, rows=righe, sheet_title="Rilievi",
        title=titolo, subtitle=f"Estratto il {timezone.localtime():%d/%m/%Y %H:%M}", filters_label=filtri,
    )
