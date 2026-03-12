from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_employeeboardconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="navigationitem",
            name="parent_code",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Solo per section='subnav': codice del gruppo (es. 'dashboard', 'assenze', 'anagrafica').",
                max_length=80,
            ),
        ),
    ]
