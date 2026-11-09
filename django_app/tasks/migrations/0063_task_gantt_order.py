from django.db import migrations, models


def numera_piani(apps, schema_editor):
    """Le righe esistenti tengono l'ordine di oggi (creazione), numerate di 10 in 10 per kickoff."""
    Task = apps.get_model("tasks", "Task")
    contatori: dict[int, int] = {}
    for pk, project_id in (
        Task.objects.exclude(project_id=None).order_by("project_id", "id").values_list("pk", "project_id")
    ):
        contatori[project_id] = contatori.get(project_id, 0) + 10
        # Un UPDATE per riga: su SQL Server gli INSERT/UPDATE a lotti rompono i savepoint.
        Task.objects.filter(pk=pk).update(gantt_order=contatori[project_id])


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0062_incontro_durata"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="gantt_order",
            field=models.PositiveIntegerField(
                db_index=True,
                default=0,
                help_text="Posizione della riga nel Gantt del kickoff (0 = in fondo, in ordine di creazione).",
            ),
        ),
        migrations.RunPython(numera_piani, migrations.RunPython.noop),
    ]
