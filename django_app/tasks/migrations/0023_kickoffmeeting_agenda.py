from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0022_kickoffmeeting_outlook"),
    ]

    operations = [
        migrations.AddField(
            model_name="kickoffmeeting",
            name="agenda_items",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="Punti all'ordine del giorno",
            ),
        ),
    ]
