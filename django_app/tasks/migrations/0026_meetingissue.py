from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_problem_text(apps, schema_editor):
    KickoffMeeting = apps.get_model("tasks", "KickoffMeeting")
    MeetingIssue = apps.get_model("tasks", "MeetingIssue")

    for meeting in KickoffMeeting.objects.exclude(problemi_aperti="").select_related("project", "created_by"):
        lines = [line.strip() for line in (meeting.problemi_aperti or "").splitlines() if line.strip()]
        if not lines and meeting.problemi_aperti.strip():
            lines = [meeting.problemi_aperti.strip()]
        for line in lines:
            MeetingIssue.objects.create(
                project_id=meeting.project_id,
                source_meeting_id=meeting.id,
                title=line[:220],
                description=line if len(line) > 220 else "",
                status="OPEN",
                created_by_id=meeting.created_by_id,
            )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0025_meetingroom"),
    ]

    operations = [
        migrations.CreateModel(
            name="MeetingIssue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220, verbose_name="Problema")),
                ("description", models.TextField(blank=True, default="", verbose_name="Dettaglio")),
                (
                    "status",
                    models.CharField(
                        choices=[("OPEN", "Aperto"), ("RESOLVED", "Risolto")],
                        default="OPEN",
                        max_length=16,
                        verbose_name="Stato",
                    ),
                ),
                ("due_date", models.DateField(blank=True, null=True, verbose_name="Scadenza")),
                ("resolution_note", models.TextField(blank=True, default="", verbose_name="Nota risoluzione")),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="meeting_issues_assigned",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Responsabile",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="meeting_issues_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "linked_task",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="meeting_issues",
                        to="tasks.task",
                        verbose_name="Attivita collegata",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="meeting_issues",
                        to="tasks.project",
                        verbose_name="Kickoff",
                    ),
                ),
                (
                    "resolution_meeting",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="issues_resolved",
                        to="tasks.kickoffmeeting",
                        verbose_name="Incontro di risoluzione",
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="meeting_issues_resolved",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Risolto da",
                    ),
                ),
                (
                    "source_meeting",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="issues_created",
                        to="tasks.kickoffmeeting",
                        verbose_name="Incontro di origine",
                    ),
                ),
            ],
            options={
                "verbose_name": "Problema incontro",
                "verbose_name_plural": "Problemi incontri",
                "ordering": ["status", "due_date", "created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="meetingissue",
            index=models.Index(fields=["project", "status"], name="tasks_meeti_project_8bbb80_idx"),
        ),
        migrations.AddIndex(
            model_name="meetingissue",
            index=models.Index(fields=["source_meeting", "status"], name="tasks_meeti_source__dd9677_idx"),
        ),
        migrations.AddIndex(
            model_name="meetingissue",
            index=models.Index(fields=["resolution_meeting", "status"], name="tasks_meeti_resolut_70488d_idx"),
        ),
        migrations.RunPython(migrate_legacy_problem_text, migrations.RunPython.noop),
    ]
