from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("assets/", views.asset_list, name="asset_list"),
    path("assets/work-machines/", views.work_machine_list, name="work_machine_list"),
    path("assets/work-machines/dashboard/", views.work_machine_dashboard, name="work_machine_dashboard"),
    path("assets/work-machines/map/", views.plant_layout_map, name="plant_layout_map"),
    path("assets/work-machines/map/editor/", views.plant_layout_editor, name="plant_layout_editor"),
    path("assets/work-machines/new/", views.work_machine_create, name="work_machine_create"),
    path("assets/work-machines/edit/<int:id>/", views.work_machine_edit, name="work_machine_edit"),
    path("assets/view/", views.asset_detail, name="asset_view"),
    path("assets/view/<int:id>/", views.asset_detail, name="asset_view"),
    path("assets/view-layout/", views.asset_detail_layout_admin, name="asset_detail_layout_admin"),
    path("assets/view/<int:id>/report.pdf", views.asset_report_pdf, name="asset_report_pdf"),
    path("assets/view/<int:id>/qr-label/", views.asset_qr_label, name="asset_qr_label"),
    path("assets/labels/", views.asset_label_designer, name="asset_label_designer"),
    path("assets/new/", views.asset_create, name="asset_create"),
    path("assets/edit/", views.asset_edit, name="asset_edit"),
    path("assets/edit/<int:id>/", views.asset_edit, name="asset_edit"),
    path("assets/assign/", views.assignment_set, name="asset_assign"),
    path("assets/assign/<int:id>/", views.assignment_set, name="asset_assign"),
    path("assets/workorders/", views.workorder_list, name="wo_list"),
    path("assets/workorders/new/", views.workorder_create, name="wo_create"),
    path("assets/workorders/new/<int:id>/", views.workorder_create, name="wo_create"),
    path("assets/workorders/view/", views.workorder_detail, name="wo_view"),
    path("assets/workorders/view/<int:id>/", views.workorder_detail, name="wo_view"),
    path("assets/workorders/close/", views.workorder_close, name="wo_close"),
    path("assets/workorders/close/<int:id>/", views.workorder_close, name="wo_close"),
    path("assets/verifiche-periodiche/", views.periodic_verification_list, name="periodic_verifications"),
    path("assets/reports/", views.reports_dashboard, name="reports"),
    path("assets/reports/manage/", views.report_template_admin, name="report_template_admin"),
    path(
        "assets/reports/work-machines/maintenance-month.pdf",
        views.work_machine_maintenance_month_pdf,
        name="work_machine_maintenance_month_pdf",
    ),
    path("assets/gestione/", views.gestione_admin, name="gestione_admin"),
    path("assets/bulk-update/", views.asset_bulk_update, name="asset_bulk_update"),
]
