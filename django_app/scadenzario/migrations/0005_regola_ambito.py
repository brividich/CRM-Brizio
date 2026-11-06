from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scadenzario", "0004_collegamenti"),
    ]

    operations = [
        migrations.AddField(
            model_name="regolavisibilita",
            name="ambito",
            field=models.CharField(
                choices=[("propri", "Propri"), ("team", "Propri e del team"), ("tutti", "Tutti")],
                default="tutti",
                max_length=10,
            ),
        ),
    ]
