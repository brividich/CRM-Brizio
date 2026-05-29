from django.contrib import admin

from .models import TwoFactorChallenge, TwoFactorPolicy, UserTwoFactor


@admin.register(TwoFactorPolicy)
class TwoFactorPolicyAdmin(admin.ModelAdmin):
    list_display = ("__str__", "enabled", "when_required", "updated_at")


@admin.register(UserTwoFactor)
class UserTwoFactorAdmin(admin.ModelAdmin):
    list_display = ("user", "method", "totp_confirmed", "is_active", "force_setup", "last_used_at")
    list_filter = ("method", "is_active", "totp_confirmed")
    search_fields = ("user__username",)
    exclude = ("totp_secret_enc",)


@admin.register(TwoFactorChallenge)
class TwoFactorChallengeAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "used", "attempts")
    list_filter = ("used",)
    search_fields = ("user__username",)
