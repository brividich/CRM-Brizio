from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0023_kickoffmeeting_agenda"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskcategory",
            name="is_machine_work",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="Se attivo, le attività di questo tipo sono 'Lavoro macchina': richiedono un campo asset e compaiono nel calendario delle macchine.",
            ),
        ),
    ]
