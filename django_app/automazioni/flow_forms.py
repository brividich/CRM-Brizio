from django import forms
from .models import ManagedFlow


class ManagedScheduleForm(forms.ModelForm):
    class Meta:
        model = ManagedFlow
        fields = ["schedule_type", "minutes", "cron"]
        labels = {"schedule_type": "Ricorrenza", "minutes": "Intervallo in minuti", "cron": "Calendario (minuto ora giorno mese giorno-settimana)"}
        help_texts = {"cron": "Esempio: 0 7 * * 1-5, alle 07:00 dal lunedì al venerdì. Fuso del portale."}
