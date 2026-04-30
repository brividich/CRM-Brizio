"""
Partial views HTMX per il designer visuale automazioni.
Gestiscono aggiunta e rimozione dinamica di azioni senza ricarica intera pagina.
"""
from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods

from admin_portale.decorators import legacy_admin_required

from .forms import AutomationActionForm
from .models import AutomationRule
from .views import _get_default_source_code


@legacy_admin_required
@require_http_methods(["POST"])
def add_azione_partial(request, rule_id: int):
    """
    HTMX partial — aggiunge una nuova azione vuota al designer.
    Ritorna l'HTML della card azione da appendere al container #actions-section-body.
    """
    if not getattr(request, "htmx", None):
        return redirect("admin_portale:automazioni_rule_designer", rule_id=rule_id)

    rule = get_object_or_404(AutomationRule, pk=rule_id)
    source_code = str(request.POST.get("source_code") or "").strip() or rule.source_code or _get_default_source_code()

    # Indice del nuovo form: il client invia il TOTAL_FORMS corrente come next index
    try:
        action_index = int(request.POST.get("actions-TOTAL_FORMS", 0))
    except (TypeError, ValueError):
        action_index = rule.actions.count()

    form = AutomationActionForm(
        prefix=f"actions-{action_index}",
        source_code=source_code,
    )

    html = render_to_string(
        "automazioni/partials/action_card_empty.html",
        {
            "form": form,
            "action_index": action_index,
            "rule": rule,
            "source_code": source_code,
        },
        request=request,
    )
    response = HttpResponse(html)
    # Header custom usato dal JS per aggiornare il management form
    response["HX-Trigger-After-Swap"] = f'{{"htmxActionAdded":{{"index":{action_index}}}}}'
    return response


@legacy_admin_required
@require_http_methods(["POST"])
def remove_azione_partial(request, rule_id: int):
    """
    HTMX partial — rimuove una azione dal designer.
    Ritorna risposta vuota: HTMX con hx-swap="outerHTML" elimina la card dal DOM.
    Per azioni già salvate in DB il frontend imposta il campo DELETE prima di chiamare.
    """
    if not getattr(request, "htmx", None):
        return redirect("admin_portale:automazioni_rule_designer", rule_id=rule_id)

    # Nessuna modifica al DB: la rimozione fisica avviene solo al save del formset principale.
    return HttpResponse("", status=200)
