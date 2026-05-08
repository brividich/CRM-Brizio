from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0028_task_progress"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GanttBaseline",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("snapshot", models.JSONField(default=dict)),
                ("fixed_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gantt_baseline",
                        to="tasks.project",
                    ),
                ),
                (
                    "fixed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="gantt_baselines_fixed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name": "Baseline Gantt"},
        ),
    ]
