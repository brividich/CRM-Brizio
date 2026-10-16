from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0081_preset_modello_organigramma"),
    ]

    operations = [
        migrations.AddField(
            model_name="accessgroupmembership",
            name="scade_il",
            field=models.DateField(blank=True, null=True),
        ),
    ]
