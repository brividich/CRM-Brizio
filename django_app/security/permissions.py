from django.db import DatabaseError
from rest_framework.permissions import BasePermission

from security.services.configuration import can_manage_security_config

# Stesso permesso canonico ACL v2 che governa /soc/ nel menu e nel middleware.
SECURITY_VIEW_PERMISSION_CODE = "security.dashboard.view"


def can_view_security_center(user):
    """Cancello di lettura del Security Center dentro le view.

    Prima riconosceva solo `is_staff` e i permessi Django del progetto standalone
    Security-Center-AI: nell'HUB i diritti si danno via ACL v2, quindi un
    amministratore del portale superava l'`ACLMiddleware` e poi la view gli
    rispondeva «Accesso negato» (Inbox, Caselle mail, documenti della guida).
    Ora chiede all'ACL v2 lo stesso permesso del middleware; restano validi i
    titoli storici. Fail-closed: se l'ACL non e' interrogabile, si nega.
    """
    if not (user and getattr(user, "is_authenticated", False)):
        return False
    if (
        user.is_staff
        or user.has_perm("security.manage_security_configuration")
        or user.has_perm("security.view_securitycenter")
        or user.has_perm("security.view_securitysource")
        or user.has_perm("security.view_securityreport")
    ):
        return True
    if can_manage_security_config(user):
        return True

    from core.acl_v2 import evaluate_permission_code_access
    from core.legacy_utils import get_legacy_user

    try:
        decision = evaluate_permission_code_access(
            permission_code=SECURITY_VIEW_PERMISSION_CODE,
            legacy_user=get_legacy_user(user),
            django_user=user,
        )
    except DatabaseError:
        return False
    return bool(decision.get("allowed"))


class CanViewSecurityCenter(BasePermission):
    def has_permission(self, request, view):
        return can_view_security_center(request.user)


class CanManageSecurityCenter(BasePermission):
    def has_permission(self, request, view):
        return can_manage_security_config(request.user)
