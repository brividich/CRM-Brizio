"""Form dell'e-learning professionale (prompt 05): regola di fruizione FAD per corso."""
from __future__ import annotations

from django import forms

from .models_formazione import TrainingCompletionRule
from .services.elearning_regole import CAMPI_FAD


class ElearningRegolaForm(forms.ModelForm):
    class Meta:
        model = TrainingCompletionRule
        fields = list(CAMPI_FAD) + ["rspp_note"]
        labels = {
            "el_tempo_minimo_minuti": "Tempo minimo di fruizione (minuti)",
            "el_richiede_tutte_slide": "Tutte le slide obbligatorie",
            "el_secondi_minimi_slide": "Permanenza minima per slide (secondi)",
            "el_inattivita_secondi": "Soglia di inattività (secondi)",
            "el_richiede_quiz": "Quiz finale obbligatorio",
            "el_soglia_pct": "Soglia di superamento (%)",
            "el_max_tentativi": "Tentativi massimi (0 = impostazione globale)",
            "el_attesa_minuti_tra_tentativi": "Attesa tra tentativi (minuti)",
            "el_domande_estratte": "Domande estratte (0 = tutte)",
            "el_mescola": "Ordine casuale di domande e risposte",
            "el_tempo_quiz_minuti": "Durata massima del quiz (minuti, 0 = senza limite)",
            "el_nuova_versione": "Se i contenuti cambiano, chi ha già completato",
            "rspp_note": "Note (riferimenti normativi, verbale)",
        }
        widgets = {"rspp_note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["el_nuova_versione"].required = False  # non inviato = valore attuale

    def clean_el_nuova_versione(self):
        return self.cleaned_data.get("el_nuova_versione") or self.instance.el_nuova_versione or "MANTIENI"

    def clean_el_soglia_pct(self):
        v = self.cleaned_data.get("el_soglia_pct")
        if v is not None and not 1 <= v <= 100:
            raise forms.ValidationError("La soglia va da 1 a 100.")
        return v

    def clean_el_inattivita_secondi(self):
        v = self.cleaned_data.get("el_inattivita_secondi") or 0
        if v < 30:
            raise forms.ValidationError("Almeno 30 secondi (il battito del player è ogni 30 secondi).")
        return v
