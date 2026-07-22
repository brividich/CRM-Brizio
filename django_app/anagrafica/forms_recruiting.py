"""Form del modulo Recruiting MOD. 05-01.

Il punteggio ponderato non compare in nessun form: è scritto solo da
``services.recruiting.ricalcola_punteggio``. Un campo modificabile a mano
renderebbe il valore non difendibile in audit.
"""
from __future__ import annotations

from django import forms

from .models_recruiting import Candidato, RecruitingCriterio


class CandidatoForm(forms.ModelForm):
    """Scheda candidato: anagrafica, provenienza, esito CV e primo colloquio."""

    class Meta:
        model = Candidato
        fields = [
            # Anagrafica e provenienza
            "cognome", "nome", "cellulare", "email", "localita", "provincia",
            "canale_provenienza", "canale_dettaglio",
            "mansione_cercata", "azienda_attuale", "mansione_attuale",
            "livello_contratto_attuale", "occupato_attualmente",
            # Informativi (mai a punteggio)
            "eta", "titolo_studio", "cittadinanza",
            # Esito CV / primo colloquio
            "data_primo_colloquio", "cv_esito", "colloquio_effettuato",
            # Valutazione non a punteggio
            "lingua_inglese_livello", "idoneita_tirocinio", "idoneita_apprendistato",
            "disponibilita", "motivo_cambio_lavoro", "note",
            "rischio_abbandono", "giudizio_finale",
            "stato",
        ]
        widgets = {
            "data_primo_colloquio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "motivo_cambio_lavoro": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 4}),
            "provincia": forms.TextInput(attrs={"maxlength": 4, "placeholder": "CN"}),
        }
        labels = {
            "eta": "Età (informativo)",
            "cittadinanza": "Cittadinanza (informativo)",
            "cv_esito": "Esito C.V.",
            "rischio_abbandono": "Rischio di abbandono (1-10)",
        }

    def clean_provincia(self):
        return (self.cleaned_data.get("provincia") or "").strip().upper()


class CandidatoStep2Form(forms.ModelForm):
    """Secondo colloquio: stessa entità del primo, campi separati."""

    class Meta:
        model = Candidato
        fields = [
            "data_secondo_colloquio", "note_secondo_colloquio",
            "comunicazione_esito", "data_assunzione",
        ]
        widgets = {
            "data_secondo_colloquio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_assunzione": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note_secondo_colloquio": forms.Textarea(attrs={"rows": 4}),
        }

    def clean(self):
        cleaned = super().clean()
        prima = self.instance.data_primo_colloquio
        secondo = cleaned.get("data_secondo_colloquio")
        if prima and secondo and secondo < prima:
            self.add_error(
                "data_secondo_colloquio",
                "Il secondo colloquio non può precedere il primo.",
            )
        return cleaned


class RecruitingCriterioForm(forms.ModelForm):
    """Configurazione di un criterio: peso, rubrica, attivazione."""

    class Meta:
        model = RecruitingCriterio
        fields = ["codice", "label", "descrizione", "rubrica", "peso_percentuale", "ordine", "is_active"]
        widgets = {
            "descrizione": forms.Textarea(attrs={"rows": 2}),
            "rubrica": forms.Textarea(
                attrs={"rows": 5, "placeholder": "1 = ...\n3 = ...\n5 = ..."},
            ),
        }
