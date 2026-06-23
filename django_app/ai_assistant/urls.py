from django.urls import path

from . import views


app_name = "ai_assistant"

urlpatterns = [
    path("", views.chat_page, name="chat"),
    path("api/chat/", views.api_chat, name="api_chat"),
    path("api/chat/stream/", views.api_chat_stream, name="api_chat_stream"),
    path("api/daily-brief/", views.api_daily_brief, name="api_daily_brief"),
    path("api/knowledge/save/", views.api_save_knowledge, name="api_save_knowledge"),
    path("api/feedback/", views.api_feedback, name="api_feedback"),
]
