"""Form del modulo Recruiting MOD. 05-01.

Il punteggio ponderato non compare in nessun form: è scritto solo da
``services.recruiting.ricalcola_punteggio``. Un campo modificabile a mano
renderebbe il valore non difendibile in audit.
"""
from __future__ import annotations

from django import forms

from .models_recruiting import Candidato, PosizioneAperta, RecruitingCriterio


class CandidatoForm(forms.ModelForm):
    """Scheda candidato: anagrafica, provenienza, esito CV e primo colloquio."""

    class Meta:
        model = Candidato
        fields = [
            # Anagrafica e provenienza
            "cognome", "nome", "codice_riferimento",
            "cellulare", "email", "localita", "provincia",
            "canale_provenienza", "canale_dettaglio",
            "posizione",
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
            "codice_riferimento": "Riferimento (riga file)",
        }
        help_texts = {
            "codice_riferimento": "Progressivo del foglio HR, per riconciliare una scheda importata anonima.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Nome e cognome restano opzionali: una scheda può essere importata
        # anonima e completata dopo. Il modello li ha già blank=True (quindi il
        # form non li impone), ma lo si rende esplicito per non regredire se un
        # domani qualcuno rimette blank=False sul modello.
        self.fields["cognome"].required = False
        self.fields["nome"].required = False
        # Solo le posizioni ancora da coprire, più quella già collegata.
        attuale = self.instance.posizione_id if self.instance and self.instance.pk else None
        filtro = PosizioneAperta.objects.filter(stato__in=PosizioneAperta.STATI_ATTIVI)
        if attuale:
            filtro = filtro | PosizioneAperta.objects.filter(pk=attuale)
        self.fields["posizione"].queryset = filtro.order_by("titolo")
        self.fields["posizione"].required = False
        self.fields["posizione"].empty_label = "— Nessuna (candidatura spontanea) —"
        self.fields["posizione"].help_text = "La mansione cercata si compila dalla posizione se lasciata vuota."

    def clean_provincia(self):
        return (self.cleaned_data.get("provincia") or "").strip().upper()

    def clean(self):
        cleaned = super().clean()
        posizione = cleaned.get("posizione")
        if posizione and not (cleaned.get("mansione_cercata") or "").strip():
            cleaned["mansione_cercata"] = posizione.mansione or posizione.titolo
        return cleaned


class PosizioneApertaForm(forms.ModelForm):
    """Richiesta di personale da coprire."""

    class Meta:
        model = PosizioneAperta
        fields = [
            "titolo", "mansione", "reparto", "posti", "motivo",
            "richiesta_da", "data_richiesta", "entro_il", "stato", "note",
        ]
        widgets = {
            "data_richiesta": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "entro_il": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "titolo": "Titolo della posizione",
            "posti": "Posti da coprire",
            "richiesta_da": "Richiesta da",
            "data_richiesta": "Data della richiesta",
            "entro_il": "Serve entro il",
        }

    def clean(self):
        cleaned = super().clean()
        richiesta, entro = cleaned.get("data_richiesta"), cleaned.get("entro_il")
        if richiesta and entro and entro < richiesta:
            self.add_error("entro_il", "La data entro cui serve la risorsa non può precedere la richiesta.")
        return cleaned


class OffertaForm(forms.Form):
    """Offerta inviata al candidato (fase facoltativa prima dell'assunzione)."""

    inviata_il = forms.DateField(label="Offerta inviata il", widget=forms.DateInput(attrs={"type": "date"}))
    data_ingresso = forms.DateField(
        label="Data di ingresso proposta", required=False, widget=forms.DateInput(attrs={"type": "date"}),
    )
    note = forms.CharField(
        label="Condizioni / note", required=False, max_length=300,
        widget=forms.TextInput(attrs={"placeholder": "Livello, contratto, RAL… (facoltativo)"}),
    )

    def clean(self):
        cleaned = super().clean()
        inviata, ingresso = cleaned.get("inviata_il"), cleaned.get("data_ingresso")
        if inviata and ingresso and ingresso < inviata:
            self.add_error("data_ingresso", "L'ingresso non può precedere l'offerta.")
        return cleaned


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
