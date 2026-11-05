from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dpi", "0017_scarpe_negozio"),
    ]

    operations = [
        migrations.AddField(
            model_name="consegnadpi",
            name="avvisi_in_sospeso_dal",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Consegna dal banco gia' registrata, con mail e PDF ancora da fare: finche' e' valorizzato si puo' annullare.",
                null=True,
            ),
        ),
    ]
