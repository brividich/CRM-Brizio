"""«I miei rilievi»: l'auditato vede solo i rilievi che lo riguardano (prompt 08, sicurezza per ruolo)."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from .acl_bootstrap import PERM_AUDIT_MIEI, PERM_AUDIT_VIEW
from .models import AuditEsito, AuditPersona
from .services.cruscotto import RILIEVI
from .views import _has_perm, _nega


def rilievi_utente(user):
    """Rilievi di audit con rapporto firmato in cui l'utente è auditato, responsabile del processo
    o responsabile dell'azione. Le bozze in compilazione non sono visibili."""
    miei_audit = AuditPersona.objects.filter(
        user=user, ruolo__in=[AuditPersona.RUOLO_AUDITATO, AuditPersona.RUOLO_PROCESSO],
    ).values("audit_id")
    return (AuditEsito.objects.filter(esito__in=RILIEVI, audit__rapporto_firmato_auditor_il__isnull=False)
            .filter(Q(responsabile_azione=user) | Q(audit_id__in=miei_audit))
            .select_related("audit", "processo", "ofi", "ofi__car_procedurale", "responsabile_azione")
            .order_by("-audit__data_inizio", "pk"))


@login_required
def miei_rilievi(request):
    if not (_has_perm(request, PERM_AUDIT_MIEI) or _has_perm(request, PERM_AUDIT_VIEW)):
        return _nega(request, "Non puoi consultare i rilievi di audit.")
    righe = []
    for esito in rilievi_utente(request.user):
        car = getattr(esito.ofi, "car_procedurale", None) if esito.ofi_id else None
        righe.append({
            "esito": esito,
            "puo_car": bool(esito.ofi_id and (esito.responsabile_azione_id == request.user.pk
                                              or (car is not None and car.responsabile_id == request.user.pk))),
            "car": car,
        })
    return render(request, "sistema_gestione/pages/audit_miei_rilievi.html", {
        "page_title": "I miei rilievi", "righe": righe, "consulta_audit": _has_perm(request, PERM_AUDIT_VIEW),
    })
