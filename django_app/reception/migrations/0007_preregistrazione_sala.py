import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reception", "0006_permessi_pannello"),
        ("tasks", "0069_punto_odg_voci"),
    ]

    operations = [
        migrations.AddField(
            model_name="preregistrazione",
            name="sala",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="tasks.meetingroom"),
        ),
        migrations.AddField(
            model_name="preregistrazione",
            name="outlook_event_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="preregistrazione",
            name="outlook_organizer_email",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
