from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitoring", "0003_backuprun_restoredrill"),
    ]

    operations = [
        migrations.AddField(
            model_name="schedulecontrol",
            name="sospeso_fino",
            field=models.DateField(blank=True, null=True),
        ),
    ]
