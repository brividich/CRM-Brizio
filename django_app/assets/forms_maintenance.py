"""Form del nuovo dominio manutenzione (Piano / Applicazione / Occorrenza / Gruppi).

Modulo separato da ``forms.py`` di proposito: quel file ha gia' superato le 3.000
righe ed e' toccato da piu' rami in parallelo. Qui dentro sta solo il nuovo
dominio, cosi' resta leggibile e i conflitti di merge non si moltiplicano.

Regola di linguaggio: nella UI non compaiono mai "regola", "override",
"threshold", "scope". Si dice Piano, Applicazione, Personalizzazione, Esclusione,
Periodicita', Preavviso.
"""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from anagrafica.models import Fornitore

from .forms import _attach_input_css
from .models import (
    Asset,
    AssetCategory,
    AssetGroup,
    AssetGroupMembership,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
)
from .services.recurrence import RECURRENCE_PRESETS

CUSTOM_PRESET = "custom"

_RECURRENCE_FIELDS = ("frequency", "interval", "weekday", "week_of_month", "day_of_month", "month_of_year")


def _active_users_queryset():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(is_active=True).order_by("last_name", "first_name", "username")


class MaintenancePlanForm(forms.ModelForm):
    """Passo "Cosa": che lavoro e', chi lo fa di norma, serve un documento."""

    class Meta:
        model = MaintenanceInterventionTemplate
        fields = [
            "label",
            "code",
            "maintenance_type",
            "description",
            "estimated_duration_minutes",
            "required_materials",
            "execution_mode",
            "default_supplier",
            "default_assignee",
            "attachment_required",
            "schedule_anchor",
            "asset_category",
            "sort_order",
            "is_active",
        ]
        labels = {
            "label": "Nome del piano",
            "code": "Codice",
            "maintenance_type": "Tipo",
            "description": "Cosa va fatto",
            "estimated_duration_minutes": "Durata prevista (minuti)",
            "required_materials": "Materiali e attrezzature",
            "execution_mode": "Chi la esegue",
            "default_supplier": "Ditta esterna predefinita",
            "default_assignee": "Manutentore predefinito",
            "attachment_required": "Documento obbligatorio alla chiusura",
            "schedule_anchor": "Da quando riparte la periodicita",
            "asset_category": "Categoria di riferimento",
            "sort_order": "Ordine",
            "is_active": "Attivo",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "required_materials": forms.Textarea(attrs={"rows": 3}),
            "estimated_duration_minutes": forms.NumberInput(attrs={"min": 0, "step": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        self.fields["code"].help_text = "Lascia vuoto: viene generato dal nome."
        self.fields["asset_category"].required = False
        self.fields["asset_category"].queryset = AssetCategory.objects.filter(
            Q(is_active=True) | Q(pk=getattr(self.instance, "asset_category_id", None))
        ).order_by("sort_order", "label", "id")
        self.fields["asset_category"].help_text = (
            "Facoltativa. Il perimetro reale lo decidono le applicazioni del piano."
        )
        self.fields["default_supplier"].required = False
        self.fields["default_supplier"].queryset = Fornitore.objects.order_by("ragione_sociale")
        self.fields["default_assignee"].required = False
        self.fields["default_assignee"].queryset = _active_users_queryset()
        self.fields["schedule_anchor"].required = False
        self.fields["schedule_anchor"].help_text = (
            "Lascia vuoto per il comportamento standard: le manutenzioni ordinarie ripartono dalla data di "
            "esecuzione, le scadenze amministrative restano ancorate alla scadenza teorica."
        )
        self.fields["attachment_required"].help_text = (
            "Sempre attivo sulle scadenze amministrative: senza il documento la scadenza non si chiude."
        )
        self.fields["estimated_duration_minutes"].required = False
        _attach_input_css(self)

    def clean_label(self):
        label = (self.cleaned_data.get("label") or "").strip()
        if not label:
            raise ValidationError("Inserisci il nome del piano.")
        return label

    def clean_estimated_duration_minutes(self):
        return int(self.cleaned_data.get("estimated_duration_minutes") or 0)

    def clean_code(self):
        from django.utils.text import slugify

        code = (self.cleaned_data.get("code") or "").strip()
        if code:
            return code
        base = slugify(self.data.get(self.add_prefix("label"), ""))[:70] or "piano"
        candidate = base
        suffix = 2
        queryset = MaintenanceInterventionTemplate.objects.exclude(pk=self.instance.pk)
        while queryset.filter(code=candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate


class RecurrenceFormMixin:
    """Periodicita' scelta da un elenco leggibile, con la via d'uscita "personalizzata".

    Nessun utente deve comporre a mano sei campi (o peggio una cron) per dire
    "ogni trimestre": si sceglie un preset. I campi grezzi restano disponibili per
    i casi che i preset non coprono.
    """

    def _init_recurrence(self):
        choices = [(key, label) for key, label, _ in RECURRENCE_PRESETS]
        choices.append((CUSTOM_PRESET, "Personalizzata..."))
        self.fields["recurrence_preset"] = forms.ChoiceField(
            choices=choices,
            required=False,
            label="Periodicita",
            help_text="Scegli una periodicita; con 'Personalizzata' compila i campi qui sotto.",
        )
        for name in _RECURRENCE_FIELDS:
            if name in self.fields:
                self.fields[name].required = False
        self.fields["recurrence_preset"].initial = self._detect_preset()

    def _detect_preset(self) -> str:
        instance = getattr(self, "instance", None)
        if instance is None or instance.pk is None:
            return "monthly"
        current = {name: getattr(instance, name, None) for name in _RECURRENCE_FIELDS}
        for key, _label, spec in RECURRENCE_PRESETS:
            candidate = {name: spec.get(name) for name in _RECURRENCE_FIELDS}
            candidate["interval"] = spec.get("interval", 1)
            if all(current.get(name) == candidate.get(name) for name in _RECURRENCE_FIELDS):
                return key
        return CUSTOM_PRESET

    def _apply_recurrence_preset(self, cleaned: dict) -> dict:
        preset_key = cleaned.get("recurrence_preset") or CUSTOM_PRESET
        if preset_key == CUSTOM_PRESET:
            cleaned["interval"] = int(cleaned.get("interval") or 1)
            return cleaned
        spec = next((spec for key, _label, spec in RECURRENCE_PRESETS if key == preset_key), None)
        if spec is None:
            return cleaned
        for name in _RECURRENCE_FIELDS:
            cleaned[name] = spec.get(name) if name != "interval" else spec.get("interval", 1)
        return cleaned


class MaintenancePlanAssignmentForm(RecurrenceFormMixin, forms.ModelForm):
    """Passi "Dove", "Quando" e "Chi": su cosa si applica il piano e con che tempi."""

    class Meta:
        model = MaintenancePlanAssignment
        fields = [
            "target_type",
            "asset",
            "asset_group",
            "asset_category",
            "frequency",
            "interval",
            "weekday",
            "week_of_month",
            "day_of_month",
            "month_of_year",
            "warning_days",
            "schedule_anchor",
            "first_due_date",
            "execution_mode",
            "supplier",
            "assigned_to",
            "auto_generate",
            "is_active",
            "notes",
        ]
        labels = {
            "target_type": "Si applica a",
            "asset": "Asset",
            "asset_group": "Gruppo di asset",
            "asset_category": "Categoria di asset",
            "frequency": "Unita",
            "interval": "Ogni",
            "weekday": "Giorno della settimana",
            "week_of_month": "Settimana del mese",
            "day_of_month": "Giorno del mese",
            "month_of_year": "Mese",
            "warning_days": "Preavviso (giorni)",
            "schedule_anchor": "Da quando riparte la periodicita",
            "first_due_date": "Prima scadenza",
            "execution_mode": "Chi la esegue",
            "supplier": "Ditta esterna",
            "assigned_to": "Manutentore",
            "auto_generate": "Genera le scadenze automaticamente",
            "is_active": "Attiva",
            "notes": "Note",
        }
        widgets = {
            "first_due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, plan: MaintenanceInterventionTemplate | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = plan or getattr(self.instance, "plan", None)
        if self.plan is not None:
            # Va agganciato ORA: la validazione del ModelForm chiama
            # instance.full_clean(), che senza piano fallisce su un campo che
            # l'utente non compila nemmeno.
            self.instance.plan = self.plan
        self._init_recurrence()

        self.fields["asset"].required = False
        self.fields["asset"].queryset = Asset.objects.order_by("asset_tag", "name")
        self.fields["asset_group"].required = False
        self.fields["asset_group"].queryset = AssetGroup.objects.filter(is_active=True).order_by("sort_order", "label")
        self.fields["asset_category"].required = False
        self.fields["asset_category"].queryset = AssetCategory.objects.filter(is_active=True).order_by(
            "sort_order", "label"
        )
        self.fields["supplier"].required = False
        self.fields["supplier"].queryset = Fornitore.objects.order_by("ragione_sociale")
        self.fields["assigned_to"].required = False
        self.fields["assigned_to"].queryset = _active_users_queryset()
        self.fields["schedule_anchor"].required = False
        self.fields["execution_mode"].required = False
        self.fields["first_due_date"].help_text = (
            "Obbligatoria se l'asset non ha storico: senza, la manutenzione risulterebbe "
            "'mai eseguita' e non ci sarebbe modo di risolverla."
        )
        self.fields["warning_days"].help_text = "Da quanti giorni prima la manutenzione diventa pianificabile."
        _attach_input_css(self)

    def clean(self):
        cleaned = super().clean()
        cleaned = self._apply_recurrence_preset(cleaned)

        target_type = cleaned.get("target_type")
        # Solo il bersaglio scelto resta valorizzato: gli altri si azzerano qui,
        # cosi' cambiare "si applica a" nel form non lascia residui.
        keep = {
            MaintenancePlanAssignment.TARGET_ASSET: "asset",
            MaintenancePlanAssignment.TARGET_GROUP: "asset_group",
            MaintenancePlanAssignment.TARGET_CATEGORY: "asset_category",
        }.get(target_type)
        for name in ("asset", "asset_group", "asset_category"):
            if name != keep:
                cleaned[name] = None
        if keep and not cleaned.get(keep):
            self.add_error(keep, "Seleziona su cosa si applica il piano.")

        if not cleaned.get("first_due_date") and not self.instance.pk:
            cleaned["first_due_date"] = timezone.localdate()
        return cleaned

    def save(self, commit=True):
        assignment = super().save(commit=False)
        if self.plan is not None:
            assignment.plan = self.plan
        for name in _RECURRENCE_FIELDS:
            setattr(assignment, name, self.cleaned_data.get(name))
        if commit:
            assignment.save()
        return assignment


class AssetPlanCustomizationForm(RecurrenceFormMixin, forms.ModelForm):
    """Dalla scheda asset: usa il gruppo / personalizza / escludi.

    Un utente che guarda una macchina non deve capire cosa sia un'"applicazione":
    deve poter dire che quella macchina si comporta diversamente, o che il piano
    non la riguarda.
    """

    MODE_INHERIT = "inherit"
    MODE_CUSTOM = "custom"
    MODE_EXCLUDE = "exclude"
    MODE_CHOICES = [
        (MODE_INHERIT, "Usa le impostazioni del gruppo"),
        (MODE_CUSTOM, "Personalizza per questo asset"),
        (MODE_EXCLUDE, "Escludi questo asset dal piano"),
    ]

    mode = forms.ChoiceField(choices=MODE_CHOICES, widget=forms.RadioSelect, label="Comportamento")

    class Meta:
        model = MaintenancePlanAssignment
        fields = [
            "frequency",
            "interval",
            "weekday",
            "week_of_month",
            "day_of_month",
            "month_of_year",
            "warning_days",
            "first_due_date",
            "notes",
        ]
        labels = {
            "interval": "Ogni",
            "frequency": "Unita",
            "warning_days": "Preavviso (giorni)",
            "first_due_date": "Prima scadenza",
            "notes": "Motivo / nota",
        }
        widgets = {
            "first_due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, plan=None, asset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = plan or getattr(self.instance, "plan", None)
        self.asset = asset or getattr(self.instance, "asset", None)
        # Piano, asset e bersaglio non sono campi del form: si fissano qui, prima
        # che _post_clean validi l'istanza.
        if self.plan is not None:
            self.instance.plan = self.plan
        if self.asset is not None:
            self.instance.asset = self.asset
        self.instance.target_type = MaintenancePlanAssignment.TARGET_ASSET
        self._init_recurrence()
        if self.instance.pk:
            self.fields["mode"].initial = self.MODE_EXCLUDE if self.instance.is_excluded else self.MODE_CUSTOM
        else:
            self.fields["mode"].initial = self.MODE_CUSTOM
        _attach_input_css(self)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("mode") == self.MODE_CUSTOM:
            cleaned = self._apply_recurrence_preset(cleaned)
        return cleaned

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.plan = self.plan
        assignment.asset = self.asset
        assignment.target_type = MaintenancePlanAssignment.TARGET_ASSET
        assignment.asset_group = None
        assignment.asset_category = None
        mode = self.cleaned_data.get("mode")
        assignment.is_excluded = mode == self.MODE_EXCLUDE
        if not assignment.is_excluded:
            for name in _RECURRENCE_FIELDS:
                setattr(assignment, name, self.cleaned_data.get(name))
        if commit:
            assignment.save()
        return assignment


class AssetGroupForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=Asset.objects.none(),
        required=False,
        label="Asset del gruppo",
        widget=forms.SelectMultiple(attrs={"size": 14}),
    )

    class Meta:
        model = AssetGroup
        fields = ["label", "code", "description", "sort_order", "is_active"]
        labels = {
            "label": "Nome del gruppo",
            "code": "Codice",
            "description": "Descrizione",
            "sort_order": "Ordine",
            "is_active": "Attivo",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        self.fields["code"].help_text = "Lascia vuoto: viene generato dal nome."
        self.fields["members"].queryset = Asset.objects.order_by("asset_tag", "name")
        if self.instance.pk:
            self.fields["members"].initial = list(self.instance.assets.values_list("pk", flat=True))
        _attach_input_css(self)

    def clean_code(self):
        from django.utils.text import slugify

        code = (self.cleaned_data.get("code") or "").strip()
        if code:
            return code
        base = slugify(self.data.get(self.add_prefix("label"), ""))[:70] or "gruppo"
        candidate = base
        suffix = 2
        queryset = AssetGroup.objects.exclude(pk=self.instance.pk)
        while queryset.filter(code=candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def save(self, commit=True, user=None):
        group = super().save(commit=commit)
        if not commit:
            return group
        wanted = {asset.pk for asset in self.cleaned_data.get("members", [])}
        current = set(group.assets.values_list("pk", flat=True))
        AssetGroupMembership.objects.filter(group=group, asset_id__in=current - wanted).delete()
        AssetGroupMembership.objects.bulk_create(
            [
                AssetGroupMembership(group=group, asset_id=asset_id, created_by=user)
                for asset_id in wanted - current
            ]
        )
        return group


class OccurrenceCompletionForm(forms.Form):
    """Chiusura di UNA manutenzione su UN asset: la chiusura non e' mai di lotto."""

    completed_on = forms.DateField(
        label="Eseguita il",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    notes = forms.CharField(label="Note", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    downtime_minutes = forms.IntegerField(
        label="Fermo macchina (minuti)", required=False, min_value=0, initial=0
    )
    report_received_at = forms.DateField(
        label="Rapporto ricevuto il",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    attachment = forms.FileField(label="Rapporto / documento", required=False)

    def __init__(self, *args, occurrence: MaintenanceOccurrence | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.occurrence = occurrence
        self.fields["completed_on"].initial = timezone.localdate()
        if occurrence is not None and not occurrence.is_external:
            del self.fields["report_received_at"]
        if occurrence is not None and occurrence.attachment_required:
            self.fields["attachment"].help_text = (
                "Obbligatorio: senza il documento aggiornato questa scadenza non si chiude."
            )
        _attach_input_css(self)

    def clean(self):
        cleaned = super().clean()
        occurrence = self.occurrence
        if occurrence is None:
            return cleaned
        if occurrence.attachment_required and not cleaned.get("attachment") and not occurrence.attachments.exists():
            self.add_error(
                "attachment",
                "Per completare questa scadenza e obbligatorio allegare il documento aggiornato.",
            )
        completed_on = cleaned.get("completed_on")
        if completed_on and completed_on > timezone.localdate():
            self.add_error("completed_on", "La data di esecuzione non puo essere nel futuro.")
        return cleaned


class WorkOrderFromOccurrencesForm(forms.Form):
    """Raccolta di piu' manutenzioni dovute in un unico ordine di lavoro."""

    title = forms.CharField(label="Titolo", required=False, max_length=255)
    assigned_to = forms.ModelChoiceField(queryset=None, required=False, label="Assegna a")
    supplier = forms.ModelChoiceField(queryset=None, required=False, label="Ditta esterna")
    due_at = forms.DateField(
        label="Da concludere entro",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = _active_users_queryset()
        self.fields["supplier"].queryset = Fornitore.objects.order_by("ragione_sociale")
        self.fields["title"].help_text = "Lascia vuoto per generarlo dal piano e dal numero di asset."
        _attach_input_css(self)


class ExecutionDayForm(forms.Form):
    execution_date = forms.DateField(
        label="Giornata",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["execution_date"].initial = timezone.localdate()
        _attach_input_css(self)


class FollowUpForm(forms.Form):
    """Follow-up di un'anomalia trovata durante la manutenzione.

    "Manutenzione eseguita" e "problema risolto" restano due cose distinte: la
    periodicita' avanza lo stesso, il problema diventa un intervento a parte.
    """

    title = forms.CharField(label="Titolo", max_length=255)
    reason = forms.CharField(label="Anomalia rilevata", widget=forms.Textarea(attrs={"rows": 3}))
    assigned_to = forms.ModelChoiceField(queryset=None, required=False, label="Assegna a")
    due_at = forms.DateField(
        label="Da verificare entro",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = _active_users_queryset()
        _attach_input_css(self)


class OccurrenceFilterForm(forms.Form):
    """Filtri condivisi da "Da fare", "Scadenze" e dashboard responsabile."""

    WINDOW_CHOICES = [
        ("", "Tutte"),
        ("overdue", "Scadute"),
        ("7", "Entro 7 giorni"),
        ("30", "Entro 30 giorni"),
        ("90", "Entro 90 giorni"),
    ]
    TYPE_CHOICES = [
        ("", "Tutti i tipi"),
        ("ordinary", "Ordinarie"),
        ("administrative", "Amministrative"),
    ]
    MODE_CHOICES = [
        ("", "Interne ed esterne"),
        ("INTERNAL", "Interne"),
        ("EXTERNAL", "Esterne"),
    ]
    PLANNING_CHOICES = [
        ("", "Con e senza OdL"),
        ("unplanned", "Senza ordine di lavoro"),
        ("planned", "Gia in un ordine di lavoro"),
    ]

    q = forms.CharField(label="Cerca", required=False)
    window = forms.ChoiceField(choices=WINDOW_CHOICES, required=False, label="Scadenza")
    plan = forms.ModelChoiceField(queryset=None, required=False, label="Piano", empty_label="Tutti i piani")
    group = forms.ModelChoiceField(queryset=None, required=False, label="Gruppo", empty_label="Tutti i gruppi")
    asset = forms.ModelChoiceField(queryset=None, required=False, label="Asset", empty_label="Tutti gli asset")
    reparto = forms.ChoiceField(choices=[], required=False, label="Reparto")
    plan_type = forms.ChoiceField(choices=TYPE_CHOICES, required=False, label="Tipo")
    execution_mode = forms.ChoiceField(choices=MODE_CHOICES, required=False, label="Esecuzione")
    planning = forms.ChoiceField(choices=PLANNING_CHOICES, required=False, label="Pianificazione")
    assignee = forms.ModelChoiceField(queryset=None, required=False, label="Assegnatario", empty_label="Chiunque")
    supplier = forms.ModelChoiceField(queryset=None, required=False, label="Fornitore", empty_label="Tutti")
    report_missing = forms.BooleanField(required=False, label="Solo rapporto mancante")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = MaintenanceInterventionTemplate.objects.filter(is_active=True).order_by(
            "sort_order", "label"
        )
        self.fields["group"].queryset = AssetGroup.objects.filter(is_active=True).order_by("sort_order", "label")
        self.fields["asset"].queryset = Asset.objects.order_by("asset_tag", "name")
        self.fields["assignee"].queryset = _active_users_queryset()
        self.fields["supplier"].queryset = Fornitore.objects.order_by("ragione_sociale")
        reparti = (
            Asset.objects.exclude(reparto="")
            .values_list("reparto", flat=True)
            .order_by("reparto")
            .distinct()
        )
        self.fields["reparto"].choices = [("", "Tutti i reparti")] + [(value, value) for value in reparti]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "")
        _attach_input_css(self)
