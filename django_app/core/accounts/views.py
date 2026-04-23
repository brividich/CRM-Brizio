from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from werkzeug.security import generate_password_hash

from core.accounts.forms import LegacyAuthenticationForm, LegacyChangePasswordForm
from core.accounts.redirects import get_safe_redirect_target
from core.branding import get_portal_branding
from core.legacy_models import UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_auth_enabled


def _is_smartphone_request(request) -> bool:
    layout_hint = (request.GET.get("layout") or "").strip().lower()
    if layout_hint == "mobile":
        return True
    if layout_hint == "desktop":
        return False

    user_agent = (request.META.get("HTTP_USER_AGENT") or "").lower()
    if not user_agent:
        return False

    smartphone_tokens = (
        "iphone",
        "ipod",
        "windows phone",
        "blackberry",
        "bb10",
        "opera mini",
        "mobile safari",
    )
    if any(token in user_agent for token in smartphone_tokens):
        return True

    # Android tablets usually omit "mobile"; treat Android + mobile as smartphone.
    return "android" in user_agent and "mobile" in user_agent


@method_decorator(ensure_csrf_cookie, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class LegacyLoginView(LoginView):
    authentication_form = LegacyAuthenticationForm
    template_name = "core/pages/login.html"
    redirect_authenticated_user = True

    def get_template_names(self):
        if _is_smartphone_request(self.request):
            return ["core/pages/login_mobile.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.conf import settings
        from core.models import LoginBanner, SiteConfig

        portal_branding = get_portal_branding()
        login_config = SiteConfig.get_many(
            {
                "login_titolo":      portal_branding.portal_name,
                "login_sottotitolo": portal_branding.portal_subtitle or "Area autenticata",
                "login_sso_label":   "Accedi con credenziali Windows",
                "login_sso_visibile": "1",
                "login_logo_url":    portal_branding.brand_logo_full,
            }
        )

        ctx["ldap_enabled"]       = getattr(settings, "LDAP_ENABLED", False)
        ctx["login_titolo"]       = login_config["login_titolo"]
        ctx["login_sottotitolo"]  = login_config["login_sottotitolo"]
        ctx["login_sso_label"]    = login_config["login_sso_label"]
        ctx["login_sso_visibile"] = login_config["login_sso_visibile"] == "1"
        ctx["login_logo_url"]     = login_config["login_logo_url"]
        ctx["login_banners"]      = list(LoginBanner.objects.filter(is_active=True))
        return ctx

    def dispatch(self, request, *args, **kwargs):
        reason = (request.GET.get("reason") or "").strip().lower()
        if reason == "expired":
            messages.warning(request, "Sessione scaduta per inattivita. Effettua di nuovo il login.")
        elif reason == "logout":
            messages.info(request, "Logout eseguito.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)  # crea la sessione autenticata
        legacy_user = get_legacy_user(self.request.user)
        if legacy_auth_enabled() and legacy_user and bool(legacy_user.deve_cambiare_password):
            return redirect("cambia_password")
        return response

    def get_success_url(self):
        raw_next = (
            self.request.POST.get(self.redirect_field_name)
            or self.request.GET.get(self.redirect_field_name)
            or ""
        ).strip()
        if raw_next:
            return get_safe_redirect_target(self.request, raw_next) or reverse("dashboard_home")
        try:
            # Gli amministratori vanno sempre alla dashboard, indipendentemente dal redirect configurato
            if not self.request.user.is_superuser:
                legacy_user = get_legacy_user(self.request.user)
                if not (legacy_user and is_legacy_admin(legacy_user)):
                    from core.models import SiteConfig
                    redirect_target = SiteConfig.objects.filter(
                        key="module_login_redirect_target"
                    ).values_list("value", flat=True).first()
                    if redirect_target:
                        from hub_tools.views import MODULE_DEFS
                        module = next((m for m in MODULE_DEFS if m["key"] == redirect_target), None)
                        if module and module.get("home_url"):
                            return module["home_url"]
        except Exception:
            pass
        return reverse("dashboard_home")


@login_required(login_url=reverse_lazy("login"))
def cambia_password(request):
    legacy_user = get_legacy_user(request.user)
    if legacy_auth_enabled() and legacy_user is None:
        messages.error(request, "Profilo legacy non associato.")
        return redirect("dashboard_home")

    if request.method == "POST":
        form = LegacyChangePasswordForm(request.POST)
        if form.is_valid():
            if legacy_user is not None:
                legacy_user.password = generate_password_hash(form.cleaned_data["nuova_password"])
                legacy_user.deve_cambiare_password = False
                legacy_user.save(update_fields=["password", "deve_cambiare_password"])
            try:
                from core.audit import log_action
                log_action(request, "cambio_password", "core")
            except Exception:
                pass
            messages.success(request, "Password aggiornata con successo.")
            return redirect("dashboard_home")
    else:
        form = LegacyChangePasswordForm()

    return render(
        request,
        "core/pages/cambia_password.html",
        {
            "form": form,
            "page_title": "Cambia password",
        },
    )


def logout_view(request):
    logout(request)
    return redirect(f"{reverse('login')}?reason=logout")
