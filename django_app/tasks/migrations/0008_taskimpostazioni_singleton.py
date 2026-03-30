from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0007_taskimpostazioni"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="taskimpostazioni",
            constraint=models.CheckConstraint(
                check=models.Q(pk=1),
                name="taskimpostazioni_singleton",
            ),
        ),
    ]
