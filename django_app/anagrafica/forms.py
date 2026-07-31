from __future__ import annotations

from django import forms
from django.db.models import Q
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
    SkillMatrixConfig,
    TipoVisitaMedica,
    VisitaMedica,
)
from .models_formazione import (
    AttestatoFormazioneConfig,
    ElearningConfig,
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
    TrainingSlide,
    TrainingQuizQuestion,
    TrainingQuizOption,
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
            "caporeparto_legacy_id",
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

        # Area aziendale: dropdown filtrato via JS sul Reparto scelto (client-side,
        # vedi cascading in dipendente_detail.html). Il queryset include le aree
        # attive più quella eventualmente già assegnata (anche se nel frattempo
        # disattivata), stesso criterio già usato sopra per "area".
        area_aziendale_corrente_id = self.instance.area_aziendale_id if self.instance.pk else None
        self.fields["area_aziendale"].queryset = AreaAziendale.objects.filter(
            Q(is_active=True) | Q(pk=area_aziendale_corrente_id)
        ).order_by("nome")
        self.fields["area_aziendale"].label = "Area aziendale"
        self.fields["area_aziendale"].empty_label = "— Nessuna —"
        self.fields["area_aziendale"].widget.attrs.update({
            "class": "dp-input",
            "data-current": str(area_aziendale_corrente_id or ""),
        })

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
_FM_DATE = {"class": "fm-input js-datepicker", "type": "date"}
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
            "piano", "categoria", "qualifica", "codice", "titolo", "descrizione",
            "durata_ore_teorica", "validita_mesi",
            "obbligatorio", "costo_unitario",
            "is_elearning", "quiz_punteggio_minimo",
            "stato", "note", "versione", "is_active",
        ]
        widgets = {
            "piano":              forms.Select(attrs=_FM_SELECT),
            "categoria":          forms.Select(attrs=_FM_SELECT),
            "qualifica":          forms.Select(attrs=_FM_SELECT),
            "codice":             forms.TextInput(attrs=_FM),
            "titolo":             forms.TextInput(attrs=_FM),
            "descrizione":        forms.Textarea(attrs=_FM_TEXTAREA),
            "durata_ore_teorica": forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.5", "min": "0.5"}),
            "validita_mesi":      forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0"}),
            "obbligatorio":       forms.CheckboxInput(attrs=_FM_CHECK),
            "costo_unitario":     forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.01", "min": "0"}),
            "is_elearning":       forms.CheckboxInput(attrs=_FM_CHECK),
            "quiz_punteggio_minimo": forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0", "max": "100"}),
            "stato":              forms.Select(attrs=_FM_SELECT),
            "note":               forms.Textarea(attrs=_FM_TEXTAREA),
            "versione":           forms.TextInput(attrs=_FM),
            "is_active":          forms.CheckboxInput(attrs=_FM_CHECK),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["piano"].queryset = TrainingPlan.objects.filter(is_active=True).order_by("nome")
        # Categoria di rischio (deriva i fattori → pertinenza) e qualifica àncora
        # (competency management): entrambe opzionali, settabili in creazione/modifica.
        from .models import TipoQualifica
        from .models_rischi import CategoriaCorso
        self.fields["categoria"].queryset = CategoriaCorso.objects.filter(is_active=True).order_by("nome")
        self.fields["categoria"].required = False
        self.fields["categoria"].empty_label = "— Nessuna (nessuna derivazione rischio) —"
        self.fields["qualifica"].queryset = TipoQualifica.objects.filter(is_active=True).order_by("categoria", "nome")
        self.fields["qualifica"].required = False
        self.fields["qualifica"].empty_label = "— Nessuna (corso non legato a qualifica) —"

        # Dropdown qualifica raggruppato per tipologia (optgroups per categoria).
        from itertools import groupby
        _cat_labels = dict(TipoQualifica.CATEGORIA_CHOICES)
        _grouped = [("", self.fields["qualifica"].empty_label)]
        for _cat, _items in groupby(self.fields["qualifica"].queryset, key=lambda q: q.categoria):
            _grouped.append((_cat_labels.get(_cat, _cat), [(q.pk, q.nome) for q in _items]))
        self.fields["qualifica"].widget.choices = _grouped

        # Processi qualificati (MOD.128) che richiedono questo corso (reverse M2M
        # di ProcessoQualificato.corsi_richiesti): gestibile anche dal lato corso.
        try:
            from .models_mpq import ProcessoQualificato
            self.fields["processi_richiedenti"] = forms.ModelMultipleChoiceField(
                queryset=ProcessoQualificato.objects.select_related("cliente").order_by("cliente__nome", "nome"),
                required=False,
                label="Processi qualificati che lo richiedono (MOD.128)",
                help_text="Chi è abilitato a questi processi sarà tenuto a questo corso.",
                widget=forms.SelectMultiple(attrs={
                    "class": "fm-input fm-select", "size": "5",
                    "data-picker": "", "data-picker-placeholder": "Cerca processo qualificato…"}),
            )
            self.fields["processi_richiedenti"].label_from_instance = (
                lambda p: f"{p.nome} ({p.cliente.nome})")
            if self.instance and self.instance.pk:
                self.fields["processi_richiedenti"].initial = list(
                    self.instance.processi_richiedenti.values_list("pk", flat=True))
        except Exception:
            pass

    def salva_processi(self, corso) -> None:
        """Persiste il reverse-M2M dei processi qualificati che richiedono il corso.

        Va chiamato dalla view dopo il salvataggio del corso (il create usa
        ``save(commit=False)`` senza ``save_m2m``)."""
        if "processi_richiedenti" in self.fields:
            corso.processi_richiedenti.set(self.cleaned_data.get("processi_richiedenti") or [])

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


# ── E-learning: slide e quiz dei micro-corsi ───────────────────────────────

class TrainingSlideForm(forms.ModelForm):
    class Meta:
        model = TrainingSlide
        fields = ["titolo", "ordine", "contenuto", "is_active"]
        widgets = {
            "titolo":    forms.TextInput(attrs=_FM),
            "ordine":    forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "1"}),
            "contenuto": forms.Textarea(attrs={**_FM_TEXTAREA, "rows": 10}),
            "is_active": forms.CheckboxInput(attrs=_FM_CHECK),
        }
        help_texts = {
            "contenuto": "Markdown: # titolo, **grassetto**, *corsivo*, liste con - , link [testo](https://…).",
        }


class TrainingQuizQuestionForm(forms.ModelForm):
    class Meta:
        model = TrainingQuizQuestion
        fields = ["testo", "ordine", "is_active"]
        widgets = {
            "testo":     forms.Textarea(attrs={**_FM_TEXTAREA, "rows": 2}),
            "ordine":    forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "1"}),
            "is_active": forms.CheckboxInput(attrs=_FM_CHECK),
        }


class TrainingQuizOptionForm(forms.ModelForm):
    class Meta:
        model = TrainingQuizOption
        fields = ["testo", "ordine", "corretta"]
        widgets = {
            "testo":    forms.TextInput(attrs=_FM),
            "ordine":   forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "1"}),
            "corretta": forms.CheckboxInput(attrs=_FM_CHECK),
        }


class ElearningConfigForm(forms.ModelForm):
    class Meta:
        model = ElearningConfig
        fields = ["quiz_punteggio_minimo_default", "validita_mesi_default", "max_tentativi_quiz", "libreoffice_path"]
        widgets = {
            "quiz_punteggio_minimo_default": forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0", "max": "100"}),
            "validita_mesi_default":         forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0"}),
            "max_tentativi_quiz":            forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0"}),
            "libreoffice_path":              forms.TextInput(attrs=_FM),
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
        # Codice edizione e data di fine sono ricavabili: lasciarli vuoti non deve
        # bloccare il salvataggio (codice = <CORSO>-E<N>, fine = inizio per la
        # sessione di un solo giorno). Vedi services.formazione_pianificazione.
        self.fields["codice_sessione"].required = False
        self.fields["codice_sessione"].help_text = (
            "Vuoto = generato dal codice corso (es. SIC-01-E1)."
        )
        self.fields["data_fine"].required = False
        self.fields["data_fine"].help_text = "Vuoto = sessione di un solo giorno."

    def clean(self):
        cd = super().clean()
        d_inizio = cd.get("data_inizio")
        d_fine   = cd.get("data_fine")
        if d_inizio and not d_fine:
            cd["data_fine"] = d_fine = d_inizio
        if d_inizio and d_fine and d_fine < d_inizio:
            raise forms.ValidationError("La data di fine non può essere precedente alla data di inizio.")
        # Codice edizione automatico dal corso quando non digitato.
        if not (cd.get("codice_sessione") or "").strip() and cd.get("corso"):
            from .services.formazione_pianificazione import genera_codice_sessione
            cd["codice_sessione"] = genera_codice_sessione(cd["corso"])
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


class _TrainingOrarioMixin(forms.Form):
    """Orario-tipo di una giornata d'aula: inizio, fine e pausa non formativa.

    Le ore **formative** sono al netto della pausa (08:00–17:00 con 60′ = 8 ore):
    la stessa regola di ``TrainingLesson.durata_ore``, applicata qui prima ancora
    che la lezione esista."""

    ora_inizio = forms.TimeField(
        label="Ora inizio", required=False, initial="08:00",
        widget=forms.TimeInput(attrs={**_FM, "type": "time"}, format="%H:%M"),
    )
    ora_fine = forms.TimeField(
        label="Ora fine", required=False, initial="17:00",
        widget=forms.TimeInput(attrs={**_FM, "type": "time"}, format="%H:%M"),
    )
    pausa_minuti = forms.IntegerField(
        label="Pausa (minuti)", required=False, initial=60, min_value=0, max_value=480,
        help_text="Interruzione non formativa (pausa pranzo): viene scalata dalle ore del corso.",
        widget=forms.NumberInput(attrs={**_FM_NUMBER, "step": "15", "min": "0", "max": "480"}),
    )

    def _valida_orario(self, cd: dict) -> None:
        """Coerenza inizio/fine/pausa. Non impone la presenza degli orari: chi
        estende decide se sono obbligatori."""
        t_i, t_f = cd.get("ora_inizio"), cd.get("ora_fine")
        pausa = cd.get("pausa_minuti") or 0
        if t_i and t_f and t_f <= t_i:
            self.add_error("ora_fine", "L'ora di fine deve essere successiva all'ora di inizio.")
            return
        if t_i and t_f and pausa:
            minuti_aula = (t_f.hour * 60 + t_f.minute) - (t_i.hour * 60 + t_i.minute)
            if pausa >= minuti_aula:
                self.add_error(
                    "pausa_minuti",
                    f"La pausa ({pausa}′) non può coprire tutta la giornata ({minuti_aula}′ in aula).",
                )


GIORNI_SETTIMANA_CHOICES = [
    ("0", "Lun"), ("1", "Mar"), ("2", "Mer"), ("3", "Gio"),
    ("4", "Ven"), ("5", "Sab"), ("6", "Dom"),
]
_GIORNI_FERIALI = ["0", "1", "2", "3", "4"]


def _parse_date_puntuali(testo: str) -> list:
    """Converte «una data per riga» (gg/mm/aaaa, aaaa-mm-gg o gg-mm-aaaa) in date.

    Righe vuote ignorate. Solleva ``ValueError`` col testo della riga incriminata,
    così il chiamante può segnalare quale riga non si capisce.
    """
    import datetime as _dt

    date_lista = []
    for riga in (testo or "").splitlines():
        riga = riga.strip()
        if not riga:
            continue
        parsed = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                parsed = _dt.datetime.strptime(riga, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError(riga)
        date_lista.append(parsed)
    return sorted(set(date_lista))


class TrainingSessioneUnicaForm(_TrainingOrarioMixin):
    """Blocco «Programmazione» del wizard nuovo corso: la sessione unica.

    Opzionale per costruzione — se ``pianifica`` è spento il corso nasce senza
    edizioni (corso a catalogo, o corso esterno di cui si registrerà solo il
    completamento). Se acceso, corso + sessione + giornate nascono insieme.
    Usare con ``prefix='sess'`` per non collidere coi campi del corso."""

    pianifica = forms.BooleanField(
        label="Pianifica subito la sessione unica", required=False,
        help_text="Crea insieme al corso la sua unica edizione, con le giornate già a calendario.",
        widget=forms.CheckboxInput(attrs=_FM_CHECK),
    )
    data_inizio = forms.DateField(
        label="Data", required=False,
        widget=forms.DateInput(attrs=_FM_DATE),
    )
    data_fine = forms.DateField(
        label="Data fine", required=False,
        help_text="Vuoto = corso di un solo giorno.",
        widget=forms.DateInput(attrs=_FM_DATE),
    )
    modalita = forms.ChoiceField(
        label="Modalità", required=False, initial="IN_SEDE",
        choices=TrainingSession.MODALITA_CHOICES,
        widget=forms.Select(attrs=_FM_SELECT),
    )
    sede = forms.CharField(
        label="Sede", required=False, max_length=200,
        help_text="Aula, indirizzo o link remoto.",
        widget=forms.TextInput(attrs=_FM),
    )
    docente = forms.ModelChoiceField(
        label="Docente", required=False, queryset=TrainingInstructor.objects.none(),
        widget=forms.Select(attrs=_FM_SELECT),
    )
    giorni_settimana = forms.MultipleChoiceField(
        label="Giorni della settimana", required=False, choices=GIORNI_SETTIMANA_CHOICES,
        initial=_GIORNI_FERIALI,
        help_text="Solo questi giorni, dentro l'intervallo sopra, generano una lezione — utile "
                  "per un corso settimanale (es. solo Mar e Gio). Ignorato se compili «Date puntuali».",
        widget=forms.CheckboxSelectMultiple,
    )
    date_puntuali = forms.CharField(
        label="Date puntuali (facoltativo)", required=False,
        help_text="Clicca le giornate sul calendario (selezione multipla), per lezioni non "
                  "consecutive: sostituisce l'intervallo e i giorni della settimana sopra.",
        widget=forms.Textarea(attrs={
            **_FM, "class": _FM["class"] + " js-datepicker-multi", "rows": 2,
            "placeholder": "06/06/2026\n13/06/2026\n02/07/2026",
        }),
    )
    n_gruppi = forms.IntegerField(
        label="Numero di gruppi", required=False, initial=1, min_value=1, max_value=10,
        help_text="Più di 1 = il corso nasce già diviso in gruppi paralleli (stesso programma, "
                  "iscritti separati) — utile quando l'aula non li contiene tutti insieme. "
                  "Le date dei gruppi successivi si aggiustano dal dettaglio sessione.",
        widget=forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "1", "max": "10"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["docente"].queryset = TrainingInstructor.objects.filter(is_active=True).order_by("nome")
        self.fields["docente"].empty_label = "— Nessuno —"

    def clean(self):
        cd = super().clean()
        if not cd.get("pianifica"):
            return cd
        try:
            cd["date_puntuali_lista"] = _parse_date_puntuali(cd.get("date_puntuali") or "")
        except ValueError as exc:
            self.add_error("date_puntuali", f"Data non valida: «{exc}». Usa il formato gg/mm/aaaa.")
            cd["date_puntuali_lista"] = []
        usa_date_puntuali = bool(cd["date_puntuali_lista"])
        if not usa_date_puntuali and not cd.get("data_inizio"):
            self.add_error(
                "data_inizio",
                "Indica la data della sessione, elenca le date puntuali, o togli la spunta «Pianifica subito».",
            )
        if not cd.get("ora_inizio") or not cd.get("ora_fine"):
            self.add_error("ora_fine", "Indica l'orario della giornata (o togli la spunta «Pianifica subito»).")
        d_i, d_f = cd.get("data_inizio"), cd.get("data_fine")
        if not usa_date_puntuali:
            if d_i and not d_f:
                cd["data_fine"] = d_f = d_i
            if d_i and d_f and d_f < d_i:
                self.add_error("data_fine", "La data di fine non può essere precedente alla data di inizio.")
            if not cd.get("giorni_settimana"):
                self.add_error(
                    "giorni_settimana",
                    "Seleziona almeno un giorno della settimana, o elenca le date puntuali.",
                )
        self._valida_orario(cd)
        return cd

    @property
    def ore_giornata(self) -> float:
        """Ore formative di una giornata secondo i dati validati (0 se incompleti)."""
        cd = getattr(self, "cleaned_data", None) or {}
        if not cd.get("ora_inizio") or not cd.get("ora_fine"):
            return 0.0
        from .services.formazione_pianificazione import ore_nette
        return ore_nette(cd["ora_inizio"], cd["ora_fine"], cd.get("pausa_minuti") or 0)


class TrainingLezioniGeneraForm(_TrainingOrarioMixin):
    """Generatore di giornate su una sessione già esistente.

    Sforna una lezione per giorno dell'intervallo della sessione con lo stesso
    orario-tipo: sostituisce l'inserimento a mano di dieci giornate identiche."""

    argomento = forms.CharField(
        label="Argomento", required=False, max_length=500,
        help_text="Vuoto = titolo del corso.",
        widget=forms.TextInput(attrs=_FM),
    )
    docente = forms.ModelChoiceField(
        label="Docente", required=False, queryset=TrainingInstructor.objects.none(),
        widget=forms.Select(attrs=_FM_SELECT),
    )
    giorni_settimana = forms.MultipleChoiceField(
        label="Giorni della settimana", required=False, choices=GIORNI_SETTIMANA_CHOICES,
        initial=_GIORNI_FERIALI,
        help_text="Solo questi giorni, dentro l'intervallo già impostato sulla sessione, generano "
                  "una lezione. Ignorato se compili «Date puntuali».",
        widget=forms.CheckboxSelectMultiple,
    )
    date_puntuali = forms.CharField(
        label="Date puntuali (facoltativo)", required=False,
        help_text="Clicca le giornate sul calendario: aggiunge solo quelle, anche fuori "
                  "dall'intervallo attuale della sessione (che si allarga di conseguenza).",
        widget=forms.Textarea(attrs={
            **_FM, "class": _FM["class"] + " js-datepicker-multi", "rows": 2,
            "placeholder": "06/06/2026\n13/06/2026",
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["docente"].queryset = TrainingInstructor.objects.filter(is_active=True).order_by("nome")
        self.fields["docente"].empty_label = "— Come la sessione —"

    def clean(self):
        cd = super().clean()
        if not cd.get("ora_inizio") or not cd.get("ora_fine"):
            raise forms.ValidationError("Indica l'orario di inizio e di fine della giornata-tipo.")
        try:
            cd["date_puntuali_lista"] = _parse_date_puntuali(cd.get("date_puntuali") or "")
        except ValueError as exc:
            self.add_error("date_puntuali", f"Data non valida: «{exc}». Usa il formato gg/mm/aaaa.")
            cd["date_puntuali_lista"] = []
        if not cd["date_puntuali_lista"] and not cd.get("giorni_settimana"):
            self.add_error(
                "giorni_settimana",
                "Seleziona almeno un giorno della settimana, o elenca le date puntuali.",
            )
        self._valida_orario(cd)
        return cd


class TrainingDividiGruppiForm(forms.Form):
    """Divide gli iscritti già presenti in una sessione fra più gruppi logistici.

    Il caso che risolve: un corso apre con 10 iscritti su un'unica sessione, ma
    l'aula (o il turno di lavoro) non li contiene tutti insieme — servono 2 gruppi
    da 5, ciascuno con il proprio calendario. Vedi
    ``services.formazione_pianificazione.dividi_in_gruppi``."""

    n_gruppi = forms.IntegerField(
        label="Numero di gruppi", min_value=2, max_value=10, initial=2,
        widget=forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "2", "max": "10"}),
    )
    edizione = forms.CharField(
        label="Edizione", required=False, max_length=80,
        help_text="Etichetta che collega i gruppi (es. «2026 · 1° semestre»). Vuota = generata automaticamente.",
        widget=forms.TextInput(attrs=_FM),
    )
    giorni_tra_gruppi = forms.IntegerField(
        label="Sfasamento fra un gruppo e il successivo (giorni)", required=False, initial=0,
        min_value=0, max_value=365,
        help_text="0 = stesse date per tutti i gruppi (cambia solo aula/turno). "
                  "Un valore > 0 sposta ogni gruppo successivo di quel numero di giorni "
                  "rispetto al precedente, lezioni comprese.",
        widget=forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "0"}),
    )

    def clean_edizione(self):
        return (self.cleaned_data.get("edizione") or "").strip()


class TrainingCompletamentoDirettoForm(forms.Form):
    """Completamento registrato **senza sessione** (corso già frequentato altrove).

    Non tutti i corsi passano dall'aula interna: un attestato preso presso un ente
    esterno, o un corso storico, va a libretto senza inventare una sessione e un
    registro presenze fittizi. ``TrainingEmployeeRecord.sessione`` è nullable
    proprio per questo. I dipendenti arrivano dal POST (``dipendenti_selezionati``)
    come nel resto della sezione."""

    data_completamento = forms.DateField(
        label="Data completamento",
        widget=forms.DateInput(attrs=_FM_DATE),
    )
    ore_frequentate = forms.DecimalField(
        label="Ore frequentate", required=False, min_value=0, max_digits=7, decimal_places=2,
        help_text="Vuoto = durata teorica del corso.",
        widget=forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.5", "min": "0"}),
    )
    erogato_da = forms.CharField(
        label="Ente / docente erogatore", required=False, max_length=200,
        help_text="Chi ha erogato il corso (resta a storico sull'attestato).",
        widget=forms.TextInput(attrs=_FM),
    )
    idoneo = forms.BooleanField(
        label="Esito positivo (idoneo)", required=False, initial=True,
        widget=forms.CheckboxInput(attrs=_FM_CHECK),
    )
    note = forms.CharField(
        label="Note", required=False,
        widget=forms.Textarea(attrs={**_FM_TEXTAREA, "rows": 2}),
    )

    def clean_data_completamento(self):
        from django.utils import timezone as _tz
        data = self.cleaned_data["data_completamento"]
        if data > _tz.localdate():
            raise forms.ValidationError("La data di completamento non può essere nel futuro.")
        return data


class TrainingEnrollmentEditForm(forms.ModelForm):
    """Modifica stato iscrizione e dati di completamento."""

    class Meta:
        model = TrainingEnrollment
        fields = [
            "stato", "ore_frequentate",
            "percentuale_presenza", "idoneo",
            "verifica_superata", "data_verifica",
            "esito_esame", "data_completamento", "note",
        ]
        widgets = {
            "stato":                forms.Select(attrs=_FM_SELECT),
            "ore_frequentate":      forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.5", "min": "0"}),
            "percentuale_presenza": forms.NumberInput(attrs={**_FM_NUMBER, "step": "0.01", "min": "0", "max": "100"}),
            "idoneo":               forms.CheckboxInput(attrs=_FM_CHECK),
            "verifica_superata":    forms.CheckboxInput(attrs=_FM_CHECK),
            "data_verifica":        forms.DateInput(attrs=_FM_DATE),
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
            "numero", "data", "ora_inizio", "ora_fine", "pausa_minuti",
            "argomento", "docente", "docente_nome", "note",
        ]
        widgets = {
            "numero":      forms.NumberInput(attrs={**_FM_NUMBER, "step": "1", "min": "1"}),
            "data":        forms.DateInput(attrs=_FM_DATE),
            "ora_inizio":  forms.TimeInput(attrs={**_FM, "type": "time"}),
            "ora_fine":    forms.TimeInput(attrs={**_FM, "type": "time"}),
            "pausa_minuti": forms.NumberInput(attrs={**_FM_NUMBER, "step": "15", "min": "0", "max": "480"}),
            "argomento":   forms.TextInput(attrs=_FM),
            "docente":     forms.Select(attrs=_FM_SELECT),
            "docente_nome": forms.TextInput(attrs=_FM),
            "note":        forms.Textarea(attrs=_FM_TEXTAREA),
        }
        labels = {"pausa_minuti": "Pausa (minuti)"}

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
        # La pausa non può divorare l'intera lezione (durata formativa nulla).
        pausa = cd.get("pausa_minuti") or 0
        if t_inizio and t_fine and t_fine > t_inizio and pausa:
            minuti_aula = (t_fine.hour * 60 + t_fine.minute) - (t_inizio.hour * 60 + t_inizio.minute)
            if pausa >= minuti_aula:
                self.add_error(
                    "pausa_minuti",
                    f"La pausa ({pausa}′) non può coprire tutta la lezione ({minuti_aula}′ in aula).",
                )
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


# ── Skill Matrix MOD.187 — configurazione (singleton) ──────────────────────────
class SkillMatrixConfigForm(forms.ModelForm):
    """Form di gestione del singleton ``SkillMatrixConfig``.

    Espone i parametri che governano "operativo" (soglia livello, CAR come
    riserva), il rischio uomo-solo, le cadenze di continuità/refresh e le
    etichette della scala. Gated in view da ``anagrafica.skillmatrix.manage``.
    """

    class Meta:
        model = SkillMatrixConfig
        fields = [
            "soglia_operativa", "includi_car_come_riserva", "regola_multivoce",
            "soglia_uomo_solo", "finestra_continuita_mesi", "preavviso_continuita_mesi",
            "periodicita_refresh_mesi", "preavviso_refresh_giorni",
            "etichetta_i", "etichetta_l", "etichetta_u", "etichetta_o",
        ]
        widgets = {
            "soglia_operativa": forms.Select(attrs={"class": "ana-input"}),
            "regola_multivoce": forms.Select(attrs={"class": "ana-input"}),
            "includi_car_come_riserva": forms.CheckboxInput(attrs={"class": "ana-check"}),
            "soglia_uomo_solo": forms.NumberInput(attrs={"class": "ana-input", "min": 1}),
            "finestra_continuita_mesi": forms.NumberInput(attrs={"class": "ana-input", "min": 0}),
            "preavviso_continuita_mesi": forms.NumberInput(attrs={"class": "ana-input", "min": 0}),
            "periodicita_refresh_mesi": forms.NumberInput(attrs={"class": "ana-input", "min": 0}),
            "preavviso_refresh_giorni": forms.NumberInput(attrs={"class": "ana-input", "min": 0}),
            "etichetta_i": forms.TextInput(attrs={"class": "ana-input"}),
            "etichetta_l": forms.TextInput(attrs={"class": "ana-input"}),
            "etichetta_u": forms.TextInput(attrs={"class": "ana-input"}),
            "etichetta_o": forms.TextInput(attrs={"class": "ana-input"}),
        }

    def clean_soglia_uomo_solo(self):
        v = self.cleaned_data.get("soglia_uomo_solo")
        if v is not None and v < 1:
            raise forms.ValidationError("La soglia uomo-solo deve essere almeno 1.")
        return v
