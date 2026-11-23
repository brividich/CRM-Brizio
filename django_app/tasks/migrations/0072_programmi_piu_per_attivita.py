"""Un'attività può avere più programmi: ``ProjectTechRef.task`` da uno-a-uno a chiave esterna.

Solo il vincolo di unicità sparisce (operazione standard di Django, nessun SQL
scritto a mano): colonna e dati restano. Tornando indietro il vincolo va
rimesso, quindi prima si lascia a ogni attività un solo programma (il primo
inserito); gli altri restano nella commessa «senza attività», non si cancellano.
"""
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Count


def _uno_per_attivita(apps, schema_editor):
    ProjectTechRef = apps.get_model("tasks", "ProjectTechRef")
    doppie = (
        ProjectTechRef.objects.filter(task__isnull=False)
        .values("task_id").annotate(n=Count("id")).filter(n__gt=1)
    )
    for task_id in [r["task_id"] for r in doppie]:
        ids = list(ProjectTechRef.objects.filter(task_id=task_id).order_by("id").values_list("id", flat=True))
        ProjectTechRef.objects.filter(id__in=ids[1:]).update(task=None)


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0071_utensile_attivita"),
    ]

    operations = [
        migrations.AlterField(
            model_name="projecttechref",
            name="task",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="tech_refs", to="tasks.task", verbose_name="Attività",
            ),
        ),
        # In avanti non fa niente; all'indietro gira prima di rimettere il vincolo.
        migrations.RunPython(migrations.RunPython.noop, _uno_per_attivita),
    ]
