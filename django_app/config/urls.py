"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles import views as staticfiles_views
from django.urls import include, path
from django.urls import re_path
from django.views.static import serve as media_serve
from monitoring import views as monitoring_views
from tasks import views as task_views

urlpatterns = [
    # Liveness/readiness — root, prima di setup_wizard cosi' restano disponibili
    # anche durante un primo avvio non finalizzato. IP allowlist via settings.
    path("healthz", monitoring_views.healthz, name="healthz"),
    path("readyz", monitoring_views.readyz, name="readyz"),
    # Setup wizard — deve essere prima di tutto per intercettare il primo avvio
    path("setup/", include(("setup_wizard.urls", "setup_wizard"), namespace="setup_wizard")),
    # Compat alias un-namespaced (evita NoReverseMatch su vecchi riferimenti "project_list"/"project_gantt")
    path("tasks/projects/", task_views.project_list, name="project_list"),
    path("tasks/projects/<int:project_id>/gantt/", task_views.project_gantt, name="project_gantt"),
    path("", include("dashboard.urls")),
    path("hub/home/", include(("dashboard.urls_home_portale", "home_portale"), namespace="home_portale")),
    path("assistente-ai/", include(("ai_assistant.urls", "ai_assistant"), namespace="ai_assistant")),
    path("", include("assenze.urls")),
    path("", include("anomalie.urls")),
    path("", include(("assets.urls", "assets"), namespace="assets")),
    path("", include(("attrezzature.urls", "attrezzature"), namespace="attrezzature")),
    path("", include(("tasks.urls", "tasks"), namespace="tasks")),
    path("carichi-macchina/", include(("gestione_carichi_macchina.urls", "gestione_carichi_macchina"), namespace="gestione_carichi_macchina")),
    path("gestione-specifiche/", include(("gestione_specifiche.urls", "gestione_specifiche"), namespace="gestione_specifiche")),
    path("suggestion-corner/", include(("suggestion_corner.urls", "suggestion_corner"), namespace="suggestion_corner")),
    path("notizie/", include("notizie.urls")),
    path(
        "admin-portale/monitoring/",
        include(("monitoring.admin_urls", "monitoring_admin"), namespace="monitoring_admin"),
    ),
    path("admin-portale/", include(("admin_portale.urls", "admin_portale"), namespace="admin_portale")),
    path("admin-portale/hub/", include(("hub_tools.urls", "hub_tools"), namespace="hub_tools")),
    path("automazioni/", include(("automazioni.urls", "automazioni"), namespace="automazioni")),
    # Approval proxy — endpoint GET per Entra Application Proxy.
    # Pubblicare SOLO /approval-actions/* nell'Application Proxy (non /automazioni/).
    path("approval-actions/", include(("automazioni.approval_proxy_urls", "approval_proxy"), namespace="approval_proxy")),
    path("monitoring/", include(("monitoring.urls", "monitoring"), namespace="monitoring")),
    path("anagrafica/", include(("anagrafica.urls", "anagrafica"), namespace="anagrafica")),
    path("fornitori/", include(("fornitori.urls", "fornitori"), namespace="fornitori")),
    path("", include(("timbri.urls", "timbri"), namespace="timbri")),
    path("tickets/",    include(("tickets.urls",    "tickets"),    namespace="tickets")),
    path("diario-preposto/", include(("diario_preposto.urls", "diario_preposto"), namespace="diario_preposto")),
    path("rilevazione-incidenti/", include(("rilevazione_incidenti.urls", "rilevazione_incidenti"), namespace="rilevazione_incidenti")),
    path("", include("rentri.urls")),
    path("", include(("planimetria.urls", "planimetria"), namespace="planimetria")),
    path("dpi/", include(("dpi.urls", "dpi"), namespace="dpi")),
    path("procedure-refresh/", include(("procedure_refresh.urls", "procedure_refresh"), namespace="procedure_refresh")),
    path("schede-sicurezza/", include(("schede_sicurezza.urls", "schede_sicurezza"), namespace="schede_sicurezza")),
    path("contatori/", include(("contatori.urls", "contatori"), namespace="contatori")),
    path("soc/", include(("security.urls_hub", "security"), namespace="security")),
    path("2fa/", include(("twofa.urls", "twofa"), namespace="twofa")),
    path("", include("core.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG or getattr(settings, "DEV_SERVE_STATIC_AND_MEDIA", False):
    urlpatterns += [
        re_path(
            rf"^{settings.STATIC_URL.lstrip('/')}(?P<path>.*)$",
            staticfiles_views.serve,
            {"insecure": True},
        ),
        re_path(
            rf"^{settings.MEDIA_URL.lstrip('/')}(?P<path>.*)$",
            media_serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
