from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0029_ganttbaseline"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskDependency",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "dependency_type",
                    models.CharField(
                        choices=[
                            ("FS", "Fine → Inizio (FS)"),
                            ("SS", "Inizio → Inizio (SS)"),
                            ("FF", "Fine → Fine (FF)"),
                            ("SF", "Inizio → Fine (SF)"),
                        ],
                        default="FS",
                        max_length=2,
                    ),
                ),
                (
                    "lag_days",
                    models.SmallIntegerField(
                        default=0,
                        help_text="Giorni di ritardo/anticipo (positivo = lag, negativo = lead).",
                    ),
                ),
                (
                    "predecessor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="successors",
                        to="tasks.task",
                    ),
                ),
                (
                    "successor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="predecessors",
                        to="tasks.task",
                    ),
                ),
            ],
            options={"verbose_name": "Dipendenza task"},
        ),
        migrations.AddConstraint(
            model_name="taskdependency",
            constraint=models.UniqueConstraint(
                fields=["predecessor", "successor"],
                name="tasks_taskdependency_unique_pair",
            ),
        ),
    ]
