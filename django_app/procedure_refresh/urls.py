from django.urls import path

from . import views

app_name = "procedure_refresh"

urlpatterns = [
    # ── User views ──────────────────────────────────────────────────────────
    path("", views.my_assignments, name="my_assignments"),
    path("<int:pk>/", views.assignment_detail, name="assignment_detail"),

    # ── Admin — dashboard ───────────────────────────────────────────────────
    path("admin/", views.admin_dashboard, name="admin_dashboard"),

    # ── Admin — documenti ───────────────────────────────────────────────────
    path("admin/documenti/", views.document_list, name="document_list"),
    path("admin/documenti/nuovo/", views.document_form, name="document_create"),
    path("admin/documenti/<int:pk>/", views.document_form, name="document_edit"),
    path("admin/documenti/<int:pk>/elimina/", views.document_delete, name="document_delete"),

    # ── Admin — revisioni ───────────────────────────────────────────────────
    path("admin/documenti/<int:doc_pk>/revisioni/nuova/", views.revision_form, name="revision_create"),
    path("admin/documenti/<int:doc_pk>/revisioni/<int:pk>/", views.revision_form, name="revision_edit"),

    # ── Admin — campagne ────────────────────────────────────────────────────
    path("admin/campagne/", views.campaign_list, name="campaign_list"),
    path("admin/campagne/nuova/", views.campaign_form, name="campaign_create"),
    path("admin/campagne/<int:pk>/", views.campaign_detail, name="campaign_detail"),
    path("admin/campagne/<int:pk>/modifica/", views.campaign_form, name="campaign_edit"),
    path("admin/campagne/<int:pk>/pubblica/", views.campaign_publish, name="campaign_publish"),
    path("admin/campagne/<int:pk>/chiudi/", views.campaign_close, name="campaign_close"),
    path("admin/campagne/<int:pk>/aggiungi-documento/", views.campaign_add_document, name="campaign_add_document"),
    path("admin/campagne/<int:pk>/rimuovi-documento/<int:cd_pk>/", views.campaign_remove_document, name="campaign_remove_document"),
    path("admin/campagne/<int:pk>/assegna/", views.assign_users, name="assign_users"),
    path("admin/assegnazioni/<int:pk>/annulla/", views.cancel_assignment, name="cancel_assignment"),

    # ── API ─────────────────────────────────────────────────────────────────
    path("api/parse-sharepoint-url/", views.api_parse_sharepoint_url, name="api_parse_sharepoint_url"),

    # ── Admin — report ──────────────────────────────────────────────────────
    path("admin/report/utente/", views.report_user, name="report_user"),
    path("admin/report/documento/", views.report_document, name="report_document"),
    path("admin/report/campagna/", views.report_campaign, name="report_campaign"),
    path("admin/export-csv/", views.export_csv, name="export_csv"),
]
