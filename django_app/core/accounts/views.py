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
from core.legacy_models import UtenteLegacy
from core.legacy_utils import get_legacy_user, legacy_auth_enabled


@method_decorator(ensure_csrf_cookie, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class LegacyLoginView(LoginView):
    authentication_form = LegacyAuthenticationForm
    template_name = "core/pages/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.conf import settings
        from core.models import LoginBanner, SiteConfig

        login_config = SiteConfig.get_many(
            {
                "login_titolo":      "Portale Applicativo",
                "login_sottotitolo": "Example Organization",
                "login_sso_label":   "Accedi con credenziali Windows",
                "login_sso_visibile": "1",
                "login_logo_url":    "",
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
        # Salva la password in sessione per il relay SSO (es. GuestPortal).
        # Viene cancellata automaticamente al logout insieme all'intera sessione.
        raw_password = form.cleaned_data.get("password", "")
        response = super().form_valid(form)  # crea la sessione autenticata
        if raw_password:
            self.request.session["_sso_relay_pwd"] = raw_password
        legacy_user = get_legacy_user(self.request.user)
        if legacy_auth_enabled() and legacy_user and bool(legacy_user.deve_cambiare_password):
            return redirect("cambia_password")
        return response

    def get_success_url(self):
        next_url = self.get_redirect_url()
        if next_url:
            return next_url
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
