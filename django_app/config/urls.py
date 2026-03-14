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
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from tasks import views as task_views

urlpatterns = [
    # Setup wizard — deve essere prima di tutto per intercettare il primo avvio
    path("setup/", include(("setup_wizard.urls", "setup_wizard"), namespace="setup_wizard")),
    # Compat alias un-namespaced (evita NoReverseMatch su vecchi riferimenti "project_list"/"project_gantt")
    path("tasks/projects/", task_views.project_list, name="project_list"),
    path("tasks/projects/<int:project_id>/gantt/", task_views.project_gantt, name="project_gantt"),
    path("", include("dashboard.urls")),
    path("", include("assenze.urls")),
    path("", include("anomalie.urls")),
    path("", include(("assets.urls", "assets"), namespace="assets")),
    path("", include(("tasks.urls", "tasks"), namespace="tasks")),
    path("notizie/", include("notizie.urls")),
    path("admin-portale/", include(("admin_portale.urls", "admin_portale"), namespace="admin_portale")),
    path("admin-portale/hub/", include(("hub_tools.urls", "hub_tools"), namespace="hub_tools")),
    path("anagrafica/", include(("anagrafica.urls", "anagrafica"), namespace="anagrafica")),
    path("", include(("timbri.urls", "timbri"), namespace="timbri")),
    path("tickets/",    include(("tickets.urls",    "tickets"),    namespace="tickets")),
    path("", include(("rentri.urls", "rentri"), namespace="rentri")),
    path("", include(("planimetria.urls", "planimetria"), namespace="planimetria")),
    path("", include("core.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
