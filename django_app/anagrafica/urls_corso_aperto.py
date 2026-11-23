"""Corso e-learning dal link aperto (``/corso-aperto/``, senza login). Vedi views_corso_aperto."""
from django.urls import path

from . import views_corso_aperto as v

app_name = "corso_aperto"

urlpatterns = [
    path("<str:token>/", v.corso, name="corso"),
    path("<str:token>/quiz/", v.quiz_finale, name="quiz"),
    path("<str:token>/slide/<int:slide_id>/immagine", v.immagine, name="immagine"),
    path("<str:token>/slide/<int:slide_id>/video", v.video, name="video"),
]
