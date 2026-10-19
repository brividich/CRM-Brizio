from django.urls import path

from . import views


app_name = "ai_assistant"

urlpatterns = [
    path("", views.chat_page, name="chat"),
    path("guida/", views.guida, name="guida"),
    path("api/chat/", views.api_chat, name="api_chat"),
    path("api/chat/stream/", views.api_chat_stream, name="api_chat_stream"),
    path("api/daily-brief/", views.api_daily_brief, name="api_daily_brief"),
    path("api/cerca-documenti/", views.api_cerca_documenti, name="api_cerca_documenti"),
    path("api/report/", views.api_genera_report, name="api_report"),
    path("api/knowledge/save/", views.api_save_knowledge, name="api_save_knowledge"),
    path("api/feedback/", views.api_feedback, name="api_feedback"),
    path("api/conversazioni/", views.api_conversazioni, name="api_conversazioni"),
    path("api/conversazioni/elimina-tutte/", views.api_conversazioni_elimina_tutte,
         name="api_conversazioni_elimina_tutte"),
    path("api/conversazioni/<int:conversation_id>/", views.api_conversazione, name="api_conversazione"),
    path("api/conversazioni/<int:conversation_id>/elimina/", views.api_conversazione_elimina,
         name="api_conversazione_elimina"),
]
