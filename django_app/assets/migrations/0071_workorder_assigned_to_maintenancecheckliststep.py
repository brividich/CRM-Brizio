import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0070_alter_assetdocument_category_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="workorder",
            name="assigned_to",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="workorders_assigned",
                to=settings.AUTH_USER_MODEL,
                help_text="Manutentore assegnato all'intervento",
            ),
        ),
        migrations.CreateModel(
            name="MaintenanceChecklistStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("step_number", models.PositiveSmallIntegerField(default=10)),
                ("description", models.CharField(max_length=255)),
                (
                    "intervention_template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checklist_steps",
                        to="assets.maintenanceinterventiontemplate",
                    ),
                ),
            ],
            options={
                "verbose_name": "Step checklist template",
                "verbose_name_plural": "Step checklist template",
                "ordering": ["intervention_template", "step_number", "id"],
            },
        ),
    ]
