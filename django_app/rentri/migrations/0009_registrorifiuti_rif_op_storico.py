from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rentri", "0008_catalogo_eer_promemoria"),
    ]

    operations = [
        migrations.AddField(
            model_name="registrorifiuti",
            name="rif_op_storico",
            field=models.TextField(blank=True, default=""),
        ),
    ]
