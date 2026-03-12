from django.urls import path

from . import views


urlpatterns = [
    path("dashboard", views.dashboard_home, name="dashboard_home"),
    path("dashboard", views.dashboard_home, name="dashboard"),
    path("richieste", views.richieste, name="richieste"),
    path("anomalie-menu", views.anomalie_menu, name="anomalie_menu"),
    path("api/my-dashboard-toggle", views.api_my_dashboard_toggle, name="api_my_dashboard_toggle"),
    path("api/my-dashboard-layout", views.api_my_dashboard_layout, name="api_my_dashboard_layout"),
    path("api/debug-ui-meta", views.api_debug_ui_meta, name="api_debug_ui_meta"),
    # Employee infographic board
    path("scheda-dipendente", views.employee_board, name="employee_board"),
    path("api/employee-board/layout", views.api_employee_board_layout, name="api_employee_board_layout"),
    path("api/employee-board/widget-config", views.api_employee_board_widget_config, name="api_employee_board_widget_config"),
    path("api/employee-board/data", views.api_employee_board_data, name="api_employee_board_data"),
    path("scheda-dipendente/pdf", views.employee_board_pdf, name="employee_board_pdf"),
]
