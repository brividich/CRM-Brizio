"""Corso e-learning dal link aperto (``/corso-aperto/``, senza login). Vedi views_corso_aperto."""
from django.urls import path

from . import views_aula_pubblica as va
from . import views_corso_aperto as v

app_name = "corso_aperto"

urlpatterns = [
    # QR d'aula delle sessioni in presenza: prima del token del corso.
    path("aula/<str:token>/", va.firma, name="aula"),
    path("aula/<str:token>/test/", va.test, name="aula_test"),
    path("<str:token>/", v.corso, name="corso"),
    path("<str:token>/registrati/", v.registrati, name="registrati"),
    path("<str:token>/pronto/", v.pronto, name="pronto"),
    path("<str:token>/materiale/", v.materiale, name="materiale"),
    path("<str:token>/video-avanz", v.video_avanz, name="video_avanz"),
    path("<str:token>/quiz/", v.quiz_finale, name="quiz"),
    path("<str:token>/slide/<int:slide_id>/immagine", v.immagine, name="immagine"),
    path("<str:token>/slide/<int:slide_id>/video", v.video, name="video"),
]
