"""Gestione (scritture) separata dalla consultazione nel modulo Contatori.

La route e' gia' protetta dall'ACL v2 (binding in migrazione 0025); qui si
ricontrolla `contatori.gestione.manage` dentro le view, perche' alcune pagine
(es. Stampanti MFC) uniscono consultazione e scrittura sulla stessa route.
"""
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

PERM_GESTIONE = "contatori.gestione.manage"


def puo_gestire(request) -> bool:
    """Esito memorizzato sulla request: i template lo chiedono piu' volte."""
    if not hasattr(request, "_contatori_gestione"):
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        try:
            legacy_user = get_legacy_user(request.user)
        except Exception:
            legacy_user = None
        request._contatori_gestione = bool(evaluate_permission_code_access(
            permission_code=PERM_GESTIONE, legacy_user=legacy_user, django_user=request.user,
        ).get("allowed"))
    return request._contatori_gestione


def nega(request):
    messages.error(request, "Non hai il permesso di modificare i dati dei contatori: "
                            "chiedi l'abilitazione «Contatori - Gestione».")
    return redirect("contatori:dashboard")


def richiede_gestione(view=None, *, solo_post=False):
    """Decoratore: blocca la view (o solo i POST) a chi non ha la gestione."""
    def decora(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if (not solo_post or request.method == "POST") and not puo_gestire(request):
                return nega(request)
            return func(request, *args, **kwargs)
        return wrapper
    return decora(view) if view else decora
