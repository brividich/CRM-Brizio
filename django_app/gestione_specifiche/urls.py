from django.urls import path

from . import admin_views, views
from .api import api as ninja_api

app_name = "gestione_specifiche"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("kpi/", views.kpi, name="kpi"),
    path("nuova/", views.nuova_specifica, name="nuova"),
    path("cartella-suggerita/", views.cartella_suggerita, name="cartella_suggerita"),
    path("allegato/<int:pk>/", views.allegato_download, name="allegato_download"),
    path("<int:pk>/", views.dettaglio, name="dettaglio"),
    path("<int:pk>/modifica/", views.modifica_specifica, name="modifica"),
    path("<int:pk>/avvia-flow-down/", views.avvia_flow_down_view, name="avvia_flow_down"),
    path("<int:pk>/claim/", views.claim, name="claim"),
    path("<int:pk>/mod133/", views.mod133_compila, name="mod133_compila"),
    path("<int:pk>/mod133/riga/", views.mod133_riga_add, name="mod133_riga_add"),
    path("<int:pk>/mod133/chiudi/", views.mod133_chiudi, name="mod133_chiudi"),
    path("<int:pk>/mod133/approva/", views.mod133_approva, name="mod133_approva"),
    path("<int:pk>/mod133/riga/<int:riga_id>/genera-ofi/", views.riga_genera_ofi, name="riga_genera_ofi"),
    path("azione-ofi/<int:azione_id>/approva/", views.azione_ofi_approva, name="azione_ofi_approva"),
    path("<int:pk>/distribuisci/", views.distribuzione_nuova, name="distribuzione_nuova"),
    # F6b-1 — anteprima composito ufficiale (nessuna scrittura sulla share)
    path("<int:pk>/composito/anteprima/", views.composito_preview, name="composito_preview"),
    path("<int:pk>/composito/miniatura.png", views.composito_thumb, name="composito_thumb"),
    # Storico consultabile + export
    path("<int:pk>/storico/", views.scheda_storico, name="scheda_storico"),
    path("<int:pk>/storico/export.csv", views.storico_export_csv, name="storico_export_csv"),
    path("<int:pk>/storico/export.pdf", views.storico_export_pdf, name="storico_export_pdf"),
    # Azioni di stato SSR (inline)
    path("<int:pk>/sospendi/", views.sospendi_view, name="sospendi"),
    path("<int:pk>/ripristina/", views.ripristina_view, name="ripristina"),
    path("<int:pk>/annulla/", views.annulla_view, name="annulla"),
    # F9 — Copilota AI (proposte) + ricerca semantica
    path("ricerca/", views.ricerca_semantica_view, name="ricerca"),
    path("guida/", views.guida, name="guida"),
    # #6 — sezione Amministrazione (ACL PERM_ADMIN)
    path("admin/", admin_views.admin_home, name="admin_home"),
    path("admin/cartelle/", admin_views.admin_cartelle, name="admin_cartelle"),
    path("admin/cartelle/<int:pk>/modifica/", admin_views.admin_cartella_edit, name="admin_cartella_edit"),
    path("admin/cartelle/<int:pk>/elimina/", admin_views.admin_cartella_delete, name="admin_cartella_delete"),
    path("admin/auto-approvazione/", admin_views.admin_auto_approva, name="admin_auto_approva"),
    path("admin/notifiche/", admin_views.admin_notifiche, name="admin_notifiche"),
    path("admin/log/", admin_views.admin_log, name="admin_log"),
    path("admin/specifiche/", admin_views.admin_specifiche, name="admin_specifiche"),
    path("admin/specifiche/<int:pk>/riassegna/", admin_views.admin_specifica_riassegna, name="admin_specifica_riassegna"),
    path("admin/timbri/", admin_views.admin_timbri, name="admin_timbri"),
    path("admin/timbri/<int:pk>/elimina/", admin_views.admin_timbro_delete, name="admin_timbro_delete"),
    path("<int:pk>/ai/precompila-mod133/", views.ai_precompila_mod133, name="ai_precompila_mod133"),
    path("<int:pk>/ai/proponi-tag/", views.ai_proponi_tag, name="ai_proponi_tag"),
    path("<int:pk>/ai/diff-mod133/", views.ai_diff_mod133, name="ai_diff_mod133"),
    # API django-ninja
    path("api/", ninja_api.urls),
]
