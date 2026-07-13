from rest_framework.permissions import BasePermission

from security.services.configuration import can_manage_security_config


def can_view_security_center(user):
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_staff
            or user.has_perm("security.manage_security_configuration")
            or user.has_perm("security.view_securitycenter")
            or user.has_perm("security.view_securitysource")
            or user.has_perm("security.view_securityreport")
        )
    )


class CanViewSecurityCenter(BasePermission):
    def has_permission(self, request, view):
        return can_view_security_center(request.user)


class CanManageSecurityCenter(BasePermission):
    def has_permission(self, request, view):
        return can_manage_security_config(request.user)
