from __future__ import annotations

from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.db.models import Q

from core.legacy_models import UtenteLegacy
from core.upload_mime import (
    UploadMimeValidationError,
    safe_filename,
    validate_extension_and_mime,
)
from attrezzature.models import Attrezzatura


# Allegati task/progetto: 30 MB, formati office/immagini/PDF.
TASKS_ATTACHMENT_MAX_BYTES = 30 * 1024 * 1024
TASKS_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
    ".zip",
}
TASKS_ATTACHMENT_MIMES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}

from .models import (
    KickoffMeeting, Project, ProjectComment, SubTask, Task, TaskAttachment,
    TaskCategory, TaskComment, TaskPriority, TaskRoleAssignment, TaskRoleType,
    TaskStatus,
)


def task_active_users_queryset():
    """Utenti Django assegnabili nei task, allineati agli utenti portale attivi.

    La gestione utenti admin lavora sulla tabella legacy `utenti` (`attivo`).
    I form Django pero' salvano FK verso `auth_user`, quindi mostriamo gli
    utenti Django collegati a legacy attivi. Se il mapping legacy non e'
    disponibile (test/dev minimale), fallback non bloccante agli auth_user attivi.
    """
    base_qs = User.objects.filter(is_active=True).select_related("profile")
    try:
        active_legacy_ids = list(
            UtenteLegacy.objects.filter(attivo=True).values_list("id", flat=True)
        )
    except DatabaseError:
        return base_qs.order_by("first_name", "last_name", "username")
    if not active_legacy_ids:
        return base_qs.order_by("first_name", "last_name", "username")
    mapped_qs = base_qs.filter(profile__legacy_user_id__in=active_legacy_ids)
    if not mapped_qs.exists():
        return base_qs.order_by("first_name", "last_name", "username")
    return mapped_qs.order_by("first_name", "last_name", "username")


def _users_for_role(role_type: str):
    """Ritorna queryset utenti abilitati per un ruolo operativo kickoff.

    Se nessun utente e' mappato per il ruolo, fallback a tutti gli utenti
    (ordine coerente) per non bloccare l'operativita' quando la mappatura
    admin non e' ancora stata completata.
    """
    assigned = User.objects.filter(
        task_role_assignments__role_type=role_type,
    ).distinct()
    if assigned.exists():
        return assigned.order_by("first_name", "last_name", "username")
    return User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")


def _users_for_capo_commessa():
    """Utenti capocommessa/caporeparto: da anagrafica o da assignment in base al setting."""
    from .models import TaskImpostazioni
    cfg = TaskImpostazioni.get_singleton()
    if cfg.roles_source == "anagrafica":
        try:
            from anagrafica.models import Reparto
            ids = set(
                Reparto.objects.filter(is_active=True, caporeparto_legacy_id__isnull=False)
                .exclude(caporeparto_legacy_id=0)
                .values_list("caporeparto_legacy_id", flat=True)
            )
            if ids:
                qs = User.objects.filter(
                    profile__legacy_user_id__in=ids,
                    is_active=True,
                ).distinct().order_by("first_name", "last_name", "username")
                if qs.exists():
                    return qs
        except Exception:
            pass
    return _users_for_role(TaskRoleType.CAPO_COMMESSA)

User = get_user_model()


def _project_option_label(project: Project) -> str:
    parts: list[str] = [project.name]
    if project.part_number:
        parts.append(f"P/N {project.part_number}")
    if project.revisione:
        parts.append(f"Rev {project.revisione}")
    if project.versione:
        parts.append(f"Ver {project.versione}")
    if project.client_name:
        parts.append(f"Cliente {project.client_name}")
    return " | ".join(parts)


class ProjectChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return _project_option_label(obj)


class ProjectKickoffForm(forms.ModelForm):
    """Form dedicato alla creazione di un kickoff (Project) senza task.

    Usato dal flow /tasks/projects/new/: anagrafica kickoff -> redirect al
    vrf_compile -> redirect al gantt con CTA 'aggiungi prima attivita'.
    La duplicate-identity logica (stesso P/N + rev + versione) viene
    intercettata in clean() e restituita via reuse_existing_project per
    consentire alla view di redirigere al kickoff gia esistente.
    """

    project_manager = forms.ModelChoiceField(
        required=False, queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Project manager",
    )
    capo_commessa = forms.ModelChoiceField(
        required=False, queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Capocommessa",
    )
    programmer = forms.ModelChoiceField(
        required=False, queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Programmatore",
    )

    class Meta:
        model = Project
        fields = [
            "client_name",
            "part_number",
            "revisione",
            "versione",
            "description",
            "control_method",
            "safety_impact",
            "vrf_quote_number",
            "vrf_description",
            "vrf_esp",
        ]
        widgets = {
            "client_name":      forms.TextInput(attrs={"class": "input", "maxlength": 180, "placeholder": "Cliente"}),
            "part_number":      forms.TextInput(attrs={"class": "input", "maxlength": 120, "placeholder": "P/N"}),
            "revisione":        forms.TextInput(attrs={"class": "input", "maxlength": 60,  "placeholder": "es. A, B, 01"}),
            "versione":         forms.TextInput(attrs={"class": "input", "maxlength": 60,  "placeholder": "es. 1.0, 2.3"}),
            "description":      forms.Textarea(attrs={"class": "input", "rows": 2, "placeholder": "Descrizione kickoff (opzionale)"}),
            "control_method":   forms.TextInput(attrs={"class": "input", "maxlength": 180, "placeholder": "Metodo di controllo"}),
            "safety_impact":    forms.CheckboxInput(attrs={"class": "input-checkbox"}),
            "vrf_quote_number": forms.TextInput(attrs={"class": "input", "maxlength": 120, "placeholder": "Preventivo n."}),
            "vrf_description":  forms.TextInput(attrs={"class": "input", "maxlength": 500, "placeholder": "Descrizione scheda VRF"}),
            "vrf_esp":          forms.TextInput(attrs={"class": "input", "maxlength": 120, "placeholder": "Esp"}),
        }

    def __init__(self, *args, project_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.reused_existing_project: Project | None = None
        self.project_queryset = project_queryset if project_queryset is not None else Project.objects.all()
        self.fields["project_manager"].queryset = _users_for_role(TaskRoleType.PROJECT_MANAGER)
        self.fields["capo_commessa"].queryset   = _users_for_capo_commessa()
        self.fields["programmer"].queryset      = _users_for_role(TaskRoleType.PROGRAMMER)
        for name in ("part_number", "revisione", "versione",
                     "description", "control_method", "vrf_quote_number",
                     "vrf_description", "vrf_esp"):
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        part_number = (cleaned.get("part_number") or "").strip()
        revisione   = (cleaned.get("revisione") or "").strip()
        versione    = (cleaned.get("versione") or "").strip()

        client_name = (cleaned.get("client_name") or "").strip()
        if not client_name:
            self.add_error("client_name", "Il campo Cliente è obbligatorio.")

        team_filled = any([
            cleaned.get("project_manager"),
            cleaned.get("capo_commessa"),
            cleaned.get("programmer"),
        ])
        if not team_filled:
            raise forms.ValidationError(
                "Almeno un membro del team di progetto (Project manager, Capocommessa o Programmatore) è obbligatorio."
            )

        if (revisione or versione) and not part_number:
            raise forms.ValidationError(
                "Revisione e versione sono valide solo con un P/N indicato."
            )

        if part_number:
            match_qs = self.project_queryset.filter(
                part_number__iexact=part_number,
                revisione__iexact=revisione,
                versione__iexact=versione,
            ).order_by("-updated_at", "-id")
            match = match_qs.first()
            if match is not None:
                self.reused_existing_project = match
        return cleaned

    def save(self, commit=True):
        if self.reused_existing_project is not None:
            return self.reused_existing_project
        project = super().save(commit=False)
        project.project_manager = self.cleaned_data.get("project_manager")
        project.capo_commessa = self.cleaned_data.get("capo_commessa")
        project.programmer = self.cleaned_data.get("programmer")
        if commit:
            project.save()
        return project


class TaskForm(forms.ModelForm):
    TASK_SCOPE_SINGLE = "single"
    TASK_SCOPE_PROJECT = "project"
    TASK_SCOPE_CHOICES = (
        (TASK_SCOPE_SINGLE, "Attivita singola"),
        (TASK_SCOPE_PROJECT, "Attivita in kickoff"),
    )
    PROJECT_LINK_EXISTING = "existing"
    PROJECT_LINK_NEW = "new"
    PROJECT_LINK_MODE_CHOICES = (
        (PROJECT_LINK_EXISTING, "Aggancia a kickoff esistente"),
        (PROJECT_LINK_NEW, "Crea nuovo kickoff"),
    )
    ASSIGNMENT_CONFLICT_KEEP = "keep_priority"
    ASSIGNMENT_CONFLICT_RAISE = "raise_to_high"
    ASSIGNMENT_CONFLICT_CHOICES = (
        (ASSIGNMENT_CONFLICT_KEEP, "Mantieni priorita inserita"),
        (ASSIGNMENT_CONFLICT_RAISE, "Alza priorita a High"),
    )
    TOOLING_NONE = "none"
    TOOLING_LINK_EXISTING = "link_existing"
    TOOLING_REQUEST_NEW = "request_new"
    TOOLING_VERIFICATION_REQUIRED = "verification_required"
    TOOLING_MODE_CHOICES = (
        (TOOLING_NONE, "Nessuna azione attrezzatura"),
        (TOOLING_LINK_EXISTING, "Collega attrezzatura esistente"),
        (TOOLING_REQUEST_NEW, "Richiedi nuovo attrezzo per P/N"),
        (TOOLING_VERIFICATION_REQUIRED, "Richiedi verifica disponibilita"),
    )

    task_scope = forms.ChoiceField(
        required=False,
        choices=TASK_SCOPE_CHOICES,
        initial=TASK_SCOPE_SINGLE,
        widget=forms.RadioSelect(attrs={"class": "input-radio"}),
        label="Contesto lavoro",
    )
    category = forms.ModelChoiceField(
        required=False,
        queryset=TaskCategory.objects.none(),
        widget=forms.Select(attrs={"class": "input", "data-role": "task-category"}),
        label="Tipo attivita",
        help_text="Seleziona il tipo per abilitare i campi specifici configurati dall'amministratore.",
    )
    project_link_mode = forms.ChoiceField(
        required=False,
        choices=PROJECT_LINK_MODE_CHOICES,
        initial=PROJECT_LINK_NEW,
        widget=forms.RadioSelect(attrs={"class": "input-radio"}),
        label="Gestione kickoff",
    )
    project_choice = ProjectChoiceField(
        required=False,
        queryset=Project.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Kickoff esistente",
    )
    project_new_name = forms.CharField(
        required=False,
        max_length=180,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 180, "placeholder": "Nome kickoff"}),
        label="Nuovo kickoff",
    )
    project_new_description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "input", "rows": 2, "placeholder": "Descrizione kickoff (opzionale)"}),
        label="Descrizione kickoff",
    )
    project_new_client = forms.CharField(
        required=False,
        max_length=180,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 180, "placeholder": "Cliente"}),
        label="Cliente",
    )
    project_new_manager = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Project manager",
    )
    project_new_capo_commessa = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Capocommessa",
    )
    project_new_programmer = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Programmatore",
    )
    project_new_control_method = forms.CharField(
        required=False,
        max_length=180,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 180, "placeholder": "Metodo di controllo"}),
        label="Metodo di controllo",
    )
    project_new_part_number = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 120, "placeholder": "P/N"}),
        label="P/N",
    )
    project_new_revisione = forms.CharField(
        required=False,
        max_length=60,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 60, "placeholder": "es. A, B, 01"}),
        label="Revisione",
    )
    project_new_versione = forms.CharField(
        required=False,
        max_length=60,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 60, "placeholder": "es. 1.0, 2.3"}),
        label="Versione",
    )
    project_similar_choice = ProjectChoiceField(
        required=False,
        queryset=Project.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Attivita simile (esistente)",
    )
    project_similar_new_note = forms.CharField(
        required=False,
        max_length=220,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 220, "placeholder": "Inserisci attivita simile ex-novo"}),
        label="Attivita simile (nuova)",
    )
    assignment_conflict_action = forms.ChoiceField(
        required=False,
        choices=ASSIGNMENT_CONFLICT_CHOICES,
        initial=ASSIGNMENT_CONFLICT_KEEP,
        widget=forms.Select(attrs={"class": "input"}),
        label="Gestione conflitto impegni",
    )
    add_to_outlook = forms.BooleanField(
        required=False, initial=False,
        widget=forms.CheckboxInput(attrs={"class": "input-checkbox"}),
        label="Aggiungi al calendario Outlook dell'assegnatario",
        help_text="Crea un evento nel calendario Outlook per la data di fine attivita'.",
    )
    outlook_target_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "input", "placeholder": "Default: email dell'assegnatario"}),
        label="Email calendario Outlook",
        help_text="Lasciare vuoto per usare l'email dell'operatore incaricato.",
    )
    reminder_portal_enabled_field = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "input-checkbox"}),
        label="Promemoria automatico sul portale",
        help_text="Crea una notifica portale 'N giorni' prima della scadenza (N da Impostazioni modulo).",
    )
    tooling_mode = forms.ChoiceField(
        required=False,
        choices=TOOLING_MODE_CHOICES,
        initial=TOOLING_NONE,
        widget=forms.Select(attrs={"class": "input"}),
        label="Azione Gestione Attrezzatura",
    )
    tooling_existing_attrezzatura = forms.ModelChoiceField(
        required=False,
        queryset=Attrezzatura.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Attrezzatura esistente",
    )
    tooling_part_number = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 120, "placeholder": "Default: P/N kickoff"}),
        label="P/N attrezzatura",
    )
    tooling_code = forms.CharField(
        required=False,
        max_length=80,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 80, "placeholder": "Codice attrezzo, se noto"}),
        label="Codice attrezzo",
    )
    tooling_description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "input", "rows": 2, "placeholder": "Nota richiesta attrezzatura"}),
        label="Nota attrezzatura",
    )

    class Meta:
        model = Task
        fields = [
            "category",
            "title",
            "description",
            "tags",
            "status",
            "priority",
            "progress",
            "due_date",
            "next_step_text",
            "next_step_due",
            "assigned_to",
            "subscribers",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "maxlength": 200}),
            "description": forms.Textarea(attrs={"class": "input", "rows": 4}),
            "tags": forms.TextInput(attrs={"class": "input", "maxlength": 250, "placeholder": "es. produzione, urgente"}),
            "status": forms.Select(attrs={"class": "input"}),
            "priority": forms.Select(attrs={"class": "input"}),
            "progress": forms.NumberInput(attrs={"class": "input", "min": 0, "max": 100, "step": 5}),
            "due_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "next_step_text": forms.TextInput(attrs={"class": "input", "maxlength": 300}),
            "next_step_due": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "assigned_to": forms.Select(attrs={"class": "input"}),
            "subscribers": forms.SelectMultiple(attrs={"class": "input"}),
        }

    def __init__(self, *args, user=None, project_queryset=None, locked_project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assignment_conflicts: list[Task] = []
        self.auto_raised_priority = False
        self.matched_existing_project = None
        self.reused_existing_project = None
        self.reused_existing_project_fields: list[str] = []
        self.locked_project = locked_project
        existing_calendar_event = None
        users_qs = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
        project_qs = project_queryset if project_queryset is not None else Project.objects.order_by("name", "id")
        self.project_queryset = project_qs

        self.fields["assigned_to"].required = False
        self.fields["assigned_to"].queryset = users_qs
        self.fields["subscribers"].required = False
        self.fields["subscribers"].queryset = users_qs
        self.fields["progress"].required = False
        self.fields["progress"].initial = 0
        self.fields["project_choice"].queryset = project_qs
        self.fields["category"].queryset = TaskCategory.objects.filter(is_active=True).order_by("order_index", "name")
        self.fields["project_new_manager"].queryset       = _users_for_role(TaskRoleType.PROJECT_MANAGER)
        self.fields["project_new_capo_commessa"].queryset = _users_for_capo_commessa()
        self.fields["project_new_programmer"].queryset    = _users_for_role(TaskRoleType.PROGRAMMER)
        self.fields["project_similar_choice"].queryset = project_qs
        self.fields["tooling_existing_attrezzatura"].queryset = Attrezzatura.objects.order_by("codice", "part_number", "id")

        self.fields["project_choice"].label = "Collega a kickoff esistente"
        self.fields["project_link_mode"].label = "Come vuoi lavorare sul kickoff"
        self.fields["project_new_name"].label = "Nome kickoff"
        self.fields["project_new_description"].label = "Descrizione kickoff"
        self.fields["project_new_client"].label = "Cliente"
        self.fields["project_new_manager"].label = "Project manager"
        self.fields["project_new_capo_commessa"].label = "Capocommessa"
        self.fields["project_new_programmer"].label = "Programmatore"
        self.fields["project_new_control_method"].label = "Metodo di controllo"
        self.fields["project_new_part_number"].label = "P/N"
        self.fields["project_new_revisione"].label = "Revisione"
        self.fields["project_new_versione"].label = "Versione"
        self.fields["project_similar_choice"].label = "Attivita simile (cerca esistente)"
        self.fields["project_similar_new_note"].label = "Attivita simile (inserisci nuova)"
        self.fields["title"].label = "Titolo attivita kickoff"
        self.fields["description"].label = "Descrizione attivita"
        self.fields["tags"].label = "Etichette"
        self.fields["status"].label = "Stato attivita kickoff"
        self.fields["priority"].label = "Priorita"
        self.fields["due_date"].label = "Data fine prevista"
        self.fields["next_step_text"].label = "Prossima azione"
        self.fields["next_step_due"].label = "Data inizio"
        self.fields["assigned_to"].label = "Operatore incaricato"
        self.fields["subscribers"].label = "Partecipanti in copia"
        self.fields["assignment_conflict_action"].label = "Se l'operatore ha altri impegni nello stesso periodo"
        self.fields["due_date"].help_text = "Puoi inserire anche una data passata: l'attivita verra segnalata come overdue."
        self.fields["next_step_due"].help_text = "Data di inizio attivita (di norma il giorno successivo alla fine dell'attivita precedente)."
        self.fields["tags"].help_text = "Separare le etichette con virgola. Esempio: produzione, urgente."
        self.fields["assignment_conflict_action"].help_text = (
            "Il sistema controlla eventuali altre attivita kickoff attive assegnate all'operatore nello stesso intervallo date."
        )
        self.fields["project_link_mode"].help_text = (
            "Scegli se collegare l'attivita a un kickoff gia presente oppure se aprire un nuovo kickoff."
        )
        self.fields["project_choice"].help_text = (
            "La lista include nome kickoff, cliente e identificativo P/N per velocizzare l'aggancio corretto."
        )
        self.fields["project_similar_choice"].help_text = "Seleziona un'attivita simile gia presente, se disponibile."
        self.fields["project_similar_new_note"].help_text = "Usa questo campo solo se l'attivita simile non esiste ancora."
        self.fields["tooling_mode"].help_text = (
            "Opzionale: crea o collega il workflow Gestione Attrezzatura mentre salvi l'attivita KICK-OFF."
        )

        # Initial per i nuovi campi outlook/reminder: in edit legge dall'istanza,
        # in create usa default (reminder attivo, outlook disattivo).
        if self.instance and self.instance.pk:
            existing_calendar_event = self.instance.calendar_events.order_by("-created_at", "-id").first()
            self.initial.setdefault("reminder_portal_enabled_field", bool(self.instance.reminder_portal_enabled))
            if existing_calendar_event is not None:
                self.initial.setdefault("add_to_outlook", True)
                self.initial.setdefault("outlook_target_email", existing_calendar_event.target_email)
        else:
            self.initial.setdefault("reminder_portal_enabled_field", True)

        default_outlook_email = ""
        if existing_calendar_event is not None and existing_calendar_event.target_email:
            default_outlook_email = str(existing_calendar_event.target_email).strip()
        elif self.instance and self.instance.pk and self.instance.assigned_to_id:
            default_outlook_email = str(getattr(self.instance.assigned_to, "email", "") or "").strip()
        if default_outlook_email:
            self.fields["outlook_target_email"].widget.attrs["placeholder"] = (
                f"Default: {default_outlook_email}"
            )
            if existing_calendar_event is None:
                self.fields["outlook_target_email"].help_text = (
                    "Lasciare vuoto per usare l'email dell'operatore incaricato "
                    f"({default_outlook_email})."
                )

        if self.locked_project is not None:
            self.initial["task_scope"] = self.TASK_SCOPE_PROJECT
            self.initial["project_link_mode"] = self.PROJECT_LINK_EXISTING
            self.initial["project_choice"] = self.locked_project.pk
        elif self.instance and self.instance.pk:
            if self.instance.project_id:
                self.initial.setdefault("task_scope", self.TASK_SCOPE_PROJECT)
                self.initial.setdefault("project_link_mode", self.PROJECT_LINK_EXISTING)
                self.initial.setdefault("project_choice", self.instance.project_id)
            else:
                self.initial.setdefault("task_scope", self.TASK_SCOPE_SINGLE)
        else:
            self.initial.setdefault("task_scope", self.TASK_SCOPE_SINGLE)
            self.initial.setdefault("project_link_mode", self.PROJECT_LINK_EXISTING)

    def _matching_projects_for_new_entry(self, *, part_number: str, revisione: str, versione: str):
        part_number = str(part_number or "").strip()
        revisione = str(revisione or "").strip()
        versione = str(versione or "").strip()
        if not part_number:
            return self.project_queryset.none()
        return self.project_queryset.filter(
            part_number__iexact=part_number,
            revisione__iexact=revisione,
            versione__iexact=versione,
        ).order_by("name", "id")

    def clean(self):
        self.assignment_conflicts = []
        self.auto_raised_priority = False
        self.matched_existing_project = None
        cleaned_data = super().clean()
        if cleaned_data.get("progress") in (None, ""):
            cleaned_data["progress"] = 0
        if self.locked_project is not None:
            cleaned_data["task_scope"] = self.TASK_SCOPE_PROJECT
            cleaned_data["project_link_mode"] = self.PROJECT_LINK_EXISTING
            cleaned_data["project_choice"] = self.locked_project
        due_date = cleaned_data.get("due_date")
        next_step_due = cleaned_data.get("next_step_due")
        task_scope = cleaned_data.get("task_scope") or self.TASK_SCOPE_SINGLE
        raw_project_link_mode = cleaned_data.get("project_link_mode")
        project_choice = cleaned_data.get("project_choice")
        project_new_description = (cleaned_data.get("project_new_description") or "").strip()
        project_new_client = (cleaned_data.get("project_new_client") or "").strip()
        project_new_control_method = (cleaned_data.get("project_new_control_method") or "").strip()
        project_new_part_number = (cleaned_data.get("project_new_part_number") or "").strip()
        project_new_revisione = (cleaned_data.get("project_new_revisione") or "").strip()
        project_new_versione = (cleaned_data.get("project_new_versione") or "").strip()
        similar_choice = cleaned_data.get("project_similar_choice")
        similar_new_note = (cleaned_data.get("project_similar_new_note") or "").strip()
        project_new_fields_present = any(
            [
                project_new_description,
                project_new_client,
                cleaned_data.get("project_new_manager"),
                cleaned_data.get("project_new_capo_commessa"),
                cleaned_data.get("project_new_programmer"),
                project_new_control_method,
                project_new_part_number,
                project_new_revisione,
                project_new_versione,
                similar_choice,
                similar_new_note,
            ]
        )
        if raw_project_link_mode in {self.PROJECT_LINK_EXISTING, self.PROJECT_LINK_NEW}:
            project_link_mode = raw_project_link_mode
        elif project_choice:
            project_link_mode = self.PROJECT_LINK_EXISTING
        elif project_new_fields_present:
            project_link_mode = self.PROJECT_LINK_NEW
        else:
            project_link_mode = self.PROJECT_LINK_EXISTING
        cleaned_data["project_link_mode"] = project_link_mode

        if due_date and next_step_due and due_date <= next_step_due:
            self.add_error("due_date", "La data richiesta fine deve essere successiva alla data inizio.")

        if cleaned_data.get("status") not in {TaskStatus.DONE, TaskStatus.CANCELED}:
            assigned_to = cleaned_data.get("assigned_to")
            window = self._resolve_planning_window(next_step_due=next_step_due, due_date=due_date)
            if assigned_to and window:
                window_start, window_end = window
                self.assignment_conflicts = self._load_assignment_conflicts(
                    assigned_to=assigned_to,
                    window_start=window_start,
                    window_end=window_end,
                )
                if self.assignment_conflicts:
                    conflict_action = (
                        cleaned_data.get("assignment_conflict_action") or self.ASSIGNMENT_CONFLICT_KEEP
                    )
                    if conflict_action == self.ASSIGNMENT_CONFLICT_RAISE and cleaned_data.get("priority") != TaskPriority.HIGH:
                        cleaned_data["priority"] = TaskPriority.HIGH
                        self.auto_raised_priority = True

        if task_scope == self.TASK_SCOPE_SINGLE:
            cleaned_data["project_choice"] = None
            cleaned_data["project_new_name"] = ""
            cleaned_data["project_new_description"] = ""
            cleaned_data["project_new_client"] = ""
            cleaned_data["project_new_manager"] = None
            cleaned_data["project_new_capo_commessa"] = None
            cleaned_data["project_new_programmer"] = None
            cleaned_data["project_new_control_method"] = ""
            cleaned_data["project_new_part_number"] = ""
            cleaned_data["project_new_revisione"] = ""
            cleaned_data["project_new_versione"] = ""
            cleaned_data["project_similar_choice"] = None
            cleaned_data["project_similar_new_note"] = ""
            cleaned_data["project_link_mode"] = ""
            return cleaned_data

        if similar_choice and similar_new_note:
            msg = "Seleziona un'attivita simile esistente oppure inseriscine una nuova, non entrambe."
            self.add_error("project_similar_choice", msg)
            self.add_error("project_similar_new_note", msg)

        if project_link_mode == self.PROJECT_LINK_EXISTING:
            if not project_choice:
                self.add_error("project_choice", "Seleziona un kickoff esistente per continuare.")
            cleaned_data["project_new_name"] = ""
            cleaned_data["project_new_description"] = ""
            cleaned_data["project_new_client"] = ""
            cleaned_data["project_new_manager"] = None
            cleaned_data["project_new_capo_commessa"] = None
            cleaned_data["project_new_programmer"] = None
            cleaned_data["project_new_control_method"] = ""
            cleaned_data["project_new_part_number"] = ""
            cleaned_data["project_new_revisione"] = ""
            cleaned_data["project_new_versione"] = ""
            cleaned_data["project_similar_choice"] = None
            cleaned_data["project_similar_new_note"] = ""
            return cleaned_data

        if (project_new_revisione or project_new_versione) and not project_new_part_number:
            self.add_error("project_new_part_number", "Compila il P/N prima di usare revisione o versione.")

        matching_projects = self._matching_projects_for_new_entry(
            part_number=project_new_part_number,
            revisione=project_new_revisione,
            versione=project_new_versione,
        )
        if matching_projects.exists():
            if matching_projects.count() == 1:
                self.matched_existing_project = matching_projects.first()
            else:
                msg = (
                    "Esistono gia piu kickoff con lo stesso P/N / Revisione / Versione. "
                    "Seleziona il kickoff corretto dalla lista dei kickoff esistenti."
                )
                self.add_error("project_new_part_number", msg)
                self.add_error("project_choice", msg)

        cleaned_data["project_choice"] = None
        cleaned_data["project_new_name"] = ""
        cleaned_data["project_new_description"] = project_new_description
        cleaned_data["project_new_client"] = project_new_client
        cleaned_data["project_new_control_method"] = project_new_control_method
        cleaned_data["project_new_part_number"] = project_new_part_number
        cleaned_data["project_new_revisione"] = project_new_revisione
        cleaned_data["project_new_versione"] = project_new_versione
        cleaned_data["project_similar_new_note"] = similar_new_note

        tooling_mode = cleaned_data.get("tooling_mode") or self.TOOLING_NONE
        if tooling_mode == self.TOOLING_LINK_EXISTING and not cleaned_data.get("tooling_existing_attrezzatura"):
            self.add_error("tooling_existing_attrezzatura", "Seleziona l'attrezzatura da collegare.")
        if tooling_mode in {self.TOOLING_REQUEST_NEW, self.TOOLING_VERIFICATION_REQUIRED}:
            has_pn = bool(
                (cleaned_data.get("tooling_part_number") or "").strip()
                or project_new_part_number
                or (cleaned_data.get("project_choice") and cleaned_data["project_choice"].part_number)
                or (self.instance and self.instance.pk and self.instance.project_id and self.instance.project.part_number)
            )
            if not has_pn:
                self.add_error("tooling_part_number", "Indica il P/N o collega l'attivita a un kickoff con P/N.")
        return cleaned_data

    def resolve_project(self, created_by):
        self.new_project_created = False
        self.reused_existing_project = None
        self.reused_existing_project_fields = []

        if (self.cleaned_data.get("task_scope") or self.TASK_SCOPE_SINGLE) == self.TASK_SCOPE_SINGLE:
            return None

        project = self.cleaned_data.get("project_choice")
        if project:
            return project

        if self.matched_existing_project is not None:
            project = self.matched_existing_project
            field_updates = {
                "description": (self.cleaned_data.get("project_new_description") or "").strip(),
                "client_name": (self.cleaned_data.get("project_new_client") or "").strip(),
                "project_manager": self.cleaned_data.get("project_new_manager"),
                "capo_commessa": self.cleaned_data.get("project_new_capo_commessa"),
                "programmer": self.cleaned_data.get("project_new_programmer"),
                "control_method": (self.cleaned_data.get("project_new_control_method") or "").strip(),
                "similar_project": self.cleaned_data.get("project_similar_choice"),
                "similar_work_note": (self.cleaned_data.get("project_similar_new_note") or "").strip(),
            }
            updated_fields: list[str] = []
            for field_name, value in field_updates.items():
                if value in (None, ""):
                    continue
                if getattr(project, field_name) != value:
                    setattr(project, field_name, value)
                    updated_fields.append(field_name)
            if updated_fields:
                project.save()
            self.reused_existing_project = project
            self.reused_existing_project_fields = updated_fields
            return project

        self.new_project_created = True
        return Project.objects.create(
            name="",
            description=(self.cleaned_data.get("project_new_description") or "").strip(),
            client_name=(self.cleaned_data.get("project_new_client") or "").strip(),
            project_manager=self.cleaned_data.get("project_new_manager"),
            capo_commessa=self.cleaned_data.get("project_new_capo_commessa"),
            programmer=self.cleaned_data.get("project_new_programmer"),
            control_method=(self.cleaned_data.get("project_new_control_method") or "").strip(),
            part_number=(self.cleaned_data.get("project_new_part_number") or "").strip(),
            revisione=(self.cleaned_data.get("project_new_revisione") or "").strip(),
            versione=(self.cleaned_data.get("project_new_versione") or "").strip(),
            similar_project=self.cleaned_data.get("project_similar_choice"),
            similar_work_note=(self.cleaned_data.get("project_similar_new_note") or "").strip(),
            created_by=created_by,
        )

    @staticmethod
    def _resolve_planning_window(*, next_step_due: date | None, due_date: date | None) -> tuple[date, date] | None:
        if next_step_due and due_date:
            return min(next_step_due, due_date), max(next_step_due, due_date)
        if next_step_due:
            return next_step_due, next_step_due
        if due_date:
            return due_date, due_date
        return None

    def _load_assignment_conflicts(self, *, assigned_to, window_start: date, window_end: date) -> list[Task]:
        active_statuses = [TaskStatus.TODO, TaskStatus.IN_PROGRESS]
        overlap_q = (
            Q(next_step_due__isnull=False, due_date__isnull=False, next_step_due__lte=window_end, due_date__gte=window_start)
            | Q(next_step_due__isnull=True, due_date__isnull=False, due_date__range=(window_start, window_end))
            | Q(next_step_due__isnull=False, due_date__isnull=True, next_step_due__range=(window_start, window_end))
        )
        query = Task.objects.filter(assigned_to=assigned_to, status__in=active_statuses).filter(overlap_q)
        if self.instance and self.instance.pk:
            query = query.exclude(pk=self.instance.pk)
        return list(query.select_related("project").order_by("due_date", "next_step_due", "id")[:8])

    def assignment_conflict_summary(self, *, limit: int = 3) -> str:
        if not self.assignment_conflicts:
            return ""

        chunks: list[str] = []
        for conflict in self.assignment_conflicts[: max(1, limit)]:
            start_date = conflict.next_step_due or conflict.due_date
            end_date = conflict.due_date or conflict.next_step_due
            if start_date and end_date and end_date < start_date:
                start_date, end_date = end_date, start_date
            if start_date and end_date and start_date != end_date:
                date_label = f"{start_date.strftime('%d-%m-%Y')} - {end_date.strftime('%d-%m-%Y')}"
            elif start_date:
                date_label = start_date.strftime("%d-%m-%Y")
            elif end_date:
                date_label = end_date.strftime("%d-%m-%Y")
            else:
                date_label = "senza data"
            chunks.append(f"{conflict.title} ({date_label})")

        summary = "; ".join(chunks)
        if len(self.assignment_conflicts) > max(1, limit):
            summary += "; ..."
        return summary


class TaskFilterForm(forms.Form):
    mine = forms.BooleanField(required=False, initial=True)
    status = forms.ChoiceField(
        required=False,
        choices=[("", "Tutti")] + list(TaskStatus.choices),
        widget=forms.Select(attrs={"class": "input"}),
    )
    priority = forms.ChoiceField(
        required=False,
        choices=[("", "Tutte")] + list(TaskPriority.choices),
        widget=forms.Select(attrs={"class": "input"}),
    )
    overdue = forms.BooleanField(required=False)
    unassigned = forms.BooleanField(required=False)
    without_due_date = forms.BooleanField(required=False)
    without_project = forms.BooleanField(required=False)
    due_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
    )
    due_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
    )
    assigned_to = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
    )
    project = forms.ModelChoiceField(
        required=False,
        queryset=Project.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
    )
    tag = forms.CharField(
        required=False,
        max_length=50,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "Tag"}),
    )

    def __init__(self, *args, user=None, project_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
        if project_queryset is not None:
            self.fields["project"].queryset = project_queryset
        else:
            self.fields["project"].queryset = Project.objects.order_by("name", "id")
        self.fields["unassigned"].label = "Solo non assegnate"
        self.fields["without_due_date"].label = "Senza data prevista"
        self.fields["without_project"].label = "Attivita singole (senza kickoff)"

    def clean(self):
        cleaned_data = super().clean()
        due_from = cleaned_data.get("due_from")
        due_to = cleaned_data.get("due_to")
        if due_from and due_to and due_to < due_from:
            self.add_error("due_to", "La data fine non puo essere precedente alla data inizio.")
        return cleaned_data


class TaskStatusForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={"class": "input"}),
        }


class TaskDueDateForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["due_date"]
        widgets = {
            "due_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
        }


class TaskCommentForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ["body", "target_user"]
        widgets = {
            "body": forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Scrivi un commento"}),
            "target_user": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, user=None, notify_user_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_user"].required = False
        if notify_user_queryset is not None:
            self.fields["target_user"].queryset = notify_user_queryset
        else:
            self.fields["target_user"].queryset = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")


class ProjectCommentForm(forms.ModelForm):
    class Meta:
        model = ProjectComment
        fields = ["body", "target_user"]
        widgets = {
            "body": forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Scrivi un commento kickoff"}),
            "target_user": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, user=None, notify_user_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_user"].required = False
        if notify_user_queryset is not None:
            self.fields["target_user"].queryset = notify_user_queryset
        else:
            self.fields["target_user"].queryset = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")


class SubTaskForm(forms.ModelForm):
    class Meta:
        model = SubTask
        fields = ["title", "assigned_to", "due_date", "order_index"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "maxlength": 200}),
            "assigned_to": forms.Select(attrs={"class": "input"}),
            "due_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "order_index": forms.NumberInput(attrs={"class": "input", "min": 0}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].required = False
        self.fields["assigned_to"].queryset = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")


class SubTaskStatusForm(forms.ModelForm):
    class Meta:
        model = SubTask
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={"class": "input"}),
        }


class TaskAttachmentForm(forms.ModelForm):
    TARGET_TASK = "task"
    TARGET_PROJECT = "project"

    attach_to = forms.ChoiceField(
        choices=((TARGET_TASK, "Task corrente"),),
        widget=forms.Select(attrs={"class": "input"}),
        label="Destinazione",
    )

    class Meta:
        model = TaskAttachment
        fields = ["attach_to", "file"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, task=None, **kwargs):
        self.task = task
        super().__init__(*args, **kwargs)
        choices = [(self.TARGET_TASK, "Task corrente")]
        if task and task.project_id:
            choices.append((self.TARGET_PROJECT, "Kickoff collegato"))
        self.fields["attach_to"].choices = choices
        self.fields["attach_to"].initial = choices[0][0]

    def clean(self):
        cleaned_data = super().clean()
        attach_to = cleaned_data.get("attach_to")
        if attach_to == self.TARGET_PROJECT and (not self.task or not self.task.project_id):
            self.add_error("attach_to", "L'attivita non e collegata a un kickoff.")
        uploaded_file = cleaned_data.get("file")
        if uploaded_file:
            try:
                validate_extension_and_mime(
                    uploaded_file,
                    allowed_extensions=TASKS_ATTACHMENT_EXTENSIONS,
                    allowed_mimes=TASKS_ATTACHMENT_MIMES,
                    max_bytes=TASKS_ATTACHMENT_MAX_BYTES,
                    label=safe_filename(getattr(uploaded_file, "name", "")) or "Allegato",
                    allow_empty=False,
                )
            except UploadMimeValidationError as exc:
                self.add_error("file", str(exc))
        return cleaned_data

    def _post_clean(self):
        attach_to = self.cleaned_data.get("attach_to")
        if self.task and attach_to == self.TARGET_PROJECT and self.task.project_id:
            self.instance.project = self.task.project
            self.instance.task = None
        elif self.task:
            self.instance.task = self.task
            self.instance.project = None
        super()._post_clean()


class ProjectTaskGanttUpdateForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["next_step_due", "due_date", "status", "progress"]
        widgets = {
            "next_step_due": forms.DateInput(attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"),
            "due_date": forms.DateInput(attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"),
            "status": forms.Select(attrs={"class": "input"}),
            "progress": forms.NumberInput(attrs={"class": "input", "min": 0, "max": 100, "step": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["progress"].required = False

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("progress") in (None, ""):
            cleaned_data["progress"] = getattr(self.instance, "progress", 0) or 0
        due_date = cleaned_data.get("due_date")
        next_step_due = cleaned_data.get("next_step_due")
        if due_date and next_step_due and due_date < next_step_due:
            self.add_error("due_date", "La data fine deve essere uguale o successiva alla data inizio.")
        return cleaned_data


class KickoffMeetingForm(forms.ModelForm):
    # Campo hidden gestito da JS: lista JSON dei punti all'ordine del giorno
    agenda_items_raw = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "id_agenda_items_raw"}),
    )

    class Meta:
        model = KickoffMeeting
        fields = [
            "titolo", "data", "ora", "luogo",
            "partecipanti_utenti", "partecipanti_email_extra", "partecipanti_testo",
            "ordine_del_giorno", "note", "problemi_aperti", "next_steps",
            "sync_outlook", "outlook_organizer_email",
        ]
        widgets = {
            "titolo": forms.TextInput(attrs={"class": "input", "placeholder": "Titolo opzionale"}),
            "data": forms.DateInput(attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"),
            "ora": forms.TimeInput(attrs={"class": "input", "type": "time"}, format="%H:%M"),
            "luogo": forms.TextInput(attrs={"class": "input", "placeholder": "Es. Sala riunioni / Teams"}),
            "partecipanti_utenti": forms.CheckboxSelectMultiple(),
            "partecipanti_email_extra": forms.Textarea(
                attrs={"class": "input", "rows": 3, "placeholder": "uno@dominio.it\naltra@dominio.it"}
            ),
            "partecipanti_testo": forms.Textarea(
                attrs={"class": "input", "rows": 2, "placeholder": "Note aggiuntive sui partecipanti (facoltativo)"}
            ),
            "ordine_del_giorno": forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Note testuali aggiuntive (facoltativo — usa i punti strutturati sopra)"}),
            "note": forms.Textarea(attrs={"class": "input", "rows": 6, "placeholder": "Verbale / Note incontro"}),
            "problemi_aperti": forms.Textarea(attrs={"class": "input", "rows": 4, "placeholder": "Problemi emersi, con responsabile e scadenza"}),
            "next_steps": forms.Textarea(attrs={"class": "input", "rows": 4, "placeholder": "Chi fa cosa entro quando"}),
            "sync_outlook": forms.CheckboxInput(attrs={"class": "mf-toggle"}),
            "outlook_organizer_email": forms.EmailInput(
                attrs={"class": "input", "placeholder": "organizzatore@azienda.it (lascia vuoto = tuo account)"}
            ),
        }

    def __init__(self, *args, **kwargs):
        import json
        super().__init__(*args, **kwargs)
        self.fields["partecipanti_utenti"].queryset = task_active_users_queryset()
        self.fields["partecipanti_utenti"].required = False
        self.fields["partecipanti_email_extra"].required = False
        self.fields["partecipanti_testo"].required = False
        self.fields["outlook_organizer_email"].required = False
        # Pre-popola il campo hidden con i punti agenda dell'istanza (per edit)
        if self.instance.pk:
            self.initial["agenda_items_raw"] = json.dumps(self.instance.agenda_items or [])

    def clean_agenda_items_raw(self):
        import json
        raw = self.cleaned_data.get("agenda_items_raw") or "[]"
        try:
            items = json.loads(raw)
            if not isinstance(items, list):
                return []
            result = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                titolo = str(item.get("titolo", "")).strip()[:200]
                if not titolo:
                    continue
                task_id = item.get("task_id")
                custom_fields = []
                raw_custom_fields = item.get("custom_fields") or []
                if isinstance(raw_custom_fields, list):
                    for custom_field in raw_custom_fields[:12]:
                        if not isinstance(custom_field, dict):
                            continue
                        label = str(custom_field.get("label", "")).strip()[:80]
                        value = str(custom_field.get("value", "")).strip()[:500]
                        if label and value:
                            custom_fields.append({"label": label, "value": value})
                result.append({
                    "id": str(item.get("id", "")),
                    "titolo": titolo,
                    "nota": str(item.get("nota", "")).strip()[:1000],
                    "task_id": int(task_id) if task_id else None,
                    "task_label": str(item.get("task_label", "")).strip()[:200],
                    "issue_id": int(item.get("issue_id")) if item.get("issue_id") else None,
                    "source": str(item.get("source", "")).strip()[:40],
                    "locked": bool(item.get("locked", False)),
                    "custom_fields": custom_fields,
                    "done": bool(item.get("done", False)),
                })
            return result
        except (json.JSONDecodeError, TypeError, ValueError):
            return []

    def clean_partecipanti_email_extra(self) -> str:
        raw = self.cleaned_data.get("partecipanti_email_extra", "")
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        invalid = [l for l in lines if "@" not in l]
        if invalid:
            raise forms.ValidationError(
                f"Indirizzi non validi (manca @): {', '.join(invalid)}"
            )
        return "\n".join(lines)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.agenda_items = self.cleaned_data.get("agenda_items_raw") or []
        if commit:
            instance.save()
            self.save_m2m()
        return instance
