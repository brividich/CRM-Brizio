from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0027_project_safety_impact"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="progress",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Avanzamento manuale dell'attività (0–100).",
            ),
        ),
    ]
