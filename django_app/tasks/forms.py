from __future__ import annotations

from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Project, ProjectComment, SubTask, Task, TaskAttachment, TaskComment, TaskPriority, TaskStatus

User = get_user_model()


class TaskForm(forms.ModelForm):
    TASK_SCOPE_SINGLE = "single"
    TASK_SCOPE_PROJECT = "project"
    TASK_SCOPE_CHOICES = (
        (TASK_SCOPE_SINGLE, "Task singolo"),
        (TASK_SCOPE_PROJECT, "Task in progetto"),
    )
    ASSIGNMENT_CONFLICT_KEEP = "keep_priority"
    ASSIGNMENT_CONFLICT_RAISE = "raise_to_high"
    ASSIGNMENT_CONFLICT_CHOICES = (
        (ASSIGNMENT_CONFLICT_KEEP, "Mantieni priorita inserita"),
        (ASSIGNMENT_CONFLICT_RAISE, "Alza priorita a High"),
    )

    task_scope = forms.ChoiceField(
        required=False,
        choices=TASK_SCOPE_CHOICES,
        initial=TASK_SCOPE_SINGLE,
        widget=forms.RadioSelect(attrs={"class": "input-radio"}),
        label="Contesto lavoro",
    )
    project_choice = forms.ModelChoiceField(
        required=False,
        queryset=Project.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Progetto esistente",
    )
    project_new_name = forms.CharField(
        required=False,
        max_length=180,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 180, "placeholder": "Nome nuovo progetto"}),
        label="Nuovo progetto",
    )
    project_new_description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "input", "rows": 2, "placeholder": "Descrizione progetto (opzionale)"}),
        label="Descrizione nuovo progetto",
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
    project_similar_choice = forms.ModelChoiceField(
        required=False,
        queryset=Project.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="Lavorazione simile (esistente)",
    )
    project_similar_new_note = forms.CharField(
        required=False,
        max_length=220,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": 220, "placeholder": "Inserisci lavorazione simile ex-novo"}),
        label="Lavorazione simile (nuova)",
    )
    assignment_conflict_action = forms.ChoiceField(
        required=False,
        choices=ASSIGNMENT_CONFLICT_CHOICES,
        initial=ASSIGNMENT_CONFLICT_KEEP,
        widget=forms.Select(attrs={"class": "input"}),
        label="Gestione conflitto impegni",
    )

    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "tags",
            "status",
            "priority",
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
            "due_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "next_step_text": forms.TextInput(attrs={"class": "input", "maxlength": 300}),
            "next_step_due": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "assigned_to": forms.Select(attrs={"class": "input"}),
            "subscribers": forms.SelectMultiple(attrs={"class": "input"}),
        }

    def __init__(self, *args, user=None, project_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assignment_conflicts: list[Task] = []
        self.auto_raised_priority = False
        users_qs = User.objects.order_by("first_name", "last_name", "username")
        project_qs = project_queryset if project_queryset is not None else Project.objects.order_by("name", "id")

        self.fields["assigned_to"].required = False
        self.fields["assigned_to"].queryset = users_qs
        self.fields["subscribers"].required = False
        self.fields["subscribers"].queryset = users_qs
        self.fields["project_choice"].queryset = project_qs
        self.fields["project_new_manager"].queryset = users_qs
        self.fields["project_new_capo_commessa"].queryset = users_qs
        self.fields["project_new_programmer"].queryset = users_qs
        self.fields["project_similar_choice"].queryset = project_qs

        self.fields["project_choice"].label = "Collega a progetto esistente"
        self.fields["project_new_name"].label = "Nuovo progetto (nome)"
        self.fields["project_new_description"].label = "Nuovo progetto (descrizione)"
        self.fields["project_new_client"].label = "Cliente"
        self.fields["project_new_manager"].label = "Project manager"
        self.fields["project_new_capo_commessa"].label = "Capocommessa"
        self.fields["project_new_programmer"].label = "Programmatore"
        self.fields["project_new_control_method"].label = "Metodo di controllo"
        self.fields["project_new_part_number"].label = "P/N"
        self.fields["project_similar_choice"].label = "Lavorazione simile (cerca esistente)"
        self.fields["project_similar_new_note"].label = "Lavorazione simile (inserisci nuova)"
        self.fields["title"].label = "Titolo attivita"
        self.fields["description"].label = "Descrizione operativa"
        self.fields["tags"].label = "Etichette"
        self.fields["status"].label = "Stato attivita"
        self.fields["priority"].label = "Priorita"
        self.fields["due_date"].label = "Data richiesta fine"
        self.fields["next_step_text"].label = "Prossima azione"
        self.fields["next_step_due"].label = "Data inizio"
        self.fields["assigned_to"].label = "Operatore incaricato"
        self.fields["subscribers"].label = "Partecipanti in copia"
        self.fields["assignment_conflict_action"].label = "Se l'operatore ha altri impegni nello stesso periodo"
        self.fields["due_date"].help_text = "Puoi inserire anche una data passata: la task verra segnalata come overdue."
        self.fields["next_step_due"].help_text = "Data di inizio attivita (di norma il giorno successivo alla fine della task precedente)."
        self.fields["tags"].help_text = "Separare le etichette con virgola. Esempio: produzione, urgente."
        self.fields["assignment_conflict_action"].help_text = (
            "Il sistema controlla eventuali altre task attive assegnate all'operatore nello stesso intervallo date."
        )
        self.fields["project_similar_choice"].help_text = "Seleziona una lavorazione simile gia presente, se disponibile."
        self.fields["project_similar_new_note"].help_text = "Usa questo campo solo se la lavorazione simile non esiste ancora."

        if self.instance and self.instance.pk:
            if self.instance.project_id:
                self.initial.setdefault("task_scope", self.TASK_SCOPE_PROJECT)
                self.initial.setdefault("project_choice", self.instance.project_id)
            else:
                self.initial.setdefault("task_scope", self.TASK_SCOPE_SINGLE)
        else:
            self.initial.setdefault("task_scope", self.TASK_SCOPE_SINGLE)

    def clean(self):
        self.assignment_conflicts = []
        self.auto_raised_priority = False
        cleaned_data = super().clean()
        due_date = cleaned_data.get("due_date")
        next_step_due = cleaned_data.get("next_step_due")
        task_scope = cleaned_data.get("task_scope") or self.TASK_SCOPE_SINGLE
        project_choice = cleaned_data.get("project_choice")
        project_new_name = (cleaned_data.get("project_new_name") or "").strip()
        project_new_description = (cleaned_data.get("project_new_description") or "").strip()

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
            cleaned_data["project_similar_choice"] = None
            cleaned_data["project_similar_new_note"] = ""
            return cleaned_data

        if project_choice and project_new_name:
            msg = "Scegli un progetto esistente oppure creane uno nuovo, non entrambi."
            self.add_error("project_choice", msg)
            self.add_error("project_new_name", msg)
        elif not project_choice and not project_new_name:
            self.add_error("project_choice", "Seleziona un progetto esistente o inserisci il nome di un nuovo progetto.")

        if project_new_description and not project_new_name:
            self.add_error("project_new_name", "Inserisci il nome del nuovo progetto.")

        similar_choice = cleaned_data.get("project_similar_choice")
        similar_new_note = (cleaned_data.get("project_similar_new_note") or "").strip()
        if similar_choice and similar_new_note:
            msg = "Seleziona una lavorazione simile esistente oppure inseriscine una nuova, non entrambe."
            self.add_error("project_similar_choice", msg)
            self.add_error("project_similar_new_note", msg)

        if project_choice:
            cleaned_data["project_new_name"] = ""
            cleaned_data["project_new_description"] = ""
            cleaned_data["project_new_client"] = ""
            cleaned_data["project_new_manager"] = None
            cleaned_data["project_new_capo_commessa"] = None
            cleaned_data["project_new_programmer"] = None
            cleaned_data["project_new_control_method"] = ""
            cleaned_data["project_new_part_number"] = ""
            cleaned_data["project_similar_choice"] = None
            cleaned_data["project_similar_new_note"] = ""
            return cleaned_data

        cleaned_data["project_new_name"] = project_new_name
        cleaned_data["project_new_description"] = project_new_description
        cleaned_data["project_new_client"] = (cleaned_data.get("project_new_client") or "").strip()
        cleaned_data["project_new_control_method"] = (cleaned_data.get("project_new_control_method") or "").strip()
        cleaned_data["project_new_part_number"] = (cleaned_data.get("project_new_part_number") or "").strip()
        cleaned_data["project_similar_new_note"] = similar_new_note
        return cleaned_data

    def resolve_project(self, created_by):
        if (self.cleaned_data.get("task_scope") or self.TASK_SCOPE_SINGLE) == self.TASK_SCOPE_SINGLE:
            return None

        project = self.cleaned_data.get("project_choice")
        if project:
            return project

        project_name = (self.cleaned_data.get("project_new_name") or "").strip()
        if not project_name:
            return None

        return Project.objects.create(
            name=project_name,
            description=(self.cleaned_data.get("project_new_description") or "").strip(),
            client_name=(self.cleaned_data.get("project_new_client") or "").strip(),
            project_manager=self.cleaned_data.get("project_new_manager"),
            capo_commessa=self.cleaned_data.get("project_new_capo_commessa"),
            programmer=self.cleaned_data.get("project_new_programmer"),
            control_method=(self.cleaned_data.get("project_new_control_method") or "").strip(),
            part_number=(self.cleaned_data.get("project_new_part_number") or "").strip(),
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
                date_label = f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"
            elif start_date:
                date_label = start_date.strftime("%d/%m/%Y")
            elif end_date:
                date_label = end_date.strftime("%d/%m/%Y")
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
        self.fields["assigned_to"].queryset = User.objects.order_by("first_name", "last_name", "username")
        if project_queryset is not None:
            self.fields["project"].queryset = project_queryset
        else:
            self.fields["project"].queryset = Project.objects.order_by("name", "id")
        self.fields["unassigned"].label = "Solo non assegnate"
        self.fields["without_due_date"].label = "Senza data prevista"
        self.fields["without_project"].label = "Task singole (senza progetto)"

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
            self.fields["target_user"].queryset = User.objects.order_by("first_name", "last_name", "username")


class ProjectCommentForm(forms.ModelForm):
    class Meta:
        model = ProjectComment
        fields = ["body", "target_user"]
        widgets = {
            "body": forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Scrivi un commento progetto"}),
            "target_user": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, user=None, notify_user_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_user"].required = False
        if notify_user_queryset is not None:
            self.fields["target_user"].queryset = notify_user_queryset
        else:
            self.fields["target_user"].queryset = User.objects.order_by("first_name", "last_name", "username")


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
        self.fields["assigned_to"].queryset = User.objects.order_by("first_name", "last_name", "username")


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
            choices.append((self.TARGET_PROJECT, "Progetto collegato"))
        self.fields["attach_to"].choices = choices
        self.fields["attach_to"].initial = choices[0][0]

    def clean(self):
        cleaned_data = super().clean()
        attach_to = cleaned_data.get("attach_to")
        if attach_to == self.TARGET_PROJECT and (not self.task or not self.task.project_id):
            self.add_error("attach_to", "La task non e collegata a un progetto.")
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
        fields = ["next_step_due", "due_date", "status"]
        widgets = {
            "next_step_due": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "due_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "status": forms.Select(attrs={"class": "input"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        due_date = cleaned_data.get("due_date")
        next_step_due = cleaned_data.get("next_step_due")
        if due_date and next_step_due and due_date <= next_step_due:
            self.add_error("due_date", "La data richiesta fine deve essere successiva alla data inizio.")
        return cleaned_data
