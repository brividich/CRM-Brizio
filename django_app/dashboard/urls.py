from django.urls import path

from . import htmx_views, views, views_bacheca, views_mie_attivita, views_scadenze


urlpatterns = [
    path("dashboard", views.dashboard_home, name="dashboard_home"),
    path("dashboard", views.dashboard_home, name="dashboard"),
    path("mie-attivita", views_mie_attivita.mie_attivita, name="mie_attivita"),
    path("scadenze", views_scadenze.scadenze_globali, name="scadenze_globali"),
    # Compat route: le richieste assenze vivono nel modulo assenze.
    path("richieste", views.richieste, name="richieste"),
    path("anomalie-menu", views.anomalie_menu, name="anomalie_menu"),
    path("api/my-dashboard-toggle", views.api_my_dashboard_toggle, name="api_my_dashboard_toggle"),
    path("api/my-dashboard-layout", views.api_my_dashboard_layout, name="api_my_dashboard_layout"),
    path("api/debug-ui-meta", views.api_debug_ui_meta, name="api_debug_ui_meta"),
    # Employee infographic board
    path("scheda-dipendente", views.employee_board, name="employee_board"),
    path("api/employee-board/layout", views.api_employee_board_layout, name="api_employee_board_layout"),
    path("api/employee-board/widget-config", views.api_employee_board_widget_config, name="api_employee_board_widget_config"),
    path("api/employee-board/reset", views.api_employee_board_reset, name="api_employee_board_reset"),
    path("api/employee-board/admin-template", views.api_employee_board_admin_template, name="api_employee_board_admin_template"),
    path("api/employee-board/data", views.api_employee_board_data, name="api_employee_board_data"),
    path("api/employee-board/widget/<str:widget_id>/partial/", htmx_views.widget_partial, name="widget_partial"),
    path("scheda-dipendente/pdf", views.employee_board_pdf, name="employee_board_pdf"),
    path("hub-preview/", views.dashboard_hub_preview, name="dashboard_hub_preview"),
    # Bacheca "Documenti & Collegamenti"
    path("bacheca/", views_bacheca.bacheca, name="bacheca"),
    path("bacheca/doc/<int:pk>/", views_bacheca.hub_link_download, name="hub_link_download"),
]
