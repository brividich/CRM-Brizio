from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_reparto_capo_mapping"),
    ]

    operations = [
        migrations.AddField(
            model_name="optioneconfig",
            name="legacy_user_id",
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
    ]
