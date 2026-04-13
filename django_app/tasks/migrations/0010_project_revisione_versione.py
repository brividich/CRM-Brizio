from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0009_rename_nav_vrf_kick_off"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="revisione",
            field=models.CharField(blank=True, default="", max_length=60),
        ),
        migrations.AddField(
            model_name="project",
            name="versione",
            field=models.CharField(blank=True, default="", max_length=60),
        ),
    ]
