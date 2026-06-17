from __future__ import annotations

from django import forms
from django.utils import timezone

from .models import (
    AreaAziendale,
    Reparto,
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    FiglioACarico,
    Mansione,
    RuoloAziendale,
    RuoloOperativo,
    TipoVisitaMedica,
    VisitaMedica,
)
from .models_formazione import (
    AttestatoFormazioneConfig,
    TrainingCourse,
    TrainingCompletionRule,
    TrainingCourseDependency,
    TrainingCourseModule,
    TrainingCourseVersion,
    TrainingEnrollment,
    TrainingInstructor,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingPlan,
    TrainingRequirementRule,
    TrainingSession,
)


# NOTE: i form Fornitore* sono stati spostati nel modulo `fornitori.forms`
# insieme alle view dei fornitori. Vedere `fornitori/forms.py`.


class PrivateClearableFileInput(forms.ClearableFileInput):
    """ClearableFileInput per file su storage privato (senza URL pubblico).

    Il widget standard, in rendering, chiama ``value.url`` per costruire il link
    "Attualmente: ...". Con ``PrivateAnagraficaStorage`` quell'accesso solleva
    ``NotImplementedError`` (i file non sono esposti su /media/). Qui sopprimiamo
    il link: mostriamo solo lo stato "file presente" + checkbox di rimozione,
    senza mai accedere a ``.url``.
    """

    template_name = "anagrafica/widgets/private_clearable_file_input.html"

    def is_initial(self, value):
        # Lo standard fa `bool(value and getattr(value, "url", False))`, che
        # innesca l'accesso a .url. Qui basta che esista un file salvato.
        return bool(value and getattr(value, "name", None))

    def format_value(self, value):
        # Non restituiamo un oggetto con .url: evita che il template provi a
        # leggerlo. Il nome file basta per mostrare "file presente".
        if self.is_initial(value):
            return getattr(value, "name", "")
        return None


class DipendenteLegacyForm(forms.Form):
    nome = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Nome"}))
    cognome = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Cognome"}))
    aliasusername = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Alias login"}))
    matricola = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Matricola"}))
    reparto = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Reparto"}))
    mansione = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Mansione"}))
    ruolo = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Ruolo"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "ana-input", "placeholder": "login@dominio"}))
    email_notifica = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "ana-input", "placeholder": "nome@example.com"}))
    attivo = forms.BooleanField(required=False, initial=True)


class AnagraficaCivileForm(forms.ModelForm):
    class Meta:
        model = DipendenteAnagraficaCivile
        exclude = ["legacy_anagrafica_id", "updated_by", "updated_at"]
        widgets = {
            "foto": PrivateClearableFileInput(attrs={"class": "dp-input", "accept": "image/*"}),
            "data_nascita": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "luogo_nascita": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Comune di nascita"}),
            "provincia_nascita": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. PI oppure PISA", "style": "text-transform:uppercase"}),
            "nazionalita": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. Italiana"}),
            "genere": forms.Select(attrs={"class": "dp-input"}),
            "indirizzo_residenza": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Via/Piazza..."}),
            "citta_residenza": forms.TextInput(attrs={"class": "dp-input"}),
            "provincia_residenza": forms.TextInput(attrs={"class": "dp-input", "maxlength": 5, "style": "text-transform:uppercase"}),
            "nazione_residenza": forms.TextInput(attrs={"class": "dp-input"}),
            "cap_residenza": forms.TextInput(attrs={"class": "dp-input", "maxlength": 10}),
            "indirizzo_domicilio": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Se diverso dalla residenza"}),
            "citta_domicilio": forms.TextInput(attrs={"class": "dp-input"}),
            "nazione_domicilio": forms.TextInput(attrs={"class": "dp-input"}),
            "cap_domicilio": forms.TextInput(attrs={"class": "dp-input", "maxlength": 10}),
            "codice_fiscale": forms.TextInput(attrs={"class": "dp-input", "maxlength": 16, "style": "text-transform:uppercase"}),
            "titolo_studio": forms.Select(attrs={"class": "dp-input"}),
            "email_privata": forms.EmailInput(attrs={"class": "dp-input"}),
            "telefono_privato": forms.TextInput(attrs={"class": "dp-input", "placeholder": "+39 ..."}),
            "nome_banca": forms.TextInput(attrs={"class": "dp-input"}),
            "iban": forms.TextInput(attrs={"class": "dp-input", "maxlength": 34, "style": "text-transform:uppercase", "placeholder": "IT..."}),
            "intestatario_conto": forms.TextInput(attrs={"class": "dp-input"}),
            "percentuale_disabilita": forms.NumberInput(attrs={"class": "dp-input", "step": "0.01", "min": "0", "max": "100", "placeholder": "es. 46.00"}),
        }

    def clean_codice_fiscale(self):
        return self.cleaned_data.get("codice_fiscale", "").upper().strip()

    def clean_iban(self):
        return self.cleaned_data.get("iban", "").replace(" ", "").upper()


class FiglioACaricoForm(forms.ModelForm):
    class Meta:
        model = FiglioACarico
        fields = ["nome", "data_nascita"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Nome (facoltativo)"}),
            # type="date" richiede il valore in formato ISO (YYYY-MM-DD), altrimenti
            # il browser non precompila il campo con la data già salvata.
            "data_nascita": forms.DateInput(attrs={"class": "dp-input", "type": "date"}, format="%Y-%m-%d"),
        }


FiglioACaricoFormSet = forms.inlineformset_factory(
    DipendenteAnagraficaCivile,
    FiglioACarico,
    form=FiglioACaricoForm,
    extra=1,
    can_delete=True,
)


class AnagraficaAziendaleForm(forms.ModelForm):
    class Meta:
        model = DipendenteAnagraficaAziendale
        exclude = [
            "legacy_anagrafica_id", "updated_by", "updated_at",
            "tipologia_contratto", "livello_inquadramento",
            "area_aziendale_nome", "caporeparto_legacy_id",
        ]
        widgets = {
            "badge": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Codice badge fisico"}),
            "taglia_scarpe": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. 42"}),
            "taglia_pantalone": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. 48 oppure 50/34"}),
            "taglia_maglia": forms.Select(attrs={"class": "dp-input"}),
            "data_consenso_privacy": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "data_prima_assunzione": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "data_assunzione_ultima": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "data_cessazione": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "prova_data_inizio": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "prova_data_fine": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "email_aziendale": forms.EmailInput(attrs={"class": "dp-input"}),
            "telefono_aziendale": forms.TextInput(attrs={"class": "dp-input", "placeholder": "+39 ..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Reparto: dropdown dal catalogo Reparto.
        # Include il valore corrente anche se non più presente nel catalogo.
        active_aree = list(Reparto.objects.filter(is_active=True).values_list("nome", flat=True).order_by("nome"))
        current_area = self.instance.area if self.instance.pk else ""
        if current_area and current_area not in active_aree:
            active_aree = [current_area] + active_aree
        area_choices = [("", "— Nessuno —")] + [(n, n) for n in active_aree]
        self.fields["area"].label = "Reparto"
        self.fields["area"].widget = forms.Select(attrs={"class": "dp-input"})
        self.fields["area"].widget.choices = area_choices

        # Ruolo aziendale: dropdown da catalogo RuoloAziendale
        active_ruoli = list(RuoloAziendale.objects.filter(is_active=True).values_list("nome", flat=True).order_by("nome"))
        current_ruolo = self.instance.ruolo_aziendale if self.instance.pk else ""
        if current_ruolo and current_ruolo not in active_ruoli:
            active_ruoli = [current_ruolo] + active_ruoli
        ruolo_choices = [("", "— Nessuno —")] + [(n, n) for n in active_ruoli]
        self.fields["ruolo_aziendale"].widget = forms.Select(attrs={"class": "dp-input"})
        self.fields["ruolo_aziendale"].widget.choices = ruolo_choices

    def clean_badge(self):
        val = self.cleaned_data.get("badge", "").strip()
        if val:
            stripped = val.lstrip("0")
            return stripped if stripped else "0"
        return val


# ---------------------------------------------------------------------------
# Visite mediche
# ---------------------------------------------------------------------------

class VisitaMedicaForm(forms.ModelForm):
    """Form di registrazione/modifica visita medica.

    Il referto è gestito come FileField separato: la view crea un
    ``DocumentoDipendente`` di tipo VISITA_MEDICA_REFERTO e lo aggancia
    a ``visita.referto_documento``.
    """

    referto_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "dp-input", "accept": ".pdf,image/*"}),
        help_text="Referto/documento allegato (opzionale). Storage privato.",
    )

    class Meta:
        model = VisitaMedica
        fields = [
            "tipo", "data_svolgimento", "esito",
            "prescrizioni", "medico_competente", "note",
        ]
        widgets = {
            "tipo": forms.Select(attrs={"class": "dp-input"}),
            "data_svolgimento": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "esito": forms.Select(attrs={"class": "dp-input"}),
            "prescrizioni": forms.Textarea(attrs={"class": "dp-input", "rows": 2}),
            "medico_competente": forms.TextInput(attrs={"class": "dp-input"}),
            "note": forms.Textarea(attrs={"class": "dp-input", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoVisitaMedica.objects.filter(is_active=True).order_by("nome")

    def clean_data_svolgimento(self):
        data = self.cleaned_data.get("data_svolgimento")
        if data and data > timezone.localdate():
            raise forms.ValidationError("La data di svolgimento non può essere nel futuro.")
        return data


# ---------------------------------------------------------------------------
# Formazione HR (PATCH-03)
# ---------------------------------------------------------------------------

_FM = {"class": "fm-input"}
_FM_SELECT = {"class": "fm-input fm-select"}
_FM_TEXTAREA = {"class": "fm-input", "rows": 3}
_FM_DATE = {"class": "fm-input", "type": "date"}
_FM_NUMBER = {"class": "fm-input"}
_FM_CHECK = {"class": "fm-check"}


class AttestatoFormazioneConfigForm(forms.ModelForm):
    """Testi/opzioni del template attestato di formazione (singleton),
    modificabili da Impostazioni Anagrafica HR."""

    class Meta:
        model = AttestatoFormazioneConfig
        fields = [
            "intestazione_eyebrow", "sezione_label",
            "titolo_partecipazione", "titolo_frequenza", "titolo_qualifica",
            "formula_attestazione",
            "firma_responsabile_label", "firma_dipendente_label",
            "responsabile_default", "mostra_dati_personali",
            "nota_legale", "logo_url", "pie_organizzazione",
            "auto_salva_attestato", "cartella_attestati", "rigenera_se_esiste",
        ]
        widgets = {
            "intestazione_eyebrow":     forms.TextInput(attrs=_FM),
            "sezione_label":            forms.TextInput(attrs=_FM),
            "titolo_partecipazione":    forms.TextInput(attrs=_FM),
            "titolo_frequenza":         forms.TextInput(attrs=_FM),
            "titolo_qualifica":         forms.TextInput(attrs=_FM),
            "formula_attestazione":     forms.TextInput(attrs=_FM),
            "firma_responsabile_label": forms.TextInput(attrs=_FM),
            "firma_dipendente_label":   forms.TextInput(attrs=_FM),
            "responsabile_default":     forms.TextInput(attrs={**_FM, "placeholder": "Es. Ing. Mario Rossi (RSPP)"}),
            "mostra_dati_personali":    forms.CheckboxInput(attrs=_FM_CHECK),
            "nota_legale":              forms.Textarea(attrs={**_FM_TEXTAREA, "rows": 3}),
            "logo_url":                 forms.URLInput(attrs={**_FM, "placeholder": "https://… (vuoto = logo predefinito)"}),
            "pie_organizzazione":       forms.TextInput(attrs=_FM),
            "auto_salva_attestato":     forms.CheckboxInput(attrs=_FM_CHECK),
            "cartella_attestati":       forms.Select(attrs=_FM_SELECT),
            "rigenera_se_esiste":       forms.CheckboxInput(attrs=_FM_CHECK),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo cartelle attive; etichetta vuota = cartella predefinita on-demand.
        from .models import CartellaDocumentoDipendente
        self.fields["cartella_attestati"].queryset = (
            CartellaDocumentoDipendente.objects.filter(attiva=True).order_by("ordine", "nome")
        )
        self.fields["cartella_attestati"].required = False
        self.fields["cartella_attestati"].empty_label = "Predefinita («Attestati formazione»)"


class TrainingPlanForm(forms.ModelForm):
    class Meta:
        model = TrainingPlan
        fields = [
            "codice", "nome", "categoria", "stato",
            "descrizione", "note",
            "ore_totali_stimate", "costo_stimato",
            "provider_esterno", "is_active",
        ]
        widgets = {
            "codice":             forms.TextInput(attrs=_FM),
            "nome":               forms.TextInput(attrs=_FM),
            "categoria":          forms.Select(attrs=_FM_SELECT),
            "stato":              forms.Select(attrs=_FM_SELECT),
            "descrizione":        forms.Textarea(attrs=_FM_TEXTAREA),
            "note":               forms.Textarea(attrs=_FM_TEXTAREA),
            "ore_totali_stimate": forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.5", "min": "0"}),
            "costo_stimato":      forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.01", "min": "0"}),
            "provider_esterno":   forms.CheckboxInput(attrs=_FM_CHECK),
            "is_active":          forms.CheckboxInput(attrs=_FM_CHECK),
        }

    def clean_codice(self):
        return (self.cleaned_data.get("codice") or "").strip().upper()


class TrainingCourseForm(forms.ModelForm):
    class Meta:
        model = TrainingCourse
        fields = [
            "piano", "codice", "titolo", "descrizione",
            "durata_ore_teorica", "validita_mesi",
            "obbligatorio", "costo_unitario",
            "stato", "note", "versione", "is_active",
        ]
        widgets = {
            "piano":              forms.Select(attrs=_FM_SELECT),
            "codice":             forms.TextInput(attrs=_FM),
            "titolo":             forms.TextInput(attrs=_FM),
            "descrizione":        forms.Textarea(attrs=_FM_TEXTAREA),
            "durata_ore_teorica": forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.5", "min": "0.5"}),
            "validita_mesi":      forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0"}),
            "obbligatorio":       forms.CheckboxInput(attrs=_FM_CHECK),
            "costo_unitario":     forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.01", "min": "0"}),
            "stato":              forms.Select(attrs=_FM_SELECT),
            "note":               forms.Textarea(attrs=_FM_TEXTAREA),
            "versione":           forms.TextInput(attrs=_FM),
            "is_active":          forms.CheckboxInput(attrs=_FM_CHECK),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["piano"].queryset = TrainingPlan.objects.filter(is_active=True).order_by("nome")

    def clean_codice(self):
        return (self.cleaned_data.get("codice") or "").strip().upper()


class TrainingInstructorForm(forms.ModelForm):
    class Meta:
        model = TrainingInstructor
        fields = [
            "tipo", "nome", "ragione_sociale",
            "email", "telefono",
            "legacy_anagrafica_id",
            "qualification_notes", "is_active",
        ]
        widgets = {
            "tipo":                  forms.Select(attrs=_FM_SELECT),
            "nome":                  forms.TextInput(attrs=_FM),
            "ragione_sociale":       forms.TextInput(attrs=_FM),
            "email":                 forms.EmailInput(attrs=_FM),
            "telefono":              forms.TextInput(attrs=_FM),
            "legacy_anagrafica_id":  forms.NumberInput(attrs={**_FM_NUMBER, "min": "1"}),
            "qualification_notes":   forms.Textarea(attrs=_FM_TEXTAREA),
            "is_active":             forms.CheckboxInput(attrs=_FM_CHECK),
        }


class TrainingRequirementRuleForm(forms.ModelForm):
    class Meta:
        model = TrainingRequirementRule
        fields = [
            "corso", "piano",
            "mansione", "area", "ruolo_operativo", "legacy_anagrafica_id",
            "is_mandatory", "override_frequenza_mesi",
            "data_inizio_validita", "data_fine_validita",
            "priority", "note", "is_active",
        ]
        widgets = {
            "corso":                   forms.Select(attrs=_FM_SELECT),
            "piano":                   forms.Select(attrs=_FM_SELECT),
            "mansione":                forms.Select(attrs=_FM_SELECT),
            "area":                    forms.Select(attrs=_FM_SELECT),
            "ruolo_operativo":         forms.Select(attrs=_FM_SELECT),
            "legacy_anagrafica_id":    forms.NumberInput(attrs={**_FM_NUMBER, "min": "1"}),
            "is_mandatory":            forms.CheckboxInput(attrs=_FM_CHECK),
            "override_frequenza_mesi": forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0"}),
            "data_inizio_validita":    forms.DateInput(attrs=_FM_DATE),
            "data_fine_validita":      forms.DateInput(attrs=_FM_DATE),
            "priority":                forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0"}),
            "note":                    forms.Textarea(attrs=_FM_TEXTAREA),
            "is_active":               forms.CheckboxInput(attrs=_FM_CHECK),
        }

    def clean(self):
        cd = super().clean()
        targets = [
            cd.get("mansione"),
            cd.get("area"),
            cd.get("ruolo_operativo"),
            cd.get("legacy_anagrafica_id"),
        ]
        if not any(targets):
            raise forms.ValidationError(
                "Almeno uno dei target (mansione, area, ruolo operativo, dipendente) deve essere valorizzato."
            )
        if cd.get("corso") and cd.get("piano"):
            raise forms.ValidationError("La regola può riguardare un corso oppure un piano, non entrambi.")
        if not cd.get("corso") and not cd.get("piano"):
            raise forms.ValidationError("Specificare il corso oppure il piano a cui si applica la regola.")
        return cd


class TrainingCompletionRuleForm(forms.ModelForm):
    class Meta:
        model = TrainingCompletionRule
        fields = [
            "ore_minime_percentuale", "presenza_minima_percentuale",
            "richiede_esame_finale", "richiede_firma_presenza",
            "richiede_attestato", "richiede_validazione_hr",
            "valid_from", "valid_to", "note", "is_active",
        ]
        widgets = {
            "ore_minime_percentuale":      forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0", "max": "100"}),
            "presenza_minima_percentuale": forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0", "max": "100"}),
            "richiede_esame_finale":       forms.CheckboxInput(attrs=_FM_CHECK),
            "richiede_firma_presenza":     forms.CheckboxInput(attrs=_FM_CHECK),
            "richiede_attestato":          forms.CheckboxInput(attrs=_FM_CHECK),
            "richiede_validazione_hr":     forms.CheckboxInput(attrs=_FM_CHECK),
            "valid_from":                  forms.DateInput(attrs=_FM_DATE),
            "valid_to":                    forms.DateInput(attrs=_FM_DATE),
            "note":                        forms.Textarea(attrs=_FM_TEXTAREA),
            "is_active":                   forms.CheckboxInput(attrs=_FM_CHECK),
        }


class TrainingCourseVersionForm(forms.ModelForm):
    class Meta:
        model = TrainingCourseVersion
        fields = [
            "version_label", "titolo_snapshot",
            "durata_ore_snapshot", "validita_mesi_snapshot",
            "data_inizio_validita", "data_fine_validita",
            "note", "is_active",
        ]
        widgets = {
            "version_label":          forms.TextInput(attrs=_FM),
            "titolo_snapshot":        forms.TextInput(attrs=_FM),
            "durata_ore_snapshot":    forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.5", "min": "0"}),
            "validita_mesi_snapshot": forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0"}),
            "data_inizio_validita":   forms.DateInput(attrs=_FM_DATE),
            "data_fine_validita":     forms.DateInput(attrs=_FM_DATE),
            "note":                   forms.Textarea(attrs=_FM_TEXTAREA),
            "is_active":              forms.CheckboxInput(attrs=_FM_CHECK),
        }


class TrainingCourseDependencyForm(forms.Form):
    prerequisito_id = forms.IntegerField(
        label="Corso prerequisito",
        widget=forms.Select(attrs=_FM_SELECT),
    )
    obbligatorio = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs=_FM_CHECK),
    )

    def __init__(self, *args, corso_principale=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = TrainingCourse.objects.filter(is_active=True).order_by("titolo")
        if corso_principale:
            qs = qs.exclude(pk=corso_principale.pk)
        choices = [(c.pk, f"[{c.codice}] {c.titolo}") for c in qs]
        self.fields["prerequisito_id"].widget.choices = [("", "— Seleziona corso —")] + choices


class TrainingSessionForm(forms.ModelForm):
    class Meta:
        model = TrainingSession
        fields = [
            "corso", "codice_sessione", "stato", "modalita",
            "data_inizio", "data_fine", "sede",
            "docente", "docente_nome", "note",
        ]
        widgets = {
            "corso":           forms.Select(attrs=_FM_SELECT),
            "codice_sessione": forms.TextInput(attrs=_FM),
            "stato":           forms.Select(attrs=_FM_SELECT),
            "modalita":        forms.Select(attrs=_FM_SELECT),
            "data_inizio":     forms.DateInput(attrs=_FM_DATE),
            "data_fine":       forms.DateInput(attrs=_FM_DATE),
            "sede":            forms.TextInput(attrs=_FM),
            "docente":         forms.Select(attrs=_FM_SELECT),
            "docente_nome":    forms.TextInput(attrs=_FM),
            "note":            forms.Textarea(attrs=_FM_TEXTAREA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["corso"].queryset = (
            TrainingCourse.objects.filter(is_active=True).order_by("piano__nome", "titolo")
        )
        self.fields["docente"].queryset = TrainingInstructor.objects.filter(is_active=True).order_by("nome")
        self.fields["docente"].required = False

    def clean(self):
        cd = super().clean()
        d_inizio = cd.get("data_inizio")
        d_fine   = cd.get("data_fine")
        if d_inizio and d_fine and d_fine < d_inizio:
            raise forms.ValidationError("La data di fine non può essere precedente alla data di inizio.")
        # Snapshot nome docente dal FK se non compilato manualmente
        docente = cd.get("docente")
        if docente and not cd.get("docente_nome"):
            cd["docente_nome"] = docente.nome
        return cd

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.docente and not instance.docente_nome:
            instance.docente_nome = instance.docente.nome
        if commit:
            instance.save()
        return instance


class TrainingEnrollmentEditForm(forms.ModelForm):
    """Modifica stato iscrizione e dati di completamento."""

    class Meta:
        model = TrainingEnrollment
        fields = [
            "stato", "ore_frequentate",
            "percentuale_presenza", "idoneo",
            "esito_esame", "data_completamento", "note",
        ]
        widgets = {
            "stato":                forms.Select(attrs=_FM_SELECT),
            "ore_frequentate":      forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.5", "min": "0"}),
            "percentuale_presenza": forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.01", "min": "0", "max": "100"}),
            "idoneo":               forms.CheckboxInput(attrs=_FM_CHECK),
            "esito_esame":          forms.TextInput(attrs=_FM),
            "data_completamento":   forms.DateInput(attrs=_FM_DATE),
            "note":                 forms.Textarea(attrs=_FM_TEXTAREA),
        }


class TrainingLessonAttendanceForm(forms.ModelForm):
    class Meta:
        model = TrainingLessonAttendance
        fields = ["stato_presenza", "ore_effettive", "firma_ingresso", "firma_uscita", "note"]
        widgets = {
            "stato_presenza": forms.Select(attrs=_FM_SELECT),
            "ore_effettive":  forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.25", "min": "0"}),
            "firma_ingresso": forms.CheckboxInput(attrs=_FM_CHECK),
            "firma_uscita":   forms.CheckboxInput(attrs=_FM_CHECK),
            "note":           forms.Textarea(attrs=_FM_TEXTAREA),
        }


class TrainingLessonForm(forms.ModelForm):
    class Meta:
        model = TrainingLesson
        fields = [
            "numero", "data", "ora_inizio", "ora_fine",
            "argomento", "docente", "docente_nome", "note",
        ]
        widgets = {
            "numero":      forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "1"}),
            "data":        forms.DateInput(attrs=_FM_DATE),
            "ora_inizio":  forms.TimeInput(attrs={**_FM, "type": "time"}),
            "ora_fine":    forms.TimeInput(attrs={**_FM, "type": "time"}),
            "argomento":   forms.TextInput(attrs=_FM),
            "docente":     forms.Select(attrs=_FM_SELECT),
            "docente_nome": forms.TextInput(attrs=_FM),
            "note":        forms.Textarea(attrs=_FM_TEXTAREA),
        }

    def __init__(self, *args, sessione=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sessione = sessione
        self.fields["docente"].queryset = TrainingInstructor.objects.filter(is_active=True).order_by("nome")
        self.fields["docente"].required = False

    def clean(self):
        cd = super().clean()
        t_inizio = cd.get("ora_inizio")
        t_fine   = cd.get("ora_fine")
        if t_inizio and t_fine and t_fine <= t_inizio:
            self.add_error("ora_fine", "L'ora di fine deve essere successiva all'ora di inizio.")
        # Verifica che la data ricada nell'intervallo della sessione
        if self.sessione and cd.get("data"):
            if cd["data"] < self.sessione.data_inizio or cd["data"] > self.sessione.data_fine:
                self.add_error(
                    "data",
                    f"La data della lezione deve essere compresa tra "
                    f"{self.sessione.data_inizio.strftime('%d-%m-%Y')} e "
                    f"{self.sessione.data_fine.strftime('%d-%m-%Y')}.",
                )
        # Snapshot nome docente
        docente = cd.get("docente")
        if docente and not cd.get("docente_nome"):
            cd["docente_nome"] = docente.nome
        return cd

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.docente and not instance.docente_nome:
            instance.docente_nome = instance.docente.nome
        if commit:
            instance.save()
        return instance


# ─────────────────────────────────────────────────────────────────────────────
# Safety / Rischi (PATCH-RISK-02)
# ─────────────────────────────────────────────────────────────────────────────

from .models_rischi import CategoriaCorso, EsposizioneRischio, FattoreRischio  # noqa: E402


class FattoreRischioForm(forms.ModelForm):
    class Meta:
        model = FattoreRischio
        fields = [
            "codice", "nome", "categoria", "descrizione",
            "periodicita_formazione_mesi", "periodicita_sorveglianza_mesi",
            "richiede_formazione", "richiede_visita_medica", "richiede_dpi",
            "tipi_visita", "categorie_dpi",
            "is_active", "note",
        ]
        widgets = {
            "codice":      forms.TextInput(attrs={**_FM, "maxlength": 20, "placeholder": "es. R-RUMORE"}),
            "nome":        forms.TextInput(attrs={**_FM, "maxlength": 200, "placeholder": "es. Rumore"}),
            "categoria":   forms.Select(attrs=_FM_SELECT),
            "descrizione": forms.Textarea(attrs=_FM_TEXTAREA),
            "periodicita_formazione_mesi":   forms.NumberInput(attrs={**_FM_NUMBER, "min": "0", "step": "1"}),
            "periodicita_sorveglianza_mesi": forms.NumberInput(attrs={**_FM_NUMBER, "min": "0", "step": "1"}),
            "richiede_formazione":    forms.CheckboxInput(attrs=_FM_CHECK),
            "richiede_visita_medica": forms.CheckboxInput(attrs=_FM_CHECK),
            "richiede_dpi":           forms.CheckboxInput(attrs=_FM_CHECK),
            "tipi_visita":   forms.SelectMultiple(attrs={**_FM_SELECT, "size": "5"}),
            "categorie_dpi": forms.SelectMultiple(attrs={**_FM_SELECT, "size": "5"}),
            "is_active":              forms.CheckboxInput(attrs=_FM_CHECK),
            "note":        forms.Textarea(attrs=_FM_TEXTAREA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo tipologie/categorie attive nel selettore; il modulo dpi è
        # sempre installato ma restiamo difensivi sul queryset.
        self.fields["tipi_visita"].queryset = (
            self.fields["tipi_visita"].queryset.filter(is_active=True).order_by("nome")
        )
        try:
            self.fields["categorie_dpi"].queryset = (
                self.fields["categorie_dpi"].queryset.filter(is_active=True)
                .order_by("order_index", "nome")
            )
        except Exception:
            pass


class CategoriaCorsoForm(forms.ModelForm):
    class Meta:
        model = CategoriaCorso
        fields = ["codice", "nome", "descrizione", "fattori_rischio", "is_active"]
        widgets = {
            "codice":      forms.TextInput(attrs={**_FM, "maxlength": 20, "placeholder": "es. CAT-SIC"}),
            "nome":        forms.TextInput(attrs={**_FM, "maxlength": 200, "placeholder": "es. Sicurezza generale"}),
            "descrizione": forms.Textarea(attrs=_FM_TEXTAREA),
            "fattori_rischio": forms.SelectMultiple(attrs={**_FM_SELECT, "size": "6"}),
            "is_active":   forms.CheckboxInput(attrs=_FM_CHECK),
        }


class EsposizioneRischioForm(forms.ModelForm):
    class Meta:
        model = EsposizioneRischio
        fields = ["fattore", "mansione", "area", "note", "is_active"]
        widgets = {
            "fattore":   forms.Select(attrs=_FM_SELECT),
            "mansione":  forms.Select(attrs=_FM_SELECT),
            "area":      forms.Select(attrs=_FM_SELECT),
            "note":      forms.Textarea(attrs=_FM_TEXTAREA),
            "is_active": forms.CheckboxInput(attrs=_FM_CHECK),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("mansione") and not cleaned.get("area"):
            raise forms.ValidationError("Specificare almeno Mansione o Area come target dell'esposizione.")
        return cleaned
